"""Deterministic WASSCE aggregate calculation.

Per the course's explicit design principle - "do not use an LLM for a task
that deterministic software can perform more reliably" - this is a plain
Python function over a sourced JSON table. The LLM's only role is deciding
*when* to call this tool and how to phrase the result to the student; it
never computes or approximates the arithmetic itself.
"""

from app.core.grading_data import CREDIT_PASS as _CREDIT_PASS
from app.core.grading_data import POINTS as _POINTS
from app.models.grading import AggregateResult, GradeInput, Track


def compute_aggregate(grade_input: GradeInput) -> AggregateResult:
    """Sum the three core subjects plus the best 3 of (up to 4) elective
    grade points, and check the mandatory credit gate on English, Core
    Mathematics, and the track-dependent third core subject (Integrated
    Science for science track, Social Studies otherwise).

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
    third_core_name = (
        "Integrated Science" if grade_input.track == Track.science else "Social Studies"
    )
    core_subjects = {
        "English Language": grade_input.english,
        "Core Mathematics": grade_input.core_mathematics,
        third_core_name: grade_input.third_core,
    }

    all_subjects = dict(core_subjects)
    all_subjects.update(grade_input.electives)

    subject_points: dict[str, int] = {}
    for name, grade in all_subjects.items():
        if grade not in _POINTS:
            raise ValueError(
                f"Unknown grade '{grade}' for subject '{name}'. "
                f"Valid grades: {sorted(_POINTS)}"
            )
        subject_points[name] = _POINTS[grade]

    # Best 3 of however many electives were provided (3 or 4), by grade
    # point - lower is better. If exactly 3 were given, all 3 are used.
    elective_names_by_point = sorted(
        grade_input.electives.keys(),
        key=lambda name: subject_points[name],
    )
    electives_used = elective_names_by_point[:3]

    aggregate = sum(subject_points[name] for name in core_subjects) + sum(
        subject_points[name] for name in electives_used
    )

    gate_subjects = list(core_subjects.keys())
    failing_subjects = [s for s in gate_subjects if not _CREDIT_PASS[all_subjects[s]]]

    return AggregateResult(
        aggregate=aggregate,
        credit_gate_passed=len(failing_subjects) == 0,
        failing_subjects=failing_subjects,
        track=grade_input.track,
        subject_points=subject_points,
        electives_used=electives_used,
    )
