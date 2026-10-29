"""Deterministic, code-level safety net for institution-specific programme
claims in the model's own reply text.

Why this exists (see docs/evaluation.md Failure 14): Failure 13's fix added
a real lookup_institution_programmes tool and a prompt rule (5e) requiring
the model to call it before naming a programme at a named institution. A
live run showed the model ignoring that rule across an entire structured
answer - inventing "Bachelor of Arts" at UCC/UEW/UDS/AAMUSTED and "HND in
Civil Engineering" at all 10 technical universities, none of which have any
real programme data, without calling the tool once. It only discovered
this when directly challenged on a later turn ("I should not have
mentioned it earlier").

Every previous fix in this codebase (Failures 3, 9, 11, 12, 13) assumed
the model's prose might ADD a little beyond a real tool result. This
failure is different in kind: the model skipped the tool entirely across
a whole answer. A per-field deterministic result (cohort_stats,
institutions_lookup, institution_programmes) is no longer enough on its
own, because the model doesn't have to use those tools at all - it can
just... not call them, and write confident prose regardless.

This module is the backstop: it scans the model's FINAL reply text,
independent of whether it called any tool, for institution names paired
with programme-sounding language, and flags any institution that wasn't
actually verified this turn via a real lookup_institution_programmes call
that returned has_data_for_institution=True. It cannot rewrite or remove
the model's fabricated claim - no code can safely edit free-form natural
language without risking new errors - but it can attach a prominent,
deterministic warning the frontend renders regardless of what the model's
own text says, which is the same "render the real thing, independent of
the model's text" principle as every other fix in this project, applied
to absence of verification rather than presence of a wrong value.
"""
import re

from app.tools.programme_lookup import all_known_institution_names

_DEGREE_KEYWORD_RE = re.compile(
    r"\b(HND|Bachelor|BSc|BA|B\.A\.|B\.Sc\.|B\.Eng|BEng|LLB|Diploma|Doctor of|"
    r"MBChB|Master|M\.Sc\.|MSc|programmes?|courses?|degree)\b",
    re.IGNORECASE,
)
# Widened after Failure 17 (docs/evaluation.md): the original pattern only
# matched "programme in"/"course in" as fixed phrases, so a reply saying
# "law programmes" or "a law programme" - the actual live phrasing that
# slipped through - matched nothing at all. Matching the bare words
# "programme(s)"/"course(s)"/"degree" risks more false positives (an
# extra warning banner on an ordinary sentence that happens to use the
# word "programme"), which this project has already decided, repeatedly,
# is the cheaper mistake compared to a real fabrication going unflagged.

# Exactly the false positive that widening above introduced - see
# Failure 18 (docs/evaluation.md): a reply that explicitly declines to
# make a programme claim and asks a clarifying question instead ("I
# would need to check the programme-specific data - would you like me to
# check...") still matched the keyword regex and got an institution
# flagged as if a confident, unverified claim had been made, when none
# was. These phrases mean the model is deferring, not asserting.
_DEFERRAL_RE = re.compile(
    r"would need to check|would you like me to check|"
    r"i don'?t have (that|per-programme|specific)|"
    r"no data (on file|yet)|can'?t confirm|not able to confirm",
    re.IGNORECASE,
)


def detect_unverified_institution_claims(reply_text: str, verified_institutions: set[str]) -> list[str]:
    """Returns the subset of known institution names that appear in
    reply_text (anywhere) while reply_text ALSO contains at least one
    degree-sounding keyword (anywhere), excluding any institution in
    verified_institutions (ones a real tool call this turn confirmed
    has_data_for_institution=True for).

    This is a conservative, whole-reply heuristic, not positional - it does
    not require the institution and the keyword to be adjacent. That is a
    deliberate choice: a false positive here only adds an extra warning
    banner, which is a far cheaper mistake than a false negative letting a
    real fabrication through unflagged. The one exception is a reply that
    explicitly defers rather than claims (see _DEFERRAL_RE above) - that
    case returns [] entirely, even if an institution and a keyword both
    appear elsewhere in the same reply. This is a whole-reply exclusion,
    not a per-institution one: a reply that defers on one institution
    while confidently fabricating about a different one in the same
    message would currently go unflagged for BOTH. That trade-off is
    accepted for now because the live case that motivated this exclusion
    was a single, uniformly cautious reply - not yet observed to combine
    a real claim and a deferral in one message - and is written down here
    as a known limitation rather than silently accepted.
    """
    if not reply_text or not _DEGREE_KEYWORD_RE.search(reply_text):
        return []
    if _DEFERRAL_RE.search(reply_text):
        return []

    flagged = []
    for institution in all_known_institution_names():
        if institution in verified_institutions:
            continue
        if institution in reply_text:
            flagged.append(institution)
    return sorted(flagged)
