"""Load the assignment's 12 test cases. The eval grades against these verbatim."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CASES_PATH = Path(__file__).resolve().parents[2] / "assignment" / "test_cases.json"


def load_cases(path: str | Path | None = None) -> list[dict[str, Any]]:
    with open(path or CASES_PATH, encoding="utf-8") as fh:
        return json.load(fh)["test_cases"]
