"""A scenario is a folder in /scenarios with scenario.json, the starting code,
a visible test the agents can see, and a hidden test that decides success."""
import json
from functools import lru_cache

from . import config


@lru_cache(maxsize=None)
def load(scenario_id):
    folder = config.SCENARIO_DIR / scenario_id
    meta = json.loads((folder / "scenario.json").read_text(encoding="utf-8"))

    def read(names):
        return {n: (folder / n).read_text(encoding="utf-8") for n in names}

    meta["start_files"] = read(meta["editable_files"])
    meta["visible_test_files"] = read(meta["visible_tests"])
    meta["hidden_test_files"] = read(meta["hidden_tests"])
    meta["mock_variants"] = {}
    for variant in ("mock_good", "mock_bad"):
        vdir = folder / variant
        if vdir.is_dir():
            meta["mock_variants"][variant] = {p.name: p.read_text(encoding="utf-8") for p in vdir.glob("*.py")}
    return meta


def all_scenarios():
    out = []
    for folder in config.SCENARIO_DIR.iterdir():
        if (folder / "scenario.json").exists():
            s = load(folder.name)
            out.append({"id": s["id"], "title": s["title"], "task": s["task"], "order": s.get("order", 50),
                        "level": s.get("level"),  # optional: "experienced" if only technical edits fix it
                        "checks": s.get("checks", {})})  # plain sentence per hidden test
    return sorted(out, key=lambda s: (s["order"], s["title"]))
