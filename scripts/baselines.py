"""Precompute no-change baselines for the runs you will use in sessions.

The app shows "Your change: k of n. Without your change: b of m." The "without"
part comes from replaying the run from that step with the step left unchanged.
If it isn't ready when a participant replays, the app computes it after their
tries, so they wait longer. Precomputing avoids that.

Usage (the app must be running):
    .venv\\Scripts\\python scripts\\baselines.py run-1025-175821-d89e run-1025-210012-974f
    .venv\\Scripts\\python scripts\\baselines.py run-... --steps plan          (only the plan step)
    .venv\\Scripts\\python scripts\\baselines.py run-... --tries 3

Cost: replaying from the request repeats the whole run (about 8 LLM calls per try);
later steps are cheaper. All editable steps x 3 tries is roughly 80 calls per run.
Steps that already have a baseline (including calibration's no-change replays) are skipped.
"""
import argparse
import json
import time
import urllib.error
import urllib.request

def call(base, path, body=None):
    req = urllib.request.Request(base + path, method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{path}: {exc.code} {exc.read().decode()[:300]}")
    except urllib.error.URLError:
        raise SystemExit(f"Can't reach {base}. Start the app first (run.bat).")


def describe(step):
    if step["agent"] == "user":
        return "request"
    if step["data"].get("kind") == "plan":
        return "plan"
    return f"instruction {step['data'].get('plan_step', '')}".strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="run ids")
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--steps", choices=["all", "plan"], default="all")
    ap.add_argument("--tries", type=int, default=3)
    args = ap.parse_args()

    for rid in args.runs:
        run = call(args.url, f"/api/runs/{rid}")
        steps = [s for s in run["trace"] if s["i"] in run["editable_steps"]]
        if args.steps == "plan":
            steps = [s for s in steps if s["data"].get("kind") == "plan"]
        print(f"\n== {rid} ({run['scenario_id']})")
        for st in steps:
            label = f"step {st['i'] + 1} ({describe(st)})"
            res = call(args.url, f"/api/runs/{rid}/baseline", {"step": st["i"], "n": args.tries})
            if not res["started"] and res["summary"] and not res["summary"]["running"]:
                print(f"  {label}: already have {res['summary']['k']} of {res['summary']['n']}")
                continue
            start = time.time()
            while True:
                row = call(args.url, f"/api/runs/{rid}/baselines").get(str(st["i"]), {})
                if row and not row.get("running"):
                    print(f"\r  {label}: without any change, passed {row['k']} of {row['n']}          ")
                    break
                print(f"\r  {label}: working... {int(time.time() - start)}s ", end="", flush=True)
                time.sleep(3)


if __name__ == "__main__":
    main()
