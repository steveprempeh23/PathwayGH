"""Deterministic lookup of the REAL, already-computed eligibility verdict
for one category, from this session's most recent /calculate submission.

Why this exists (see docs/evaluation.md Failure 15): chat has no tool
access to compute_aggregate/check_eligibility (Failure 6), so its only way
to answer "am I eligible for category X" on a later turn was to recall/
reread the plain-text summary injected into conversation history by
/calculate (see Failure 8). A live run showed the model getting this
wrong: it told a student they WERE eligible for "Engineering / Pharmacy /
Actuarial Science" when the real calculation, sitting in the same
conversation, had marked it "Not eligible" (electives didn't match). This
tool gives the model a real, callable way to check the actual verdict
instead of rereading/misreading the text.
"""
from app.core import session_store
from app.models.eligibility_status import SavedEligibilityStatus


def get_saved_eligibility(session_id: str, programme_category: str) -> SavedEligibilityStatus:
    """Raises ValueError if no calculation has been saved for this session
    yet (student hasn't used "Enter My Grades"), or if programme_category
    doesn't match any category in the saved result."""
    saved = session_store.get_last_calculation(session_id)
    if saved is None:
        raise ValueError(
            "No calculation result found for this session yet - the student "
            "needs to submit their grades via the 'Enter My Grades' button first."
        )

    matches = saved["eligibility"]["matches"]
    for m in matches:
        if m["category"] == programme_category:
            return SavedEligibilityStatus(
                category=m["category"],
                overall_eligible=m["overall_eligible"],
                aggregate_eligible=m["aggregate_eligible"],
                electives_match=m["electives_match"],
                reason=m["reason"],
            )

    valid = [m["category"] for m in matches]
    raise ValueError(
        f"Unknown programme_category '{programme_category}'. Valid categories: {valid}"
    )
