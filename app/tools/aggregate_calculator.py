"""Deterministic WASSCE aggregate calculation.

Per the course's explicit design principle - "do not use an LLM for a task
that deterministic software can perform more reliably" - this is a plain
Python function over a sourced JSON table. The LLM's only role is deciding
*when* to call this tool and how to phrase the result to the student; it
never computes or approximates the arithmetic itself.
"""

from app.core.grading_data import CREDIT_PASS as _CREDIT_PASS
from app.core.grading_data import POINTS as _POINTS
from app.models.grading import AggregateResult, GradeInput


def compute_aggregate(grade_input: GradeInput) -> AggregateResult:
    """Sum English + Core Mathematics + the BETTER of Integrated
    Science/Social Studies, plus the best 3 of (up to 4) elective grade
    points, and check the mandatory credit gate on those same three core
    subjects actually counted.

    Both Integrated Science and Social Studies are always provided (see
    GradeInput's docstring for why - every WASSCE candidate sits both,
    regardless of track) and the one with the better (lower) point value
    is the one counted toward the aggregate and the credit gate - this
    matches real WAEC aggregate-calculation practice, NOT a fixed
    track-based choice. See docs/evaluation.md Failure 16: an earlier
    version locked this to track, which could report a worse aggregate
    than the student's real one. Ties are broken toward Integrated
    Science (an arbitrary but documented choice - WAEC itself doesn't
    publish a tie-break rule, and a tie means the aggregate is identical
    either way).

    If a student provides 4 electives, only the best 3 (lowest point sum -
    lower is better in WASSCE grading) count toward the aggregate, matching
    real WAEC practice: the student doesn't choose which 3, WAEC's own
    system does. The 4th, weaker elective is recorded in subject_points for
    transparency but excluded from the aggregate sum - see electives_used
    on the result for exactly which ones counted.

    Raises:
        ValueError: if a grade isn't one of the nine valid WASSCE grades.
            GradeInput validation should normally catch this first, but the
            tool re-checks defensively rather than trusting its caller.
    """
    always_core = {
        "English Language": grade_input.english,
        "Core Mathematics": grade_input.core_mathematics,
    }
    both_third_core_options = {
        "Integrated Science": grade_input.integrated_science,
        "Social Studies": grade_input.social_studies,
    }

    all_subjects = dict(always_core)
    all_subjects.update(both_third_core_options)
    all_subjects.update(grade_input.electives)

    subject_points: dict[str, int] = {}
    for name, grade in all_subjects.items():
        if grade not in _POINTS:
            raise ValueError(
                f"Unknown grade '{grade}' for subject '{name}'. "
                f"Valid grades: {sorted(_POINTS)}"
            )
        subject_points[name] = _POINTS[grade]

    # Whichever of Integrated Science/Social Studies has the better (lower)
    # point value is the one actually counted - see docstring above.
    third_core_used = min(
        both_third_core_options.keys(),
        key=lambda name: subject_points[name],
    )
    core_subjects_used = {**always_core, third_core_used: both_third_core_options[third_core_used]}

    # Best 3 of however many electives were provided (3 or 4), by grade
    # point - lower is better. If exactly 3 were given, all 3 are used.
    elective_names_by_point = sorted(
        grade_input.electives.keys(),
        key=lambda name: subject_points[name],
    )
    electives_used = elective_names_by_point[:3]

    aggregate = sum(subject_points[name] for name in core_subjects_used) + sum(
        subject_points[name] for name in electives_used
    )

    # Only the three core subjects actually counted toward THIS aggregate
    # need to be credit passes - the unused one (e.g. a weaker Social
    # Studies grade when Integrated Science was better) doesn't gate
    # anything, matching real practice: it was never "your" core subject.
    gate_subjects = list(core_subjects_used.keys())
    failing_subjects = [s for s in gate_subjects if not _CREDIT_PASS[all_subjects[s]]]

    return AggregateResult(
        aggregate=aggregate,
        credit_gate_passed=len(failing_subjects) == 0,
        failing_subjects=failing_subjects,
        track=grade_input.track,
        subject_points=subject_points,
        third_core_used=third_core_used,
        electives_used=electives_used,
    )
