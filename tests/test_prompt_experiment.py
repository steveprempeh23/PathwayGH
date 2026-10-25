"""Tests for scripts/prompt_experiment.py - the Question 3 prompt-variation
harness. These test the HARNESS's own mechanics (prompt-swapping, metric
computation, aggregation) using the script's --dry-run FakeChat, not real
comparative results - no live Ollama is available in CI, and this file
must never be mistaken for evidence about which prompt variant is
actually better. See the script's own module docstring for that honesty
boundary.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import prompt_experiment as pe  # noqa: E402


def test_rule_5c_is_still_findable_in_system_prompt():
    """If system_prompt.py's rule 5c is ever renumbered or reworded past
    recognition, this script's string-splice approach breaks silently -
    this test exists so that breaks loudly instead, at test time."""
    from app.llm.system_prompt import SYSTEM_PROMPT

    assert pe.RULE_5C_START in SYSTEM_PROMPT
    assert pe.RULE_5C_END_MARKER in SYSTEM_PROMPT


def test_all_three_variants_produce_a_complete_valid_prompt():
    """Each variant must splice cleanly into a prompt that still contains
    every OTHER rule unchanged - the whole point of a controlled
    experiment is that only rule 5c differs between runs."""
    from app.llm.system_prompt import SYSTEM_PROMPT

    for name, text in pe.RULE_5C_VARIANTS.items():
        spliced = (
            SYSTEM_PROMPT[: SYSTEM_PROMPT.find(pe.RULE_5C_START)]
            + text
            + SYSTEM_PROMPT[SYSTEM_PROMPT.find(pe.RULE_5C_END_MARKER) + 1 :]
        )
        assert "5b." in spliced, f"{name}: rule 5b lost in splice"
        assert "5d." in spliced, f"{name}: rule 5d lost in splice"
        assert "get_saved_eligibility" in spliced or name == "V1_weak_memory_based"


def test_score_reply_detects_contradiction_free_and_not():
    free = pe.score_reply("You are not eligible for that.", contradictions=[])
    assert free["contradiction_free"] is True

    not_free = pe.score_reply(
        "You are eligible.",
        contradictions=[{"category": "X", "model_said": "eligible", "actual": "not eligible"}],
    )
    assert not_free["contradiction_free"] is False


def test_score_reply_detects_list_structure_and_hedging():
    with_list = pe.score_reply("- point one\n- point two", contradictions=[])
    assert with_list["has_list_structure"] is True

    without_list = pe.score_reply("Just a plain sentence.", contradictions=[])
    assert without_list["has_list_structure"] is False

    hedged = pe.score_reply("This is an approximate_band figure, not a guarantee.", contradictions=[])
    assert hedged["has_hedge_language"] is True


def test_dry_run_harness_runs_end_to_end_without_live_ollama():
    """The full dry-run path - prompt swap, session seeding, FakeChat,
    scoring, aggregation - must complete without touching live Ollama."""
    per_case = pe.run_variant(
        "V2_current_deployed",
        pe.RULE_5C_VARIANTS["V2_current_deployed"],
        repeats=2,
        dry_run_fake_chat_factory=pe._dry_run_fake_chat_factory,
    )
    summary = pe.summarize("V2_current_deployed", per_case)
    assert summary["variant"] == "V2_current_deployed"
    assert 0.0 <= summary["accuracy (contradiction-free rate)"] <= 1.0
    assert len(per_case) == 3  # the fixed 3-case battery


def test_dry_run_fixture_actually_exercises_the_contradiction_guard():
    """Regression guard for a bug caught while building this test suite:
    an earlier version of the dry-run fixture didn't name the real
    category in its fake reply, so the real guard correctly found
    nothing to flag - which looked like '100% accuracy' for entirely the
    wrong reason. The fixture must genuinely trigger a contradiction for
    the two 'really ineligible' cases."""
    per_case = pe.run_variant(
        "V2_current_deployed",
        pe.RULE_5C_VARIANTS["V2_current_deployed"],
        repeats=1,
        dry_run_fake_chat_factory=pe._dry_run_fake_chat_factory,
    )
    ineligible_cases = [m for label, metrics in per_case.items() if "really ineligible" in label for m in metrics]
    assert ineligible_cases, "No 'really ineligible' case found in the battery"
    assert all(m["contradiction_free"] is False for m in ineligible_cases)
