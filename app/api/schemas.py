from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.analysis import CohortStats
from app.models.eligibility import EligibilityResult
from app.models.institution_programmes import InstitutionProgrammeLookup
from app.models.institutions import InstitutionsLookup
from app.models.grading import AggregateResult, GradeInput
from app.models.recommendation import Recommendation


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        """min_length=1 alone would still accept a string of pure
        whitespace - that's the "empty input" failure mode Question 11
        explicitly calls out, so it's checked here, not left to slip
        through as a technically-non-empty string.
        """
        if not v.strip():
            raise ValueError("message cannot be empty or whitespace-only")
        return v


class CalculationBundle(BaseModel):
    """The real, deterministic compute_aggregate/check_eligibility results
    for a chat turn, carried alongside the model's reply - independent of
    whatever the model's own text says. Added after a live run showed the
    chat model fabricating programme category names; see docs/evaluation.md
    Failure 3. The frontend renders this with the exact same card used by
    the no-LLM /calculate endpoint, so a student always sees the true
    numbers regardless of how (in)accurately the model narrated them.
    """

    aggregate: Optional[AggregateResult] = None
    eligibility: Optional[EligibilityResult] = None


class ChatResponse(BaseModel):
    reply: str
    recommendation: Optional[Recommendation] = None
    calculation: Optional[CalculationBundle] = None
    cohort_stats: Optional[CohortStats] = None
    """The real analyze_outcomes result for this turn, if it ran - see
    docs/evaluation.md Failure 9. Without this field, FastAPI's
    response_model would silently strip cohort_stats from
    orchestrator.handle_turn()'s return dict, which would have made the
    Failure-9 fix invisible to the actual API response even though the
    orchestrator computed it correctly - the same class of bug the fix
    itself is about (real data getting lost before it reaches the user).
    """
    institutions_lookup: Optional[InstitutionsLookup] = None
    """The real list_institutions result for this turn, if it ran - see
    docs/evaluation.md Failure 12 (model fabricated institutions that
    weren't in the real institutions_example list for the category it was
    asked about). Same reasoning as cohort_stats above for why this needs
    its own schema field rather than being left implicit."""
    institution_programmes: Optional[InstitutionProgrammeLookup] = None
    """The real lookup_institution_programmes result for this turn, if it
    ran - see docs/evaluation.md Failure 13 (model invented institution-
    specific programme titles with no real data behind them). Same
    reasoning as the fields above."""
    eligibility_contradictions: list[dict] = []
    """Deterministic, code-level flag for Failure 15 (docs/evaluation.md):
    categories named in `reply` alongside an eligibility verdict ("eligible"
    / "not eligible") that CONTRADICTS the real, saved result for this
    session's most recent "Enter My Grades" submission. Unlike
    unverified_institution_claims below, this has absolute ground truth
    (session_store.get_last_calculation) to compare against, so a non-empty
    list here means the reply is definitely wrong for that category, not
    merely unverified - a live run showed the model telling a student they
    WERE eligible for a category the real calculation had marked
    ineligible."""
    unverified_institution_claims: list[str] = []
    """Deterministic, code-level flag for Failure 14 (docs/evaluation.md):
    institutions named in `reply` alongside degree-sounding language that
    were NOT actually verified this turn via a real
    lookup_institution_programmes call. Unlike the fields above, this is
    not "the real version of a tool result" - it is a safety-net check
    that runs on every reply regardless of which tools the model chose to
    call, because a live run showed the model skipping the real tool
    entirely across a whole structured answer rather than merely
    embellishing a correct result. A non-empty list here means the
    reply's own institution-specific claims should be treated as
    unverified and the frontend should warn accordingly."""


class CalculateRequest(BaseModel):
    """session_id is optional so /calculate can still be called standalone
    (e.g. direct API testing) without a chat session existing yet - but
    the web UI always sends the current session's id, so a calculation
    done via the button gets recorded into that session's history. See
    docs/evaluation.md Failure 8: without this, the calculator and chat
    never shared any context, so a student asking a chat follow-up about
    a result they'd just seen got "I don't have that information" even
    though the real answer was computed moments earlier.
    """

    session_id: Optional[str] = None
    grades: GradeInput


class NewSessionResponse(BaseModel):
    session_id: str


class ResetRequest(BaseModel):
    session_id: str = Field(min_length=1)


class ResetResponse(BaseModel):
    session_id: str
    deleted_messages: int
