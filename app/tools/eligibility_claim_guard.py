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

# Splits on sentence-ending punctuation AND newlines (a model answering in
# a bullet list, one category per line, rarely uses terminal punctuation
# per line at all). See Failure 18 (docs/evaluation.md) for why this
# matters: a fixed character window (the original approach) read far
# enough past one category's mention to pick up the NEXT category's
# verdict in the same paragraph, misattributing a correct "eligible" as
# a false "contradiction".
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def detect_eligibility_contradictions(reply_text: str, session_id: str) -> list[dict]:
    """Returns a list of {"category", "model_said", "actual"} dicts for
    every category the reply names alongside an eligibility verdict that
    contradicts the real, saved result for this session. Returns []
    if no calculation has been saved yet, or if reply_text doesn't appear
    to state a verdict for any known category.

    Verdict language is looked for only within the SAME sentence/line as
    the category's mention, not a fixed character window spanning
    multiple sentences - see Failure 18 for the live false positive this
    fixes (a correct "eligible" for one category misread as "not
    eligible" because a different category's real "not eligible" fell
    inside the old window, in the very next sentence).
    """
    if not reply_text:
        return []

    saved = session_store.get_last_calculation(session_id)
    if saved is None:
        return []

    actual_by_category = {
        m["category"]: m["overall_eligible"] for m in saved["eligibility"]["matches"]
    }

    sentences = _SENTENCE_SPLIT_RE.split(reply_text)

    contradictions = []
    for category, actual_eligible in actual_by_category.items():
        claimed_eligible = None
        for sentence in sentences:
            if category not in sentence:
                continue
            if _NOT_ELIGIBLE_RE.search(sentence):
                claimed_eligible = False
            elif _ELIGIBLE_RE.search(sentence):
                claimed_eligible = True
            if claimed_eligible is not None:
                break  # first sentence that states a verdict for this category wins

        if claimed_eligible is None:
            continue  # category named, but no verdict language in its own sentence

        if claimed_eligible != actual_eligible:
            contradictions.append({
                "category": category,
                "model_said": "eligible" if claimed_eligible else "not eligible",
                "actual": "eligible" if actual_eligible else "not eligible",
            })

    return contradictions
