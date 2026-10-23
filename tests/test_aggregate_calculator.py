import pytest

from app.models.grading import GradeInput, Track
from app.tools.aggregate_calculator import compute_aggregate


def test_worked_example_from_source_doc():
    """English(B3=3) + Core Math(B2=2) + Int.Science(C4=4) + three electives
    (B2=2, B3=3, C4=4) = 18. This exact example is quoted in
    data/raw/wassce_grading_and_admission_guide.md, sourced from a public
    WAEC-aggregate explainer - using it as a test case ties the test directly
    back to the cited source rather than an invented number. Social Studies
    is given a deliberately worse grade (F9) so Integrated Science remains
    the one actually used, preserving the source example's arithmetic.
    """
    grade_input = GradeInput(
        english="B3",
        core_mathematics="B2",
        integrated_science="C4",
        social_studies="F9",
        electives={"Elective 1": "B2", "Elective 2": "B3", "Elective 3": "C4"},
        track=Track.science,
    )
    result = compute_aggregate(grade_input)
    assert result.aggregate == 18
    assert result.credit_gate_passed is True
    assert result.failing_subjects == []
    assert result.third_core_used == "Integrated Science"


def test_credit_gate_fails_on_core_maths_below_c6():
    """A1s everywhere else but D7 in Core Maths: numerically low aggregate,
    but must still fail the mandatory credit gate - this is the exact
    scenario documented in the source guide as a real admission pitfall.
    """
    grade_input = GradeInput(
        english="A1",
        core_mathematics="D7",
        integrated_science="A1",
        social_studies="A1",
        electives={"Elective 1": "A1", "Elective 2": "A1", "Elective 3": "A1"},
        track=Track.non_science,
    )
    result = compute_aggregate(grade_input)
    assert result.aggregate == 12
    assert result.credit_gate_passed is False
    assert "Core Mathematics" in result.failing_subjects


def test_third_core_uses_whichever_is_better_regardless_of_track():
    """Regression test for Failure 16 (docs/evaluation.md): the third core
    subject counted is whichever of Integrated Science/Social Studies gives
    the better (lower) point value - NOT a fixed track-based choice. Here a
    non-science-track student's Integrated Science (B2=2) beats their
    Social Studies (C5=5), so Integrated Science must be the one used, even
    though track is non_science.
    """
    grade_input = GradeInput(
        english="B2",
        core_mathematics="B2",
        integrated_science="B2",
        social_studies="C5",
        electives={"Elective 1": "C4", "Elective 2": "C5", "Elective 3": "C6"},
        track=Track.non_science,
    )
    result = compute_aggregate(grade_input)
    assert result.third_core_used == "Integrated Science"
    # Both grades are still recorded for transparency, even the unused one.
    assert result.subject_points["Social Studies"] == 5
    assert result.subject_points["Integrated Science"] == 2


def test_third_core_uses_social_studies_when_better_even_on_science_track():
    """The reverse of the test above - a science-track student whose
    Social Studies grade is better than their Integrated Science grade
    must still get Social Studies counted. Track locking this to
    Integrated Science (the pre-Failure-16 behavior) would have reported
    a worse aggregate than the student's real one.
    """
    grade_input = GradeInput(
        english="B2",
        core_mathematics="B2",
        integrated_science="C6",
        social_studies="B3",
        electives={"Biology": "B2", "Chemistry": "B3", "Physics": "A1"},
        track=Track.science,
    )
    result = compute_aggregate(grade_input)
    assert result.third_core_used == "Social Studies"


def test_four_electives_uses_best_three_per_real_waec_rule():
    """A science student commonly sits 4 electives (Elective Maths + 3
    sciences). WAEC uses the best 3 by grade automatically - the student
    doesn't choose. Here the weakest (Chemistry C6) should be dropped.
    """
    grade_input = GradeInput(
        english="B2",
        core_mathematics="B2",
        integrated_science="B2",
        social_studies="F9",
        electives={
            "Elective Mathematics": "A1",
            "Biology": "A1",
            "Physics": "B3",
            "Chemistry": "C6",  # weakest - should be excluded
        },
        track=Track.science,
    )
    result = compute_aggregate(grade_input)
    assert set(result.electives_used) == {"Elective Mathematics", "Biology", "Physics"}
    assert "Chemistry" not in result.electives_used
    # 3 core (B2=2 each => 6) + best 3 electives (1+1+3=5) = 11
    assert result.aggregate == 11
    # The dropped elective's grade is still recorded for transparency.
    assert result.subject_points["Chemistry"] == 6


def test_three_electives_all_count_as_before():
    """Exactly 3 electives: no selection needed, all 3 count - confirms
    the 4-elective change didn't alter the original 3-elective behavior."""
    grade_input = GradeInput(
        english="B2",
        core_mathematics="B2",
        integrated_science="B2",
        social_studies="F9",
        electives={"Biology": "A1", "Physics": "B3", "Chemistry": "C6"},
        track=Track.science,
    )
    result = compute_aggregate(grade_input)
    assert set(result.electives_used) == {"Biology", "Physics", "Chemistry"}


def test_subject_points_always_includes_both_core_options():
    """Both Integrated Science and Social Studies must always appear in
    subject_points, regardless of which one was actually used - this is
    what makes it possible for check_eligibility to later verify a
    category's specific required_core requirement against whichever
    subject it actually names (see docs/evaluation.md Failure 16)."""
    grade_input = GradeInput(
        english="B2",
        core_mathematics="B2",
        integrated_science="A1",
        social_studies="C6",
        electives={"Biology": "A1", "Physics": "B3", "Chemistry": "C6"},
        track=Track.science,
    )
    result = compute_aggregate(grade_input)
    assert "Integrated Science" in result.subject_points
    assert "Social Studies" in result.subject_points


def test_invalid_grade_raises_via_pydantic_validation():
    with pytest.raises(ValueError):
        GradeInput(
            english="Z9",  # not a real WASSCE grade
            core_mathematics="B2",
            integrated_science="C4",
            social_studies="C4",
            electives={"Elective 1": "B2", "Elective 2": "B3", "Elective 3": "C4"},
            track=Track.science,
        )
