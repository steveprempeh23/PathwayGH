import pytest

from app.core import session_store
from app.core.exceptions import LLMUnavailableError
from app.llm import orchestrator


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Point session_store at a throwaway DB file for every test, so tests
    never touch the real app_state.db."""
    monkeypatch.setattr(session_store, "DB_PATH", tmp_path / "test.db")
    yield


class FakeChat:
    """Returns canned responses in sequence, one per call, regardless of
    the messages passed in. Lets us script a multi-hop tool-calling
    conversation deterministically."""

    def __init__(self, responses: list[dict]):
        self._responses = responses
        self.calls = []

    def __call__(self, messages, tools=None):
        self.calls.append(messages)
        if not self._responses:
            raise AssertionError("FakeChat ran out of scripted responses")
        return self._responses.pop(0)


def _assistant(content="", tool_calls=None):
    return {"role": "assistant", "content": content, "tool_calls": tool_calls or []}


def test_full_happy_path_with_both_tools_and_recommendation():
    fake = FakeChat(
        [
            _assistant(
                tool_calls=[
                    {
                        "name": "compute_aggregate",
                        "arguments": {
                            "english": "B3",
                            "core_mathematics": "B2",
                            "integrated_science": "C4", "social_studies": "C4",
                            "electives": {"Biology": "B2", "Chemistry": "B3", "Physics": "C4"},
                            "track": "science",
                        },
                    }
                ]
            ),
            _assistant(
                tool_calls=[
                    {
                        "name": "check_eligibility",
                        "arguments": {
                            "aggregate": 18,
                            "track": "science",
                            "electives": {"Biology": "B2", "Chemistry": "B3", "Physics": "C4"},
                        },
                    }
                ]
            ),
            _assistant(
                tool_calls=[
                    {
                        "name": "submit_recommendation",
                        "arguments": {
                            "programme_category": "General Science (non-clinical)",
                            "fit_reason": "Your aggregate and science electives fit this category.",
                            "confidence": "medium",
                            "caveats": ["Cutoff band is approximate, not a confirmed current figure."],
                            "sources": [],  # no retrieve_context was called in this scenario
                        },
                    }
                ]
            ),
            _assistant(content="You're a good fit for General Science programmes."),
        ]
    )

    result = orchestrator.handle_turn("session-1", "Here are my grades...", chat_fn=fake)

    assert result["recommendation"]["programme_category"] == "General Science (non-clinical)"
    assert "General Science" in result["reply"]
    assert len(fake.calls) == 4

    # Conversation memory persisted - only the visible turns, not tool chatter.
    history = session_store.get_history("session-1")
    assert history[0] == {"role": "user", "content": "Here are my grades..."}
    assert history[1]["role"] == "assistant"


def test_recommendation_repairs_once_then_succeeds():
    fake = FakeChat(
        [
            _assistant(
                tool_calls=[
                    {
                        "name": "submit_recommendation",
                        "arguments": {"programme_category": "X"},  # missing required fields
                    }
                ]
            ),
            _assistant(
                tool_calls=[
                    {
                        "name": "submit_recommendation",
                        "arguments": {
                            "programme_category": "Business / Finance / Accounting",
                            "fit_reason": "Fixed on retry.",
                            "confidence": "low",
                            "caveats": [],
                            "sources": [],
                        },
                    }
                ]
            ),
            _assistant(content="Here's a fit after correcting the format."),
        ]
    )

    result = orchestrator.handle_turn("session-2", "my grades are...", chat_fn=fake)

    assert result["recommendation"]["programme_category"] == "Business / Finance / Accounting"


def test_recommendation_fails_twice_returns_fallback():
    bad_args = {"programme_category": "X"}  # always invalid
    fake = FakeChat(
        [
            _assistant(tool_calls=[{"name": "submit_recommendation", "arguments": bad_args}]),
            _assistant(tool_calls=[{"name": "submit_recommendation", "arguments": bad_args}]),
        ]
    )

    result = orchestrator.handle_turn("session-3", "grades", chat_fn=fake)

    assert result["recommendation"] is None
    assert "wasn't able to put together" in result["reply"]


def test_llm_unavailable_returns_fallback_not_exception():
    def always_fails(messages, tools=None):
        raise LLMUnavailableError("Ollama is down")

    result = orchestrator.handle_turn("session-4", "hello", chat_fn=always_fails)

    assert result["recommendation"] is None
    assert "temporarily unavailable" in result["reply"]


def test_retrieve_context_tool_included_in_happy_path(monkeypatch):
    """Exercises orchestrator wiring for retrieve_context without touching
    real embeddings - app.rag.retriever.retrieve is stubbed directly, since
    that's the orchestrator's actual dependency boundary."""
    from app.llm import orchestrator as orch_module

    def fake_retrieve(query, embed_fn=None, k=3):
        return [
            {
                "text": "English, Core Mathematics, and Social Studies are core for Business.",
                "section_title": "Core Subject Rules",
                "source_urls": ["https://example.com/guide"],
                "document_title": "WASSCE Guide",
                "distance": 0.1,
            }
        ]

    monkeypatch.setattr(orch_module.rag_retriever, "retrieve", fake_retrieve)

    fake = FakeChat(
        [
            _assistant(
                tool_calls=[{"name": "retrieve_context", "arguments": {"query": "Business core subjects"}}]
            ),
            _assistant(content="Business uses English, Core Maths, and Social Studies as core subjects."),
        ]
    )

    result = orchestrator.handle_turn("session-6", "what core subjects does business need?", chat_fn=fake)

    assert "Social Studies" in result["reply"]
    assert result["recommendation"] is None


def test_retrieve_context_error_fed_back_to_model_not_raised(monkeypatch):
    from app.llm import orchestrator as orch_module
    from app.core.exceptions import RetrievalError

    def broken_retrieve(query, embed_fn=None, k=3):
        raise RetrievalError("embedding model unreachable")

    monkeypatch.setattr(orch_module.rag_retriever, "retrieve", broken_retrieve)

    fake = FakeChat(
        [
            _assistant(tool_calls=[{"name": "retrieve_context", "arguments": {"query": "anything"}}]),
            _assistant(content="I couldn't retrieve supporting information for that right now."),
        ]
    )

    result = orchestrator.handle_turn("session-7", "a factual question", chat_fn=fake)

    assert "couldn't retrieve" in result["reply"]


def test_analyze_outcomes_tool_wired_through_orchestrator():
    fake = FakeChat(
        [
            _assistant(
                tool_calls=[
                    {
                        "name": "analyze_outcomes",
                        "arguments": {"programme_category": "Medicine / Dentistry"},
                    }
                ]
            ),
            _assistant(content="On average, admitted Medicine students had aggregate around X (synthetic demo data)."),
        ]
    )

    result = orchestrator.handle_turn("session-8", "what's typical for Medicine?", chat_fn=fake)

    assert "synthetic" in result["reply"]
    assert result["recommendation"] is None


def test_cohort_stats_carries_synthetic_caveat_even_when_model_narration_drops_it():
    """Regression test for Failure 9 (docs/evaluation.md): a live model call
    answered a cohort-statistics question with a bare percentage and NO
    mention that the dataset is synthetic, even though system_prompt rule 5
    requires that caveat every time. The fix (mirroring Failure 3's fix for
    calculation results) is that result['cohort_stats']['data_source'] must
    carry the real caveat from code, independent of whatever the model's own
    reply text says or omits.
    """
    fake = FakeChat(
        [
            _assistant(
                tool_calls=[
                    {
                        "name": "analyze_outcomes",
                        "arguments": {"programme_category": "Open Public-University Entry (general eligibility floor)"},
                    }
                ]
            ),
            # Deliberately omits the synthetic-data caveat - exactly what
            # the live model did.
            _assistant(content="The admission rate for that category is 61.4%."),
        ]
    )

    result = orchestrator.handle_turn("session-cohort", "what's the acceptance rate?", chat_fn=fake)

    # The model's text can omit the caveat...
    assert "synthetic" not in result["reply"]
    # ...but cohort_stats must carry it regardless.
    assert result["cohort_stats"] is not None
    assert "synthetic" in result["cohort_stats"]["data_source"].lower()


def test_institutions_lookup_carries_real_list_even_when_model_narration_invents_others():
    """Regression test for Failure 12 (docs/evaluation.md): a live model
    call, asked which schools it's eligible for in Physician Assistantship
    / Allied Health (real institutions_example: ['UHAS', 'UDS']), invented
    four extra institutions (University of Ghana, UCC, KNUST, UMaT) that
    aren't in that list at all. The fix (mirroring Failure 3's and Failure
    9's fix) is that result['institutions_lookup']['institutions_example']
    must carry the real list from code, independent of whatever the
    model's own reply text says or adds.
    """
    fake = FakeChat(
        [
            _assistant(
                tool_calls=[
                    {
                        "name": "list_institutions",
                        "arguments": {"programme_category": "Physician Assistantship / Allied Health"},
                    }
                ]
            ),
            # Deliberately invents institutions beyond the real list -
            # exactly what the live model did.
            _assistant(
                content=(
                    "You're eligible at University of Ghana, UCC, UDS, UHAS, "
                    "KNUST, and UMaT."
                )
            ),
        ]
    )

    result = orchestrator.handle_turn(
        "session-institutions", "schools i am eligible for physician assistantship", chat_fn=fake
    )

    # The model's text can invent extra institutions...
    assert "KNUST" in result["reply"]
    # ...but institutions_lookup must carry only the real, sourced list.
    assert result["institutions_lookup"] is not None
    assert result["institutions_lookup"]["institutions_example"] == ["UHAS", "UDS"]
    assert "KNUST" not in result["institutions_lookup"]["institutions_example"]


def test_institution_programmes_carries_real_rows_even_when_model_narration_invents_others():
    """Regression test for Failure 13 (docs/evaluation.md): a live model
    call, asked about programmes at named institutions, invented
    institution-specific degree titles ("Bachelor of Medicine and Surgery
    at UDS", "Bachelor of Arts in English at University of Ghana") with no
    real data behind any of it. The fix (mirroring Failure 12's fix) is
    that result['institution_programmes']['matches'] must carry the real,
    sourced rows from institution_programmes.json, independent of whatever
    the model's own reply text invents.
    """
    fake = FakeChat(
        [
            _assistant(
                tool_calls=[
                    {
                        "name": "lookup_institution_programmes",
                        "arguments": {"institution": "University of Ghana", "keyword": "medicine"},
                    }
                ]
            ),
            # Deliberately invents a programme/institution pairing beyond
            # what the tool actually returned - exactly what the live
            # model did for UDS.
            _assistant(
                content=(
                    "You're eligible for Bachelor of Medicine and Bachelor of "
                    "Surgery at University of Ghana, and also Bachelor of "
                    "Medicine and Surgery at UDS."
                )
            ),
        ]
    )

    result = orchestrator.handle_turn(
        "session-programmes", "what programmes can I do in medicine at UG", chat_fn=fake
    )

    # The model's text can invent an institution/programme pairing...
    assert "UDS" in result["reply"]
    # ...but institution_programmes must carry only the real rows for the
    # institution that was actually queried.
    lookup = result["institution_programmes"]
    assert lookup is not None
    assert lookup["has_data_for_institution"] is True
    programmes = [m["programme"] for m in lookup["matches"]]
    assert "Bachelor of Medicine and Bachelor of Surgery" in programmes
    assert all(m["institution"] == "University of Ghana" for m in lookup["matches"])


def test_institution_programmes_no_data_flagged_honestly():
    """UDS has no per-programme data on file - the tool must say so
    plainly (has_data_for_institution=False), never silently return an
    empty-looking list that could be mistaken for 'UDS offers nothing'."""
    fake = FakeChat(
        [
            _assistant(
                tool_calls=[
                    {"name": "lookup_institution_programmes", "arguments": {"institution": "UDS"}}
                ]
            ),
            _assistant(content="I don't have per-programme data for UDS yet."),
        ]
    )
    result = orchestrator.handle_turn("session-programmes-2", "programmes at UDS", chat_fn=fake)
    lookup = result["institution_programmes"]
    assert lookup["has_data_for_institution"] is False
    assert lookup["matches"] == []


def test_unverified_institution_claims_flagged_when_model_never_calls_the_tool():
    """Regression test for Failure 14 (docs/evaluation.md): a live model
    answered an entire structured "schools and programmes" question by
    inventing institution-specific degree titles (Bachelor of Arts at UCC/
    UEW/UDS/AAMUSTED, HND in Civil Engineering at all 10 technical
    universities) WITHOUT calling lookup_institution_programmes even once.
    Rule 5e and the Failure-13 tool existing were not enough on their own.
    The fix is a deterministic, code-level scan of the final reply text
    that flags any institution named alongside degree-sounding language
    that was never actually verified this turn.
    """
    fake = FakeChat(
        [
            # The model answers directly with fabricated claims, calling
            # no tool at all - exactly what happened live.
            _assistant(
                content=(
                    "UCC: Bachelor of Arts, Bachelor of Social Sciences. "
                    "Accra Technical University: HND in Civil Engineering."
                )
            ),
        ]
    )

    result = orchestrator.handle_turn(
        "session-claims", "list the schools and programmes I'm eligible for", chat_fn=fake
    )

    flagged = result["unverified_institution_claims"]
    assert "UCC" in flagged
    assert "Accra Technical University" in flagged


def test_unverified_institution_claims_empty_when_tool_actually_verified_it():
    """When the model DOES call lookup_institution_programmes and the
    institution has real data, that institution must NOT be flagged, even
    though its name and a degree keyword both appear in the reply."""
    fake = FakeChat(
        [
            _assistant(
                tool_calls=[
                    {
                        "name": "lookup_institution_programmes",
                        "arguments": {"institution": "University of Ghana", "keyword": "medicine"},
                    }
                ]
            ),
            _assistant(
                content="University of Ghana offers Bachelor of Medicine and Bachelor of Surgery."
            ),
        ]
    )

    result = orchestrator.handle_turn("session-claims-2", "medicine at UG", chat_fn=fake)

    assert "University of Ghana" not in result["unverified_institution_claims"]


def test_eligibility_contradiction_flagged_when_model_contradicts_real_result():
    """Regression test for Failure 15 (docs/evaluation.md): a live model,
    asked a follow-up question, told a student they WERE eligible for
    "Engineering / Pharmacy / Actuarial Science" when the real, saved
    calculation had marked it "Not eligible" - without calling
    get_saved_eligibility to check. The fix is a deterministic guard that
    compares the reply text against the real saved result, independent of
    whether the model called any tool.
    """
    from app.tools.eligibility_checker import check_eligibility

    elig = check_eligibility(
        aggregate=6,
        track="technical",
        electives={"Technical Drawing": "A1", "Applied Electricity": "A1", "Electronics": "A1"},
    )
    session_store.set_last_calculation("session-contra", {"aggregate": 6}, elig.model_dump())

    fake = FakeChat(
        [
            # The model answers straight from (mis)memory, calling no tool.
            _assistant(
                content=(
                    "Based on the tool's output, you are eligible for the "
                    "category 'Engineering / Pharmacy / Actuarial Science'."
                )
            ),
        ]
    )

    result = orchestrator.handle_turn(
        "session-contra", "where can i get civil engineering", chat_fn=fake
    )

    contradictions = result["eligibility_contradictions"]
    assert len(contradictions) == 1
    assert contradictions[0]["category"] == "Engineering / Pharmacy / Actuarial Science"
    assert contradictions[0]["model_said"] == "eligible"
    assert contradictions[0]["actual"] == "not eligible"


def test_eligibility_contradiction_empty_when_model_states_the_truth():
    from app.tools.eligibility_checker import check_eligibility

    elig = check_eligibility(
        aggregate=6,
        track="technical",
        electives={"Technical Drawing": "A1", "Applied Electricity": "A1", "Electronics": "A1"},
    )
    session_store.set_last_calculation("session-contra-2", {"aggregate": 6}, elig.model_dump())

    fake = FakeChat(
        [
            _assistant(
                content=(
                    "You are not eligible for Engineering / Pharmacy / "
                    "Actuarial Science because your electives don't match."
                )
            ),
        ]
    )

    result = orchestrator.handle_turn("session-contra-2", "civil engineering?", chat_fn=fake)
    assert result["eligibility_contradictions"] == []


def test_eligibility_contradiction_empty_when_no_calculation_saved_yet():
    """No saved calculation at all for this session - nothing to compare
    against, so no contradiction can be (or should be) claimed."""
    fake = FakeChat([_assistant(content="You are eligible for Medicine / Dentistry.")])
    result = orchestrator.handle_turn("session-no-calc", "medicine?", chat_fn=fake)
    assert result["eligibility_contradictions"] == []


def test_get_saved_eligibility_tool_wired_through_orchestrator():
    from app.tools.eligibility_checker import check_eligibility

    elig = check_eligibility(
        aggregate=6,
        track="technical",
        electives={"Technical Drawing": "A1", "Applied Electricity": "A1", "Electronics": "A1"},
    )
    session_store.set_last_calculation("session-tool", {"aggregate": 6}, elig.model_dump())

    fake = FakeChat(
        [
            _assistant(
                tool_calls=[
                    {
                        "name": "get_saved_eligibility",
                        "arguments": {"programme_category": "Engineering / Pharmacy / Actuarial Science"},
                    }
                ]
            ),
            _assistant(content="Checked - you are not eligible for that category."),
        ]
    )

    result = orchestrator.handle_turn("session-tool", "am I eligible for engineering", chat_fn=fake)
    assert "not eligible" in result["reply"]
    assert result["eligibility_contradictions"] == []


def test_get_saved_eligibility_no_calculation_yet_returns_error_not_exception():
    fake = FakeChat(
        [
            _assistant(
                tool_calls=[
                    {
                        "name": "get_saved_eligibility",
                        "arguments": {"programme_category": "Medicine / Dentistry"},
                    }
                ]
            ),
            _assistant(content="Please use the Enter My Grades button first."),
        ]
    )
    result = orchestrator.handle_turn("session-empty", "am I eligible for medicine", chat_fn=fake)
    assert "Enter My Grades" in result["reply"]


def test_analyze_outcomes_unknown_category_error_fed_back_not_raised():
    fake = FakeChat(
        [
            _assistant(
                tool_calls=[
                    {"name": "analyze_outcomes", "arguments": {"programme_category": "Not A Real Category"}}
                ]
            ),
            _assistant(content="I don't recognize that programme category."),
        ]
    )

    result = orchestrator.handle_turn("session-9", "stats for fake category", chat_fn=fake)

    assert "don't recognize" in result["reply"]


class FakeStream:
    """Fake stream_fn - yields canned text chunks regardless of input."""

    def __init__(self, chunks: list[str]):
        self._chunks = chunks

    def __call__(self, messages, tools=None):
        yield from self._chunks


def test_stream_emits_progress_then_tokens_then_done():
    fake_chat = FakeChat(
        [
            _assistant(
                tool_calls=[
                    {
                        "name": "compute_aggregate",
                        "arguments": {
                            "english": "B3",
                            "core_mathematics": "B2",
                            "integrated_science": "C4", "social_studies": "C4",
                            "electives": {"Biology": "B2", "Chemistry": "B3", "Physics": "C4"},
                            "track": "science",
                        },
                    }
                ]
            ),
            _assistant(content=""),  # decision loop ends with no more tool calls
        ]
    )
    fake_stream = FakeStream(["Your ", "aggregate ", "is 18."])

    events = list(
        orchestrator.handle_turn_stream(
            "session-10", "my grades...", chat_fn=fake_chat, stream_fn=fake_stream
        )
    )

    event_types = [e["type"] for e in events]
    assert event_types == ["progress", "token", "token", "token", "done"]
    assert events[0]["tool"] == "compute_aggregate"

    full_text = "".join(e["text"] for e in events if e["type"] == "token")
    assert full_text == "Your aggregate is 18."

    # Persisted conversation matches the streamed text exactly.
    history = session_store.get_history("session-10")
    assert history[-1] == {"role": "assistant", "content": "Your aggregate is 18."}


def test_stream_llm_unavailable_during_decision_yields_error_not_exception():
    def always_fails(messages, tools=None):
        raise LLMUnavailableError("down")

    events = list(
        orchestrator.handle_turn_stream("session-11", "hello", chat_fn=always_fails)
    )

    assert events[-1]["type"] == "error"
    assert "unavailable" in events[-1]["message"]


def test_stream_llm_unavailable_during_final_streaming_yields_error():
    fake_chat = FakeChat([_assistant(content="")])  # no tools needed, straight to streaming

    def broken_stream(messages, tools=None):
        raise LLMUnavailableError("down mid-stream")
        yield  # pragma: no cover - makes this a generator function

    events = list(
        orchestrator.handle_turn_stream(
            "session-12", "hello", chat_fn=fake_chat, stream_fn=broken_stream
        )
    )

    assert events[-1]["type"] == "error"


def test_stream_recommendation_with_no_narrative_gets_deterministic_leadin():
    fake_chat = FakeChat(
        [
            _assistant(
                tool_calls=[
                    {
                        "name": "submit_recommendation",
                        "arguments": {
                            "programme_category": "Business / Finance / Accounting",
                            "fit_reason": "Fits your profile.",
                            "confidence": "medium",
                            "caveats": [],
                            "sources": [],
                        },
                    }
                ]
            ),
            _assistant(content=""),  # model submitted the tool but no trailing text
        ]
    )

    events = list(
        orchestrator.handle_turn_stream("session-13", "grades", chat_fn=fake_chat, stream_fn=FakeStream([]))
    )

    assert events[-1]["type"] == "done"
    assert events[-1]["recommendation"]["programme_category"] == "Business / Finance / Accounting"
    token_events = [e for e in events if e["type"] == "token"]
    assert len(token_events) == 1  # deterministic lead-in, not a real stream


def test_calculation_surfaces_real_data_even_when_model_narration_is_wrong():
    """This is the actual fix for the live-observed hallucination (see
    docs/evaluation.md Failure 3): even if the model's own text fabricates
    category names, result['calculation'] must carry the REAL tool output,
    independent of what the model says.
    """
    fake = FakeChat(
        [
            _assistant(
                tool_calls=[
                    {
                        "name": "compute_aggregate",
                        "arguments": {
                            "english": "B2", "core_mathematics": "B2", "integrated_science": "B2", "social_studies": "B2",
                            "electives": {"Biology": "B2", "Chemistry": "B2", "Physics": "B2"},
                            "track": "science",
                        },
                    }
                ]
            ),
            _assistant(
                tool_calls=[
                    {
                        "name": "check_eligibility",
                        "arguments": {
                            "aggregate": 12, "track": "science",
                            "electives": {"Biology": "B2", "Chemistry": "B2", "Physics": "B2"},
                        },
                    }
                ]
            ),
            # Deliberately fabricated narration - exactly what the live model did.
            _assistant(content="You qualify for Engineering/Technology and General Education!"),
        ]
    )

    result = orchestrator.handle_turn("session-calc", "my grades...", chat_fn=fake)

    # The model's text can say whatever it wants...
    assert "Engineering/Technology" in result["reply"]
    # ...but calculation must contain the REAL categories regardless.
    assert result["calculation"] is not None
    assert result["calculation"]["aggregate"]["aggregate"] == 12
    real_categories = {m["category"] for m in result["calculation"]["eligibility"]["matches"]}
    assert "Engineering/Technology" not in real_categories
    assert "Medicine / Dentistry" in real_categories  # one of the real 7


def test_calculation_is_none_when_no_calculator_tools_ran():
    fake = FakeChat([_assistant(content="Hi, how can I help?")])
    result = orchestrator.handle_turn("session-calc-2", "hello", chat_fn=fake)
    assert result["calculation"] is None


def test_stream_calculation_in_done_event_matches_real_data():
    fake_chat = FakeChat(
        [
            _assistant(
                tool_calls=[
                    {
                        "name": "compute_aggregate",
                        "arguments": {
                            "english": "A1", "core_mathematics": "A1", "integrated_science": "A1", "social_studies": "A1",
                            "electives": {"Biology": "A1", "Chemistry": "B2", "Physics": "B2"},
                            "track": "science",
                        },
                    }
                ]
            ),
            _assistant(content=""),
        ]
    )
    fake_stream = FakeStream(["Low aggregate, strong options."])

    events = list(
        orchestrator.handle_turn_stream(
            "session-calc-3", "grades", chat_fn=fake_chat, stream_fn=fake_stream
        )
    )
    done_event = events[-1]
    assert done_event["type"] == "done"
    assert done_event["calculation"]["aggregate"]["aggregate"] == 8


def test_fabricated_source_url_rejected_even_when_schema_valid():
    """Regression test for Failure 9: a live model cited a specific
    university's admissions URL that was never actually retrieved - a
    fabricated citation, schema-valid but factually baseless. This must be
    rejected the same way malformed structured output is, not accepted
    just because it parses."""
    fake = FakeChat(
        [
            _assistant(
                tool_calls=[
                    {
                        "name": "submit_recommendation",
                        "arguments": {
                            "programme_category": "Engineering / Pharmacy / Actuarial Science",
                            "fit_reason": "Good fit.",
                            "confidence": "medium",
                            "caveats": [],
                            "sources": ["https://www.ashesi.edu.gh/admissions"],  # never retrieved
                        },
                    }
                ]
            ),
            _assistant(
                tool_calls=[
                    {
                        "name": "submit_recommendation",
                        "arguments": {
                            "programme_category": "Engineering / Pharmacy / Actuarial Science",
                            "fit_reason": "Good fit, no citation this time.",
                            "confidence": "medium",
                            "caveats": [],
                            "sources": [],
                        },
                    }
                ]
            ),
            _assistant(content="Here you go."),
        ]
    )

    result = orchestrator.handle_turn("session-fab", "engineering at ashesi?", chat_fn=fake)

    # Retried with an honest empty-sources answer after the fabricated one was rejected.
    assert result["recommendation"]["sources"] == []
    assert "ashesi" not in str(result["recommendation"]).lower()


def test_source_url_accepted_when_actually_retrieved_first():
    """The flip side: a source IS valid when retrieve_context genuinely
    returned it earlier in the same turn - the check isn't "no sources
    ever", it's "no sources you didn't actually get"."""
    from app.llm import orchestrator as orch_module

    def fake_retrieve(query, embed_fn=None, k=3):
        return [
            {
                "text": "Business uses English, Core Maths, and Social Studies as core.",
                "section_title": "Core Subject Rules",
                "source_urls": ["https://real-source.example/guide"],
                "document_title": "WASSCE Guide",
                "distance": 0.1,
            }
        ]

    import unittest.mock
    with unittest.mock.patch.object(orch_module.rag_retriever, "retrieve", fake_retrieve):
        fake = FakeChat(
            [
                _assistant(
                    tool_calls=[{"name": "retrieve_context", "arguments": {"query": "Business core"}}]
                ),
                _assistant(
                    tool_calls=[
                        {
                            "name": "submit_recommendation",
                            "arguments": {
                                "programme_category": "Business / Finance / Accounting",
                                "fit_reason": "Fits.",
                                "confidence": "high",
                                "caveats": [],
                                "sources": ["https://real-source.example/guide"],
                            },
                        }
                    ]
                ),
                _assistant(content="Here you go."),
            ]
        )
        result = orchestrator.handle_turn("session-real-source", "business?", chat_fn=fake)

    assert result["recommendation"]["sources"] == ["https://real-source.example/guide"]


def test_tool_hop_limit_prevents_infinite_loop():
    """If the model kept calling an unknown/looping tool forever, the
    orchestrator must still terminate rather than hang - AND must return a
    real fallback message, not a silent blank reply (regression test for a
    bug where the unprocessed final response's empty content leaked through)."""
    responses = [
        _assistant(tool_calls=[{"name": "compute_aggregate", "arguments": {}}])
        for _ in range(orchestrator.MAX_TOOL_HOPS + 2)
    ]
    fake = FakeChat(responses)

    result = orchestrator.handle_turn("session-5", "grades", chat_fn=fake)

    # Terminated at MAX_TOOL_HOPS rather than exhausting all scripted responses.
    assert len(fake.calls) <= orchestrator.MAX_TOOL_HOPS + 1
    assert result["recommendation"] is None
    assert result["reply"] == orchestrator.FALLBACK_TOO_MANY_TOOL_CALLS
    assert result["reply"] != ""  # the actual bug this regression test catches


def test_stream_tool_hop_limit_yields_error_not_blank():
    responses = [
        _assistant(tool_calls=[{"name": "compute_aggregate", "arguments": {}}])
        for _ in range(orchestrator.MAX_TOOL_HOPS + 2)
    ]
    fake = FakeChat(responses)

    events = list(orchestrator.handle_turn_stream("session-14", "grades", chat_fn=fake))

    assert events[-1]["type"] == "error"
    assert events[-1]["message"] == orchestrator.FALLBACK_TOO_MANY_TOOL_CALLS
    token_events = [e for e in events if e["type"] == "token"]
    assert token_events == []  # never got to streaming at all - bailed first
