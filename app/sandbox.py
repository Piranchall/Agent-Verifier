"""Runs a scenario's unit tests against the agents' code.

Docker mode (default): code goes into a throwaway container over stdin, so no
folders are mounted (avoids Windows path issues), networking is off, and memory
and process counts are capped. Nothing the agents write can touch your machine.

Local mode (SANDBOX=local): same runner in a temp folder with your own Python.
Only for development without Docker; the agents' code is NOT isolated.
"""
import json
import subprocess
import sys
import uuid

from . import config

MARKER = "@@RESULT@@"

RUNNER = r'''
import io, json, os, sys, tempfile, unittest
payload = json.loads(sys.stdin.read())
work = tempfile.mkdtemp()
for name, content in payload["files"].items():
    with open(os.path.join(work, name), "w", encoding="utf-8") as fh:
        fh.write(content)
os.chdir(work)
sys.path.insert(0, work)
stream = io.StringIO()
loader = unittest.TestLoader()
suite = unittest.TestSuite()
load_errors = []
for mod in payload["tests"]:
    try:
        suite.addTests(loader.loadTestsFromName(mod))
    except Exception as exc:
        load_errors.append(f"{mod}: {type(exc).__name__}: {exc}")
result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
failed = [str(t[0]).split(" ")[0] for t in result.failures + result.errors]
total = result.testsRun
out = {
    "total": total,
    "passed": total - len(failed),
    "failed_tests": failed,
    "load_errors": load_errors,
    "output": stream.getvalue()[-3000:],
}
print("@@RESULT@@" + json.dumps(out))
'''


def run_tests(files, test_files):
    """files: {name: content}. test_files: list of test file names. Returns a result dict."""
    payload = json.dumps({"files": files, "tests": [t.removesuffix(".py") for t in test_files]})
    name = f"agentverify-{uuid.uuid4().hex[:10]}"
    if config.SANDBOX == "local":
        cmd = [sys.executable, "-c", RUNNER]
    else:
        cmd = [
            "docker", "run", "--rm", "-i", "--name", name,
            "--network", "none", "--memory", "256m", "--cpus", "1", "--pids-limit", "64",
            config.DOCKER_IMAGE, "python", "-c", RUNNER,
        ]
    try:
        proc = subprocess.run(
            cmd, input=payload, capture_output=True, text=True,
            timeout=config.TEST_TIMEOUT, encoding="utf-8",
        )
    except FileNotFoundError:
        return _error("Docker was not found. Start Docker Desktop, or set SANDBOX=local in .env.")
    except subprocess.TimeoutExpired:
        if config.SANDBOX != "local":
            subprocess.run(["docker", "kill", name], capture_output=True)
        return _error(f"Tests took longer than {config.TEST_TIMEOUT}s and were stopped (possible infinite loop).")

    for line in (proc.stdout or "").splitlines():
        if line.startswith(MARKER):
            res = json.loads(line[len(MARKER):])
            res["ok"] = res["total"] > 0 and res["passed"] == res["total"] and not res["load_errors"]
            res["error"] = None
            if res["load_errors"]:
                res["output"] = "\n".join(res["load_errors"]) + "\n" + res["output"]
            return res
    return _error((proc.stderr or proc.stdout or "No output from test runner.")[-2000:])


def _error(message):
    return {"ok": False, "total": 0, "passed": 0, "failed_tests": [], "load_errors": [],
            "output": message, "error": message}
