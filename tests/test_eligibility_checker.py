from app.tools.eligibility_checker import check_eligibility


def test_correct_electives_and_aggregate_eligible_for_medicine():
    result = check_eligibility(
        aggregate=8,
        track="science",
        electives={"Biology": "B2", "Chemistry": "B3", "Physics": "A1"},
    )
    medicine = next(m for m in result.matches if "Medicine" in m.category)
    assert medicine.aggregate_eligible is True
    assert medicine.electives_match is True
    assert medicine.overall_eligible is True


def test_regression_in_band_aggregate_but_wrong_electives_is_not_eligible():
    """This is exactly the false-positive the earlier version had: aggregate
    looks fine for Medicine, but the student never took the required
    science electives at all.
    """
    result = check_eligibility(
        aggregate=8,
        track="science",
        electives={"Economics": "B2", "Government": "B3", "Literature": "A1"},
    )
    medicine = next(m for m in result.matches if "Medicine" in m.category)
    assert medicine.aggregate_eligible is True
    assert medicine.electives_match is False
    assert medicine.overall_eligible is False  # the actual fix


def test_elective_grade_below_minimum_fails_match():
    """Right subjects, but Chemistry grade (C6) is below Medicine's B3 minimum."""
    result = check_eligibility(
        aggregate=8,
        track="science",
        electives={"Biology": "A1", "Chemistry": "C6", "Physics": "A1"},
    )
    medicine = next(m for m in result.matches if "Medicine" in m.category)
    assert medicine.electives_match is False


def test_generic_category_reports_none_not_a_guess():
    """General Humanities/Education lists 'any approved Arts elective' - this
    cannot be checked against specific subject names and must report None,
    not silently True or False.
    """
    result = check_eligibility(
        aggregate=20, track="arts", electives={"Literature": "B2", "History": "B3", "French": "A1"}
    )
    humanities = next(m for m in result.matches if "Humanities" in m.category)
    assert humanities.electives_match is None
    # aggregate-only eligibility still applies since electives_match isn't False
    assert humanities.overall_eligible == humanities.aggregate_eligible


def test_high_aggregate_ineligible_for_medicine_but_eligible_for_hnd():
    result = check_eligibility(
        aggregate=40,
        track="technical",
        electives={"Business Management": "C5", "Economics": "C6", "ICT": "C4"},
    )
    medicine = next(m for m in result.matches if "Medicine" in m.category)
    hnd = next(m for m in result.matches if "HND" in m.category)
    assert medicine.aggregate_eligible is False
    assert hnd.aggregate_eligible is True


def test_institutions_example_populated_from_real_sourced_data():
    """Regression test for Failure 7: the chat model invented school names
    instead of using real sourced data that already existed in
    programmes.json but was never surfaced anywhere. Confirms it now is."""
    result = check_eligibility(
        aggregate=8,
        track="science",
        electives={"Biology": "B2", "Chemistry": "B3", "Physics": "A1"},
    )
    medicine = next(m for m in result.matches if "Medicine" in m.category)
    assert "University of Ghana" in medicine.institutions_example
    assert len(medicine.institutions_example) > 0


def test_every_category_present_in_result():
    result = check_eligibility(aggregate=20, track="general", electives={})
    categories = {m.category for m in result.matches}
    assert len(categories) == 7
