import pytest
from fastapi.testclient import TestClient

from app.core import session_store
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(session_store, "DB_PATH", tmp_path / "test.db")
    yield


def test_root_serves_the_web_ui():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "PathwayGH Advisor" in response.text


def test_new_session_returns_a_session_id():
    response = client.post("/session/new")
    assert response.status_code == 200
    assert response.json()["session_id"]


def test_chat_rejects_empty_message():
    response = client.post("/chat", json={"session_id": "s1", "message": ""})
    assert response.status_code == 422


def test_chat_rejects_whitespace_only_message():
    response = client.post("/chat", json={"session_id": "s1", "message": "   "})
    assert response.status_code == 422


def test_chat_rejects_missing_session_id():
    response = client.post("/chat", json={"message": "hello"})
    assert response.status_code == 422


def test_chat_happy_path_with_stubbed_orchestrator(monkeypatch):
    from app.api import routes

    def fake_handle_turn(session_id, message):
        return {"reply": "Here is your answer.", "recommendation": None, "calculation": None}

    monkeypatch.setattr(routes, "handle_turn", fake_handle_turn)

    response = client.post("/chat", json={"session_id": "s1", "message": "my grades are B2 B3 C4..."})
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Here is your answer."
    assert body["recommendation"] is None


def test_chat_calculation_field_carries_real_data_over_wrong_narration(monkeypatch):
    """End-to-end proof over the actual HTTP endpoint (not just the
    orchestrator function) that /chat's response carries the real
    calculation, independent of the model's own (here: deliberately wrong)
    text - this is the live-observed-hallucination fix, Failure 3."""
    from app.api import routes

    fake_eligibility = {
        "aggregate": 12,
        "track": "science",
        "matches": [
            {
                "category": "Medicine / Dentistry",
                "aggregate_eligible": True,
                "electives_match": True,
                "overall_eligible": True,
                "reason": "fits",
                "confidence": "approximate_band",
                "aggregate_band": [6, 10],
            }
        ],
    }

    def fake_handle_turn(session_id, message):
        return {
            "reply": "You qualify for Engineering/Technology!",  # fabricated, on purpose
            "recommendation": None,
            "calculation": {
                "aggregate": {
                    "aggregate": 12, "credit_gate_passed": True, "failing_subjects": [],
                    "track": "science", "subject_points": {},
                },
                "eligibility": fake_eligibility,
            },
        }

    monkeypatch.setattr(routes, "handle_turn", fake_handle_turn)

    response = client.post("/chat", json={"session_id": "s1", "message": "my grades..."})
    assert response.status_code == 200
    body = response.json()
    assert "Engineering/Technology" in body["reply"]  # the model's fabrication, present...
    real_categories = {m["category"] for m in body["calculation"]["eligibility"]["matches"]}
    assert "Engineering/Technology" not in real_categories  # ...but not in the real data
    assert "Medicine / Dentistry" in real_categories


def test_chat_unexpected_exception_returns_500_not_raw_traceback(monkeypatch):
    from app.api import routes

    def broken_handle_turn(session_id, message):
        raise RuntimeError("something truly unexpected")

    monkeypatch.setattr(routes, "handle_turn", broken_handle_turn)

    response = client.post("/chat", json={"session_id": "s1", "message": "hello"})
    assert response.status_code == 500
    assert "truly unexpected" not in response.text  # internals must not leak
    assert response.json()["detail"] == "Something went wrong processing your message."


def test_session_reset_returns_deleted_count():
    session_store.append_message("s2", "user", "hi")
    session_store.append_message("s2", "assistant", "hello")

    response = client.post("/session/reset", json={"session_id": "s2"})
    assert response.status_code == 200
    assert response.json()["deleted_messages"] == 2

    # Confirms the reset actually happened, not just reported.
    assert session_store.get_history("s2") == []


def test_chat_stream_emits_sse_events(monkeypatch):
    from app.api import routes

    def fake_stream(session_id, message):
        yield {"type": "progress", "tool": "compute_aggregate", "message": "Calculating..."}
        yield {"type": "token", "text": "Your "}
        yield {"type": "token", "text": "aggregate is 18."}
        yield {"type": "done", "recommendation": None}

    monkeypatch.setattr(routes, "handle_turn_stream", fake_stream)

    with client.stream(
        "POST", "/chat/stream", json={"session_id": "s3", "message": "my grades..."}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        raw = "".join(response.iter_text())

    assert 'data: {"type": "progress"' in raw
    assert 'data: {"type": "token", "text": "Your "}' in raw
    assert 'data: {"type": "done", "recommendation": null}' in raw


def test_chat_stream_rejects_empty_message():
    response = client.post("/chat/stream", json={"session_id": "s3", "message": ""})
    assert response.status_code == 422


def test_calculate_endpoint_is_deterministic_and_matches_real_categories():
    """Regression test for a live failure: a small chat model fabricated
    programme category names ('Engineering/Technology', 'General Education')
    that don't exist in programmes.json. This endpoint returns the real
    categories directly, with no LLM paraphrasing involved."""
    response = client.post(
        "/calculate",
        json={
            "grades": {
                "english": "A1",
                "core_mathematics": "A1",
                "third_core": "A1",
                "electives": {"Biology": "A1", "Chemistry": "B2", "Physics": "B2"},
                "track": "science",
            }
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["aggregate"]["aggregate"] == 8  # within Medicine's 6-10 band
    categories = {m["category"] for m in body["eligibility"]["matches"]}
    # The real 9 categories from programmes.json - not hallucinated ones.
    assert categories == {
        "Medicine / Dentistry",
        "Physician Assistantship / Allied Health",
        "Engineering / Pharmacy / Actuarial Science",
        "General Science (non-clinical)",
        "Business / Finance / Accounting",
        "General Humanities / Social Sciences / Education",
        "Open Public-University Entry (general eligibility floor)",
        "Private University Entry",
        "HND / Polytechnic (Technical University) Tracks",
    }
    medicine = next(m for m in body["eligibility"]["matches"] if "Medicine" in m["category"])
    assert medicine["overall_eligible"] is True  # correct science electives


def test_calculate_endpoint_rejects_invalid_grade():
    response = client.post(
        "/calculate",
        json={
            "grades": {
                "english": "Z9",
                "core_mathematics": "B2",
                "third_core": "A1",
                "electives": {"Biology": "B2", "Chemistry": "B3", "Physics": "B3"},
                "track": "science",
            }
        },
    )
    assert response.status_code == 422  # Pydantic rejects it before the route even runs


def test_calculate_with_session_id_records_history_for_followup_chat():
    """Regression test for Failure 8: the calculator and chat never shared
    state, so a correct result on the button was invisible to a later chat
    question in the same session. Confirms /calculate now writes a usable
    summary into session history when a session_id is given.
    """
    session_id = "calc-history-test"
    response = client.post(
        "/calculate",
        json={
            "session_id": session_id,
            "grades": {
                "english": "A1",
                "core_mathematics": "A1",
                "third_core": "A1",
                "electives": {"Biology": "A1", "Chemistry": "B2", "Physics": "B2"},
                "track": "science",
            },
        },
    )
    assert response.status_code == 200

    history = session_store.get_history(session_id)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assistant_summary = history[1]["content"]
    assert history[1]["role"] == "assistant"
    assert "Aggregate: 8" in assistant_summary
    assert "Medicine / Dentistry" in assistant_summary


def test_calculate_without_session_id_does_not_touch_history():
    """session_id is optional - standalone API use (no chat session) must
    not silently create history entries anywhere."""
    response = client.post(
        "/calculate",
        json={
            "grades": {
                "english": "B2", "core_mathematics": "B2", "third_core": "B2",
                "electives": {"Biology": "B2", "Chemistry": "B2", "Physics": "B2"},
                "track": "science",
            }
        },
    )
    assert response.status_code == 200
    # No session_id was given, so nothing to check in session_store - this
    # test mainly confirms the endpoint doesn't error without one.


def test_analytics_endpoint_returns_cohort_stats():
    response = client.get("/analytics", params={"programme_category": "Medicine / Dentistry"})
    assert response.status_code == 200
    body = response.json()
    assert body["sample_size"] == 60
    assert "synthetically generated" in body["data_source"]


def test_analytics_endpoint_unknown_category_returns_400():
    response = client.get("/analytics", params={"programme_category": "Not Real"})
    assert response.status_code == 400


def test_session_reset_on_nonexistent_session_is_zero_not_error():
    response = client.post("/session/reset", json={"session_id": "never-existed"})
    assert response.status_code == 200
    assert response.json()["deleted_messages"] == 0
