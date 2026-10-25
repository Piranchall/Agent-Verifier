"""Offline stand-in for the LLM (LLM_PROVIDER=mock).

Lets the team build and test the UI without spending free-tier quota. It is
random on purpose so replays disagree, and it responds to steering: if the
task or the Planner's instruction contains one of the scenario's hint
phrases, the Coder is much more likely to write the correct fix.
Never use mock mode for real study sessions.
"""
import json
import random
import re
import time

from . import config


def _hinted(scenario, *texts):
    blob = " ".join(t or "" for t in texts).lower()
    return any(re.search(p, blob) for p in scenario["mock"]["hint_patterns"])


def respond(purpose, ctx):
    time.sleep(config.MOCK_DELAY)
    return {"plan": _plan, "planner": _planner, "coder": _coder, "ranker": _ranker, "summary": _summary}[purpose](ctx)


def _plan(ctx):
    return json.dumps({"plan": [
        "Find the code behind the feature the user describes.",
        "Change it so the main case in the request works.",
        "Tidy up the change and keep the rest of the code as it was.",
    ]})


def _planner(ctx):
    state = ctx["state"]
    if ctx.get("fixup"):
        failing = ", ".join((state.get("last_test") or {}).get("failed_tests") or []) or "the visible test"
        instruction = f"The plan is done but {failing} still fails. Look at the test output and correct the code."
    else:
        k = ctx.get("plan_step", 1)
        instruction = f"Carry out plan step {k}: {state['plan'][k - 1]}"
    return json.dumps({"instruction": instruction})


def _coder(ctx):
    s, state = ctx["scenario"], ctx["state"]
    hinted = _hinted(s, ctx["instruction"], state["task"], ctx.get("plan_text"))
    p_good = s["mock"]["p_good_hinted"] if hinted else s["mock"]["p_good_base"]
    r = random.random()
    if state["files"] == s["mock_variants"]["mock_good"]:
        files, note = state["files"], "Checked the code; it already does what the step asks."
    elif r < p_good:
        files, note = s["mock_variants"]["mock_good"], "Rewrote the method so it uses the right items."
    elif r < p_good + 0.15:
        files, note = state["files"], "Tidied the method; logic is unchanged."
    else:
        files, note = s["mock_variants"]["mock_bad"], "Adjusted the method so the visible test passes."
    blocks = "".join(f"=== FILE: {n} ===\n{body.rstrip()}\n=== END FILE ===\n" for n, body in files.items())
    return f"NOTE: {note}\n{blocks}"


def _ranker(ctx):
    return json.dumps({"steps": [{
        "step": i,
        "why_plain": "Say clearly what the app must remember so later steps keep it.",
        "why_technical": "State the invariant the hidden checks test, so every later coder step preserves it.",
    } for i in ctx.get("order", [])]})


def _summary(ctx):
    out = {}
    for s in ctx["trace"]:
        if s["agent"] == "planner" and s["data"].get("kind") == "plan":
            out[str(s["i"])] = "The planner split the work into steps."
        elif s["agent"] == "planner":
            out[str(s["i"])] = "The planner told the coder what to change next."
        elif s["agent"] == "coder":
            out[str(s["i"])] = "The coder changed the code."
    return json.dumps(out)
