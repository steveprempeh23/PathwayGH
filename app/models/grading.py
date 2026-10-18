from enum import Enum
from typing import Dict, List

from pydantic import BaseModel, Field, field_validator

VALID_GRADES = {"A1", "B2", "B3", "C4", "C5", "C6", "D7", "E8", "F9"}


class Track(str, Enum):
    science = "science"
    non_science = "non_science"


class GradeInput(BaseModel):
    """Raw grades a student reports: English, Core Mathematics, one
    track-dependent third core subject, and 3-4 electives.

    Only 3 core subjects ever count toward the tertiary admission
    aggregate under real WAEC rules, regardless of how many a student
    registers for - there is no "4th core" field because collecting one
    would gather data the aggregate calculation never uses.

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
    third_core: str = Field(
        description="Integrated Science if track=science, Social Studies if track=non_science"
    )
    electives: Dict[str, str] = Field(min_length=3, max_length=4)
    track: Track

    @field_validator("english", "core_mathematics", "third_core")
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
    electives_used: List[str] = []
    """Which elective subjects actually counted toward the aggregate - the
    best 3 by grade point if 4 were provided, all 3 if only 3 were given.
    Lets the UI show the student exactly which subjects were used, since
    the answer isn't always "all of them you entered"."""
