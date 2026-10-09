"""Loading packaged example scenarios and user-supplied scenario files."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from boardroom.models import Scenario

MAX_FILE_BYTES = 64 * 1024


def list_scenarios() -> list[str]:
    root = resources.files("boardroom") / "scenarios"
    return sorted(p.name.removesuffix(".json") for p in root.iterdir() if p.name.endswith(".json"))


def load_packaged(scenario_id: str) -> Scenario:
    if scenario_id not in list_scenarios():
        raise KeyError(
            f"unknown scenario {scenario_id!r} (available: {', '.join(list_scenarios())})"
        )
    text = (resources.files("boardroom") / "scenarios" / f"{scenario_id}.json").read_text("utf-8")
    return Scenario.model_validate(json.loads(text))


def load_file(path: Path) -> Scenario:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"scenario file is larger than {MAX_FILE_BYTES // 1024} KB")
    return Scenario.model_validate(json.loads(path.read_text("utf-8")))
