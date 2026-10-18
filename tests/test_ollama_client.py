from app.llm.ollama_client import _extract_fallback_tool_calls

# Exact text from a live run (see docs/evaluation.md Failure 5) where
# qwen2.5:1.5b wrote fake tool-call JSON directly into its reply instead of
# using Ollama's native tool-calling mechanism.
REAL_OBSERVED_CONTENT = """Now, let's calculate your WASSCE aggregate:

```json
{"name": "compute_aggregate", "arguments": {"track": {"science": "Integrated Science", "english": "B2", "core_mathematics": "B2", "third_core": "N/A", "electives": {"Biology": "B2", "Chemistry": "N/A", "Physics": "N/A", "Computer Science": "N/A", "English Literature": "N/A"}}}}
```

Let's compute the aggregate:

```json
{"name": "compute_aggregate", "arguments": {"track": {"science": "Integrated Science", "english": "B2", "core_mathematics": "B2", "third_core": "N/A", "electives": {"Biology": "B2", "Chemistry": "N/A", "Physics": "N/A", "Computer Science": "N/A", "English Literature": "N/A"}}}}
```

```json
{"name": "check_eligibility", "arguments": {"aggregate": 72, "track": "science", "electives": {"Biology": "B2", "Chemistry": "N/A", "Physics": "N/A", "Computer Science": "N/A", "English Literature": "N/A"}}}
```

Based on the computed aggregate..."""


def test_extracts_calls_from_real_observed_failure_text():
    calls = _extract_fallback_tool_calls(REAL_OBSERVED_CONTENT)
    names = [c["name"] for c in calls]
    # Two identical compute_aggregate blocks deduped to one, plus the
    # check_eligibility block - three distinct calls in the raw text,
    # two distinct after dedup.
    assert names == ["compute_aggregate", "check_eligibility"]


def test_duplicate_identical_blocks_are_deduped():
    content = (
        '{"name": "compute_aggregate", "arguments": {"english": "B2"}} '
        '{"name": "compute_aggregate", "arguments": {"english": "B2"}}'
    )
    calls = _extract_fallback_tool_calls(content)
    assert len(calls) == 1


def test_nested_json_in_arguments_does_not_break_brace_matching():
    """The real failure's arguments contain a nested `electives` dict - a
    naive non-greedy regex would stop at the first inner '}' and produce
    truncated, unparseable JSON. Brace-matching must handle this."""
    content = '{"name": "check_eligibility", "arguments": {"aggregate": 10, "electives": {"Biology": "B2", "Chemistry": "A1"}}}'
    calls = _extract_fallback_tool_calls(content)
    assert len(calls) == 1
    assert calls[0]["arguments"]["electives"] == {"Biology": "B2", "Chemistry": "A1"}


def test_unknown_tool_name_is_ignored():
    content = '{"name": "delete_all_data", "arguments": {}}'
    calls = _extract_fallback_tool_calls(content)
    assert calls == []


def test_malformed_json_is_skipped_not_raised():
    content = '{"name": "compute_aggregate", "arguments": {not valid json}}'
    calls = _extract_fallback_tool_calls(content)
    assert calls == []  # skipped silently, no exception


def test_plain_text_with_no_json_returns_empty():
    calls = _extract_fallback_tool_calls("Hello, how can I help you today?")
    assert calls == []


def test_real_tool_call_json_mixed_with_prose_is_still_found():
    content = 'Sure! Here is what I will do: {"name": "retrieve_context", "arguments": {"query": "Business electives"}} Let me check that for you.'
    calls = _extract_fallback_tool_calls(content)
    assert calls == [{"name": "retrieve_context", "arguments": {"query": "Business electives"}}]
