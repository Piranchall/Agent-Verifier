# Agent Verifier

**Interactive verification and safe steering of AI coding agents.**

Agent Verifier is a research prototype for studying how people debug and steer multi-agent coding systems. A small AI team (Planner, Coder and Test runner) tries to fix a bug in a to-do app. When it fails, the tool helps you find where to step in, edit that step, replay the run, and check whether your fix actually worked.

> Built as an HCI course project. For the full write-up, including the study design, calibration results, logging schema and limitations, see **[REPORT.md](REPORT.md)**.

---

## Features

| | Feature | What it does |
| --- | --- | --- |
| 🎯 | **Where to intervene** | Ranks the steps of a failed run by how much the rest of the run depends on them, and explains what in each step should change. |
| ⏪ | **Edit and replay** | Rewind to any editable step (the request, the plan or an instruction), change it, and fork a new run from that point. |
| ✅ | **Did the fix hold?** | Replays your edit several times against hidden acceptance tests and compares the result with a no-change baseline, for example *"Your change: 3 of 3. Without your change: 1 of 3."* |
| 🔍 | **Two levels of detail** | A **Simple** view with plain-language summaries, and a **Detailed** view that shows the agents' raw output. |
| 🛑 | **Irreversible actions** *(optional)* | Simulates a release (deploy and customer email) and lets you hold actions that can't be undone before you replay. |
| 🧪 | **Study mode** | Participant sessions, confidence ratings, planted errors and a full action log for user studies. |

## How it works

```
Request ──► Planner ──► Plan (2–3 steps)
                          │
                          ▼  for each step
                 Planner instruction ──► Coder ──► Test runner
                          │
                          ▼
               Fix-up round (if the visible test still fails)
                          │
                          ▼
               Hidden acceptance tests decide success
```

The agents only see one simple visible test. Success is judged by hidden tests, so a run can pass the visible test and still be wrong. That gap is what the verification features are built to expose.

## Quick start

### Prerequisites

- **Python 3.11+**
- **Docker Desktop**, used to run the agents' code in an isolated sandbox

```bash
docker pull python:3.11-slim
```

### Run

**Windows:** double-click `run.bat`

**macOS / Linux:**
```bash
./run.sh
```

The first run creates a virtual environment, installs dependencies and copies `.env.example` to `.env`. Then open **http://localhost:8000**.

The app starts in **mock mode**, with offline fake agents and no API key needed, so you can explore the interface right away.

### Use real agents

1. Get a free API key from [Groq](https://console.groq.com/keys). No credit card is required.
2. Edit `.env`:
   ```env
   LLM_PROVIDER=groq
   GROQ_API_KEY=gsk_...
   ```
3. Restart the server.

Gemini (`LLM_PROVIDER=gemini`), local Ollama models (`LLM_PROVIDER=ollama`) and any OpenAI-compatible endpoint (`LLM_BASE_URL`, `LLM_MODEL`) are also supported.

### Check your setup

| Check | How |
| --- | --- |
| Sandbox | Open http://localhost:8000/api/sandbox/check. It should return `"ok": true`. |
| End-to-end, no key or Docker needed | `python scripts/smoke_test.py` |

## Configuration

All settings live in `.env`. The most common ones:

| Variable | Default | Description |
| --- | --- | --- |
| `LLM_PROVIDER` | `mock` | `mock`, `groq`, `gemini` or `ollama` |
| `SANDBOX` | `docker` | `docker` (isolated) or `local` (not isolated; only use it if Docker isn't available) |
| `DEFAULT_REPLAYS` | `3` | Replays per verification |
| `BASELINE_REPLAYS` | `3` | No-change replays used for comparison |
| `RELEASE_ACTIONS` | `off` | Turns on the simulated release step |
| `STUDY_MODE` | `off` | Allows planted errors for user studies |

See [`.env.example`](.env.example) for the full list.

## Project structure

```
app/          Backend: FastAPI server, LangGraph agent team, evidence ranking, replays, study logic
static/       Frontend: single-page UI
scenarios/    Bug-fix tasks, each with visible and hidden tests and mock solutions
scripts/      Calibration, baseline precomputation and smoke tests
study/        Participant session plans
```

## Scenarios

| Scenario | Challenge |
| --- | --- |
| Repeating tasks | Monthly tasks must return to their original day after a short month. |
| Duplicated tasks | Copy numbers must never be reused after a delete. |
| Rescheduled tasks | Moving one copy of a weekly task must not shift the series. |
| Practice tasks | Undo, delete and clear completed, used as warm-ups. |

See [REPORT.md](REPORT.md#scenarios-and-calibration) for calibration results and how to add your own scenario.

## Documentation

- **[REPORT.md](REPORT.md)**: detailed design, API cost and rate limits, calibration, the no-change baseline, study sessions, the event log, and known limitations.
