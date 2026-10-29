"""Deterministic guard: flags an institution named alongside a programme
category it does NOT actually belong to.

Why this exists (see docs/evaluation.md Failure 18): a live run, asked
"What am I eligible for in KNUST", answered "you are eligible for Private
University Entry in KNUST" - but KNUST is a public university and has
never been in "Private University Entry"'s real institutions_example list
at all. Neither existing guard catches this: institution_claim_guard
(Failure 14) only checks institution+PROGRAMME pairs against
lookup_institution_programmes, not institution+CATEGORY pairs against
programmes.json's own institutions_example; eligibility_claim_guard
(Failure 15) only checks eligibility VERDICTS against the saved result,
not which institutions belong to which category. This is a third,
distinct kind of claim the model can get wrong, and needed its own check.

Sentence-scoped, the same way eligibility_claim_guard.py was fixed after
Failure 18's other half (the window-based version read into the next
sentence and produced a false positive) - an institution and a category
are only considered "named together" if they appear in the same
sentence/line, not merely somewhere in the same reply.
"""
import re

from app.tools.programme_lookup import all_known_institution_names, category_institutions_map

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def detect_institution_category_mismatches(reply_text: str) -> list[dict]:
    """Returns a list of {"institution", "category"} dicts for every
    (institution, category) pair named together in the same sentence
    where that institution is NOT actually in that category's real
    institutions_example list. Returns [] for empty input or when no
    mismatch is found.
    """
    if not reply_text:
        return []

    sentences = _SENTENCE_SPLIT_RE.split(reply_text)
    institutions = all_known_institution_names()
    category_map = category_institutions_map()

    mismatches = []
    seen = set()
    for sentence in sentences:
        institutions_in_sentence = [i for i in institutions if i in sentence]
        if not institutions_in_sentence:
            continue
        for category, real_institutions in category_map.items():
            if category not in sentence:
                continue
            for institution in institutions_in_sentence:
                if institution in real_institutions:
                    continue
                key = (institution, category)
                if key in seen:
                    continue
                seen.add(key)
                mismatches.append({"institution": institution, "category": category})

    return mismatches
