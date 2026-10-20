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
    assert len(categories) == 9


def test_aggregate_better_than_bands_best_is_still_eligible():
    """Regression test for Failure 11 (docs/evaluation.md): a student with
    aggregate 6 (excellent - lower is better in WASSCE) was marked
    INELIGIBLE for Physician Assistantship's 9-24 band purely because 6 is
    better than the band's `best`=9. There is no such thing as "too good"
    an aggregate in this system - any aggregate at or better than a
    category's `worst` cutoff clears every real cutoff in that category.
    """
    result = check_eligibility(
        aggregate=6,
        track="science",
        electives={"Biology": "B2", "Chemistry": "B2", "Physics": "A1"},
    )
    pa = next(m for m in result.matches if "Physician Assistantship" in m.category)
    assert pa.aggregate_band == (9, 24)
    assert pa.aggregate_eligible is True
    assert pa.overall_eligible is True


def test_aggregate_worse_than_bands_worst_is_ineligible():
    """The upper bound still correctly excludes a genuinely weaker aggregate."""
    result = check_eligibility(
        aggregate=30,
        track="science",
        electives={"Biology": "B2", "Chemistry": "B2", "Physics": "A1"},
    )
    pa = next(m for m in result.matches if "Physician Assistantship" in m.category)
    assert pa.aggregate_eligible is False


def test_private_university_entry_institutions_are_real_and_dont_duplicate_public_ones():
    """UPSA and GCTU are public (already in 'Open Public-University Entry')
    and must NOT also appear under 'Private University Entry' - a live
    correction of the user-supplied school list that originally
    misclassified both as private (see
    programmes.json's _private_university_category_note)."""
    result = check_eligibility(aggregate=20, track="general", electives={})
    private = next(m for m in result.matches if m.category == "Private University Entry")
    public_floor = next(
        m for m in result.matches if m.category == "Open Public-University Entry (general eligibility floor)"
    )
    assert "UPSA" not in private.institutions_example
    assert "GCTU" not in private.institutions_example
    assert "UPSA" in public_floor.institutions_example
    assert "GCTU" in public_floor.institutions_example
    assert "Ashesi University" in private.institutions_example
    assert len(private.institutions_example) == 15


def test_physician_assistantship_eligible_with_right_electives_and_c6_grades():
    """C6 (an ordinary credit pass) is enough for Physician Assistantship -
    deliberately less competitive than Medicine/Dentistry's B3 minimum,
    even though both categories require the same three electives. This is
    the actual, sourced distinction (see programmes.json's
    _physician_assistantship_note), not a copy of the Medicine test."""
    result = check_eligibility(
        aggregate=20,
        track="science",
        electives={"Biology": "C6", "Chemistry": "C6", "Physics": "C6"},
    )
    pa = next(m for m in result.matches if "Physician Assistantship" in m.category)
    assert pa.aggregate_eligible is True
    assert pa.electives_match is True
    assert pa.overall_eligible is True


def test_physician_assistantship_same_grades_fail_medicine_but_pass_pa():
    """Same student, same subjects, same aggregate: fails Medicine's B3
    elective floor but clears Physician Assistantship's C6 floor - the
    whole point of giving them different elective_min_grade values."""
    result = check_eligibility(
        aggregate=9,
        track="science",
        electives={"Biology": "C6", "Chemistry": "C6", "Physics": "C6"},
    )
    medicine = next(m for m in result.matches if m.category == "Medicine / Dentistry")
    pa = next(m for m in result.matches if "Physician Assistantship" in m.category)
    assert medicine.electives_match is False
    assert pa.electives_match is True


def test_physician_assistantship_institutions_example_is_real_sourced_public_universities():
    result = check_eligibility(
        aggregate=12,
        track="science",
        electives={"Biology": "B2", "Chemistry": "B2", "Physics": "B2"},
    )
    pa = next(m for m in result.matches if "Physician Assistantship" in m.category)
    assert "UHAS" in pa.institutions_example
    assert len(pa.institutions_example) > 0
