"""Single source of truth for loading grading_scale.json. Both
aggregate_calculator and eligibility_checker need grade-point lookups;
previously each loaded the JSON independently, which is a small but real
duplication risk (one could drift from the other). Centralized here instead.
"""

import json
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "structured" / "grading_scale.json"


def _load() -> dict:
    with open(_DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


_GRADING_SCALE = _load()

POINTS: dict[str, int] = {g["grade"]: g["points"] for g in _GRADING_SCALE["grades"]}
CREDIT_PASS: dict[str, bool] = {g["grade"]: g["credit_pass"] for g in _GRADING_SCALE["grades"]}


def meets_min_grade(grade: str, min_grade: str) -> bool:
    """True if `grade` is at least as good as `min_grade` (lower points = better)."""
    if grade not in POINTS or min_grade not in POINTS:
        raise ValueError(f"Unknown grade in comparison: '{grade}' vs '{min_grade}'")
    return POINTS[grade] <= POINTS[min_grade]
