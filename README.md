# Agent Verifier

A working prototype for **Interactive Verification and Safe Steering of AI Coding Agents** (HCI course project).

A small AI coding team tries to fix a bug in a to-do app. It works plan-then-execute, like Cursor or Claude Code: the Planner splits the job into 2–3 steps, then for each step the Planner instructs the Coder and the Test runner checks the code, with one fix-up round at the end if the visible test still fails. A run is about 11 steps with five places a person can intervene: the request, the plan, and each instruction. When the run fails, you can:

- **see where to fix it** (Feature 1). Steps are ordered by how the team uses them: the plan and your request are read again at every later step, while an instruction is mainly read once. Each suggestion says that plainly, and an LLM adds *what* in that step should change. Simple view shows two candidates, Detailed shows three;
- **change a step and replay** from that point (fork, AGDebugger-style);
- **see whether the fix was real** (Feature 2): the edited run is replayed several times (at least 3) and checked against hidden acceptance tests. The result is shown next to a **no-change baseline**, so you see *"Your change: 3 of 3. Without your change: 1 of 3."* That separates the effect of the edit from luck, because some bugs get fixed now and then by replaying alone. Verdicts say how much a few tries can and can't show.

Every hidden acceptance check has a plain-language sentence, and with the tool on the result lists them all with ✓/✕, so the evidence can be checked rather than just trusted.

In **Simple** view, each step's summary has the agent's actual words one click away. Editing invites your own words: they're added to the request, added as the first step of the plan, or written as a new instruction, with "Edit their full text instead" available. **Detailed** view edits the original text directly.

There is one trace with two levels of detail (**Simple** / **Detailed**), a 1–7 confidence rating after each verification, a baseline condition with the tool switched off, and researcher controls for planted errors.

**Feature 3 (optional): hold back what can't be undone.** With `RELEASE_ACTIONS=on`, a run whose visible tests pass ends with a release step: deploy to staging, deploy to production, and email the customer that the bug is fixed. It's all **simulated**; nothing real happens. A failing run has therefore shipped broken code and told the customer it works, and every replay would do it again. Before replaying, the person is warned and can **hold** each irreversible action (it's recorded but not done), let it run, or **mark it as safe**. A panel shows what the team did outside the code, for example "the customer received 4 emails".

---

## Setup on Windows

1. Install **Python 3.11 or newer** from python.org. Tick "Add python.exe to PATH".
2. Install **Docker Desktop** and start it. Then, in a terminal, pull the image once:
   ```
   docker pull python:3.11-slim
   ```
3. Double-click **`run.bat`**. The first time, it creates a virtual environment, installs packages, and copies `.env.example` to `.env`.
4. Open **http://localhost:8000**.

It starts in **mock mode**, with fake offline agents. Use that to check that everything works. Then switch to real agents:

5. Create a free Groq account at https://console.groq.com and make an API key. No card is needed.
6. Edit `.env`:
   ```
   LLM_PROVIDER=groq
   GROQ_API_KEY=gsk_...
   ```
7. Stop the server (Ctrl+C) and run `run.bat` again.

To check the sandbox: open http://localhost:8000/api/sandbox/check. It should say `"ok": true`. If Docker isn't working yet, you can set `SANDBOX=local` in `.env` to keep going, but then the agents' code runs on your machine without isolation.

To check the whole loop without a key or Docker: `python scripts/smoke_test.py`.

## Free-tier budget (read this before running sessions)

Groq's free limits apply **per account (organisation), not per key**. A sample model limit is about 30 requests/min, 1,000/day, 8,000 tokens/min and 200,000 tokens/day. Check your own limits under Console → Limits.

Rough cost of one participant debugging loop:

- one original run: 2–6 LLM calls;
- the step ranking: 1 call;
- the plain-language summaries: 1 call;
- a verification with 3 tries: 6–18 calls.

The binding limit is **tokens per minute**: a 3-try verification can take a few minutes on the free tier. That's why `LLM_MIN_INTERVAL` exists, and why the default is 3 tries.

Each teammate should use their **own** Groq account. Mock mode costs nothing, so build UI changes in mock mode.

To use Gemini instead, set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY`. For a local model, install Ollama and set `LLM_PROVIDER=ollama`. Any other OpenAI-compatible service works with `LLM_BASE_URL` and `LLM_MODEL`.

## Scenarios and calibration

| Scenario | The trap | Calibration (plan-then-execute team, Groq) |
| --- | --- | --- |
| Repeating tasks get the wrong date | Monthly tasks must go back to their original day after a short month (Jan 31 → Feb 28 → Mar 31). The model computes the original day, then reuses `add()`, which quietly recalculates it. | **KEEP**: failed 3/3 alone; no change 0/3; good edit 3/3. Good edit at request or plan 4/4, at instructions 0/6. |
| Duplicated tasks get confusing names | Copies are numbered like files, and numbers are never reused after a delete. Picking the next free number from existing titles passes the visible test but reuses deleted numbers. | **KEEP**: failed 2/3 alone; no change 0/3; good edit 3/3. Good edit worked at every step (8/8). |
| Weekly tasks drift after rescheduling | Moving one copy of a weekly task must not shift the series. Computing the next copy from the current due date drifts after a reschedule. Same "remember the original date" idea as repeating tasks, so put them apart in task order. | **KEEP**: failed 2/3 alone; no change 1/3; good edit 3/3. Good edit at request or plan 4/4, at instructions 0/6. |
| Practice: undo / delete / clear completed | Warm-ups. The model often or always solves them alone. Use them to teach participants the interface. | not calibrated as main tasks |

What makes a scenario work, learned from calibration: the model fails reliably when a rule depends on **history that the current data no longer shows** (the original day after Feb 28, the copy number after a delete, the planned weekday after a reschedule), so the natural fix, deriving the answer from what is stored now, works in the common case and breaks later. Bugs in code the model can read are fixed even when subtle. **Retired because the model solved them every time:** shopping-total rounding, duplicate position, tag rename, postpone, and habit streak.

Every request states the full rules: nothing is hidden from the agents. The agents only *see* one simple test; the hidden tests check every rule in the request.

**Before the study, calibrate with the real model.** With the app running, open a second terminal in the project folder:
```
.venv\Scripts\python scripts\calibrate.py
```
For each scenario it:

1. runs the team on its own a few times, to collect failing runs;
2. replays one failing run from its plan with **no change**;
3. replays the same run with a known-good edit to the plan (`good_edit` in `scenario.json`).

Add `--plain` to test whether a **beginner** could reach the fix. It tries the scenario's `plain_edit`, which says what should happen in everyday words with no function names or code, in the request and in the plan. The verdict is beginner-reachable, partly, or experienced only. If a scenario is experienced only, add `"level": "experienced"` to its `scenario.json`, and the dropdown will label it. To reuse failing runs you already have instead of making new ones:
```
.venv\Scripts\python scripts\calibrate.py --from-run run-AAA run-BBB run-CCC --plain --skip-main
```
That costs about 45 LLM calls per run (3 tries in the request plus 3 in the plan).

Add `--per-step` to also put the same good advice at **every** editable step (appended to the request, as the first plan step, or as an instruction) with 2 replays each. That shows whether early edits beat late ones, and so which steps are genuinely wrong places for a planted "where to fix" suggestion. Pick a planted step where the good edit rarely worked.

A scenario is worth keeping when the good edit usually works and clearly beats no change. That gap is what lets "k of n" tell a real fix from luck. The verdicts are **KEEP**, **too easy** (no failing run), **hard to steer** and **weak contrast**. The script also lists the failing run ids, which you can reuse as canonical runs. Results are appended to `data/calibration.json`.

A run is now about 7–9 LLM calls, so calibration costs roughly 60–70 calls per scenario, plus about 40 with `--per-step`. That is a large share of one Groq account's free daily tokens. To spread the cost, calibrate one scenario at a time with `--scenarios repeat_dates`, or split scenarios across teammates' accounts.

## While replays run

Replays can take minutes on a free tier, so the waiting screen shows:
- what each try is doing right now (e.g. "the coder is changing the code", "the planner is writing the instruction for plan step 2 of 3");
- a progress bar per try;
- a time estimate based on the tries already finished;
- whether other replays are queued ahead;
- whether a no-change comparison will run afterwards.

**Watch** opens a running try so the person can follow it live. Pass/fail stays hidden until all tries finish, so one lucky try doesn't decide for the person, and a planted "k of n" stays consistent. The data comes from `GET /api/verifications/{id}/progress`. Opening a try is logged as `watch_try_opened`.

## The no-change baseline

"k of n" alone says whether the bug got fixed when replaying from a step, not whether **your edit** fixed it. So for every step someone edits, the app also replays that step **unchanged** (`BASELINE_REPLAYS`, default 3) and shows "Without your change: b of m" under the result.

- **Pooled and cached** per run and step. Any no-change replay counts, including calibration's no-change replays, so the plan step of your calibrated runs already has one.
- **Computed after the person's own tries** if it doesn't exist yet, so their result isn't delayed. They see "Checking what happens without your change…" until it arrives.
- **Never planted, and it never touches the simulated world.** All release actions are held during baseline replays.
- **Precompute for the runs you use in sessions,** so participants don't wait:
  ```
  .venv\Scripts\python scripts\baselines.py run-AAA run-BBB run-CCC
  ```
  All editable steps × 3 tries is roughly 80 LLM calls per run. Add `--steps plan` to do only the plan step.

## Study mode

Planted errors make the tool show false evidence on purpose. So they only work with `STUDY_MODE=on` in `.env`; it's off by default.

With it off:
- the researcher panel has no plant controls, and planting through the API is refused;
- any planted fields in `study/plan.json` are reported as problems by `/api/plan/check`, because they wouldn't apply.

`/api/plan/check` also warns about any run that still carries a per-run plant from the researcher panel. Turn study mode on only on the machines used for sessions.

## Feature 3 in detail

Turn it on with `RELEASE_ACTIONS=on` in `.env` and restart. Runs made while it was off have no release step. Their replays will release, but the original run won't show the deploy and email, so make your canonical runs with it on. Turning it on doesn't change any code or test results, so calibration results stay valid.

| Action | Undoable? | In the run |
| --- | --- | --- |
| Deploy to staging | yes | always runs; shown for contrast |
| Deploy to production | **no** | runs unless held |
| Email the customer | **no** | runs unless held |

The release step is fixed: no LLM, the same three actions in the same order, only when the visible tests pass. Each action is a step in the timeline, tagged "can't be undone", with the exact call shown in the Detailed view. Every action, done or held, goes to `data/world/effects.jsonl`. The "What the team did outside the code" panel counts them for the open run's family: the original run plus this person's tries for this task.

Warnings appear when the feature is on, the tool is on, and (in a session) the task has `warn_actions` true, which is the default. In the editor, a red box lists the irreversible actions. For each one the person must choose **Hold during replays** or **Let it happen**; nothing is pre-selected, so the choice measures the warning and not a default. Replaying is blocked until every action has a choice. In the Detailed view, **Mark as safe** stops warning about that action for this person, and it runs from then on. With warnings off (`warn_actions: false`, or tool off), the actions simply run on every replay. That is the RQ4 baseline.

## Running study sessions

A session walks one participant through their tasks in order. Each task:

- starts from a fixed failing run;
- has its own condition (tool on or off, starting view);
- has its own planted errors.

Participants only ever see the session screens. They can't start runs, browse other runs, or see anyone else's tries.

**1. Make the plan.** Copy `study/plan.example.json` to `study/plan.json` and fill it in. For each participant, list their tasks with these fields:

| Field | Meaning |
| --- | --- |
| `run_id` | A finished, **failing** run to start from. `calibrate.py` lists failing run ids, and the researcher panel (`?researcher=1`) shows the id of the open run. The same run can be used for many participants. |
| `tool` | `on`, or `off` for the baseline: no suggestion, one replay, no "k of n". |
| `mode` | Starting view: `simple` or `detailed`. The participant can still switch. |
| `plant_suggest_step` | Step **number as shown in the app** that "where to fix" will point at instead of the real suggestion. `null` = honest. |
| `overstate_by` | Added to the shown "k of n", capped at n. `0` = honest. |
| `minutes` | Optional soft time limit, shown as a timer. |
| `practice` | `true` marks a warm-up task. |
| `warn_actions` | Feature 3, only with `RELEASE_ACTIONS=on` and tool on. `true` (default) = warned and can hold; `false` = actions just happen (RQ4 baseline). |
| `group` | On the participant, e.g. `beginner` or `experienced`. Copied into every log line for RQ2. |

Planted errors in the plan apply only to that participant's task, so the same run can be honest for P01 and planted for P02.

**2. Check it.** Open **http://localhost:8000/api/plan/check**. It flags:
- missing runs;
- runs that passed (nothing to fix);
- planted steps that can't be edited;
- planted errors on tool-off tasks.

**3. Run the session.** Open **http://localhost:8000/?session=P01** on the participant's screen. Flow:

1. The participant sees a welcome screen, then each task in turn.
2. Before every replay they rate 1–7 how sure they are the change will work.
3. After the result they rate again.
4. They click "I'm done with this task" to move on.

Reloading the page resumes where they were. Progress is saved in `data/sessions/`.

**Ethics:** planted errors deceive participants, so plan a debrief and check your institution's ethics/IRB rules before running sessions.

### The action log

Everything a participant does is appended to `data/events.jsonl`, one JSON object per line. Every line carries the time, participant, group and task. The server adds the ground truth, which participants never see.

| Event | Key fields |
| --- | --- |
| `task_started` / `task_finished` | condition (tool, mode, planted values); finish adds seconds taken, number of attempts, and the last attempt's shown and true k |
| `suggest_clicked`, `suggestion_shown` | shown steps vs **true** steps, `planted` |
| `editor_opened`, `editor_cancelled`, `jumped_to_step` | which step, and what the suggestion pointed at |
| `replay_started` | step edited, the edit text and the original text, `pre_rating`, `suggested_top_step`, `true_top_step`, `edited_suggested_step` (RQ3: did they follow it?) |
| `replays_finished`, `result_seen` | shown k vs **true** k, n; `result_seen` also records the no-change baseline the person saw (`baseline_k`, `baseline_n`) |
| `rating_after` | the 1–7 rating after the result, next to `pre_rating`, shown k and true k (RQ1: calibration) |
| `view_switched`, `run_opened`, `earlier_change_opened` | navigation |
| `actions_warning_shown`, `action_choice`, `action_marked_safe` | Feature 3: which actions were warned about, and each hold or let-it-happen choice |
| `edit_submitted`, `editor_full_text` | how the edit was made: `mode` is `add_to_request`, `add_plan_step`, `new_instruction` or `full_text`, plus the typed length |
| `action_done`, `action_held` | Feature 3: one per action per replay (`replay_started` also lists `held_actions`) |

`result_seen` can appear twice for the same result if the page is reloaded; count unique `verification_id`s.

Outside sessions, `?pid=P01` still logs events and asks for both ratings, and the per-run researcher controls (`?researcher=1`) still work.

## How it maps to the project

| Project idea | Where it lives |
| --- | --- |
| Plan-then-execute agent team + checkpoint after every step | `app/agents.py` (LangGraph, SQLite checkpointer) |
| Rewind, edit, fork | `runs._fork_start`: copies the checkpoint after the edited step into a new thread and resumes |
| Feature 1: where to intervene | `app/evidence.py`: the order comes from a rule (plan, request, instructions) with a grounded `how_used` reason; one LLM call explains what to change in each step. Cached per run (`ranking_version` 2). |
| Feature 2: did it hold | `runs.summarize`: k of n on hidden tests, where each try first diverged from try 1, how many different final code versions; `runs.baseline_summary` / `ensure_baseline`: the no-change comparison |
| Two levels of detail | Simple/Detailed switch. Plain summaries come from one cached LLM call per run. |
| Planted errors | Only with `STUDY_MODE=on`. Per task in `study/plan.json` (or per run via `?researcher=1`); stripped from everything participants receive |
| Confidence calibration | 1–7 rating before each replay and after its result, logged with true and shown k |
| Sessions + action log | `app/study.py`, `?session=`, `data/events.jsonl` |
| Feature 3: irreversible actions | `app/actions.py` (definitions, simulated world), release node in `app/agents.py`, `action_policy` on replays |

**Why visible vs hidden tests.** The agents only see one simple test. Success is judged by hidden tests, so the team can "pass" and still be wrong, like a real fix that only works on the example. Each scenario ships with a plausible wrong fix that passes the visible test.

**Adding a scenario.** Copy a folder in `scenarios/` and write:

- `scenario.json`, including:
  - a `good_edit` (a known technical fix);
  - a `plain_edit` (the same idea in everyday words, no code);
  - `checks` (one plain sentence per hidden test; `smoke_test.py` checks they match);
  - an `order` for the dropdown;
  - optionally `"level": "experienced"`;
- the buggy file(s);
- `test_visible.py` (fails on the buggy code) and `test_hidden.py` (checks every rule in the request);
- `mock_good/` and `mock_bad/` versions for mock mode.

Mock `hint_patterns` must not appear in the request text. `scripts/smoke_test.py` checks this. Restart the server so the new scenario appears in the dropdown, then calibrate it.

## Known limits

- **Whether the three main scenarios fail often enough on Groq is unknown until you run `calibrate.py`.** I could only test them with mock agents. If they come back "too easy", the fallbacks are:
  - a smaller model (`LLM_MODEL`);
  - fewer plan steps (`PLAN_MAX_STEPS`);
  - vaguer requests, with the full rules shown only to participants.
- People can edit the request, the plan and the Planner's instructions, not the Coder's code or test output.
- **Cost.** Longer runs mean about 7–9 LLM calls per run, and a 3-try replay from the plan is about 20 calls. On Groq's free tier, expect each replay to take a few minutes and a full participant session to use much of one account's daily tokens. Measure this in the pilot.
- "Same outcome" uses the hidden tests plus a structural comparison of the steps. It does not use the LLM trajectory comparison from the roadmap, to save free-tier quota.
- One job runs at a time with real agents, so a verification blocks new runs until it finishes.
- Restarting the server marks unfinished runs as errors. Finished runs and their checkpoints are kept in `data/`.
