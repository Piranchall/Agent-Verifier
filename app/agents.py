"""The agent team under test, working plan-then-execute:

    Planner writes a 2-3 step plan
    for each plan step:  Planner instruction -> Coder -> Test runner
    if the visible test still fails at the end: one fix-up round, then stop
    (Feature 3, if RELEASE_ACTIONS=on) if the visible test passes: release step
        = deploy to staging, deploy to production, email the customer (simulated)

Every step appends one entry to state["trace"]. LangGraph checkpoints the full
state (trace + code files + plan) after every step, which is what lets us rewind
to any step, change it, and replay from there (see runs.py). The editable steps
are the user's request, the plan, and each planner instruction.
"""
import difflib
import re
import sqlite3
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from . import actions, llm, sandbox, scenarios
from . import config as cfg


class TeamState(TypedDict):
    scenario_id: str
    task: str
    files: dict
    trace: list
    round: int          # coder rounds done so far
    last_test: dict
    plan: list          # plan items (strings)
    plan_index: int     # next plan item to carry out
    action_policy: dict # Feature 3: {tool: "run" | "hold"} for this thread; missing = run


def _step(trace, agent, content, **data):
    return {"i": len(trace), "agent": agent, "content": content, "data": data, "edited": False}


def _files_block(files):
    return "\n\n".join(f"--- {name} ---\n{body}" for name, body in files.items())


def _recent(trace, n=6):
    lines = []
    for s in trace[-n:]:
        text = s["content"].replace("\n", " ")
        lines.append(f"[{s['i']}] {s['agent']}: {text[:300]}")
    return "\n".join(lines)


def _meter(config):
    return (config or {}).get("configurable", {}).get("thread_id")


# ---------------------------------------------------------------- planner
PLAN_SYSTEM = (
    "You are the Planner in a small AI coding team (Planner, Coder, Test runner). "
    "Read the user's request and the current code, then break the work into 2 or 3 small, ordered "
    "steps for the Coder. Each step is one sentence. The Coder will carry them out one at a time. "
    'Reply with JSON only: {"plan": ["first step", "second step"]}.'
)

INSTRUCTION_SYSTEM = (
    "You are the Planner in a small AI coding team (Planner, Coder, Test runner). You made a plan; "
    "now give the Coder ONE clear instruction for the plan step named below, taking the current code "
    "and the latest test results into account. "
    'Reply with JSON only: {"instruction": "..."}. Keep the instruction under 80 words.'
)

FIXUP_SYSTEM = (
    "You are the Planner in a small AI coding team (Planner, Coder, Test runner). The plan is done "
    "but the tests you can see still fail. Give the Coder ONE clear instruction to make them pass. "
    'Reply with JSON only: {"instruction": "..."}. Keep the instruction under 80 words.'
)

PLAN_LINE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s*")


def parse_plan(text):
    """Turn a numbered plan (as shown to people, and as people edit it) back into items."""
    items = [PLAN_LINE.sub("", line).strip() for line in text.splitlines()]
    return [x for x in items if x] or ["Fix the bug the user described."]


def format_plan(items):
    return "\n".join(f"{k}. {item}" for k, item in enumerate(items, 1))


def _test_text(state):
    last = state.get("last_test") or {}
    if not last:
        return "Tests have not been run yet."
    return f"{last.get('passed')}/{last.get('total')} passed\n{last.get('output', '')[-1200:]}"


def plan(state: TeamState, config=None):
    s = scenarios.load(state["scenario_id"])
    user = f"User request:\n{state['task']}\n\nCurrent code:\n{_files_block(state['files'])}"
    text = llm.chat(
        [{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": user}],
        purpose="plan", meter=_meter(config), mock_ctx={"scenario": s, "state": state}, max_tokens=900,
    )
    parsed = llm.extract_json(text) or {}
    items = [str(x).strip() for x in parsed.get("plan", []) if str(x).strip()][: cfg.PLAN_MAX_STEPS]
    if not items:
        items = parse_plan(text)[: cfg.PLAN_MAX_STEPS]
    trace = state["trace"] + [_step(state["trace"], "planner", format_plan(items), kind="plan", items=items)]
    return {"trace": trace, "plan": items, "plan_index": 0}


def planner(state: TeamState, config=None):
    s = scenarios.load(state["scenario_id"])
    items = state.get("plan") or []
    idx = state.get("plan_index", 0)
    fixup = idx >= len(items)
    if fixup:
        system, focus = FIXUP_SYSTEM, "All plan steps are done; the visible tests still fail."
    else:
        system, focus = INSTRUCTION_SYSTEM, f"Plan step {idx + 1} of {len(items)}: {items[idx]}"
    user = (
        f"User request:\n{state['task']}\n\nThe plan:\n{format_plan(items)}\n\n{focus}\n\n"
        f"Current code:\n{_files_block(state['files'])}\n\n"
        f"Tests you can see:\n{_files_block(s['visible_test_files'])}\n\n"
        f"Latest test result:\n{_test_text(state)}\n\nConversation so far:\n{_recent(state['trace'])}"
    )
    text = llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        purpose="planner", meter=_meter(config),
        mock_ctx={"scenario": s, "state": state, "fixup": fixup, "plan_step": idx + 1}, max_tokens=900,
    )
    parsed = llm.extract_json(text) or {}
    instruction = str(parsed.get("instruction") or text or "Fix the bug the user described.").strip()
    step = _step(state["trace"], "planner", instruction, kind="instruction",
                 plan_step="fix-up" if fixup else idx + 1, decision="continue")
    return {"trace": state["trace"] + [step]}


# ---------------------------------------------------------------- coder
CODER_SYSTEM = (
    "You are the Coder in a small AI coding team. Follow the Planner's latest instruction. "
    "Return the FULL new content of every file you change, in exactly this format:\n"
    "NOTE: <one sentence describing your change>\n"
    "=== FILE: <filename> ===\n<full file content>\n=== END FILE ===\n"
    "Do not use markdown fences. Never change test files. Files you may change: {files}."
)
FILE_RE = re.compile(r"=== FILE:\s*(\S+)\s*===\n(.*?)\n=== END FILE ===", re.S)


def coder(state: TeamState, config=None):
    s = scenarios.load(state["scenario_id"])
    instruction = next((x["content"] for x in reversed(state["trace"]) if x["agent"] == "planner"), state["task"])
    last = state.get("last_test") or {}
    plan_text = format_plan(state.get("plan") or [])
    user = (
        f"User request:\n{state['task']}\n\nThe team's plan:\n{plan_text}\n\n"
        f"Planner's instruction for this step:\n{instruction}\n\n"
        f"Current code:\n{_files_block(state['files'])}\n\n"
        f"Latest test output:\n{(last.get('output') or 'not run yet')[-1200:]}"
    )
    text = llm.chat(
        [{"role": "system", "content": CODER_SYSTEM.format(files=", ".join(s["editable_files"]))},
         {"role": "user", "content": user}],
        purpose="coder", meter=_meter(config),
        mock_ctx={"scenario": s, "state": state, "instruction": instruction, "plan_text": plan_text},
        max_tokens=2500,
    )
    new_files = dict(state["files"])
    changed = []
    for name, body in FILE_RE.findall(text):
        body = re.sub(r"^```\w*\n|\n```$", "", body)
        if name in s["editable_files"] and body.strip() and body != new_files.get(name):
            new_files[name] = body.rstrip("\n") + "\n"
            changed.append(name)
    note_match = re.search(r"NOTE:\s*(.+)", text)
    note = note_match.group(1).strip() if note_match else ("Changed " + ", ".join(changed) if changed else "")
    if not changed:
        note = (note + " " if note else "") + "(no file changes were made)"
    diff = "".join(
        "".join(difflib.unified_diff(state["files"][n].splitlines(True), new_files[n].splitlines(True),
                                     fromfile=f"a/{n}", tofile=f"b/{n}"))
        for n in changed
    )
    trace = state["trace"] + [_step(state["trace"], "coder", note, changed=changed, diff=diff,
                                    code_hash=_hash(new_files))]
    return {"trace": trace, "files": new_files}


def _hash(files):
    import hashlib
    return hashlib.sha1("".join(f"{k}\0{v}" for k, v in sorted(files.items())).encode()).hexdigest()[:10]


# ---------------------------------------------------------------- tests
def tests(state: TeamState, config=None):
    s = scenarios.load(state["scenario_id"])
    res = sandbox.run_tests({**state["files"], **s["visible_test_files"]}, s["visible_tests"])
    if res.get("error"):
        summary = f"Tests could not run: {res['error'][:200]}"
    else:
        summary = f"{res['passed']} of {res['total']} visible tests passed"
        if res["failed_tests"]:
            summary += " (failing: " + ", ".join(res["failed_tests"]) + ")"
    trace = state["trace"] + [_step(state["trace"], "tests", summary, result=res)]
    return {"trace": trace, "last_test": res, "round": state["round"] + 1,
            "plan_index": state.get("plan_index", 0) + 1}


# ---------------------------------------------------------------- release (Feature 3)
def release(state: TeamState, config=None):
    """Fixed release step: no LLM. Each action runs or is held according to action_policy."""
    run_id = _meter(config)
    policy = state.get("action_policy") or {}
    trace = list(state["trace"])
    for tool, spec in actions.TOOLS.items():
        status = "held" if policy.get(tool) == "hold" else "done"
        call = actions.call_text(tool, state["scenario_id"], state["files"])
        trace.append(_step(trace, "release", spec["held" if status == "held" else "done"],
                           kind="action", tool=tool, status=status, call=call,
                           irreversible=spec["irreversible"]))
        actions.record(run_id, tool, status, call)
    return {"trace": trace}


# ---------------------------------------------------------------- routing
def after_tests(state):
    plan_len = len(state.get("plan") or [])
    if state.get("plan_index", 0) < plan_len:
        return "planner"                                  # carry out the next plan step
    if state["last_test"].get("ok"):
        return "release" if cfg.RELEASE_ACTIONS else END  # done: ship it (Feature 3)
    if state["round"] >= plan_len + cfg.FIXUP_ROUNDS:
        return END                                        # give up, nothing is shipped
    return "planner"                                      # fix-up round


def node_for_step(step):
    """Which graph node produced an editable step (used when forking from it)."""
    return "plan" if step["data"].get("kind") == "plan" else "planner"


def build_graph():
    g = StateGraph(TeamState)
    g.add_node("plan", plan)
    g.add_node("planner", planner)
    g.add_node("coder", coder)
    g.add_node("tests", tests)
    g.add_node("release", release)
    g.add_edge(START, "plan")
    g.add_edge("plan", "planner")
    g.add_edge("planner", "coder")
    g.add_edge("coder", "tests")
    g.add_conditional_edges("tests", after_tests, ["planner", "release", END])
    g.add_edge("release", END)
    conn = sqlite3.connect(str(cfg.CHECKPOINT_DB), check_same_thread=False)
    return g.compile(checkpointer=SqliteSaver(conn))


GRAPH = build_graph()


def initial_state(scenario_id, task=None):
    s = scenarios.load(scenario_id)
    task = task or s["task"]
    return {
        "scenario_id": scenario_id,
        "task": task,
        "files": dict(s["start_files"]),
        "trace": [_step([], "user", task)],
        "round": 0,
        "last_test": {},
        "plan": [],
        "plan_index": 0,
        "action_policy": {},
    }
