"""Turns a deterministic compute_aggregate/check_eligibility result into
plain text suitable for appending to a chat session's history - see
docs/evaluation.md Failure 8. This is NOT shown to the user directly (the
UI renders the real result card); it exists purely so a later chat turn
in the same session has the real numbers available as context, instead of
the calculator and the chat being two silos that never share anything.
"""

from app.models.eligibility import EligibilityResult
from app.models.grading import AggregateResult


def build_calculation_summary(
    aggregate: AggregateResult, eligibility: EligibilityResult
) -> str:
    lines = [
        f"Aggregate: {aggregate.aggregate} "
        f"(credit gate {'passed' if aggregate.credit_gate_passed else 'FAILED: ' + ', '.join(aggregate.failing_subjects)})."
    ]

    eligible = [m for m in eligibility.matches if m.overall_eligible]
    ineligible = [m for m in eligibility.matches if not m.overall_eligible]

    if eligible:
        parts = []
        for m in eligible:
            inst = f" (example institutions: {', '.join(m.institutions_example)})" if m.institutions_example else ""
            note = " [electives not independently verifiable for this category]" if m.electives_match is None else ""
            parts.append(f"{m.category}{inst}{note}")
        lines.append("Eligible for: " + "; ".join(parts) + ".")

    if ineligible:
        lines.append("NOT eligible for: " + ", ".join(m.category for m in ineligible) + ".")

    lines.append(
        "All bands are approximate guides, not confirmed current cutoffs; "
        "institution examples are illustrative, not a guarantee of admission."
    )

    return " ".join(lines)
