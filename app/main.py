"""HTTP API + static UI. Start with:  python -m uvicorn app.main:app --port 8000"""
import copy

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import actions, config, evidence, llm, runs, sandbox, scenarios, study

app = FastAPI(title="Agent Verifier")
STATIC = config.ROOT / "static"


# ------------------------------------------------------------ helpers
def _participant_view_run(rec):
    rec = copy.deepcopy(rec)
    rec.pop("plant", None)
    rec["has_ranking"] = bool(rec.pop("ranking_true", None))
    # If this replay belongs to a verification with a planted overstatement,
    # show the outcome the participant was told, so opening a try doesn't contradict it.
    if rec.get("kind") == "replay" and rec.get("verification_id") and rec.get("outcome"):
        v = runs.get_verification(rec["verification_id"])
        if v and v.get("result") and v["result"].get("planted"):
            row = next((r for r in _participant_view_verification(v)["result"]["replays"] if r["run_id"] == rec["id"]), None)
            if row and row["ok"] and not rec["outcome"]["ok"]:
                total = rec["outcome"]["total"]
                rec["outcome"].update(ok=True, passed=total, failed_tests=[], output="")
    return rec


def _participant_view_verification(v):
    v = copy.deepcopy(v)
    v.pop("plant", None)
    res = v.get("result")
    if res:
        extra = res["k"] - res["true_k"]
        for row in res["replays"]:  # keep the detail table consistent with the shown count
            if extra > 0 and not row["ok"] and row["status"] == "done":
                row["ok"], row["failed_tests"], extra = True, [], extra - 1
                total = row["hidden"].split("/")[1] if row["hidden"] else "?"
                row["hidden"] = f"{total}/{total}"
        res.pop("true_k", None)
        res.pop("planted", None)
    return v


def _404(what):
    raise HTTPException(status_code=404, detail=f"{what} not found")


# ------------------------------------------------------------ models
class NewRun(BaseModel):
    scenario_id: str


class VerifyReq(BaseModel):
    step: int
    text: str = Field(min_length=1, max_length=4000)
    n: int = config.DEFAULT_REPLAYS
    participant: str | None = None
    task_index: int | None = None          # set by the session runner
    pre_confidence: int | None = Field(default=None, ge=1, le=7)
    action_policy: dict[str, str] | None = None   # Feature 3: {tool: "run" | "hold"}
    want_baseline: bool = False                    # also make sure a no-change baseline exists for this step


class BaselineReq(BaseModel):
    step: int
    n: int = config.BASELINE_REPLAYS


class EventReq(BaseModel):
    event: str = Field(min_length=1, max_length=60)
    participant: str | None = None
    task_index: int | None = None
    run_id: str | None = None
    data: dict = Field(default_factory=dict)


class ConfidenceReq(BaseModel):
    rating: int = Field(ge=1, le=7)
    participant: str | None = None


class PlantReq(BaseModel):
    rank_move_to_step: int | None = None
    verify_overstate_by: int = Field(default=0, ge=0, le=5)


# ------------------------------------------------------------ routes
@app.get("/api/config")
def get_config():
    return {
        "provider": config.LLM_PROVIDER, "model": config.LLM_MODEL, "sandbox": config.SANDBOX,
        "default_replays": config.DEFAULT_REPLAYS, "max_replays": config.MAX_REPLAYS,
        "max_rounds": config.MAX_ROUNDS,
        "release_actions": config.RELEASE_ACTIONS, "tools": actions.public_tools(),
        "min_replays": config.MIN_REPLAYS, "baseline_replays": config.BASELINE_REPLAYS,
        "study_mode": config.STUDY_MODE,
    }


@app.get("/api/sandbox/check")
def sandbox_check():
    res = sandbox.run_tests(
        {"m.py": "def f():\n    return 1\n",
         "test_m.py": "import unittest\nfrom m import f\nclass T(unittest.TestCase):\n    def test(self):\n        self.assertEqual(f(), 1)\n"},
        ["test_m.py"])
    return {"ok": res["ok"], "detail": res.get("error") or "Sandbox works."}


@app.get("/api/scenarios")
def get_scenarios():
    return scenarios.all_scenarios()


@app.get("/api/runs")
def get_runs():
    return runs.list_runs()


@app.post("/api/runs")
def new_run(req: NewRun):
    try:
        scenarios.load(req.scenario_id)
    except FileNotFoundError:
        _404("Scenario")
    return {"id": runs.start_run(req.scenario_id)}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, researcher: bool = False):
    rec = runs.get_run(run_id) or _404("Run")
    rec["editable_steps"] = runs.editable_steps(rec["trace"])
    return rec if researcher else _participant_view_run(rec)


def _session_plant(pid, task_index):
    if not config.STUDY_MODE:
        return {}  # never plant outside study mode (an empty dict also overrides per-run plants)
    return study.plant_for(pid, task_index) if pid and study.task(pid, task_index) else None


@app.post("/api/runs/{run_id}/rank")
def rank(run_id: str, researcher: bool = False, participant: str | None = None, task_index: int | None = None,
         restore: bool = False):
    runs.get_run(run_id) or _404("Run")
    try:
        result = evidence.rank_steps(run_id, _session_plant(participant, task_index))
    except (ValueError, llm.LLMError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not researcher:
        if not restore:  # restore = re-showing a suggestion this person already asked for
            study.log("suggestion_shown", participant=participant, run_id=run_id,
                      task=task_index + 1 if task_index is not None else None,
                      shown_steps=[r["step"] + 1 for r in result["ranking"]],
                      true_steps=[r["step"] + 1 for r in result["true_ranking"]], planted=result["planted"])
        return {"ranking": result["ranking"]}
    return result


@app.post("/api/runs/{run_id}/summaries")
def summaries(run_id: str):
    runs.get_run(run_id) or _404("Run")
    try:
        return evidence.summarize_steps(run_id)
    except (ValueError, llm.LLMError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/runs/{run_id}/verify")
def verify(run_id: str, req: VerifyReq):
    rec = runs.get_run(run_id) or _404("Run")
    if rec["status"] != "done":
        raise HTTPException(status_code=400, detail="Wait for the run to finish before changing it.")
    plant = _session_plant(req.participant, req.task_index)
    context = {"task": req.task_index + 1} if req.participant and study.task(req.participant, req.task_index) else {}
    shown_top = true_top = None
    if rec.get("ranking_true") and rec.get("ranking_version") == evidence.RANKING_VERSION:  # cached: no LLM call
        ranking = evidence.rank_steps(run_id, plant)
        shown_top, true_top = ranking["ranking"][0]["step"] + 1, ranking["true_ranking"][0]["step"] + 1
    try:
        policy = {k: v for k, v in (req.action_policy or {}).items() if k in actions.TOOLS and v in ("run", "hold")}
        vid = runs.start_verification(run_id, req.step, req.text.strip(), req.n, req.participant,
                                      plant=plant, pre_confidence=req.pre_confidence, context=context,
                                      action_policy=policy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if req.want_baseline:  # queued after the person's own tries, so their result isn't delayed
        runs.ensure_baseline(run_id, req.step, config.BASELINE_REPLAYS)
    study.log("replay_started", participant=req.participant, run_id=run_id, verification_id=vid,
              step=req.step + 1, n=req.n, pre_rating=req.pre_confidence,
              original_text=rec["trace"][req.step]["content"], edit_text=req.text.strip(),
              suggested_top_step=shown_top, true_top_step=true_top,
              edited_suggested_step=(req.step + 1 == shown_top) if shown_top else None,
              held_actions=[k for k, v in (req.action_policy or {}).items() if v == "hold"] or None, **context)
    return {"id": vid}


@app.get("/api/runs/{run_id}/effects")
def run_effects(run_id: str, participant: str | None = None, task_index: int | None = None):
    """Feature 3: what the release steps did for this run's family (simulated world)."""
    rec = runs.get_run(run_id) or _404("Run")
    root = rec.get("root_run_id") or rec["id"]
    items = runs.effects_for(root, participant, task_index + 1 if task_index is not None else None)
    counts = {}
    for e in items:
        key = f"{e['tool']}:{e['status']}"
        counts[key] = counts.get(key, 0) + 1
    return {"root_run_id": root, "effects": items, "counts": counts}


@app.get("/api/runs/{run_id}/baselines")
def get_baselines(run_id: str):
    """No-change replays per editable step: {step: {k, n, running}}, pooled. Always the true results."""
    runs.get_run(run_id) or _404("Run")
    return {str(k): v for k, v in runs.baseline_summary(run_id).items()}


@app.post("/api/runs/{run_id}/baseline")
def make_baseline(run_id: str, req: BaselineReq):
    rec = runs.get_run(run_id) or _404("Run")
    if rec["status"] != "done":
        raise HTTPException(status_code=400, detail="Wait for the run to finish first.")
    if req.step not in runs.editable_steps(rec["trace"]):
        raise HTTPException(status_code=400, detail="Baselines are only for editable steps.")
    vid = runs.ensure_baseline(run_id, req.step, max(1, min(req.n, config.MAX_REPLAYS)))
    return {"started": vid, "summary": runs.baseline_summary(run_id).get(req.step)}


@app.get("/api/runs/{run_id}/verifications")
def run_verifications(run_id: str, researcher: bool = False):
    items = sorted((v for v in runs.list_verifications(run_id) if researcher or not runs.is_baseline(v)),
                   key=lambda v: v["created"])
    return items if researcher else [_participant_view_verification(v) for v in items]


@app.get("/api/verifications/{vid}")
def get_verification(vid: str, researcher: bool = False):
    v = runs.get_verification(vid) or _404("Verification")
    return v if researcher else _participant_view_verification(v)


@app.get("/api/verifications/{vid}/progress")
def verification_progress(vid: str):
    return runs.verification_progress(vid) or _404("Verification")


@app.post("/api/verifications/{vid}/confidence")
def confidence(vid: str, req: ConfidenceReq):
    runs.get_verification(vid) or _404("Verification")
    return runs.record_confidence(vid, req.rating, req.participant)


@app.post("/api/runs/{run_id}/plant")
def plant(run_id: str, req: PlantReq):
    if not config.STUDY_MODE:
        raise HTTPException(status_code=403, detail="Planted errors only work with STUDY_MODE=on in .env.")
    runs.get_run(run_id) or _404("Run")
    runs.update_run(run_id, plant=req.model_dump())
    return {"ok": True, "plant": req.model_dump()}


# ------------------------------------------------------------ study sessions
@app.post("/api/events")
def log_event(req: EventReq):
    study.log(req.event, participant=req.participant, run_id=req.run_id,
              task=req.task_index + 1 if req.task_index is not None else None, **req.data)
    return {"ok": True}


@app.get("/api/session/{pid}")
def get_session(pid: str):
    p = study.participant(pid) or _404(f"A study plan for {pid}")
    problems = [x for x in study.check_plan(runs.get_run) if x.startswith(f"{pid} ") or x.startswith(f"{pid}:")]
    return {"pid": pid, "tasks": [study.public_task(t, i) for i, t in enumerate(p["tasks"])],
            "progress": study.progress(pid), "problems": problems}


@app.post("/api/session/{pid}/tasks/{index}/start")
def start_session_task(pid: str, index: int):
    t = study.task(pid, index) or _404("Task")
    prog = study.start_task(pid, index)
    plant = study.plant_for(pid, index)
    study.log("task_started", participant=pid, task=index + 1, run_id=t["run_id"],
              tool=t.get("tool", "on"), mode=t.get("mode", "simple"), practice=bool(t.get("practice")),
              planted_suggest_step=plant["rank_move_to_step"] + 1 if plant["rank_move_to_step"] is not None else None,
              planted_overstate=plant["verify_overstate_by"] or None,
              warn_actions=study.public_task(t, index)["warn_actions"] if config.RELEASE_ACTIONS else None)
    return prog


@app.post("/api/session/{pid}/tasks/{index}/finish")
def finish_session_task(pid: str, index: int):
    t = study.task(pid, index) or _404("Task")
    mine = [v for v in runs.list_verifications(t["run_id"])
            if v.get("participant") == pid and (v.get("context") or {}).get("task") == index + 1]
    last = max(mine, key=lambda v: v["created"]) if mine else None
    started = study.progress(pid)["tasks"].get(str(index), {}).get("started")
    prog = study.finish_task(pid, index)
    study.log("task_finished", participant=pid, task=index + 1, run_id=t["run_id"],
              seconds=round(prog["tasks"][str(index)]["finished"] - started) if started else None,
              attempts=len(mine),
              last_step=last["step"] + 1 if last else None,
              last_shown_k=last["result"]["k"] if last and last.get("result") else None,
              last_true_k=last["result"]["true_k"] if last and last.get("result") else None,
              last_n=last["n"] if last else None)
    return prog


@app.get("/api/plan/check")
def plan_check():
    found = study.check_plan(runs.get_run)
    for r in runs.list_runs():  # leftover per-run plants (from ?researcher=1) would affect anyone using that run
        p = (runs.get_run(r["id"]) or {}).get("plant") or {}
        if p.get("rank_move_to_step") is not None or p.get("verify_overstate_by"):
            found.append(f"Warning: run {r['id']} has a per-run planted error set in the researcher panel.")
    problems = [x for x in found if not x.startswith("Warning:")]
    return {"ok": not problems, "problems": problems, "warnings": [x for x in found if x.startswith("Warning:")]}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
