from typing import List, Optional, Tuple

from pydantic import BaseModel


class ProgrammeMatch(BaseModel):
    category: str

    aggregate_eligible: bool
    """Whether the computed aggregate falls within this category's band."""

    electives_match: Optional[bool]
    """True: student's elective subjects/grades satisfy the requirement.
    False: they don't (e.g. missing a required science elective, or grade
    below the category's minimum).
    None: the category's required electives are generic placeholder text
    (e.g. "any approved Arts elective"), so this cannot be checked against
    specific subject names - must not be reported as True or False.
    """

    required_core_match: Optional[bool] = None
    """Whether the student's grade in this category's SPECIFICALLY NAMED
    required core subject (Integrated Science for science categories,
    Social Studies for business/humanities ones - see required_core in
    programmes.json) meets a credit-pass threshold. True/False only when
    required_core names one specific subject; None when it's generic
    ("...track-dependent", or just English/Core Mathematics with no third
    subject named) or when core_grades wasn't supplied to check_eligibility
    at all. This is deliberately independent of which core subject was
    better for the student's OWN overall aggregate (AggregateResult.
    third_core_used) - a science category can require Integrated Science
    specifically even if Social Studies gave the student a better overall
    number. See docs/evaluation.md Failure 16.
    """

    overall_eligible: bool
    """True only when aggregate_eligible is True AND electives_match is not
    False AND required_core_match is not False. A None value for either
    keeps overall_eligible tied to what IS checkable, with the uncertainty
    surfaced in `reason` instead of silently resolved either way.
    """

    reason: str
    confidence: str  # "approximate_band" or "verified_example" - see programmes.json
    aggregate_band: Tuple[int, int]
    institutions_example: List[str] = []
    """Real, sourced example institutions for this category, from
    programmes.json's institutions_example field. These are illustrative
    examples (e.g. "University of Ghana"), not a claim that every listed
    institution currently admits at the shown band. Added so the chat
    model has real grounded data to point to for "which schools" questions
    instead of inventing school names - see docs/evaluation.md Failure 7.
    """


class EligibilityResult(BaseModel):
    aggregate: int
    track: str
    matches: List[ProgrammeMatch]
