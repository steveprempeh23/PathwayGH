"""Deterministic lookup of a programme category's real, sourced
institutions_example list.

app/tools/eligibility_checker.py already returns this data alongside a full
eligibility check, but the chat model has no tool access to
compute_aggregate/check_eligibility (see docs/evaluation.md Failure 6) - its
only way to answer a bare "which schools for category X" question was to
recall/paraphrase the "Aggregate: ..." table text injected into the
conversation earlier (see docs/evaluation.md Failure 8). A live run showed
exactly the failure that invites: asked "schools eligible for Physician
Assistantship", the model invented four institutions (University of Ghana,
UCC, KNUST, UMaT) that aren't in that category's real institutions_example
([UHAS, UDS]) at all - see docs/evaluation.md Failure 12.

This tool gives the chat model a real, callable path to the same data
instead, so it has something better to do than recall from memory. Per
Failure 12's own honest limitation note: giving the model a tool reduces
but does not guarantee it won't still answer from memory instead of calling
this - there is no code-level way to force a free-text reply to only name
institutions a tool actually returned (same acknowledged gap as Failure 9's
"model could still assert things in plain text").
"""
import json
from pathlib import Path

from app.models.institutions import InstitutionsLookup

_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "structured" / "programmes.json"


def _load_programmes() -> list[dict]:
    with open(_DATA_PATH, encoding="utf-8") as f:
        return json.load(f)["programme_categories"]


def lookup_institutions(programme_category: str) -> InstitutionsLookup:
    """Exact-match lookup by category name.

    Raises:
        ValueError: if programme_category doesn't match a known category -
            fed back to the model as a tool error so it can retry with a
            correct name, rather than silently returning an empty-looking
            result that could be mistaken for "this category has no
            institutions on file."
    """
    programmes = _load_programmes()
    for prog in programmes:
        if prog["category"] == programme_category:
            return InstitutionsLookup(
                category=prog["category"],
                institutions_example=prog.get("institutions_example", []),
                confidence=prog["confidence"],
            )

    valid = [p["category"] for p in programmes]
    raise ValueError(
        f"Unknown programme_category '{programme_category}'. Valid categories: {valid}"
    )


def category_institutions_map() -> dict[str, list[str]]:
    """Maps each category name to its real institutions_example list -
    used by app/tools/institution_category_mismatch_guard.py (Failure 18)
    to check whether an institution the model names for a category
    actually belongs to it."""
    return {prog["category"]: prog.get("institutions_example", []) for prog in _load_programmes()}


def all_known_institution_names() -> set[str]:
    """Every institution name that appears in any category's
    institutions_example list, across the whole file. Used by
    app/tools/institution_claim_guard.py to catch a reply naming a real
    institution alongside an invented programme - see docs/evaluation.md
    Failure 14."""
    names: set[str] = set()
    for prog in _load_programmes():
        names.update(prog.get("institutions_example", []))
    return names
