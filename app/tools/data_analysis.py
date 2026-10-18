"""Question 9: Data Analysis Capability.

Mean, median, min, max, percentage, and trend are all computed with pandas,
never asked of the LLM - exactly the "Numerical calculation -> Python"
design principle stated in the course brief, applied here to cohort-level
aggregation rather than the single-student arithmetic in
aggregate_calculator.py.

IMPORTANT: the dataset this analyzes (data/structured/historical_student_outcomes.csv)
is synthetically generated (see scripts/generate_synthetic_outcomes.py), not
real admissions data. Every result includes a data_source note saying so -
this must be surfaced to the user, not silently dropped, so the system never
implies these are real historical outcomes.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

from app.models.analysis import CohortStats

_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "structured" / "historical_student_outcomes.csv"
_PROGRAMMES_PATH = Path(__file__).resolve().parents[2] / "data" / "structured" / "programmes.json"

DATA_SOURCE_NOTE = (
    "This dataset is synthetically generated for demonstration purposes "
    "(see scripts/generate_synthetic_outcomes.py) and does not represent "
    "real admissions records. These figures illustrate the analysis "
    "capability, not actual historical outcomes."
)


@lru_cache(maxsize=1)
def _load() -> pd.DataFrame:
    return pd.read_csv(_DATA_PATH)


@lru_cache(maxsize=1)
def _valid_categories() -> set[str]:
    with open(_PROGRAMMES_PATH, encoding="utf-8") as f:
        return {c["category"] for c in json.load(f)["programme_categories"]}


def analyze_outcomes(
    programme_category: Optional[str] = None, track: Optional[str] = None
) -> CohortStats:
    """Filters the synthetic cohort by category/track (either or both may be
    omitted for a whole-dataset summary) and returns deterministic
    aggregate statistics.

    Raises:
        ValueError: if programme_category is given but doesn't match a
            known category - catches typos early rather than silently
            returning an empty-looking zero-stats result that could be
            mistaken for "this category has no admitted students."
    """
    if programme_category and programme_category not in _valid_categories():
        raise ValueError(
            f"Unknown programme_category '{programme_category}'. "
            f"Valid categories: {sorted(_valid_categories())}"
        )

    df = _load()
    if programme_category:
        df = df[df["programme_category"] == programme_category]
    if track:
        df = df[df["track"] == track]

    if df.empty:
        return CohortStats(
            filter_programme_category=programme_category,
            filter_track=track,
            sample_size=0,
            mean_aggregate=0.0,
            median_aggregate=0.0,
            min_aggregate=0,
            max_aggregate=0,
            admission_rate_percent=0.0,
            admission_rate_by_year={},
            data_source=DATA_SOURCE_NOTE,
        )

    admission_rate_by_year = df.groupby("year")["admitted"].mean().mul(100).round(1)

    return CohortStats(
        filter_programme_category=programme_category,
        filter_track=track,
        sample_size=len(df),
        mean_aggregate=round(float(df["aggregate"].mean()), 2),
        median_aggregate=float(df["aggregate"].median()),
        min_aggregate=int(df["aggregate"].min()),
        max_aggregate=int(df["aggregate"].max()),
        admission_rate_percent=round(float(df["admitted"].mean()) * 100, 1),
        admission_rate_by_year={str(k): float(v) for k, v in admission_rate_by_year.items()},
        data_source=DATA_SOURCE_NOTE,
    )
