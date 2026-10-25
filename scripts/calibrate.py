"""Measure whether each scenario is good study material with the real model.

For each scenario it answers three questions:
  1. Does the AI team fail it on its own at least sometimes?  (you need failing runs to start from)
  2. Replaying a failing run from its plan with NO change, how often does it pass?  (want: rarely)
     These no-change replays also count as that run's baseline in the app.
  3. Replaying it with a known-good edit to the plan, how often does it pass?     (want: most of the time)
With --per-step it also puts the same good advice at EVERY editable step (the
request, the plan, each instruction) to show whether early edits beat late ones.
That tells you which steps are genuinely "wrong" places for a planted suggestion.

With --plain it also tries the scenario's plain-words edit (plain_edit in
scenario.json: what should happen, in everyday words, no function names) in the
request and in the plan. That shows whether a beginner could realistically reach
a fix. A scenario only technical edits can fix belongs to experienced users.

To reuse failing runs you already have instead of making new ones:
    .venv\\Scripts\\python scripts\\calibrate.py --from-run run-AAA run-BBB --plain --skip-main
The study needs a clear gap between 2 and 3: then "k of n" separates a real
fix from luck. A scenario that a good edit can't fix can't be steered by
participants either.

Usage (the app must be running, e.g. via run.bat, in another window):
    .venv\\Scripts\\python scripts\\calibrate.py
    .venv\\Scripts\\python scripts\\calibrate.py --scenarios repeat_dates --runs 5 --edit-tries 3

Free-tier cost: a run is about 7-9 LLM calls, so the defaults cost roughly
60-70 calls per scenario, and --per-step adds about 40 more; calibrate one or two
scenarios per account per day, or spread them across teammates' accounts.
The runs it creates appear in the app; failing ones make good canonical runs.
"""
import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEEP_EDIT_RATE = 2 / 3 - 1e-9  # the good edit must work at least this often (2 of 3 counts)
KEEP_GAP = 0.5         # ...and beat "no change" by at least this much


def call(base, path, body=None):
    req = urllib.request.Request(
        base + path, method="POST" if body is not None else "GET",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{path}: {exc.code} {exc.read().decode()[:300]}")
    except urllib.error.URLError:
        raise SystemExit(f"Can't reach {base}. Start the app first (run.bat), then run this script.")


def wait(base, path, label):
    start = time.time()
    while True:
        rec = call(base, path)
        if rec["status"] in ("done", "error"):
            return rec
        print(f"\r  {label}: working... {int(time.time() - start)}s ", end="", flush=True)
        time.sleep(3)


def describe(step):
    if step["agent"] == "user":
        return "request"
    if step["data"].get("kind") == "plan":
        return "plan"
    return f"instruction {step['data'].get('plan_step', '')}".strip()


def edit_text(step, advice):
    """Put the same good advice at any editable step, in the form that step takes."""
    if step["agent"] == "user":
        return step["content"].rstrip() + "\n\n" + advice
    if step["data"].get("kind") == "plan":
        items = step["data"].get("items") or []
        return "\n".join(f"{k}. {item}" for k, item in enumerate([advice] + items, 1))
    return advice


HOLD_ALL = {}  # filled in main(): calibration never touches the simulated world (Feature 3)


def plain_level(rows):
    """Can a beginner-style edit reach the fix? Judged by its best position."""
    done = [r for r in rows if r["k"] is not None]
    if not done:
        return None
    best = max(r["k"] / r["n"] for r in done)
    if best >= KEEP_EDIT_RATE:
        return "beginner-reachable: a plain-words edit fixes it most of the time"
    if best > 0:
        return "partly beginner-reachable: a plain-words edit only sometimes fixes it"
    return "experienced only: a plain-words edit never fixed it (mark the scenario level: experienced)"


def replay(base_url, run_id, step, text, n, label):
    vid = call(base_url, f"/api/runs/{run_id}/verify",
               {"step": step, "text": text, "n": n, "action_policy": HOLD_ALL})["id"]
    v = wait(base_url, f"/api/verifications/{vid}", label)
    if v["status"] != "done":
        print(f"\r  {label}: ERROR {v.get('error', '')[:120]}")
        return None
    print(f"\r  {label}: passed in {v['result']['k']} of {n} replays               ")
    return v["result"]["k"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--scenarios", nargs="*", help="scenario ids (default: all with a good_edit)")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--tries", type=int, default=3, help="replays for the no-change and the good-edit checks")
    ap.add_argument("--per-step", action="store_true", help="also try the good edit at every editable step")
    ap.add_argument("--step-tries", type=int, default=2, help="replays per step for --per-step")
    ap.add_argument("--plain", action="store_true", help="also try the plain-words edit in the request and the plan")
    ap.add_argument("--plain-tries", type=int, default=3, help="replays per position for --plain")
    ap.add_argument("--from-run", nargs="*", default=[], help="use these failing runs instead of making new ones")
    ap.add_argument("--skip-main", action="store_true", help="skip the no-change and good-edit checks")
    args = ap.parse_args()

    cfg = call(args.url, "/api/config")
    print(f"Model: {cfg['model']} ({cfg['provider']}), tests in {cfg['sandbox']}")
    HOLD_ALL.update({tool: "hold" for tool in cfg.get("tools", {})})
    if cfg["provider"] == "mock":
        print("WARNING: mock agents are running. Results say nothing about the real model.\n")

    metas = {}
    for f in sorted((ROOT / "scenarios").glob("*/scenario.json")):
        m = json.loads(f.read_text(encoding="utf-8"))
        if m.get("good_edit") and (not args.scenarios or m["id"] in args.scenarios):
            metas[m["id"]] = m
    if not metas:
        raise SystemExit("No matching scenarios with a good_edit.")

    results = []
    preset = {}
    for rid in args.from_run:
        run = call(args.url, f"/api/runs/{rid}")
        if run["status"] != "done" or run["outcome"]["ok"]:
            raise SystemExit(f"{rid} is not a finished, failing run.")
        preset.setdefault(run["scenario_id"], []).append(rid)
    if preset:
        metas = {sid: m for sid, m in metas.items() if sid in preset}

    for sid, meta in metas.items():
        print(f"\n== {meta['title']} ({sid})")
        outcomes, failing, tokens = [], list(preset.get(sid, [])), 0
        for i in range(0 if preset else args.runs):
            rid = call(args.url, "/api/runs", {"scenario_id": sid})["id"]
            run = wait(args.url, f"/api/runs/{rid}", f"original run {i + 1}/{args.runs}")
            tokens += sum(run.get("usage", {}).get(k, 0) for k in ("prompt_tokens", "completion_tokens"))
            if run["status"] == "error":
                print(f"\r  original run {i + 1}: ERROR {run['error'][:120]}")
                outcomes.append("error")
                continue
            ok = run["outcome"]["ok"]
            outcomes.append("pass" if ok else "fail")
            if not ok:
                failing.append(rid)
            print(f"\r  original run {i + 1}: {'passed' if ok else 'FAILED'} "
                  f"({run['outcome']['passed']}/{run['outcome']['total']} hidden checks)      ")

        finished = [o for o in outcomes if o != "error"]
        if preset:
            outcomes, finished = ["fail"] * len(failing), ["fail"] * len(failing)
        fail_rate = finished.count("fail") / len(finished) if finished else 0
        base_k = good_k = None
        n = args.tries
        per_step, plain = [], []
        if failing:
            base = failing[0]
            run = call(args.url, f"/api/runs/{base}")
            plan_step = next((st["i"] for st in run["trace"] if st["data"].get("kind") == "plan"), None)
            step = plan_step if plan_step is not None else run["editable_steps"][-1]
            main_checks = () if args.skip_main else (
                ("no change", run["trace"][step]["content"]),
                ("good edit", edit_text(run["trace"][step], meta["good_edit"]["text"])))
            for label, text in main_checks:
                k = replay(args.url, base, step, text, n, f"{label} (from step {step + 1})")
                if label == "no change":
                    base_k = k
                else:
                    good_k = k
            if args.per_step:
                for st in run["trace"]:
                    if st["i"] in run["editable_steps"]:
                        k = replay(args.url, base, st["i"], edit_text(st, meta["good_edit"]["text"]),
                                   args.step_tries, f"good edit at step {st['i'] + 1} ({describe(st)})")
                        per_step.append({"step": st["i"] + 1, "what": describe(st), "k": k, "n": args.step_tries})
            if args.plain:
                if not meta.get("plain_edit"):
                    print("  plain edit skipped: this scenario has no plain_edit in scenario.json")
                else:
                    for st in run["trace"]:
                        if st["agent"] == "user" or st["data"].get("kind") == "plan":
                            k = replay(args.url, base, st["i"], edit_text(st, meta["plain_edit"]["text"]),
                                       args.plain_tries, f"plain-words edit in the {describe(st)} (step {st['i'] + 1})")
                            plain.append({"step": st["i"] + 1, "what": describe(st), "k": k, "n": args.plain_tries})

        if args.skip_main:
            verdict = "-"
        elif not finished:
            verdict = "every run errored: check the setup"
        elif not failing:
            verdict = "too easy: no failing run to start from"
        elif good_k is None or base_k is None:
            verdict = "couldn't finish the replays"
        elif good_k / n < KEEP_EDIT_RATE:
            verdict = "hard to steer: even the good edit rarely works"
        elif (good_k - base_k) / n < KEEP_GAP:
            verdict = "weak contrast: replays often pass without any change"
        else:
            verdict = "KEEP"
        results.append({"scenario": sid, "runs": outcomes, "fail_rate": round(fail_rate, 2),
                        "no_change": f"{base_k}/{n}" if base_k is not None else None,
                        "good_edit": f"{good_k}/{n}" if good_k is not None else None, "verdict": verdict,
                        "per_step": per_step, "plain": plain, "level": plain_level(plain),
                        "failing_run_ids": failing, "time": time.time()})

    print("\n\nScenario          Failed alone  No change  Good edit  Verdict")
    for r in results:
        failed = f"{r['runs'].count('fail')}/{len([o for o in r['runs'] if o != 'error'])}"
        print(f"{r['scenario']:<18}{failed:<14}{(r['no_change'] or '-'):<11}{(r['good_edit'] or '-'):<11}{r['verdict']}")
        if r["failing_run_ids"]:
            print(f"{'':<18}failing runs you can reuse: {', '.join(r['failing_run_ids'])}")
        for row in r["per_step"]:
            shown = f"{row['k']}/{row['n']}" if row["k"] is not None else "error"
            print(f"{'':<18}good edit at step {row['step']:<3}{row['what']:<16}{shown}")
        for row in r["plain"]:
            shown = f"{row['k']}/{row['n']}" if row["k"] is not None else "error"
            print(f"{'':<18}plain-words edit in the {row['what']:<10}{shown}")
        if r["level"]:
            print(f"{'':<18}=> {r['level']}")

    out = ROOT / "data" / "calibration.json"
    history = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    out.write_text(json.dumps(history + results, indent=1), encoding="utf-8")
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
