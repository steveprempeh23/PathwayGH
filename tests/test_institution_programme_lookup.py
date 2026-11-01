"""Data-integrity tests for data/structured/institution_programmes.json and
the alias resolution in app/tools/institution_programme_lookup.py - same
pattern as tests/test_institution_lookup.py, applied to the per-programme
cutoff data rather than the SHS list.
"""
import json
from pathlib import Path

from app.tools.institution_programme_lookup import lookup_institution_programmes

_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "structured" / "institution_programmes.json"


def _rows():
    return json.load(_DATA_PATH.open(encoding="utf-8"))["programmes"]


def test_loads_without_error():
    assert len(_rows()) > 0


def test_every_row_has_a_source_url():
    for row in _rows():
        assert row.get("source_url"), f"missing source_url: {row['institution']} / {row['programme']}"


def test_every_row_has_a_confidence_tier():
    valid = {"official_institution_source", "third_party_source"}
    for row in _rows():
        assert row.get("confidence") in valid, f"bad confidence tier: {row}"


def test_ucc_rows_present_and_well_formed():
    ucc_rows = [r for r in _rows() if r["institution"] == "UCC"]
    assert len(ucc_rows) == 54
    for row in ucc_rows:
        assert row["confidence"] == "third_party_source"
        # every row is either a real integer cutoff or honestly "Not published" -
        # never silently missing or guessed.
        if row["cutoff_display"] == "Not published":
            assert row["cutoff_primary"] is None
            assert row["notes"]
        else:
            assert isinstance(row["cutoff_primary"], int)


def test_lookup_finds_real_ucc_programme():
    result = lookup_institution_programmes("UCC", keyword="law")
    assert result.has_data_for_institution is True
    assert any(m.programme == "LLB Law" and m.cutoff_display == "12" for m in result.matches)


def test_lookup_resolves_ucc_full_name_alias():
    """Regression case: 'University of Cape Coast' is far more natural
    phrasing than 'UCC', but the data is stored under 'UCC' only (same
    short form programmes.json's institutions_example lists use). Without
    alias resolution, this would wrongly return has_data_for_institution
    False despite real data existing."""
    by_full_name = lookup_institution_programmes("University of Cape Coast", keyword="medicine")
    by_short_name = lookup_institution_programmes("UCC", keyword="medicine")
    assert by_full_name.has_data_for_institution is True
    assert by_full_name.matches == by_short_name.matches
    # The alias only resolves internally - the echoed institution field
    # still carries the caller's own original string unchanged (see
    # orchestrator.py's verified_institutions tracking, Failure 20).
    assert by_full_name.institution == "University of Cape Coast"


def test_lookup_reports_not_published_honestly():
    result = lookup_institution_programmes("UCC", keyword="Physician Assistant")
    assert result.has_data_for_institution is True
    row = next(m for m in result.matches if m.programme == "BSc Physician Assistant Studies")
    assert row.cutoff_display == "Not published"


def test_lookup_still_reports_no_data_for_truly_uncovered_institutions():
    """UCC now has data; most institutions still don't - this must not
    regress into assuming any named institution has data."""
    result = lookup_institution_programmes("UDS")
    assert result.has_data_for_institution is False
