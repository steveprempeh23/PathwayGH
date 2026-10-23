"""Deterministic programme-eligibility lookup against programmes.json.

Checks two independent things per category:
1. Does the computed aggregate fall within the category's band?
2. Do the student's actual elective subjects/grades satisfy the category's
   `required_electives` structure?

Earlier version (v0) checked only (1), which meant a student could be told
they're "eligible" for Medicine on aggregate alone without having taken
Biology/Chemistry/Physics at all - a real false positive. Fixed here.

Some categories (General Humanities, Open Public-University Entry, HND)
describe required electives in generic terms ("any approved Arts elective",
"varies by programme") rather than specific subject names. These cannot be
checked against a student's literal subject list, so electives_match for
those categories is explicitly None (unverifiable) - never silently coerced
to True or False.
"""

from typing import Dict, Optional

import json
from pathlib import Path

from app.core.grading_data import meets_min_grade
from app.models.eligibility import EligibilityResult, ProgrammeMatch

_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "structured" / "programmes.json"

_GENERIC_MARKERS = ("any approved", "varies by programme", "department-specific")

# required_core entries this specific enough to check against a named
# subject the student actually has a grade for. Anything else (e.g.
# "Integrated Science or Social Studies (track-dependent)") is left
# unverifiable - see docs/evaluation.md Failure 16.
_CHECKABLE_CORE_SUBJECTS = ("Integrated Science", "Social Studies")
_CORE_CREDIT_MIN_GRADE = "C6"


def _load_programmes() -> list[dict]:
    with open(_DATA_PATH, encoding="utf-8") as f:
        return json.load(f)["programme_categories"]


_PROGRAMMES = _load_programmes()


def _is_generic(options: list[str]) -> bool:
    return any(marker in opt.lower() for opt in options for marker in _GENERIC_MARKERS)


def _check_electives(
    required: dict, student_electives: Dict[str, str], elective_min_grade: str
) -> Optional[bool]:
    """Returns True/False if checkable against named subjects, None if the
    requirement is generic text and cannot be matched to literal subjects.
    """
    options = required.get("options", [])
    if _is_generic(options):
        return None

    req_type = required.get("type")

    if req_type == "all_of":
        for subject in options:
            grade = student_electives.get(subject)
            if grade is None or not meets_min_grade(grade, elective_min_grade):
                return False
        return True

    if req_type == "choose_n":
        n = required.get("n", 1)
        matched = [
            s
            for s in options
            if s in student_electives and meets_min_grade(student_electives[s], elective_min_grade)
        ]
        if len(matched) < n:
            return False

        for subject in required.get("also_required", []):
            grade = student_electives.get(subject)
            if grade is None or not meets_min_grade(grade, elective_min_grade):
                return False

        plus_additional = required.get("plus_additional")
        if plus_additional:
            remaining = [
                s
                for s, g in student_electives.items()
                if s not in matched and meets_min_grade(g, elective_min_grade)
            ]
            if len(remaining) < plus_additional:
                return False

        return True

    # Unknown structure - do not guess.
    return None


def _check_required_core(
    required_core: list[str], core_grades: Optional[Dict[str, str]]
) -> Optional[bool]:
    """Returns False if required_core names a specific subject (Integrated
    Science or Social Studies) that the student's core_grades don't meet
    at a credit pass (C6+), True if every specifically-named subject does,
    None if required_core names nothing checkable or core_grades wasn't
    supplied at all - never silently coerced to True or False either way.
    English Language and Core Mathematics are not re-checked here since
    compute_aggregate's credit_gate_passed already covers them; this
    exists specifically for the Integrated-Science-vs-Social-Studies
    nuance that credit_gate_passed does NOT cover on its own (see
    docs/evaluation.md Failure 16).
    """
    named = [s for s in required_core if s in _CHECKABLE_CORE_SUBJECTS]
    if not named or core_grades is None:
        return None

    for subject in named:
        grade = core_grades.get(subject)
        if grade is None or not meets_min_grade(grade, _CORE_CREDIT_MIN_GRADE):
            return False
    return True


def check_eligibility(
    aggregate: int,
    track: str,
    electives: Dict[str, str],
    core_grades: Optional[Dict[str, str]] = None,
) -> EligibilityResult:
    """core_grades, when supplied, should be {"Integrated Science": grade,
    "Social Studies": grade} - the student's ACTUAL grades in both, not
    just whichever was used for their overall aggregate (see
    AggregateResult.third_core_used). Optional and defaults to None for
    backward compatibility; without it, required_core_match is always None
    (unverifiable) rather than guessed. See docs/evaluation.md Failure 16.
    """
    matches: list[ProgrammeMatch] = []

    for prog in _PROGRAMMES:
        band = prog["aggregate_band"]
        # WASSCE aggregates run lower-is-better. `best` is the most
        # competitive cutoff actually observed/estimated for this category,
        # `worst` the least competitive - the band is the RANGE of cutoffs
        # seen across institutions in the category, not a floor a student
        # must clear from below. A student whose aggregate is better than
        # even the most competitive cutoff in the category (aggregate <
        # best) clears every real cutoff in it and must be eligible, not
        # excluded - see docs/evaluation.md Failure 11 for the live case
        # that exposed this (aggregate 6 marked ineligible for a 9-24 band).
        aggregate_eligible = aggregate <= band["worst"]

        electives_match = _check_electives(
            prog["required_electives"], electives, prog["elective_min_grade"]
        )
        required_core_match = _check_required_core(
            prog.get("required_core", []), core_grades
        )

        if electives_match is False or required_core_match is False:
            overall_eligible = False
        else:
            overall_eligible = aggregate_eligible

        if electives_match is None:
            elective_note = (
                "elective requirements for this category are generic and could not be "
                "checked against specific subjects"
            )
        elif electives_match:
            elective_note = "elective subjects/grades satisfy this category's requirement"
        else:
            elective_note = "elective subjects/grades do NOT satisfy this category's requirement"

        if required_core_match is False:
            core_note = (
                " This category specifically requires "
                f"{' and '.join(s for s in prog.get('required_core', []) if s in _CHECKABLE_CORE_SUBJECTS)} "
                "at credit level, which the student's grade does not meet, "
                "regardless of which subject was used in their overall aggregate."
            )
        else:
            core_note = ""

        reason = (
            f"Aggregate {aggregate} {'meets' if aggregate_eligible else 'does not meet'} "
            f"the {prog['confidence']} band ({band['best']}-{band['worst']}) for "
            f"{prog['category']} (aggregate must be {band['worst']} or better); "
            f"{elective_note}.{core_note}"
        )

        matches.append(
            ProgrammeMatch(
                category=prog["category"],
                aggregate_eligible=aggregate_eligible,
                electives_match=electives_match,
                required_core_match=required_core_match,
                overall_eligible=overall_eligible,
                reason=reason,
                confidence=prog["confidence"],
                aggregate_band=(band["best"], band["worst"]),
                institutions_example=prog.get("institutions_example", []),
            )
        )

    return EligibilityResult(aggregate=aggregate, track=track, matches=matches)
