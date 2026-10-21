from typing import Optional

from pydantic import BaseModel


class SavedEligibilityStatus(BaseModel):
    """The REAL, already-computed eligibility verdict for one category,
    for the student's most recent /calculate submission this session -
    copied verbatim from the stored EligibilityResult, never re-derived
    or guessed. See docs/evaluation.md Failure 15."""

    category: str
    overall_eligible: bool
    aggregate_eligible: bool
    electives_match: Optional[bool]
    reason: str
