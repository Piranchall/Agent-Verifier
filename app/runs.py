"""Runs, forks and verifications.

- A run is one execution of the agent team (its own LangGraph thread).
- A fork starts a new thread from the checkpoint right after an edited step.
- A verification forks the same edit N times and reports how many held up
  against the hidden tests (Feature 2).
"""
import copy
import json
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from . import actions, config, llm, sandbox, scenarios, study
from .agents import GRAPH, initial_state, node_for_step, parse_plan

_pool = ThreadPoolExecutor(max_workers=2 if config.LLM_PROVIDER == "mock" else 1)
_lock = threading.Lock()
_runs, _verifs = {}, {}


# ------------------------------------------------------------ persistence
def _save(kind, rec):
    folder = config.RUNS_DIR if kind == "run" else config.VERIFY_DIR
    (folder / f"{rec['id']}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")


def _load_all():
    for path in config.RUNS_DIR.glob("*.json"):
        rec = json.loads(path.read_text(encoding="utf-8"))
        if rec["status"] in ("queued", "running"):
            rec["status"], rec["error"] = "error", "Server stopped while this run was in progress."
        _runs[rec["id"]] = rec
    for path in config.VERIFY_DIR.glob("*.json"):
        rec = json.loads(path.read_text(encoding="utf-8"))
        if rec["status"] in ("queued", "running"):
            rec["status"], rec["error"] = "error", "Server stopped while this verification was in progress."
        _verifs[rec["id"]] = rec


_load_all()


def _new_id(prefix):
    return f"{prefix}-{time.strftime('%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"


def _cfg(thread_id):
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}


# ------------------------------------------------------------ queries
def list_runs():
    with _lock:
        return sorted((_brief(r) for r in _runs.values()), key=lambda r: r["created"])


def _brief(r):
    return {k: r.get(k) for k in ("id", "scenario_id", "created", "status", "parent", "outcome", "kind",
                                  "verification_id", "participant", "root_run_id", "baseline")}


def get_run(run_id):
    rec = _runs.get(run_id)
    if rec is None:
        return None
    rec = copy.deepcopy(rec)
    if rec["status"] == "running":  # live view straight from the checkpoint
        snap = GRAPH.get_state(_cfg(run_id))
        if snap and snap.values:
            rec["trace"] = snap.values.get("trace", rec["trace"])
    rec["usage"] = llm.usage(run_id)
    return rec


def get_verification(vid):
    return copy.deepcopy(_verifs.get(vid))


def list_verifications(run_id=None):
    return [copy.deepcopy(v) for v in _verifs.values() if run_id is None or v["base_run_id"] == run_id]


# ------------------------------------------------------------ running
def _make_run(scenario_id, kind, parent=None, verification_id=None, participant=None, baseline=False):
    parent_rec = _runs.get(parent["run_id"]) if parent else None
    rec = {
        "participant": participant, "baseline": baseline,
        "id": _new_id("run"), "scenario_id": scenario_id, "kind": kind,
        "created": time.time(), "status": "queued", "error": None,
        "parent": parent, "verification_id": verification_id,
        "trace": [], "final_files": {}, "outcome": None,
    }
    # The original run a family of forks descends from (Feature 3 groups effects by it).
    rec["root_run_id"] = (parent_rec.get("root_run_id") or parent_rec["id"]) if parent_rec else rec["id"]
    with _lock:
        _runs[rec["id"]] = rec
    _save("run", rec)
    return rec


def _execute(rec, start):
    """start(): prepares the thread and returns the input for GRAPH.invoke."""
    rec["status"] = "running"
    rec["started"] = time.time()
    _save("run", rec)
    try:
        payload = start()
        final = GRAPH.invoke(payload, _cfg(rec["id"]))
        s = scenarios.load(rec["scenario_id"])
        hidden = sandbox.run_tests({**final["files"], **s["hidden_test_files"]}, s["hidden_tests"])
        rec.update(trace=final["trace"], final_files=final["files"], status="done", outcome={
            "ok": hidden["ok"], "passed": hidden["passed"], "total": hidden["total"],
            "failed_tests": hidden["failed_tests"], "output": hidden["output"], "error": hidden.get("error"),
            "rounds": final["round"], "stopped_because": _stop_reason(final),
        })
    except Exception as exc:
        snap = GRAPH.get_state(_cfg(rec["id"]))
        if snap and snap.values:
            rec["trace"] = snap.values.get("trace", rec["trace"])
        rec.update(status="error", error=f"{type(exc).__name__}: {exc}")
    rec["usage"] = llm.usage(rec["id"])
    rec["finished"] = time.time()
    _save("run", rec)
    return rec


def _stop_reason(final):
    if final["last_test"].get("ok"):
        return "the plan was done and the visible tests passed"
    return "the plan and the fix-up round were done but the visible tests still failed"


def start_run(scenario_id):
    rec = _make_run(scenario_id, "original")
    _pool.submit(_execute, rec, lambda: initial_state(scenario_id))
    return rec["id"]


def editable_steps(trace):
    return [s["i"] for s in trace if s["agent"] in ("user", "planner")]


def _fork_start(base_id, step, text, new_id, action_policy=None):
    """Return a start() that seeds thread new_id with the base run's state just after
    `step`, with that step's text replaced. Execution resumes from that point."""
    base = _runs[base_id]

    def start():
        if step == 0:
            state = initial_state(base["scenario_id"], task=text)
            state["trace"][0]["edited"] = True
            state["action_policy"] = dict(action_policy or {})
            return state
        for snap in GRAPH.get_state_history(_cfg(base_id)):
            tr = snap.values.get("trace") or []
            if len(tr) == step + 1 and tr[-1]["agent"] == "planner":
                values = copy.deepcopy(snap.values)
                break
        else:
            raise RuntimeError(f"No checkpoint found for step {step} of {base_id}.")
        target = values["trace"][step]
        target.update(content=text, edited=True)
        target["data"]["original"] = base["trace"][step]["content"]
        values["action_policy"] = dict(action_policy or {})
        node = node_for_step(target)
        if node == "plan":  # an edited plan replaces the plan the team will carry out
            items = parse_plan(text)
            target["data"]["items"] = items
            values.update(plan=items, plan_index=0)
        GRAPH.update_state(_cfg(new_id), values, as_node=node)
        return None  # resume the forked thread

    return start


# ------------------------------------------------------------ verification
def start_verification(base_id, step, text, n, participant=None, plant=None, pre_confidence=None, context=None,
                       action_policy=None, baseline=False):
    """plant (from a session task) overrides the base run's own researcher plant.
    Plants only apply in STUDY_MODE; otherwise the shown result is always the true one."""
    base = _runs[base_id]
    source = plant if plant is not None else (base.get("plant") or {})
    overstate = int(source.get("verify_overstate_by") or 0) if config.STUDY_MODE and not baseline else 0
    plant = {"overstate_by": overstate}
    if step not in editable_steps(base["trace"]):
        raise ValueError("Only the task and Planner instructions can be edited.")
    n = max(1, min(int(n), config.MAX_REPLAYS))
    v = {
        "id": _new_id("ver"), "base_run_id": base_id, "scenario_id": base["scenario_id"],
        "step": step, "original_text": base["trace"][step]["content"], "text": text,
        "n": n, "created": time.time(), "status": "queued", "error": None,
        "replay_ids": [], "result": None, "plant": plant, "confidence": [], "participant": participant,
        "pre_confidence": pre_confidence, "context": context or {}, "action_policy": action_policy or {},
        "baseline": baseline,
    }
    with _lock:
        _verifs[v["id"]] = v
    _save("ver", v)
    _pool.submit(_run_verification, v)
    return v["id"]


def _run_verification(v):
    v["status"] = "running"
    _save("ver", v)
    try:
        for _ in range(v["n"]):
            rec = _make_run(v["scenario_id"], "replay",
                            parent={"run_id": v["base_run_id"], "step": v["step"]}, verification_id=v["id"],
                            participant=v.get("participant"), baseline=bool(v.get("baseline")))
            v["replay_ids"].append(rec["id"])
            _save("ver", v)
            _execute(rec, _fork_start(v["base_run_id"], v["step"], v["text"], rec["id"], v.get("action_policy")))
            for st in rec["trace"]:
                if st["agent"] == "release":
                    study.log("action_" + st["data"]["status"], participant=v.get("participant"),
                              verification_id=v["id"], run_id=rec["id"], tool=st["data"]["tool"],
                              irreversible=st["data"]["irreversible"], **(v.get("context") or {}))
        v["result"] = summarize(v)
        v["status"] = "done"
        study.log("replays_finished", participant=v.get("participant"), verification_id=v["id"],
                  base_run_id=v["base_run_id"], step=v["step"] + 1, n=v["result"]["n"],
                  shown_k=v["result"]["k"], true_k=v["result"]["true_k"], planted_overstate=v["result"]["planted"],
                  **(v.get("context") or {}))
    except Exception as exc:
        v.update(status="error", error=f"{type(exc).__name__}: {exc}")
        study.log("replays_failed", participant=v.get("participant"), verification_id=v["id"], error=v["error"])
    _save("ver", v)


def _signature(step):
    d = step["data"]
    if step["agent"] == "planner":
        return f"planner:{d.get('decision')}"
    if step["agent"] == "coder":
        return f"coder:{d.get('code_hash')}"
    if step["agent"] == "tests":
        r = d.get("result", {})
        return f"tests:{r.get('passed')}/{r.get('total')}"
    if step["agent"] == "release":
        return f"release:{d.get('tool')}:{d.get('status')}"
    return step["agent"]


def summarize(v):
    """Feature 2: how many replays held up, and where the replays went different ways."""
    replays = [_runs[r] for r in v["replay_ids"]]
    done = [r for r in replays if r["status"] == "done"]
    k = sum(1 for r in done if r["outcome"]["ok"])
    ref = [_signature(s) for s in done[0]["trace"]] if done else []
    rows = []
    for idx, r in enumerate(replays):
        sig = [_signature(s) for s in r["trace"]]
        diverge = None
        if idx > 0 and r["status"] == "done":
            for j in range(v["step"] + 1, max(len(sig), len(ref))):
                if j >= len(sig) or j >= len(ref) or sig[j] != ref[j]:
                    diverge = j
                    break
        final_hash = next((s["data"].get("code_hash") for s in reversed(r["trace"]) if s["agent"] == "coder"), None)
        rows.append({
            "run_id": r["id"], "status": r["status"], "error": r.get("error"),
            "ok": bool(r["outcome"] and r["outcome"]["ok"]),
            "hidden": f"{r['outcome']['passed']}/{r['outcome']['total']}" if r["outcome"] else None,
            "failed_tests": r["outcome"]["failed_tests"] if r["outcome"] else [],
            "steps": len(r["trace"]), "rounds": r["outcome"]["rounds"] if r["outcome"] else None,
            "stopped_because": r["outcome"]["stopped_because"] if r["outcome"] else None,
            "diverges_from_first_at": diverge, "final_code": final_hash,
        })
    versions = Counter(row["final_code"] for row in rows if row["final_code"])
    true_k = k
    shown_k = min(len(replays), true_k + int(v["plant"].get("overstate_by", 0)))
    return {"k": shown_k, "n": len(replays), "true_k": true_k, "errors": len(replays) - len(done),
            "planted": shown_k != true_k, "replays": rows, "distinct_final_code": len(versions)}


def record_confidence(vid, rating, participant=None):
    v = _verifs[vid]
    entry = {"rating": int(rating), "participant": participant, "time": time.time(),
             "shown_k": v["result"]["k"] if v["result"] else None,
             "true_k": v["result"]["true_k"] if v["result"] else None, "n": v["n"]}
    v["confidence"].append(entry)
    _save("ver", v)
    study.log("rating_after", participant=participant, verification_id=vid, base_run_id=v["base_run_id"],
              step=v["step"] + 1, rating=entry["rating"], pre_rating=v.get("pre_confidence"),
              shown_k=entry["shown_k"], true_k=entry["true_k"], n=entry["n"], **(v.get("context") or {}))
    return entry


def update_run(run_id, **fields):
    rec = _runs[run_id]
    rec.update(fields)
    _save("run", rec)


def effects_for(root_run_id, participant=None, task=None):
    """Feature 3: what the release steps did in this family of runs.
    In a session, only the original run's effects plus this participant's own tries for this task."""
    out = []
    for eff in actions.all_effects():
        run = _runs.get(eff["run_id"])
        if not run or (run.get("root_run_id") or run["id"]) != root_run_id:
            continue
        if participant and run["kind"] == "replay":
            v = _verifs.get(run.get("verification_id")) or {}
            if v.get("participant") != participant:
                continue
            if task is not None and (v.get("context") or {}).get("task") != task:
                continue
        out.append({**eff, "kind": run["kind"]})
    return out


# ------------------------------------------------------------ no-change baselines
def is_baseline(v):
    """A no-change replay: made as a baseline, or (e.g. by calibration) with the step's text left as it was."""
    if v.get("baseline"):
        return True
    return not v.get("participant") and v.get("text", "").strip() == v.get("original_text", "").strip()


def baseline_summary(run_id):
    """{step: {"k", "n", "running"}} pooled over every no-change replay set at that step."""
    out = {}
    for v in _verifs.values():
        if v["base_run_id"] != run_id or not is_baseline(v):
            continue
        row = out.setdefault(v["step"], {"k": 0, "n": 0, "running": False})
        if v["status"] == "done" and v.get("result"):
            done = [r for r in v["result"]["replays"] if r["status"] == "done"]
            row["k"] += sum(1 for r in done if r["ok"])
            row["n"] += len(done)
        elif v["status"] in ("queued", "running"):
            row["running"] = True
    return out


def ensure_baseline(run_id, step, n):
    """Start no-change replays for (run, step) unless some already exist or are under way."""
    existing = baseline_summary(run_id).get(step)
    if existing and (existing["n"] or existing["running"]):
        return None
    base = _runs[run_id]
    hold_all = {tool: "hold" for tool in actions.TOOLS}  # a baseline must never touch the world
    return start_verification(run_id, step, base["trace"][step]["content"], n, plant={},
                              action_policy=hold_all, baseline=True)


# ------------------------------------------------------------ live progress
def verification_progress(vid):
    """What each try is doing right now, for the waiting screen. No pass/fail: results are
    shown together at the end (one lucky try shouldn't decide, and planted results need it)."""
    v = _verifs.get(vid)
    if v is None:
        return None
    tries = []
    for k in range(v["n"]):
        rid = v["replay_ids"][k] if k < len(v["replay_ids"]) else None
        rec = _runs.get(rid) if rid else None
        row = {"index": k + 1, "run_id": rid, "status": rec["status"] if rec else "waiting",
               "steps": len(rec["trace"]) if rec else 0, "next": [], "plan_index": None, "plan_len": None,
               "elapsed": None}
        if rec and rec["status"] == "running":
            snap = GRAPH.get_state(_cfg(rid))
            if snap and snap.values:
                row["steps"] = len(snap.values.get("trace") or [])
                row["next"] = list(snap.next or [])
                row["plan_index"] = snap.values.get("plan_index")
                row["plan_len"] = len(snap.values.get("plan") or [])
            row["elapsed"] = round(time.time() - rec.get("started", time.time()))
        tries.append(row)
    durations = [_runs[r]["finished"] - _runs[r]["started"] for r in v["replay_ids"]
                 if r in _runs and _runs[r].get("finished") and _runs[r].get("started")]
    eta = None
    if durations:
        avg = sum(durations) / len(durations)
        left = sum(1 for t in tries if t["status"] in ("waiting", "queued"))
        running = [t for t in tries if t["status"] == "running"]
        eta = round(avg * left + sum(max(0.0, avg - (t["elapsed"] or 0)) for t in running))
    # Is a no-change baseline queued behind these tries?
    base = baseline_summary(v["base_run_id"]).get(v["step"]) if not v.get("baseline") else None
    busy_ahead = sum(1 for x in _verifs.values()
                     if x["status"] in ("queued", "running") and x["created"] < v["created"] and x["id"] != vid)
    return {"status": v["status"], "tries": tries, "eta_seconds": eta,
            "baseline_pending": bool(base and base["running"]), "waiting_behind": busy_ahead}
