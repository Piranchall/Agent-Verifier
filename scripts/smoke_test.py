"""Checks the whole loop offline: run, rank, edit, replay, verify.
Usage (from the project folder):  python scripts/smoke_test.py
Forces mock agents and local tests, so it needs no API key or Docker."""
import os
import sys
import time

os.environ.update(LLM_PROVIDER="mock", SANDBOX="local", MOCK_DELAY="0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

c = TestClient(app)


def wait(path):
    while True:
        r = c.get(path).json()
        if r["status"] in ("done", "error"):
            return r
        time.sleep(0.1)


print("sandbox:", c.get("/api/sandbox/check").json())
for _ in range(20):
    rid = c.post("/api/runs", json={"scenario_id": "todo_delete"}).json()["id"]
    run = wait(f"/api/runs/{rid}")
    assert run["status"] == "done", run.get("error")
    if not run["outcome"]["ok"]:
        break
else:
    sys.exit("No failing run in 20 tries (mock is random); run again.")
print("failing run:", rid, f"{len(run['trace'])} steps")
print("ranking:", [x["step"] for x in c.post(f"/api/runs/{rid}/rank").json()["ranking"]])
for text in ["Fix it properly.", "Find the task by its id field, not by its position."]:
    vid = c.post(f"/api/runs/{rid}/verify", json={"step": 1, "text": text, "n": 5}).json()["id"]
    v = wait(f"/api/verifications/{vid}")
    assert v["status"] == "done", v.get("error")
    print(f"edit {text!r}: worked in {v['result']['k']} of {v['result']['n']} tries")
print("OK")

# Scenario sanity: mock hints must come from steering edits, never from the request itself.
import glob  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402

for path in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "scenarios", "*", "scenario.json"))):
    meta = json.load(open(path, encoding="utf-8"))
    pats = meta["mock"]["hint_patterns"]
    assert not any(re.search(p, meta["task"].lower()) for p in pats), f"{meta['id']}: a mock hint appears in the request"
    if meta.get("good_edit"):
        assert any(re.search(p, meta["good_edit"]["text"].lower()) for p in pats), f"{meta['id']}: good_edit has no mock hint"
print("scenario files OK")

# Every hidden test has a plain-language description (shown to people as the acceptance checks).
for path in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "scenarios", "*", "scenario.json"))):
    meta = json.load(open(path, encoding="utf-8"))
    if "checks" in meta:
        hidden = open(os.path.join(os.path.dirname(path), "test_hidden.py"), encoding="utf-8").read()
        names = set(re.findall(r"def (test_\w+)", hidden))
        assert names == set(meta["checks"]), f"{meta['id']}: checks don't match test_hidden.py: {names ^ set(meta['checks'])}"
print("check descriptions OK")
