"""
Deterministic lookup over data/structured/institutions.json.

Per docs/extending-data.md ("Adding real per-school data"), this is
intentionally a thin, read-only lookup - NOT an eligibility checker. The
dataset has no programme-offerings or cutoff fields per school, so this
module cannot and does not answer "am I eligible for school X" - only
"what schools do we have on file for region Y / category Z".

Not wired into the chat model's tool list. Per Failure 6 in
docs/evaluation.md, free-text-parsed tools on this project have a history
of failing in several different ways; exposing this to chat is a decision
left to whoever does the real per-school sourcing work next, same as
docs/extending-data.md recommends for eligibility-style lookups.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "structured" / "institutions.json"


@dataclass(frozen=True)
class Institution:
    name: str
    region: str
    ges_category: str
    confidence: str
    source_url: str
    gender: Optional[str] = None
    town: Optional[str] = None
    accommodation: Optional[str] = None


def _load_raw() -> dict:
    with _DATA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def load_institutions() -> list[Institution]:
    """Load every school in the dataset as Institution objects."""
    raw = _load_raw()
    return [
        Institution(
            name=s["name"],
            region=s["region"],
            ges_category=s["ges_category"],
            confidence=s["confidence"],
            source_url=s["source_url"],
            gender=s.get("gender"),
            town=s.get("town"),
            accommodation=s.get("accommodation"),
        )
        for s in raw["schools"]
    ]


def regions_covered() -> list[str]:
    """Regions with at least one sourced school in the dataset.

    NOTE: a region missing from this list means "not yet sourced", not
    "no schools exist there" - see the dataset's _coverage_note.
    """
    return sorted({i.region for i in load_institutions()})


def schools_by_region(region: str) -> list[Institution]:
    return [i for i in load_institutions() if i.region.lower() == region.lower()]


def schools_by_category(category: str) -> list[Institution]:
    category = category.upper()
    return [i for i in load_institutions() if i.ges_category == category]


if __name__ == "__main__":
    all_schools = load_institutions()
    print(f"{len(all_schools)} schools loaded across {len(regions_covered())} regions.")
