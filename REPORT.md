# Agent Verifier: Technical Report

This report documents the design, operation and study procedures of Agent Verifier. For a project overview and setup instructions, see [README.md](README.md).

## Contents

1. [System overview](#1-system-overview)
2. [Features in detail](#2-features-in-detail)
3. [API cost and free-tier budget](#3-api-cost-and-free-tier-budget)
4. [Scenarios and calibration](#scenarios-and-calibration)
5. [The no-change baseline](#5-the-no-change-baseline)
6. [Irreversible actions (Feature 3)](#6-irreversible-actions-feature-3)
7. [Running study sessions](#7-running-study-sessions)
8. [The action log](#8-the-action-log)
9. [Architecture mapping](#9-architecture-mapping)
10. [Adding a scenario](#10-adding-a-scenario)
11. [Known limitations](#11-known-limitations)

---

## 1. System overview

A small AI coding team tries to fix a bug in a to-do app. It works plan-then-execute, like Cursor or Claude Code:

1. The **Planner** splits the job into 2–3 steps.
2. For each step, the Planner instructs the **Coder**, and the **Test runner** checks the code.
3. If the visible test still fails at the end, there is one fix-up round.

A run is about 11 steps and offers five places where a person can intervene: the request, the plan, and each Planner instruction.

### Visible and hidden tests

The agents only see one simple test. Success is judged by hidden acceptance tests, so the team can "pass" and still be wrong, like a real fix that only works on the example. Each scenario ships with a plausible wrong fix that passes the visible test.

Every hidden check has a plain-language description. With the tool on, the result lists every check with ✓/✕, so the evidence can be checked rather than just trusted.

---

## 2. Features in detail

### Feature 1: Where to intervene

Steps are ordered by how the team uses them. The plan and the request are read again at every later step, while an instruction is mainly read once. Each suggestion states this reason, and an LLM adds *what* in that step should change. The Simple view shows two candidates and the Detailed view shows three.

### Edit and replay

A person can change any editable step and replay from that point. Like AGDebugger, the run is forked: the checkpoint after the edited step is copied into a new thread and resumed.

In the **Simple** view, the agent's actual words are one click away from each step's summary. The editor invites the person's own words, which are appended to the request, added as the first plan step, or written as a new instruction. The original text can still be edited with "Edit their full text instead". The **Detailed** view edits the original text directly.

### Feature 2: Did the fix hold?

The edited run is replayed several times (at least 3) and checked against the hidden tests. The result appears next to a **no-change baseline**:

> *Your change: 3 of 3. Without your change: 1 of 3.*

This separates the effect of the edit from luck, because some bugs get fixed now and then by replaying alone. Verdicts state what a small number of tries can and can't show.

### Two levels of detail

One trace is shown at two levels of detail: **Simple** (plain-language summaries from one cached LLM call per run) and **Detailed** (the raw agent output).

### Confidence ratings

The participant rates their confidence from 1 to 7 before each replay and again after seeing the result.

### While replays run

Replays can take minutes on a free tier, so the waiting screen shows:

- what each try is doing right now (for example, "the planner is writing the instruction for plan step 2 of 3");
- a progress bar for each try;
- a time estimate based on the tries already finished;
- whether other replays are queued ahead;
- whether a no-change comparison will run afterwards.

**Watch** opens a running try so the person can follow it live. Pass/fail stays hidden until all tries finish, so one lucky try doesn't decide for the person and a planted "k of n" stays consistent. Progress data comes from `GET /api/verifications/{id}/progress`, and opening a try is logged as `watch_try_opened`.

---

## 3. API cost and free-tier budget

Groq's free limits apply **per account (organisation), not per key**. A typical model limit is about 30 requests/min, 1,000 requests/day, 8,000 tokens/min and 200,000 tokens/day. Check the actual limits under *Console → Limits*.

### Approximate cost of one debugging loop

| Operation | LLM calls |
| --- | --- |
| One original run | 2–6 (7–9 with the full plan-then-execute team) |
| Step ranking | 1 |
| Plain-language summaries | 1 |
| Verification with 3 tries | 6–18 (about 20 when replaying from the plan) |

The binding limit is **tokens per minute**, so a 3-try verification can take a few minutes on the free tier. This is why `LLM_MIN_INTERVAL` exists and why the default is 3 tries.

### Recommendations

- Each team member should use their **own** Groq account.
- Use mock mode, which costs nothing, for UI development.
- Alternatives: `LLM_PROVIDER=gemini` with `GEMINI_API_KEY`, `LLM_PROVIDER=ollama` for local models, or any OpenAI-compatible service through `LLM_BASE_URL` and `LLM_MODEL`.

---

<a id="scenarios-and-calibration"></a>
## 4. Scenarios and calibration

### Scenarios

| Scenario | The trap | Calibration (plan-then-execute team, Groq) |
| --- | --- | --- |
| Repeating tasks get the wrong date | Monthly tasks must return to their original day after a short month (Jan 31 → Feb 28 → Mar 31). The model computes the original day, then reuses `add()`, which quietly recalculates it. | **KEEP**: failed 3/3 alone; no change 0/3; good edit 3/3. Good edit at request or plan 4/4, at instructions 0/6. |
| Duplicated tasks get confusing names | Copies are numbered like files, and numbers are never reused after a delete. Picking the next free number from existing titles passes the visible test but reuses deleted numbers. | **KEEP**: failed 2/3 alone; no change 0/3; good edit 3/3. Good edit worked at every step (8/8). |
| Weekly tasks drift after rescheduling | Moving one copy of a weekly task must not shift the series. Computing the next copy from the current due date drifts after a reschedule. It uses the same "remember the original date" idea as repeating tasks, so keep the two apart in task order. | **KEEP**: failed 2/3 alone; no change 1/3; good edit 3/3. Good edit at request or plan 4/4, at instructions 0/6. |
| Practice: undo / delete / clear completed | Warm-ups that the model often or always solves alone. Use them to teach participants the interface. | Not calibrated as main tasks |

### What makes a scenario work

The model fails reliably when a rule depends on **history that the current data no longer shows**: the original day after Feb 28, the copy number after a delete, the planned weekday after a reschedule. The natural fix, deriving the answer from what is stored now, works in the common case and breaks later. Bugs in code the model can read are fixed even when they are subtle.

**Retired because the model solved them every time:** shopping-total rounding, duplicate position, tag rename, postpone and habit streak.

Every request states the full rules, so nothing is hidden from the agents. The agents only *see* one simple test; the hidden tests check every rule in the request.

### Running calibration

Calibrate with the real model before running a study. With the app running, open a second terminal in the project folder:

```bash
.venv\Scripts\python scripts\calibrate.py
```

For each scenario, the script:

1. runs the team on its own a few times to collect failing runs;
2. replays one failing run from its plan with **no change**;
3. replays the same run with a known-good edit to the plan (`good_edit` in `scenario.json`).

| Option | Purpose |
| --- | --- |
| `--plain` | Tests whether a **beginner** could reach the fix, using the scenario's `plain_edit` (everyday words, no code) in the request and in the plan. The verdict is *beginner-reachable*, *partly* or *experienced only*. For experienced-only scenarios, add `"level": "experienced"` to `scenario.json`. |
| `--from-run run-AAA run-BBB ...` | Reuses existing failing runs instead of creating new ones. Combine with `--skip-main`. About 45 LLM calls per run. |
| `--per-step` | Applies the same good edit at **every** editable step, with 2 replays each. Shows whether early edits beat late ones, which helps choose a planted "where to fix" step where the good edit rarely works. |
| `--scenarios repeat_dates` | Calibrates one scenario at a time to spread the cost. |

**Verdicts:** **KEEP**, **too easy** (no failing run), **hard to steer**, **weak contrast**. A scenario is worth keeping when the good edit usually works and clearly beats no change; that gap is what lets "k of n" tell a real fix from luck. The script also lists failing run ids for reuse as canonical runs. Results are appended to `data/calibration.json`.

**Cost:** roughly 60–70 calls per scenario, plus about 40 with `--per-step`. That is a large share of one Groq account's free daily tokens, so consider splitting scenarios across accounts.

---

## 5. The no-change baseline

"k of n" alone shows whether the bug got fixed when replaying from a step, not whether **your edit** fixed it. So for every edited step, the app also replays that step **unchanged** (`BASELINE_REPLAYS`, default 3) and shows *"Without your change: b of m"* under the result.

- **Pooled and cached** per run and step. Any no-change replay counts, including calibration's, so the plan step of calibrated runs already has a baseline.
- **Computed after the person's own tries** if it doesn't exist yet, so their result isn't delayed. Until it arrives, they see "Checking what happens without your change…".
- **Never planted, and never touches the simulated world.** All release actions are held during baseline replays.
- **Precompute for session runs** so participants don't have to wait:
  ```bash
  .venv\Scripts\python scripts\baselines.py run-AAA run-BBB run-CCC
  ```
  All editable steps × 3 tries is roughly 80 LLM calls per run. Add `--steps plan` to compute only the plan step.

---

## 6. Irreversible actions (Feature 3)

Enable it with `RELEASE_ACTIONS=on` in `.env` and restart the server.

A run whose visible tests pass ends with a release step: deploy to staging, deploy to production, and email the customer that the bug is fixed. Everything is **simulated**, so nothing real happens. A failing run has therefore shipped broken code and told the customer it works, and every replay would do it again.

| Action | Undoable? | Behaviour |
| --- | --- | --- |
| Deploy to staging | Yes | Always runs; shown for contrast |
| Deploy to production | **No** | Runs unless held |
| Email the customer | **No** | Runs unless held |

The release step is fixed: no LLM, the same three actions in the same order, and only when the visible tests pass. Each action appears in the timeline tagged "can't be undone", with the exact call shown in the Detailed view. Every action, done or held, is written to `data/world/effects.jsonl`. The *"What the team did outside the code"* panel counts them for the open run's family (the original run plus this person's tries for this task), for example "the customer received 4 emails".

### Warnings

Warnings appear when the feature is on, the tool is on, and (in a session) the task has `warn_actions: true`, which is the default.

- The editor shows a red box listing the irreversible actions.
- For each action, the person must choose **Hold during replays** or **Let it happen**. Nothing is pre-selected, so the choice measures the warning rather than a default.
- Replaying is blocked until every action has a choice.
- In the Detailed view, **Mark as safe** stops warnings for that action for this person.

With warnings off (`warn_actions: false`, or tool off), the actions run on every replay. This is the RQ4 baseline.

### Notes

Runs made while the feature was off have no release step. Their replays will release, but the original run won't show the deploy and email, so create canonical runs with the feature on. Turning it on doesn't change code or test results, so calibration results stay valid.

---

## 7. Running study sessions

A session walks one participant through their tasks in order. Each task starts from a fixed failing run and has its own condition (tool on or off, starting view) and its own planted errors. Participants only see the session screens: they can't start runs, browse other runs, or see anyone else's tries.

### Study mode

Planted errors make the tool show false evidence on purpose, so they only work with `STUDY_MODE=on` in `.env`. It is off by default. With it off:

- the researcher panel has no plant controls, and planting through the API is refused;
- planted fields in `study/plan.json` are reported as problems by `/api/plan/check`.

`/api/plan/check` also warns about any run that still carries a per-run plant from the researcher panel. Enable study mode only on the machines used for sessions.

### Step 1: Create the plan

Copy `study/plan.example.json` to `study/plan.json` and list each participant's tasks:

| Field | Meaning |
| --- | --- |
| `run_id` | A finished, **failing** run to start from. `calibrate.py` lists failing run ids, and the researcher panel (`?researcher=1`) shows the id of the open run. The same run can be reused across participants. |
| `tool` | `on`, or `off` for the baseline (no suggestion, one replay, no "k of n"). |
| `mode` | Starting view: `simple` or `detailed`. The participant can still switch. |
| `plant_suggest_step` | Step number **as shown in the app** that "where to fix" will point at instead of the real suggestion. `null` means honest. |
| `overstate_by` | Added to the shown "k of n", capped at n. `0` means honest. |
| `minutes` | Optional soft time limit, shown as a timer. |
| `practice` | `true` marks a warm-up task. |
| `warn_actions` | Feature 3 only (needs `RELEASE_ACTIONS=on` and tool on). `true` (default) means the participant is warned and can hold actions; `false` means actions just happen (RQ4 baseline). |
| `group` | Set on the participant, for example `beginner` or `experienced`. Copied into every log line for RQ2. |

Planted errors apply only to that participant's task, so the same run can be honest for P01 and planted for P02.

### Step 2: Validate it

Open **http://localhost:8000/api/plan/check**. It flags missing runs, runs that passed (nothing to fix), planted steps that can't be edited, and planted errors on tool-off tasks.

### Step 3: Run the session

Open **http://localhost:8000/?session=P01** on the participant's screen.

1. The participant sees a welcome screen, then each task in turn.
2. Before every replay, they rate from 1 to 7 how sure they are that the change will work.
3. After the result, they rate again.
4. They click "I'm done with this task" to move on.

Reloading the page resumes where they left off. Progress is saved in `data/sessions/`.

Outside sessions, `?pid=P01` still logs events and asks for both ratings, and the per-run researcher controls (`?researcher=1`) still work.

> **Ethics:** planted errors deceive participants. Plan a debrief and check your institution's ethics/IRB requirements before running sessions.

---

## 8. The action log

Everything a participant does is appended to `data/events.jsonl`, one JSON object per line. Every line carries the time, participant, group and task. The server adds ground truth, which participants never see.

| Event | Key fields |
| --- | --- |
| `task_started` / `task_finished` | Condition (tool, mode, planted values). Finish adds seconds taken, number of attempts, and the last attempt's shown and true k. |
| `suggest_clicked`, `suggestion_shown` | Shown steps vs **true** steps, `planted` |
| `editor_opened`, `editor_cancelled`, `jumped_to_step` | Which step, and what the suggestion pointed at |
| `edit_submitted`, `editor_full_text` | How the edit was made: `mode` is `add_to_request`, `add_plan_step`, `new_instruction` or `full_text`, plus the typed length |
| `replay_started` | Step edited, edit text and original text, `pre_rating`, `suggested_top_step`, `true_top_step`, `edited_suggested_step` (RQ3: did they follow the suggestion?), `held_actions` |
| `replays_finished`, `result_seen` | Shown k vs **true** k, n. `result_seen` also records the no-change baseline shown (`baseline_k`, `baseline_n`). |
| `rating_after` | The 1–7 rating after the result, alongside `pre_rating`, shown k and true k (RQ1: calibration) |
| `view_switched`, `run_opened`, `earlier_change_opened`, `watch_try_opened` | Navigation |
| `actions_warning_shown`, `action_choice`, `action_marked_safe` | Feature 3: which actions were warned about, and each hold or let-it-happen choice |
| `action_done`, `action_held` | Feature 3: one per action per replay |

`result_seen` can appear twice for the same result if the page is reloaded, so count unique `verification_id`s.

---

## 9. Architecture mapping

| Project concept | Implementation |
| --- | --- |
| Plan-then-execute agent team with a checkpoint after every step | `app/agents.py` (LangGraph, SQLite checkpointer) |
| Rewind, edit, fork | `runs._fork_start` copies the checkpoint after the edited step into a new thread and resumes |
| Feature 1: where to intervene | `app/evidence.py`. The order comes from a rule (plan, request, instructions) with a grounded `how_used` reason; one LLM call explains what to change in each step. Cached per run (`ranking_version` 2). |
| Feature 2: did it hold | `runs.summarize` computes k of n on hidden tests, where each try first diverged from try 1, and how many distinct final code versions there were. `runs.baseline_summary` / `ensure_baseline` provide the no-change comparison. |
| Two levels of detail | Simple/Detailed switch; plain summaries come from one cached LLM call per run |
| Planted errors | Only with `STUDY_MODE=on`. Set per task in `study/plan.json` (or per run via `?researcher=1`) and stripped from everything participants receive |
| Confidence calibration | 1–7 rating before each replay and after its result, logged with true and shown k |
| Sessions and action log | `app/study.py`, `?session=`, `data/events.jsonl` |
| Feature 3: irreversible actions | `app/actions.py` (definitions, simulated world), the release node in `app/agents.py`, and `action_policy` on replays |

---

## 10. Adding a scenario

Copy a folder in `scenarios/` and provide:

- `scenario.json`, including:
  - `good_edit`: a known technical fix;
  - `plain_edit`: the same idea in everyday words, with no code;
  - `checks`: one plain sentence per hidden test (`smoke_test.py` checks that they match);
  - `order`: the position in the dropdown;
  - optionally `"level": "experienced"`;
- the buggy source file(s);
- `test_visible.py`, which fails on the buggy code, and `test_hidden.py`, which checks every rule in the request;
- `mock_good/` and `mock_bad/` versions for mock mode.

Mock `hint_patterns` must not appear in the request text; `scripts/smoke_test.py` checks this. Restart the server so the new scenario appears in the dropdown, then calibrate it.

---

## 11. Known limitations

- **Scenario difficulty depends on the model.** If calibration reports a scenario as "too easy", options include a smaller model (`LLM_MODEL`), fewer plan steps (`PLAN_MAX_STEPS`), or vaguer requests with the full rules shown only to participants.
- **Editable scope.** People can edit the request, the plan and the Planner's instructions, but not the Coder's code or the test output.
- **Cost.** A run takes about 7–9 LLM calls, and a 3-try replay from the plan about 20. On Groq's free tier, expect each replay to take a few minutes and a full participant session to use much of one account's daily tokens. Measure this in a pilot.
- **Outcome comparison.** "Same outcome" uses the hidden tests plus a structural comparison of the steps, not an LLM-based trajectory comparison, to save quota.
- **Concurrency.** With real agents only one job runs at a time, so a verification blocks new runs until it finishes.
- **Restarts.** Restarting the server marks unfinished runs as errors. Finished runs and their checkpoints are kept in `data/`.
