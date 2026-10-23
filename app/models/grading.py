from enum import Enum
from typing import Dict, List

from pydantic import BaseModel, Field, field_validator

VALID_GRADES = {"A1", "B2", "B3", "C4", "C5", "C6", "D7", "E8", "F9"}


class Track(str, Enum):
    science = "science"
    non_science = "non_science"


class GradeInput(BaseModel):
    """Raw grades a student reports: English, Core Mathematics, BOTH
    Integrated Science and Social Studies, and 3-4 electives.

    Integrated Science and Social Studies are both collected - not just
    whichever matches the student's track - because WAEC lists BOTH as
    mandatory "Core Subjects for the examination" for every WASSCE
    candidate regardless of programme/track (waecgh.org), and multiple
    independent aggregate-calculation guides agree the THIRD core subject
    that counts toward a student's own aggregate is whichever of the two
    gives the better (lower) grade - not a fixed track-based choice. See
    docs/evaluation.md Failure 16: an earlier version of this schema only
    collected one, locked to track, which (a) could report a worse
    aggregate than the student's real one if their track-locked subject
    happened to be weaker, and (b) made it structurally impossible to
    check a category's required_core when it named the OTHER subject
    (e.g. a science-track student's Social Studies grade was never
    collected, so Business/Finance's Social Studies requirement could
    never be verified for them).

    compute_aggregate picks whichever of the two is better for the
    aggregate SUM (see AggregateResult.third_core_used for which one was
    actually used) - but check_eligibility separately verifies BOTH
    against whatever specific subject a given category's required_core
    actually names, since some categories (Medicine, Engineering, General
    Science) require Integrated Science specifically and others (Business,
    Humanities) require Social Studies specifically, regardless of which
    one happened to be better for the student's own aggregate number.

    Only 3 core subjects ever count toward the tertiary admission
    aggregate under real WAEC rules - there is no "4th core" beyond these;
    English and Core Mathematics are always 2 of the 3, and the better of
    Integrated Science/Social Studies is the 3rd.

    Electives are different: many science-track students sit 4 electives
    (Elective Mathematics plus three sciences), and WAEC's own rule is to
    automatically use the best 3 of however many a student sat for the
    aggregate - the student doesn't choose which 3. compute_aggregate
    implements that same best-3-of-N selection; see AggregateResult's
    electives_used field for which ones were actually counted.

    Validated here so a malformed grade never reaches the calculation tool.
    """

    english: str
    core_mathematics: str
    integrated_science: str
    social_studies: str
    electives: Dict[str, str] = Field(min_length=3, max_length=4)
    track: Track

    @field_validator("english", "core_mathematics", "integrated_science", "social_studies")
    @classmethod
    def _valid_core_grade(cls, v: str) -> str:
        if v not in VALID_GRADES:
            raise ValueError(f"'{v}' is not a valid WASSCE grade. Valid: {sorted(VALID_GRADES)}")
        return v

    @field_validator("electives")
    @classmethod
    def _valid_elective_grades(cls, v: Dict[str, str]) -> Dict[str, str]:
        for subject, grade in v.items():
            if grade not in VALID_GRADES:
                raise ValueError(
                    f"'{grade}' is not a valid WASSCE grade for elective '{subject}'. "
                    f"Valid: {sorted(VALID_GRADES)}"
                )
        return v


class AggregateResult(BaseModel):
    aggregate: int
    credit_gate_passed: bool
    failing_subjects: List[str]
    track: Track
    subject_points: Dict[str, int]
    third_core_used: str = ""
    """Which of "Integrated Science"/"Social Studies" was actually counted
    toward the aggregate sum and the credit gate - the better (lower-point)
    of the two, per real WAEC aggregate-calculation practice. The other one
    is still present in subject_points for transparency, but did NOT count
    toward this aggregate. See docs/evaluation.md Failure 16."""
    electives_used: List[str] = []
    """Which elective subjects actually counted toward the aggregate - the
    best 3 by grade point if 4 were provided, all 3 if only 3 were given.
    Lets the UI show the student exactly which subjects were used, since
    the answer isn't always "all of them you entered"."""
