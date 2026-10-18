from app.services.calculation_summary import build_calculation_summary
from app.tools.aggregate_calculator import compute_aggregate
from app.tools.eligibility_checker import check_eligibility
from app.models.grading import GradeInput, Track


def test_summary_mentions_eligible_categories_and_institutions():
    grade_input = GradeInput(
        english="A1", core_mathematics="A1", third_core="A1",
        electives={"Biology": "A1", "Chemistry": "B2", "Physics": "B2"},
        track=Track.science,
    )
    aggregate = compute_aggregate(grade_input)
    eligibility = check_eligibility(
        aggregate=aggregate.aggregate, track="science", electives=grade_input.electives
    )

    summary = build_calculation_summary(aggregate, eligibility)

    assert "Aggregate: 8" in summary
    assert "credit gate passed" in summary
    assert "Medicine / Dentistry" in summary
    assert "University of Ghana" in summary  # institutions_example flowed through


def test_summary_mentions_failed_credit_gate():
    grade_input = GradeInput(
        english="A1", core_mathematics="D7", third_core="A1",
        electives={"E1": "A1", "E2": "A1", "E3": "A1"},
        track=Track.non_science,
    )
    aggregate = compute_aggregate(grade_input)
    eligibility = check_eligibility(
        aggregate=aggregate.aggregate, track="non_science", electives=grade_input.electives
    )

    summary = build_calculation_summary(aggregate, eligibility)

    assert "FAILED" in summary
    assert "Core Mathematics" in summary


def test_summary_lists_ineligible_categories_too():
    grade_input = GradeInput(
        english="C6", core_mathematics="C6", third_core="C6",
        electives={"Government": "C6", "History": "C6", "Literature in English": "C6"},
        track=Track.non_science,
    )
    aggregate = compute_aggregate(grade_input)
    eligibility = check_eligibility(
        aggregate=aggregate.aggregate, track="non_science", electives=grade_input.electives
    )

    summary = build_calculation_summary(aggregate, eligibility)

    assert "NOT eligible for" in summary
    assert "Medicine / Dentistry" in summary  # high aggregate, excluded from this category
