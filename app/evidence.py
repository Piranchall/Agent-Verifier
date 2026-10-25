"""Feature 1 (where to fix) and the plain-language layer for beginners.

Where to intervene is largely decided by how the team is built, so the ORDER of
the suggestions comes from a fixed rule, not from an LLM guess:

    the plan and the request are read again at every later step, so a change
    there carries through the run; an instruction is mainly read once, by the
    next coder step, and later steps can undo a change made there.

So the candidates are: plan, request, then instructions (earliest first). Each
carries that "how this step is used" reason (HOW_USED), which is always true for
this team. One LLM call then explains, for each candidate, WHAT in it should
change to fix the failing checks. Calibration on Groq backs the rule for two of
the three main scenarios (early edits 8/8, instructions 0/12); for copy_names
every step worked, which the rule doesn't contradict (plan and request still work).

In STUDY_MODE a planted suggestion can move a step (e.g. an instruction) to the top.
"""
from . import config, llm, runs

RANKING_VERSION = 2  # 1 = LLM ordered the steps; 2 = rule orders them, LLM explains them

EXPLAIN_SYSTEM = (
    "You help a person fix a failed run of an AI coding team (Planner, Coder, Test runner). "
    "The person can rewrite one step and replay the run from there. For EACH step number listed, "
    "say what in that step should change so the final code passes the failing checks. "
    'Reply with JSON only: {"steps": [{"step": <int>, '
    '"why_plain": "<one sentence a beginner understands, no code names>", '
    '"why_technical": "<one or two sentences for an experienced developer>"}]}.'
)

HOW_USED = {
    "plan": "The plan is read again at every later step, so a change here carries through the whole run.",
    "request": "Your request is read again at every later step too, so a change here also carries through.",
    "instruction": "An instruction is mainly read once, by the next coder step. Later steps can undo a change made here.",
}


def step_kind(step):
    if step["agent"] == "user":
        return "request"
    return "plan" if step["data"].get("kind") == "plan" else "instruction"


def candidate_order(trace):
    """The rule: plan, then request, then instructions in run order."""
    editable = [s for s in trace if s["agent"] in ("user", "planner")]
    rank = {"plan": 0, "request": 1, "instruction": 2}
    return [s["i"] for s in sorted(editable, key=lambda s: (rank[step_kind(s)], s["i"]))]

SUMMARY_SYSTEM = (
    "Rewrite each step of an AI coding team's run as ONE plain sentence (max 18 words) for a student "
    "with a few months of coding experience. No jargon. "
    'Reply with JSON only, mapping step number to sentence, e.g. {"1": "...", "2": "..."}.'
)


def _compact(trace):
    lines = []
    for s in trace:
        text = s["content"].replace("\n", " ")[:400]
        extra = ""
        if s["agent"] == "coder" and s["data"].get("diff"):
            extra = "\n    diff: " + s["data"]["diff"][:700].replace("\n", "\n    ")
        lines.append(f"[{s['i']}] {s['agent']}: {text}{extra}")
    return "\n".join(lines)


def rank_steps(run_id, plant=None):
    """Returns {"ranking": [...shown...], "planted": bool, "true_ranking": [...]}.
    plant (from a session task) overrides the run's own researcher plant."""
    run = runs.get_run(run_id)
    if run is None or run["status"] != "done":
        raise ValueError("The run must finish before steps can be ranked.")
    true = run.get("ranking_true") if run.get("ranking_version") == RANKING_VERSION else None
    if not true:
        true = _compute_ranking(run)
        runs.update_run(run_id, ranking_true=true, ranking_version=RANKING_VERSION)
    target = (plant if plant is not None else (run.get("plant") or {})).get("rank_move_to_step")
    if not config.STUDY_MODE:
        target = None  # outside study mode the suggestion is always the real one
    editable = runs.editable_steps(run["trace"])
    if target is None or int(target) not in editable or (true and true[0]["step"] == int(target)):
        return {"ranking": true, "planted": False, "true_ranking": true}
    target = int(target)
    moved = next((r for r in true if r["step"] == target), None) or {
        "step": target, "kind": "instruction", "how_used": HOW_USED["instruction"],
        "why_plain": "This is where the team decided how to fix the bug.",
        "why_technical": "The instruction that led to the failing change.",
    }
    shown = [moved] + [r for r in true if r["step"] != target]
    return {"ranking": shown, "planted": True, "true_ranking": true}


def _compute_ranking(run):
    """All editable steps in rule order, each with HOW_USED and the LLM's 'what to change' explanation."""
    trace = run["trace"]
    order = candidate_order(trace)
    outcome = run["outcome"]
    user = (
        f"Run:\n{_compact(trace)}\n\n"
        f"Final result on the hidden acceptance tests: {outcome['passed']}/{outcome['total']} passed. "
        f"Failing: {', '.join(outcome['failed_tests']) or 'none'}\n{outcome['output'][-1200:]}\n\n"
        f"Explain these steps: {order}"
    )
    explained = {}
    try:
        text = llm.chat([{"role": "system", "content": EXPLAIN_SYSTEM}, {"role": "user", "content": user}],
                        purpose="ranker", meter=f"rank-{run['id']}", mock_ctx={"trace": trace, "order": order},
                        max_tokens=1400)
        parsed = llm.extract_json(text) or {}
        for item in parsed.get("steps", parsed.get("ranking", [])):
            try:
                explained[int(item.get("step"))] = item
            except (TypeError, ValueError):
                continue
    except llm.LLMError:
        pass  # the rule and HOW_USED still stand without the explanations
    ranking = []
    for i in order:
        kind = step_kind(trace[i])
        item = explained.get(i, {})
        ranking.append({
            "step": i, "kind": kind, "how_used": HOW_USED[kind],
            "why_plain": str(item.get("why_plain", "")).strip(),
            "why_technical": str(item.get("why_technical", "")).strip(),
        })
    return ranking


def summarize_steps(run_id):
    run = runs.get_run(run_id)
    if run is None or run["status"] != "done":
        raise ValueError("The run must finish first.")
    if run.get("summaries"):
        return run["summaries"]
    out = {}
    for s in run["trace"]:
        if s["agent"] == "user":
            out[str(s["i"])] = "You asked the AI team: " + s["content"][:160] + ("…" if len(s["content"]) > 160 else "")
        elif s["agent"] == "release":
            from . import actions
            spec = actions.TOOLS.get(s["data"].get("tool"), {})
            verb = spec.get("label", "Release action")
            out[str(s["i"])] = (f"{verb} was held, so nothing happened." if s["data"].get("status") == "held"
                                else f"{verb}: done." + (" This can't be undone." if spec.get("irreversible") else ""))
        elif s["agent"] == "tests":
            r = s["data"].get("result", {})
            if r.get("error"):
                out[str(s["i"])] = "The tests could not run."
            elif r.get("ok"):
                out[str(s["i"])] = f"The quick check passed ({r['passed']} of {r['total']} tests)."
            else:
                out[str(s["i"])] = f"The quick check failed ({r.get('passed')} of {r.get('total')} tests passed)."
    agent_steps = [s for s in run["trace"] if s["agent"] in ("planner", "coder")]
    if agent_steps:
        try:
            text = llm.chat([{"role": "system", "content": SUMMARY_SYSTEM},
                             {"role": "user", "content": _compact(agent_steps)}],
                            purpose="summary", meter=f"sum-{run_id}", mock_ctx={"trace": agent_steps}, max_tokens=900)
            parsed = llm.extract_json(text) or {}
        except llm.LLMError:
            parsed = {}
        for s in agent_steps:
            sentence = str(parsed.get(str(s["i"]), "")).strip()
            out[str(s["i"])] = sentence or _fallback(s)
    runs.update_run(run_id, summaries=out)
    return out


def _fallback(step):
    first = step["content"].split(". ")[0][:140]
    return ("The planner said: " if step["agent"] == "planner" else "The coder: ") + first
