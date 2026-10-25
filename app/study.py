"""Study sessions: the plan, each participant's progress, and the action log.

The plan lives in study/plan.json (see study/plan.example.json). Each participant
gets an ordered list of tasks; each task starts from a fixed failing run and sets
its own condition (tool on/off, starting view) and planted errors. Planted errors
here apply only to that participant's task, unlike the per-run researcher controls.

Every action goes to data/events.jsonl, one JSON object per line. The server adds
ground truth (true ranking, planted values) to events; participants never see it.
"""
import json
import threading
import time

from . import config

PLAN_PATH = config.ROOT / "study" / "plan.json"
SESSIONS_DIR = config.DATA_DIR / "sessions"
EVENTS_PATH = config.DATA_DIR / "events.jsonl"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
_lock = threading.Lock()


# ------------------------------------------------------------ plan
def load_plan():
    if not PLAN_PATH.exists():
        return {"participants": {}}
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def participant(pid):
    return load_plan().get("participants", {}).get(pid)


def task(pid, index):
    p = participant(pid)
    if not p or index is None or not (0 <= index < len(p["tasks"])):
        return None
    return p["tasks"][index]


def plant_for(pid, index):
    """Planted errors for one participant's task, in internal (0-based) step numbers."""
    t = task(pid, index) or {}
    step = t.get("plant_suggest_step")
    return {
        "rank_move_to_step": int(step) - 1 if step else None,
        "verify_overstate_by": int(t.get("overstate_by") or 0),
    }


def public_task(t, index):
    """What the participant's browser may know about a task (no planted values)."""
    return {"index": index, "run_id": t["run_id"], "tool": t.get("tool", "on"),
            "mode": t.get("mode", "simple"), "minutes": t.get("minutes"),
            "practice": bool(t.get("practice")),
            "warn_actions": bool(t.get("warn_actions", True)) and config.RELEASE_ACTIONS and t.get("tool", "on") == "on"}


# ------------------------------------------------------------ progress
def _progress_path(pid):
    safe = "".join(c for c in pid if c.isalnum() or c in "-_")
    return SESSIONS_DIR / f"{safe}.json"


def progress(pid):
    path = _progress_path(pid)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"pid": pid, "current": 0, "tasks": {}, "finished": False}


def _save_progress(pid, prog):
    _progress_path(pid).write_text(json.dumps(prog, indent=1), encoding="utf-8")


def start_task(pid, index):
    with _lock:
        prog = progress(pid)
        prog["current"] = index
        prog["tasks"].setdefault(str(index), {}).setdefault("started", time.time())
        _save_progress(pid, prog)
    return prog


def finish_task(pid, index):
    p = participant(pid)
    with _lock:
        prog = progress(pid)
        entry = prog["tasks"].setdefault(str(index), {})
        entry.setdefault("started", time.time())
        entry["finished"] = time.time()
        prog["current"] = index + 1
        prog["finished"] = prog["current"] >= len(p["tasks"])
        _save_progress(pid, prog)
    return prog


# ------------------------------------------------------------ events
def log(event, **fields):
    """Append one event for a participant (no-op without one). None values are dropped."""
    if not fields.get("participant"):
        return None
    rec = {"time": time.time(), "event": event}
    rec.update({k: v for k, v in fields.items() if v is not None})
    pid = rec.get("participant")
    if pid and participant(pid):
        rec.setdefault("group", participant(pid).get("group"))
    with _lock, open(EVENTS_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


# ------------------------------------------------------------ plan check
def check_plan(get_run):
    """Return a list of problems with study/plan.json. get_run(id) -> run record or None."""
    if not PLAN_PATH.exists():
        return [f"No plan found at {PLAN_PATH}. Copy study/plan.example.json to study/plan.json."]
    try:
        plan = load_plan()
    except json.JSONDecodeError as exc:
        return [f"plan.json is not valid JSON: {exc}"]
    problems = []
    people = plan.get("participants", {})
    if not people:
        problems.append("The plan has no participants.")
    for pid, p in people.items():
        tasks = p.get("tasks") or []
        if not tasks:
            problems.append(f"{pid}: no tasks.")
        for i, t in enumerate(tasks, 1):
            where = f"{pid} task {i}"
            run = get_run(t.get("run_id", ""))
            if run is None:
                problems.append(f"{where}: run {t.get('run_id')!r} not found.")
                continue
            if run["status"] != "done":
                problems.append(f"{where}: run {run['id']} has not finished ({run['status']}).")
                continue
            if run["outcome"]["ok"]:
                problems.append(f"{where}: run {run['id']} passed, so there is nothing to fix.")
            if t.get("tool", "on") not in ("on", "off"):
                problems.append(f"{where}: tool must be \"on\" or \"off\".")
            if t.get("mode", "simple") not in ("simple", "detailed"):
                problems.append(f"{where}: mode must be \"simple\" or \"detailed\".")
            step = t.get("plant_suggest_step")
            if step:
                editable = [s["i"] + 1 for s in run["trace"] if s["agent"] in ("user", "planner")]
                if int(step) not in editable:
                    problems.append(f"{where}: plant_suggest_step {step} is not an editable step (choose from {editable}).")
            if (t.get("plant_suggest_step") or t.get("overstate_by")) and not config.STUDY_MODE:
                problems.append(f"{where}: planted errors are set but STUDY_MODE is off in .env, so they won't apply.")
            if (t.get("plant_suggest_step") or t.get("overstate_by")) and t.get("tool", "on") == "off":
                problems.append(f"{where}: planted errors have no effect when the tool is off.")
            if t.get("warn_actions") and not config.RELEASE_ACTIONS:
                problems.append(f"{where}: warn_actions is set but RELEASE_ACTIONS is off in .env, so there are no actions.")
            if config.RELEASE_ACTIONS and not any(s["agent"] == "release" for s in run["trace"]):
                problems.append(f"Warning: {where}: run {run['id']} has no release step (it was made before RELEASE_ACTIONS was on, "
                                "or its visible tests failed). Its replays will still release, but the original "
                                "run won't show the deploy and email.")
    return problems
