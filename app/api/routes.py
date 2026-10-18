import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.schemas import (
    CalculateRequest,
    ChatRequest,
    ChatResponse,
    NewSessionResponse,
    ResetRequest,
    ResetResponse,
)
from pydantic import ValidationError

from app.core import session_store
from app.llm.orchestrator import handle_turn, handle_turn_stream
from app.models.analysis import CohortStats
from app.services.calculation_summary import build_calculation_summary
from app.tools.aggregate_calculator import compute_aggregate
from app.tools.data_analysis import analyze_outcomes
from app.tools.eligibility_checker import check_eligibility

logger = logging.getLogger("pathwaygh.api")

router = APIRouter()


@router.post("/session/new", response_model=NewSessionResponse)
def new_session() -> NewSessionResponse:
    session_id = str(uuid.uuid4())
    logger.info("Created new session %s", session_id)
    return NewSessionResponse(session_id=session_id)


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """Empty/whitespace input is already rejected by ChatRequest validation
    (FastAPI returns 422 automatically). Anticipated failures inside the
    turn itself - LLM unavailable, malformed structured output, retrieval
    failure - are already handled inside handle_turn() and come back as a
    normal 200 with a fallback reply (see docs/architecture.md error
    boundaries). Anything that reaches this except block is genuinely
    unexpected and must never leak internals to the client.
    """
    logger.info("Chat turn for session %s (%d chars)", request.session_id, len(request.message))
    try:
        result = handle_turn(request.session_id, request.message)
    except Exception:
        logger.exception(
            "Unexpected failure handling chat turn for session %s", request.session_id
        )
        raise HTTPException(
            status_code=500, detail="Something went wrong processing your message."
        )
    return ChatResponse(**result)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Server-Sent Events version of /chat (Question 10). Emits
    {"type": "progress", ...} events as tools execute, then genuinely
    streamed {"type": "token", "text": ...} events for the final answer,
    then a {"type": "done", "recommendation": ...} event - or {"type":
    "error", ...} in place of "done" if something failed.

    ChatRequest's empty/whitespace validation still applies to the request
    body before this function is even called (standard FastAPI behavior),
    so a 422 for bad input happens exactly as it does for /chat.
    """

    def event_source():
        try:
            for event in handle_turn_stream(request.session_id, request.message):
                yield _sse(event)
        except Exception:
            logger.exception(
                "Unexpected failure streaming chat turn for session %s", request.session_id
            )
            yield _sse({"type": "error", "message": "Something went wrong processing your message."})

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.post("/calculate")
def calculate(request: CalculateRequest) -> dict:
    """Deterministic, LLM-free aggregate + eligibility calculation.

    Added after a live run showed a small chat model paraphrasing
    check_eligibility's tool output into fabricated category names that
    don't exist in programmes.json, and misreporting electives_match as
    None across every category. The underlying tools were correct - the
    model's retelling of them was not. This endpoint calls compute_aggregate
    and check_eligibility directly, with zero LLM involvement, so the core
    numbers a student relies on can never be hallucinated or mis-paraphrased.
    The chat/LLM path remains for conversational, open-ended questions
    (retrieval, follow-ups) it's actually suited for.

    If `session_id` is provided, the result is also recorded into that
    session's chat history as a plain-text summary (see
    app/services/calculation_summary.py) - see docs/evaluation.md Failure 8:
    without this, a student could get a correct result here and then have
    the chat claim total ignorance of it moments later, because the two
    paths never shared any state at all.
    """
    grade_input = request.grades
    try:
        aggregate_result = compute_aggregate(grade_input)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    eligibility_result = check_eligibility(
        aggregate=aggregate_result.aggregate,
        track=grade_input.track.value,
        electives=grade_input.electives,
    )

    if request.session_id:
        summary = build_calculation_summary(aggregate_result, eligibility_result)
        session_store.append_message(
            request.session_id, "user", "[Submitted grades via the Enter My Grades form]"
        )
        session_store.append_message(request.session_id, "assistant", summary)

    return {
        "aggregate": aggregate_result.model_dump(),
        "eligibility": eligibility_result.model_dump(),
    }


@router.get("/analytics", response_model=CohortStats)
def analytics(
    programme_category: Optional[str] = None, track: Optional[str] = None
) -> CohortStats:
    """Direct, non-chat access to the Question 9 data analysis capability -
    lets this be demonstrated live without depending on the LLM deciding to
    call analyze_outcomes on its own.
    """
    try:
        return analyze_outcomes(programme_category=programme_category, track=track)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/session/reset", response_model=ResetResponse)
def reset_session(request: ResetRequest) -> ResetResponse:
    deleted = session_store.reset_session(request.session_id)
    logger.info("Reset session %s (%d messages deleted)", request.session_id, deleted)
    return ResetResponse(session_id=request.session_id, deleted_messages=deleted)
