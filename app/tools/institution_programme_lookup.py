"""Deterministic lookup of real, per-institution, per-programme cutoff
data from data/structured/institution_programmes.json.

This exists because a live run showed the chat model inventing specific
degree titles per institution ("Bachelor of Medicine and Surgery at UDS",
"Bachelor of Arts in English at University of Ghana") with no real data
behind any of it - programmes.json only ever had category-level
institutions_example lists, never institution-level programme names (see
docs/evaluation.md Failure 13). institution_programmes.json now has real
per-programme cutoffs for University of Ghana (from UG's own official
admissions page) and KNUST (from a third-party site, lower confidence) -
see that file's own _source_note and _coverage_note for exactly what is
and isn't covered.

Scope discipline, same as every other tool in this codebase: only
institutions with real rows in the data get programme-level answers. Any
other institution - UCC, UDS, UHAS, every private university, etc. - must
get has_data_for_institution=False, never a fallback guess.
"""
import json
from pathlib import Path

from app.models.institution_programmes import (
    InstitutionProgrammeLookup,
    InstitutionProgrammeRow,
)

_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "structured" / "institution_programmes.json"

MAX_MATCHES = 30


def _load_rows() -> list[dict]:
    with _DATA_PATH.open(encoding="utf-8") as f:
        return json.load(f)["programmes"]


def lookup_institution_programmes(institution: str, keyword: str | None = None) -> InstitutionProgrammeLookup:
    """Case-insensitive exact match on institution name, optional
    case-insensitive substring match on programme name. Returns up to
    MAX_MATCHES rows - total_available_for_institution tells the caller if
    more exist than were returned, so it doesn't imply a short list is
    exhaustive when it isn't."""
    rows = _load_rows()
    institution_rows = [r for r in rows if r["institution"].lower() == institution.lower()]

    if not institution_rows:
        return InstitutionProgrammeLookup(
            institution=institution,
            keyword=keyword,
            matches=[],
            total_available_for_institution=0,
            has_data_for_institution=False,
        )

    if keyword:
        kw = keyword.lower()
        matched = [r for r in institution_rows if kw in r["programme"].lower()]
    else:
        matched = institution_rows

    return InstitutionProgrammeLookup(
        institution=institution,
        keyword=keyword,
        matches=[InstitutionProgrammeRow(**r) for r in matched[:MAX_MATCHES]],
        total_available_for_institution=len(matched),
        has_data_for_institution=True,
    )
