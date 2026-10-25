#!/usr/bin/env python3
"""Question 3's required prompt experiment: three real variations of ONE
important rule, run against the SAME fixed battery of test conversations,
compared on consistency, accuracy, structure, hallucination, tone,
verbosity, and usefulness - not just "one was better."

**Rule chosen: 5c**, the eligibility-verdict rule added to fix Failure 15
(docs/evaluation.md) - a live model directly contradicted an
already-computed eligibility result. This rule was picked because it is
the most consequential one in the whole prompt: getting it wrong means
telling a student the opposite of their real admission eligibility.

**The three variants, each swapped in for 5c alone - everything else in
SYSTEM_PROMPT (including the other numbered rules) is held IDENTICAL
across all three runs, which is what makes this a controlled comparison
of this one rule rather than three different prompts entirely:**

- V1_weak_memory_based: the rule's wording BEFORE Failure 15's fix - the
  model "may use" the earlier table to answer eligibility questions, with
  no tool call required. This is the version that produced the live
  failure that motivated this whole rule.
- V2_current_deployed: the exact rule currently in app/llm/system_prompt.py
  - mandatory tool call, cites the observed failure, explicit fallback
  instruction when no calculation exists yet.
- V3_stricter_structured: a more mechanical variant that additionally
  requires the model to quote the tool's raw category/verdict pair
  verbatim in a fixed format before writing any prose - testing whether
  more rigid structure trades away tone/usefulness for extra accuracy, or
  whether it doesn't matter once the tool-call requirement is already in
  place.

**How each dimension is actually measured, not just eyeballed:**
- accuracy / hallucination: reuses the REAL, already-tested
  eligibility_claim_guard.detect_eligibility_contradictions - the same
  deterministic ground-truth check used in production, not a judgment
  call for this experiment alone.
- consistency: same (variant, case) pair run N times; the fraction of
  runs whose contradiction status agrees with the majority.
- verbosity: reply word count.
- structure: whether the reply contains a list (numbered or bulleted).
- tone: whether the reply includes hedging/caveat language
  ("approximate", "illustrative", "not a guarantee", "check with") -
  this project's house style per system_prompt.py's other rules.
- usefulness: NOT automatically scored - printed alongside the other
  metrics for a human to judge per reply, since "useful" is a judgment
  call this script should not pretend to automate.

**This requires a LIVE Ollama instance with llama3.1:8b pulled.** It was
built and its mechanics verified with --dry-run (a scripted FakeChat that
proves the harness itself works - prompt-swapping, metric computation,
aggregation), but no Ollama was available in the environment this project
was built in, so this script has never produced real comparative numbers.
Run it yourself once you have Ollama running: the output IS the real
discussion for Question 3's writeup - don't substitute invented numbers
for it.

Usage:
    python scripts/prompt_experiment.py                  # live Ollama, real results
    python scripts/prompt_experiment.py --repeats 5       # more repeats = better consistency measurement
    python scripts/prompt_experiment.py --dry-run         # mechanics-only check, NOT real data
"""
import argparse
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import session_store
from app.core.exceptions import LLMUnavailableError
from app.llm import ollama_client, orchestrator
from app.llm.system_prompt import SYSTEM_PROMPT
from app.tools.eligibility_checker import check_eligibility

RULE_5C_START = '5c. NEVER state whether a category IS or IS NOT eligible'
RULE_5C_END_MARKER = '\n5d.'


def _extract_rule_5c(prompt: str) -> str:
    start = prompt.find(RULE_5C_START)
    end = prompt.find(RULE_5C_END_MARKER, start)
    if start == -1 or end == -1:
        raise RuntimeError("Could not locate rule 5c in SYSTEM_PROMPT - has it been renumbered?")
    return prompt[start:end]


_CURRENT_5C = _extract_rule_5c(SYSTEM_PROMPT)

RULE_5C_VARIANTS = {
    "V1_weak_memory_based": (
        "5c. If a calculation result appears earlier in this conversation "
        "(you'll see a message starting with \"Aggregate:\" listing "
        "eligible/not-eligible categories), you may use it to answer "
        "follow-up eligibility questions directly from what it shows.\n"
    ),
    "V2_current_deployed": _CURRENT_5C + "\n",
    "V3_stricter_structured": (
        "5c. NEVER state whether a category IS or IS NOT eligible without "
        "calling get_saved_eligibility for that exact category first - no "
        "exceptions, even for a category the student can apparently already "
        "see in an earlier table. Before writing any prose verdict, your "
        "response MUST begin with a line in exactly this format: "
        "'[VERIFIED: <category> = <eligible|not eligible>]' using only the "
        "values get_saved_eligibility actually returned, then continue with "
        "your normal explanation. If get_saved_eligibility errors (no saved "
        "calculation yet), write '[VERIFIED: none - no calculation on file]' "
        "and tell the student to use the 'Enter My Grades' button.\n"
    ),
}


# --------------------------------------------------------------------------
# Fixed test battery - same cases run against all three variants.
# --------------------------------------------------------------------------

def _make_case(session_id: str, aggregate: int, track: str, electives: dict, message: str, label: str):
    """Pre-seeds a REAL saved calculation (ground truth) for the session,
    then returns the (session_id, message, label) to run against it."""
    elig = check_eligibility(aggregate=aggregate, track=track, electives=electives)
    session_store.set_last_calculation(session_id, {"aggregate": aggregate}, elig.model_dump())
    return session_id, message, label


def build_test_battery(run_tag: str):
    """run_tag makes session IDs unique per variant/repeat so calculations
    from one run never leak into another's ground truth."""
    return [
        _make_case(
            f"{run_tag}-technical-eng",
            aggregate=6,
            track="technical",
            electives={"Technical Drawing": "A1", "Applied Electricity": "A1", "Electronics": "A1"},
            message="where can i get civil engineering or architecture",
            label="Failure-15 motivating case: technical electives, asks about Engineering (really ineligible)",
        ),
        _make_case(
            f"{run_tag}-science-pa",
            aggregate=6,
            track="science",
            electives={"Biology": "B2", "Chemistry": "B2", "Physics": "A1"},
            message="am I eligible for physician assistantship",
            label="Science student, strong grades, asks about PA (really eligible)",
        ),
        _make_case(
            f"{run_tag}-business-med",
            aggregate=10,
            track="business",
            electives={"Economics": "B2", "Accounting": "B2", "Costing": "B2"},
            message="can I do medicine",
            label="Business student asks about Medicine (really ineligible - wrong electives)",
        ),
    ]


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

_HEDGE_PHRASES = ("approximate", "illustrative", "not a guarantee", "check with", "check the")
_LIST_RE = re.compile(r"(^|\n)\s*(?:[-*]|\d+[.)])\s+\S", re.MULTILINE)


def score_reply(reply: str, contradictions: list) -> dict:
    return {
        "word_count": len(reply.split()),
        "has_list_structure": bool(_LIST_RE.search(reply)),
        "has_hedge_language": any(p in reply.lower() for p in _HEDGE_PHRASES),
        "contradiction_free": len(contradictions) == 0,
    }


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

def run_variant(variant_name: str, variant_rule_text: str, repeats: int, dry_run_fake_chat_factory=None):
    full_prompt = SYSTEM_PROMPT[: SYSTEM_PROMPT.find(RULE_5C_START)] + variant_rule_text + \
        SYSTEM_PROMPT[SYSTEM_PROMPT.find(RULE_5C_END_MARKER) + 1:]

    per_case_results = defaultdict(list)

    for repeat_idx in range(repeats):
        run_tag = f"experiment-{variant_name}-{repeat_idx}"
        battery = build_test_battery(run_tag)
        for session_id, message, label in battery:
            original_prompt = orchestrator.SYSTEM_PROMPT
            orchestrator.SYSTEM_PROMPT = full_prompt
            try:
                chat_fn = (
                    dry_run_fake_chat_factory(label)
                    if dry_run_fake_chat_factory
                    else ollama_client.chat
                )
                result = orchestrator.handle_turn(session_id, message, chat_fn=chat_fn)
            except LLMUnavailableError:
                print(
                    "\nOllama is not reachable. This script needs a live model to produce "
                    "real comparative results - it will not substitute fabricated numbers.\n"
                    "Start Ollama, pull llama3.1:8b, and try again - or pass --dry-run to "
                    "verify only that this script's own mechanics work correctly.\n",
                    file=sys.stderr,
                )
                sys.exit(1)
            finally:
                orchestrator.SYSTEM_PROMPT = original_prompt

            metrics = score_reply(result["reply"], result["eligibility_contradictions"])
            per_case_results[label].append(metrics)

    return per_case_results


def summarize(variant_name: str, per_case_results: dict) -> dict:
    all_metrics = [m for case_metrics in per_case_results.values() for m in case_metrics]
    accuracy = statistics.mean(1.0 if m["contradiction_free"] else 0.0 for m in all_metrics)
    verbosity = statistics.mean(m["word_count"] for m in all_metrics)
    structure_rate = statistics.mean(1.0 if m["has_list_structure"] else 0.0 for m in all_metrics)
    hedge_rate = statistics.mean(1.0 if m["has_hedge_language"] else 0.0 for m in all_metrics)

    # Consistency: for each case, what fraction of repeats agree with that
    # case's own majority contradiction-free/not status.
    consistencies = []
    for case_metrics in per_case_results.values():
        statuses = [m["contradiction_free"] for m in case_metrics]
        majority = statuses.count(True) >= len(statuses) / 2
        agree = sum(1 for s in statuses if s == majority)
        consistencies.append(agree / len(statuses))
    consistency = statistics.mean(consistencies)

    return {
        "variant": variant_name,
        "accuracy (contradiction-free rate)": round(accuracy, 3),
        "consistency (agreement with per-case majority)": round(consistency, 3),
        "avg verbosity (words)": round(verbosity, 1),
        "structure rate (uses a list)": round(structure_rate, 3),
        "hedge/caveat-language rate": round(hedge_rate, 3),
    }


def _dry_run_fake_chat_factory(label: str):
    """Scripted, deterministic responses used ONLY to prove this script's
    own mechanics (prompt-swapping, metric computation, aggregation) work
    correctly - NOT real model behavior. Clearly labeled as such in all
    --dry-run output. The response is intentionally WRONG for the
    Engineering case so the accuracy/contradiction metric has something
    real to compute even in dry-run mode."""
    from app.llm.ollama_client import chat as _unused  # noqa: F401 - import kept for clarity only

    def fake_chat(messages, tools=None):
        if "really ineligible" in label:
            # Deliberately WRONG and names the real category, so the real
            # eligibility_claim_guard has something genuine to catch -
            # this is what proves the harness's measurement actually works,
            # not just that it runs without crashing.
            category = "Engineering / Pharmacy / Actuarial Science" if "Engineering" in label else "Medicine / Dentistry"
            return {
                "role": "assistant",
                "content": f"You are eligible for the category '{category}'.",
                "tool_calls": [],
            }
        return {"role": "assistant", "content": "- You are eligible.\n- Approximate band applies.", "tool_calls": []}

    return fake_chat


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeats", type=int, default=3, help="Repeats per (variant, case) for consistency measurement.")
    parser.add_argument("--dry-run", action="store_true", help="Verify script mechanics only - NOT real experiment data.")
    args = parser.parse_args()

    if args.dry_run:
        print("=" * 70)
        print("DRY RUN - this verifies the HARNESS works correctly.")
        print("These numbers are from a scripted FakeChat, NOT a real model.")
        print("They are not evidence for or against any prompt variant.")
        print("=" * 70 + "\n")

    summaries = []
    for variant_name, variant_text in RULE_5C_VARIANTS.items():
        factory = _dry_run_fake_chat_factory if args.dry_run else None
        per_case = run_variant(variant_name, variant_text, args.repeats, factory)
        summaries.append(summarize(variant_name, per_case))
        print(f"--- {variant_name} ---")
        for label, case_metrics in per_case.items():
            n_ok = sum(1 for m in case_metrics if m["contradiction_free"])
            print(f"  {label}: {n_ok}/{len(case_metrics)} runs contradiction-free")
        print()

    print("=" * 70)
    print("SUMMARY" + (" (DRY RUN - not real data)" if args.dry_run else ""))
    print("=" * 70)
    keys = [k for k in summaries[0].keys() if k != "variant"]
    header = f"{'metric':45s} | " + " | ".join(s["variant"] for s in summaries)
    print(header)
    print("-" * len(header))
    for key in keys:
        row = f"{key:45s} | " + " | ".join(f"{s[key]:>20}" for s in summaries)
        print(row)

    print(
        "\nUsefulness is not auto-scored above - read each variant's actual "
        "replies (add --verbose-replies if you extend this script) and judge "
        "per Question 3's rubric: does the reply still read naturally, or "
        "does V3's forced '[VERIFIED: ...]' prefix make it feel mechanical "
        "at the cost of tone?"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
