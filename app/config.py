"""All settings come from the .env file (see .env.example)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _get(name, default=None):
    value = os.getenv(name)
    return value if value not in (None, "") else default


# --- LLM -----------------------------------------------------------------
# Any OpenAI-compatible endpoint works. Presets fill in base URL + model.
PROVIDER_PRESETS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
        "key_env": "GROQ_API_KEY",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash",
        "key_env": "GEMINI_API_KEY",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5-coder:7b",
        "key_env": None,
    },
    "mock": {"base_url": None, "model": "mock", "key_env": None},
}

LLM_PROVIDER = _get("LLM_PROVIDER", "mock").lower()
_preset = PROVIDER_PRESETS.get(LLM_PROVIDER, PROVIDER_PRESETS["mock"])
LLM_BASE_URL = _get("LLM_BASE_URL", _preset["base_url"])
LLM_MODEL = _get("LLM_MODEL", _preset["model"])
LLM_API_KEY = _get("LLM_API_KEY") or (_get(_preset["key_env"]) if _preset["key_env"] else None) or "not-needed"
# Only sent if set. "low" keeps gpt-oss reasoning tokens (and free-tier usage) down.
LLM_REASONING_EFFORT = _get("LLM_REASONING_EFFORT", "low" if LLM_PROVIDER == "groq" else None)
LLM_TEMPERATURE = float(_get("LLM_TEMPERATURE", "0.7"))
LLM_MAX_RETRIES = int(_get("LLM_MAX_RETRIES", "8"))
# Seconds to wait between LLM calls; helps stay under free-tier tokens/minute.
LLM_MIN_INTERVAL = float(_get("LLM_MIN_INTERVAL", "2" if LLM_PROVIDER != "mock" else "0"))
MOCK_DELAY = float(_get("MOCK_DELAY", "0.4"))

# --- Agents --------------------------------------------------------------
PLAN_MAX_STEPS = int(_get("PLAN_MAX_STEPS", "3"))  # the planner's plan is cut to this many steps
FIXUP_ROUNDS = int(_get("FIXUP_ROUNDS", "1"))      # extra rounds if the visible test still fails
MAX_ROUNDS = PLAN_MAX_STEPS + FIXUP_ROUNDS          # upper bound on coder rounds, for display
# Feature 3: end successful runs with a simulated release (deploy + email the customer)
RELEASE_ACTIONS = _get("RELEASE_ACTIONS", "off").lower() in ("on", "true", "1", "yes")
DEFAULT_REPLAYS = int(_get("DEFAULT_REPLAYS", "3"))
MIN_REPLAYS = int(_get("MIN_REPLAYS", "3"))          # fewer tries than this can't support a verdict
MAX_REPLAYS = int(_get("MAX_REPLAYS", "5"))
BASELINE_REPLAYS = int(_get("BASELINE_REPLAYS", "3"))  # no-change replays per (run, step)

# Planted errors (wrong suggestions, inflated "k of n") only work when this is on.
# Keep it off for demos and normal use, so the tool never shows faked evidence.
STUDY_MODE = _get("STUDY_MODE", "off").lower() in ("on", "true", "1", "yes")

# --- Sandbox -------------------------------------------------------------
SANDBOX = _get("SANDBOX", "docker").lower()        # "docker" or "local"
DOCKER_IMAGE = _get("DOCKER_IMAGE", "python:3.11-slim")
TEST_TIMEOUT = int(_get("TEST_TIMEOUT", "40"))

# --- Paths ---------------------------------------------------------------
SCENARIO_DIR = ROOT / "scenarios"
DATA_DIR = ROOT / "data"
RUNS_DIR = DATA_DIR / "runs"
VERIFY_DIR = DATA_DIR / "verifications"
CHECKPOINT_DB = DATA_DIR / "checkpoints.sqlite"
for d in (DATA_DIR, RUNS_DIR, VERIFY_DIR):
    d.mkdir(parents=True, exist_ok=True)
