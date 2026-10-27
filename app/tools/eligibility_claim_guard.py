"""Deterministic, code-level cross-check of eligibility verdicts the model
states in its own reply against the REAL, saved result for this session.

Why this exists (see docs/evaluation.md Failure 15): a live run showed the
model directly contradicting an already-computed result - the calculation
table in the same conversation said "Engineering / Pharmacy / Actuarial
Science ... Not eligible", and the model's own reply to a follow-up
question said "you are eligible for the category 'Engineering / Pharmacy /
Actuarial Science'". Unlike Failure 14's institution_claim_guard (which
could only flag an institution as "unverified" because there's no
absolute ground truth for which programmes any given institution runs),
this failure has a real, known-correct answer sitting in
session_store.get_last_calculation - so this guard can say definitively
WRONG, not just "unverified".

This runs on every reply regardless of which tools the model called,
because the live failure happened without the model calling
get_saved_eligibility at all - it answered straight from (mis)recalling
the earlier text summary.
"""
import re

from app.core import session_store

_ELIGIBLE_RE = re.compile(r"\beligible\b", re.IGNORECASE)
_NOT_ELIGIBLE_RE = re.compile(r"\bnot\s+eligible\b|\bineligible\b|\bno\s+match\b", re.IGNORECASE)

# How far past a category-name mention to look for the verdict language
# naming it. Generous on purpose - a false positive here only adds an
# extra correction banner, which is a far cheaper mistake than missing a
# real contradiction.
_WINDOW_BEFORE = 60
_WINDOW_AFTER = 160


def detect_eligibility_contradictions(reply_text: str, session_id: str) -> list[dict]:
    """Returns a list of {"category", "model_said", "actual"} dicts for
    every category the reply names alongside an eligibility verdict that
    contradicts the real, saved result for this session. Returns []
    if no calculation has been saved yet, or if reply_text doesn't appear
    to state a verdict for any known category."""
    if not reply_text:
        return []

    saved = session_store.get_last_calculation(session_id)
    if saved is None:
        return []

    actual_by_category = {
        m["category"]: m["overall_eligible"] for m in saved["eligibility"]["matches"]
    }

    contradictions = []
    for category, actual_eligible in actual_by_category.items():
        start = reply_text.find(category)
        if start == -1:
            continue
        cat_end = start + len(category)

        # Cap the forward window at the end of the sentence that actually
        # names this category. Without this, a verdict belonging to a
        # DIFFERENT category mentioned later in the same reply (e.g. "You
        # are eligible for X ... However, you are NOT eligible for Y") can
        # bleed into X's window and produce a false contradiction - see the
        # false-positive this caused for "Private University Entry" when a
        # later sentence about "Engineering / Pharmacy / Actuarial Science"
        # fell inside the old fixed 160-char window.
        forward_slice = reply_text[cat_end: cat_end + _WINDOW_AFTER]
        sentence_end = re.search(r"[.!?]", forward_slice)
        after_end = cat_end + (sentence_end.end() if sentence_end else len(forward_slice))

        window = reply_text[max(0, start - _WINDOW_BEFORE): after_end]

        if _NOT_ELIGIBLE_RE.search(window):
            claimed_eligible = False
        elif _ELIGIBLE_RE.search(window):
            claimed_eligible = True
        else:
            continue  # category named, but no verdict language nearby

        if claimed_eligible != actual_eligible:
            contradictions.append({
                "category": category,
                "model_said": "eligible" if claimed_eligible else "not eligible",
                "actual": "eligible" if actual_eligible else "not eligible",
            })

    return contradictions
