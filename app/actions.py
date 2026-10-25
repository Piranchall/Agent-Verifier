"""Feature 3: actions that reach outside the code, and the simulated world they change.

When RELEASE_ACTIONS=on, a run whose visible tests pass ends with a fixed release
step: deploy to staging, deploy to production, email the customer. Nothing real
happens. Each action is written to data/world/effects.jsonl, and the app shows
those effects ("the customer has received 4 emails").

Replays re-run the release step, so verifying a fix with several tries would
repeat the irreversible ones. A replay's action_policy decides, per action,
whether it runs or is held (recorded, not done).
"""
import json
import threading
import time

from . import config

WORLD_DIR = config.DATA_DIR / "world"
WORLD_DIR.mkdir(parents=True, exist_ok=True)
EFFECTS_PATH = WORLD_DIR / "effects.jsonl"
_lock = threading.Lock()

CUSTOMER = "customer@example.com"

# Order = order they happen in the release step.
TOOLS = {
    "deploy_to_staging": {
        "label": "Deploy to staging",
        "irreversible": False,
        "plain": "Puts this version on the test server. It can be replaced at any time.",
        "done": "Deployed this version to the staging server.",
        "held": "Held: would have deployed this version to the staging server.",
    },
    "deploy_to_production": {
        "label": "Deploy to production",
        "irreversible": True,
        "plain": "Replaces the live app that every user sees. The previous version is gone and this can't be undone.",
        "done": "Deployed this version to production. Every user now runs it.",
        "held": "Held: would have deployed this version to production.",
    },
    "email_customer": {
        "label": "Email the customer",
        "irreversible": True,
        "plain": "Sends the customer an email saying the bug is fixed. An email can't be unsent.",
        "done": f"Emailed the customer ({CUSTOMER}): \"Good news, the bug you reported is fixed.\"",
        "held": "Held: would have emailed the customer that the bug is fixed.",
    },
}


def call_text(tool, scenario_id, files):
    """The exact call, shown in the detailed view."""
    names = ", ".join(sorted(files))
    if tool == "email_customer":
        return (f'email_customer(to="{CUSTOMER}", subject="Your bug report", '
                f'body="Good news, the bug you reported in {scenario_id} is fixed.")')
    return f'{tool}(app="{scenario_id}", files=[{names}])'


def record(run_id, tool, status, detail):
    """Append one effect to the simulated world. status: done | held."""
    rec = {"time": time.time(), "run_id": run_id, "tool": tool, "status": status, "detail": detail}
    with _lock, open(EFFECTS_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def all_effects():
    if not EFFECTS_PATH.exists():
        return []
    with open(EFFECTS_PATH, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def public_tools():
    return {name: {k: v for k, v in t.items() if k in ("label", "irreversible", "plain")} for name, t in TOOLS.items()}
