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

# Failure 22/23 (docs/evaluation.md): a live reply stated the correct
# overall verdict ("not eligible") for a category, so
# detect_eligibility_contradictions above found nothing wrong - but the
# REASON it gave was invented and backwards, blaming the aggregate itself
# when WASSCE aggregates run lower-is-better and the real aggregate was
# comfortably inside the band. The real reason was always electives or
# required-core; the aggregate was never the problem. Observed live
# wordings for this, each needing its own branch below because they don't
# share a common word order:
#   "the aggregate ... is below the required band of 18 or better"
#   "the aggregate for X requires 18 or better, and you have an
#    aggregate of 6"
#   "your aggregate of 6 meets the approximate band for this category,
#    but you need an aggregate of 10 or better to be eligible" - note
#    this one even states the TRUE fact (aggregate meets the band) in the
#    same sentence as the false one (you need 10 or better), so catching
#    it can't rely on the sentence being uniformly negative.
_AGGREGATE_BLAME_RE = re.compile(
    r"aggregate\b[^.?!\n]{0,80}\b(is|was|does\s+not\s+meet|doesn't\s+meet|"
    r"fails?\s+to\s+meet|below|above|exceeds?|worse\s+than|higher\s+than|"
    r"too\s+high|too\s+low|not\s+within|outside|requires?)\b[^.?!\n]{0,40}"
    r"\b(required|band|cutoff|threshold|or\s+better)\b"
    r"|"
    r"\bneeds?\s+an\s+aggregate\s+of\s+\d+[^.?!\n]{0,20}\bor\s+better\b",
    re.IGNORECASE,
)


def _category_parts(category: str) -> list[str]:
    """Composite category names like "Engineering / Pharmacy / Actuarial
    Science" are rarely echoed back by the model verbatim - a student asks
    about "Actuarial Science" and the model answers about "Actuarial
    Science", not the full slash-joined category string. The original
    exact-substring match (`category not in sentence`) therefore missed
    every one of these mentions, which also meant Failure 15's own guard
    silently did nothing whenever a reply used a short form (found while
    investigating Failure 22, docs/evaluation.md). Splitting on "/" and
    matching any sufficiently long part fixes both checks that use this.
    """
    parts = [category]
    parts.extend(p.strip() for p in category.split("/") if len(p.strip()) > 3)
    return parts


def _category_mentioned(category: str, sentence: str) -> bool:
    return any(part in sentence for part in _category_parts(category))


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
    matches_by_category = {m["category"]: m for m in saved["eligibility"]["matches"]}

    for category, actual_eligible in actual_by_category.items():
        claimed_eligible = None
        verdict_sentence_idx = None
        for idx, sentence in enumerate(sentences):
            if not _category_mentioned(category, sentence):
                continue
            if _NOT_ELIGIBLE_RE.search(sentence):
                claimed_eligible = False
            elif _ELIGIBLE_RE.search(sentence):
                claimed_eligible = True
            if claimed_eligible is not None:
                verdict_sentence_idx = idx
                break  # first sentence that states a verdict for this category wins

        if claimed_eligible is None:
            continue  # category named, but no verdict language in its own sentence

        if claimed_eligible != actual_eligible:
            contradictions.append({
                "category": category,
                "model_said": "eligible" if claimed_eligible else "not eligible",
                "actual": "eligible" if actual_eligible else "not eligible",
            })
            continue  # Failure 15's own check already covers this category

        # Failure 22 (docs/evaluation.md): the verdict just matched, but
        # that doesn't mean the stated REASON is right. A model explaining
        # ineligibility very often puts the reason in the sentence right
        # after the verdict ("...not eligible for X. The aggregate score
        # of 6 is below the required band..."), referring back to the
        # category with "this category"/"it" rather than repeating its
        # name - so the blame language is checked in the verdict sentence
        # itself AND the one immediately following it, not a wider window
        # (Failure 18 showed why an unbounded window misattributes a
        # different category's language).
        if claimed_eligible is False and not matches_by_category[category]["aggregate_eligible"]:
            continue  # the aggregate genuinely WAS part of the problem
        if claimed_eligible is False:
            window = sentences[verdict_sentence_idx:verdict_sentence_idx + 2]
            if any(_AGGREGATE_BLAME_RE.search(s) for s in window):
                match = matches_by_category[category]
                aggregate = saved["eligibility"]["aggregate"]
                band = match["aggregate_band"]
                if match["electives_match"] is False:
                    real_reason = "electives"
                elif match["required_core_match"] is False:
                    real_reason = "required core subjects"
                else:
                    real_reason = "elective/core requirements"
                contradictions.append({
                    "category": category,
                    "model_said": (
                        f"your aggregate ({aggregate}) is the reason you're not "
                        f"eligible for {category}"
                    ),
                    "actual": (
                        f"your aggregate ({aggregate}) meets this category's band "
                        f"({band[0]}-{band[1]}) - the real reason is "
                        f"{real_reason}, not the aggregate"
                    ),
                })

    return contradictions
