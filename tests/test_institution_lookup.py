"""
Tests for data/structured/institutions.json and app/tools/institution_lookup.py.
"""
from app.tools.institution_lookup import (
    load_institutions,
    regions_covered,
    schools_by_category,
    schools_by_region,
)

VALID_CATEGORIES = {"A", "B", "C"}


def test_loads_without_error():
    schools = load_institutions()
    assert len(schools) > 100


def test_no_duplicate_school_names():
    schools = load_institutions()
    names = [s.name for s in schools]
    assert len(names) == len(set(names))


def test_every_school_has_a_source_url():
    for s in load_institutions():
        assert s.source_url.startswith("http")


def test_every_category_is_valid():
    for s in load_institutions():
        assert s.ges_category in VALID_CATEGORIES


def test_region_filter_matches_full_list():
    schools = load_institutions()
    accra = schools_by_region("Greater Accra")
    assert len(accra) == len([s for s in schools if s.region == "Greater Accra"])
    assert all(s.region == "Greater Accra" for s in accra)


def test_region_filter_is_case_insensitive():
    assert len(schools_by_region("greater accra")) == len(schools_by_region("Greater Accra"))


def test_category_filter_accepts_lowercase():
    assert schools_by_category("a") == schools_by_category("A")


def test_regions_covered_matches_data():
    schools = load_institutions()
    assert set(regions_covered()) == {s.region for s in schools}


def test_known_coverage_gaps_are_absent():
    # Documented in the dataset's _coverage_note: these regions are not yet
    # sourced. If one of these starts appearing, update the note - don't
    # just let this test silently rot.
    not_yet_sourced = {"Western North", "Oti", "Savannah", "North East"}
    assert not_yet_sourced.isdisjoint(set(regions_covered()))
