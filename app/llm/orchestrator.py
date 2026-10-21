"""Ties together conversation state, tool execution, and structured-output
validation for one chat turn.

Design note on what gets persisted: only the user-visible conversation (user
messages, final assistant replies) is saved to session_store. The tool-calling
exchange within a single turn (tool_call -> tool_result -> model again) is
ephemeral scaffolding to produce that turn's answer, not part of the
conversation memory itself - see docs/architecture.md "Where Application
State and Memory Reside".

Streaming design (Question 10): tool-call DECISION rounds are deliberately
non-streaming. A tool call is a structured JSON object the orchestrator must
fully parse before it can dispatch it - there's no safe, server-agnostic way
to "partially execute" a tool call from a half-streamed token. Only the
final natural-language answer, once no more tools are needed, is genuinely
streamed token-by-token (see handle_turn_stream). This does mean one extra
model call for turns that stream (the decision loop's own final content is
discarded in favor of a fresh streamed generation) - a deliberate trade-off
for honest, real token streaming over a more complex and much harder to
verify interleaved stream+tool-call parser.
"""

import json
from pydantic import ValidationError

from app.core import session_store
from app.core.exceptions import LLMUnavailableError, RetrievalError
from app.llm import ollama_client
from app.llm.system_prompt import SYSTEM_PROMPT
from app.llm.tool_schemas import ALL_TOOLS
from app.models.grading import GradeInput
from app.models.recommendation import Recommendation
from app.rag import retriever as rag_retriever
from app.tools.aggregate_calculator import compute_aggregate
from app.tools.data_analysis import analyze_outcomes
from app.tools.eligibility_checker import check_eligibility
from app.tools.eligibility_claim_guard import detect_eligibility_contradictions
from app.tools.eligibility_status_lookup import get_saved_eligibility
from app.tools.institution_claim_guard import detect_unverified_institution_claims
from app.tools.institution_programme_lookup import lookup_institution_programmes
from app.tools.programme_lookup import lookup_institutions

MAX_TOOL_HOPS = 5
MAX_RECOMMENDATION_ATTEMPTS = 2  # original attempt + one repair retry

FALLBACK_LLM_UNAVAILABLE = (
    "The advisor is temporarily unavailable (couldn't reach the language "
    "model). Please try again shortly."
)
FALLBACK_RECOMMENDATION_FAILED = (
    "I wasn't able to put together a properly formatted recommendation this "
    "time. Could you confirm your grades again? If this keeps happening, "
    "please talk to a guidance counsellor directly in the meantime."
)
FALLBACK_TOO_MANY_TOOL_CALLS = (
    "I wasn't able to finish processing this after several steps. Could you "
    "try rephrasing or simplifying your question?"
)

PROGRESS_LABELS = {
    "compute_aggregate": "Calculating your WASSCE aggregate...",
    "check_eligibility": "Checking programme eligibility...",
    "retrieve_context": "Searching the admission guide...",
    "analyze_outcomes": "Crunching cohort statistics...",
    "list_institutions": "Looking up real institutions for this category...",
    "get_saved_eligibility": "Checking your saved eligibility result...",
    "lookup_institution_programmes": "Looking up real programmes for this institution...",
    "submit_recommendation": "Preparing your recommendation...",
}


def _execute_tool(name: str, arguments: dict, session_id: str):
    """Runs one tool call. Returns (result_content_for_model, recommendation, extra).

    `extra` is a dict carrying the REAL typed result object for
    compute_aggregate/check_eligibility/analyze_outcomes calls (e.g.
    {"aggregate": AggregateResult} or {"cohort_stats": CohortStats}), or
    None otherwise. This is the ground truth the orchestrator attaches to
    its response independent of anything the model says in its own reply -
    see the "calculation"/"cohort_stats" fields on handle_turn's return
    value and the handle_turn_stream "done" event. This exists specifically
    because a small model was observed, live, paraphrasing correct tool
    output into fabricated category names (see docs/evaluation.md,
    Failure 3) - the fix is to never rely on the model's retelling for the
    numbers that actually matter. Failure 9 (see docs/evaluation.md) is the
    same failure mode applied to analyze_outcomes: the model dropped the
    mandatory "this is synthetic demonstration data" caveat from its own
    reply text even though the system prompt requires it every time -
    cohort_stats.data_source carries that caveat verbatim from code, so the
    API response has it regardless of what the model's prose says.

    recommendation is non-None only when submit_recommendation succeeds.
    Never raises for ordinary bad input - bad input becomes an error message
    fed back to the model so it can self-correct, per the tool-failure
    error-handling boundary in docs/architecture.md.
    """
    if name == "compute_aggregate":
        try:
            grade_input = GradeInput(**arguments)
            result = compute_aggregate(grade_input)
            return result.model_dump_json(), None, {"aggregate": result}
        except (ValidationError, ValueError) as exc:
            return json.dumps({"error": str(exc)}), None, None

    if name == "check_eligibility":
        try:
            result = check_eligibility(
                aggregate=arguments["aggregate"],
                track=arguments["track"],
                electives=arguments.get("electives", {}),
            )
            return result.model_dump_json(), None, {"eligibility": result}
        except (KeyError, ValueError, ValidationError) as exc:
            return json.dumps({"error": str(exc)}), None, None

    if name == "retrieve_context":
        try:
            results = rag_retriever.retrieve(arguments.get("query", ""))
        except RetrievalError as exc:
            return json.dumps({"error": str(exc)}), None, None
        if not results:
            return (
                json.dumps(
                    {"results": [], "note": "No indexed passage matched this query."}
                ),
                None,
                None,
            )
        retrieved_urls = {
            url for r in results for url in r.get("source_urls", [])
        }
        return json.dumps({"results": results}), None, {"retrieved_urls": retrieved_urls}

    if name == "analyze_outcomes":
        try:
            stats = analyze_outcomes(
                programme_category=arguments.get("programme_category"),
                track=arguments.get("track"),
            )
            return stats.model_dump_json(), None, {"cohort_stats": stats}
        except ValueError as exc:
            return json.dumps({"error": str(exc)}), None, None

    if name == "list_institutions":
        try:
            result = lookup_institutions(arguments.get("programme_category"))
            return result.model_dump_json(), None, {"institutions_lookup": result}
        except ValueError as exc:
            return json.dumps({"error": str(exc)}), None, None

    if name == "get_saved_eligibility":
        try:
            result = get_saved_eligibility(session_id, arguments.get("programme_category"))
            return result.model_dump_json(), None, {"saved_eligibility": result}
        except ValueError as exc:
            return json.dumps({"error": str(exc)}), None, None

    if name == "lookup_institution_programmes":
        result = lookup_institution_programmes(
            institution=arguments.get("institution"),
            keyword=arguments.get("keyword"),
        )
        return result.model_dump_json(), None, {"institution_programmes": result}

    if name == "submit_recommendation":
        try:
            recommendation = Recommendation(**arguments)
            return json.dumps({"status": "accepted"}), recommendation, None
        except ValidationError as exc:
            return json.dumps({"error": "validation_failed", "details": str(exc)}), None, None

    return json.dumps({"error": f"unknown tool '{name}'"}), None, None


def _resolve_tools(messages: list[dict], chat_fn, session_id: str):
    """Shared tool-calling loop, used by both handle_turn and
    handle_turn_stream. A generator: yields {"type": "progress", ...} events
    as each tool executes, and on completion returns (via StopIteration.value)
    a tuple (final_response, recommendation, early_result, aggregate_result,
    eligibility_result).

    early_result is non-None only when the turn must stop immediately (LLM
    unavailable, or recommendation retries exhausted) - callers must use
    early_result instead of final_response/recommendation in that case.

    aggregate_result/eligibility_result are the REAL typed objects from the
    most recent compute_aggregate/check_eligibility calls this turn, kept
    independent of anything the model says in its own narration - see
    _execute_tool's docstring for why.

    Also enforces, programmatically rather than only by prompt, that
    submit_recommendation's `sources` field can only contain URLs that were
    literally returned by a retrieve_context call earlier in this same
    turn - see docs/evaluation.md Failure 9, where a model fabricated a
    plausible-looking citation URL for a source that was never retrieved.
    A recommendation with any unretrieved URL is rejected the same way a
    schema-invalid one is: fed back as an error, consuming a repair attempt.
    """
    aggregate_result = None
    eligibility_result = None
    cohort_stats_result = None
    institutions_lookup_result = None
    institution_programmes_result = None
    verified_institutions: set[str] = set()
    retrieved_urls: set[str] = set()

    try:
        response = chat_fn(messages, tools=ALL_TOOLS)
    except LLMUnavailableError:
        return (
            None, None,
            {"reply": FALLBACK_LLM_UNAVAILABLE, "recommendation": None},
            None, None, None, None, None, None,
        )

    recommendation: Recommendation | None = None
    recommendation_attempts = 0
    hops = 0

    while response["tool_calls"] and hops < MAX_TOOL_HOPS:
        if response["content"]:
            messages.append({"role": "assistant", "content": response["content"]})

        for call in response["tool_calls"]:
            yield {
                "type": "progress",
                "tool": call["name"],
                "message": PROGRESS_LABELS.get(call["name"], f"Running {call['name']}..."),
            }

            result_content, maybe_recommendation, extra = _execute_tool(
                call["name"], call["arguments"], session_id
            )

            if extra:
                if "aggregate" in extra:
                    aggregate_result = extra["aggregate"]
                if "eligibility" in extra:
                    eligibility_result = extra["eligibility"]
                if "cohort_stats" in extra:
                    cohort_stats_result = extra["cohort_stats"]
                if "institutions_lookup" in extra:
                    institutions_lookup_result = extra["institutions_lookup"]
                if "institution_programmes" in extra:
                    institution_programmes_result = extra["institution_programmes"]
                    if institution_programmes_result.has_data_for_institution:
                        verified_institutions.add(institution_programmes_result.institution)
                if "retrieved_urls" in extra:
                    retrieved_urls |= extra["retrieved_urls"]

            if call["name"] == "submit_recommendation":
                if maybe_recommendation is not None:
                    fabricated = [s for s in maybe_recommendation.sources if s not in retrieved_urls]
                    if fabricated:
                        # Schema-valid but citing a URL never actually
                        # retrieved this turn - reject it exactly like a
                        # validation failure, not a success.
                        maybe_recommendation = None
                        result_content = json.dumps(
                            {
                                "error": "fabricated_sources",
                                "details": (
                                    f"These URLs were not returned by any retrieve_context "
                                    f"call in this conversation: {fabricated}. Only cite URLs "
                                    f"that literally appeared in a retrieve_context result, "
                                    f"or use an empty sources list if you have no real source."
                                ),
                            }
                        )

                if maybe_recommendation is not None:
                    recommendation = maybe_recommendation
                else:
                    recommendation_attempts += 1
                    if recommendation_attempts >= MAX_RECOMMENDATION_ATTEMPTS:
                        return (
                            None, None,
                            {"reply": FALLBACK_RECOMMENDATION_FAILED, "recommendation": None},
                            aggregate_result, eligibility_result, cohort_stats_result, institutions_lookup_result,
        institution_programmes_result, verified_institutions,
                        )

            messages.append(
                {"role": "tool", "name": call["name"], "content": result_content}
            )

        try:
            response = chat_fn(messages, tools=ALL_TOOLS)
        except LLMUnavailableError:
            return (
                None, None,
                {"reply": FALLBACK_LLM_UNAVAILABLE, "recommendation": None},
                aggregate_result, eligibility_result, cohort_stats_result, institutions_lookup_result,
        institution_programmes_result, verified_institutions,
            )

        hops += 1

    if response["tool_calls"]:
        # Loop exited because hops hit MAX_TOOL_HOPS, NOT because the model
        # was actually done calling tools - `response` here is unprocessed
        # and its content may be empty, which would otherwise surface as a
        # silent blank reply to the user. Treat this as its own failure
        # mode rather than letting it fall through.
        return (
            None, None,
            {"reply": FALLBACK_TOO_MANY_TOOL_CALLS, "recommendation": None},
            aggregate_result, eligibility_result, cohort_stats_result, institutions_lookup_result,
        institution_programmes_result, verified_institutions,
        )

    return (
        response, recommendation, None,
        aggregate_result, eligibility_result, cohort_stats_result, institutions_lookup_result,
        institution_programmes_result, verified_institutions,
    )


def _build_calculation(aggregate_result, eligibility_result):
    """Packages the real tool results into the wire-format dict the API
    schema and the frontend expect, or None if neither tool ran this turn."""
    if aggregate_result is None and eligibility_result is None:
        return None
    return {
        "aggregate": aggregate_result.model_dump() if aggregate_result else None,
        "eligibility": eligibility_result.model_dump() if eligibility_result else None,
    }


def _build_cohort_stats(cohort_stats_result):
    """Packages the real analyze_outcomes result, or None if it didn't run
    this turn. data_source is the mandatory synthetic-dataset caveat - see
    docs/evaluation.md Failure 9 for why this is surfaced from code rather
    than left to the model to repeat in its own reply."""
    if cohort_stats_result is None:
        return None
    return cohort_stats_result.model_dump()


def _build_institutions_lookup(institutions_lookup_result):
    """Packages the real list_institutions result, or None if it didn't run
    this turn. institutions_example here is copied verbatim from
    programmes.json - see docs/evaluation.md Failure 12 for the live case
    (model inventing institutions from memory) this exists to fix."""
    if institutions_lookup_result is None:
        return None
    return institutions_lookup_result.model_dump()


def _build_institution_programmes(institution_programmes_result):
    """Packages the real lookup_institution_programmes result, or None if
    it didn't run this turn. has_data_for_institution=False must be
    surfaced plainly to the student rather than papered over - see
    docs/evaluation.md Failure 13."""
    if institution_programmes_result is None:
        return None
    return institution_programmes_result.model_dump()


def _drain(gen):
    """Runs a _resolve_tools generator to completion, discarding progress
    events (used by the non-streaming handle_turn, which has no consumer
    for intermediate progress)."""
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


def handle_turn(session_id: str, user_message: str, chat_fn=ollama_client.chat) -> dict:
    """Processes one user turn end to end, non-streaming. `chat_fn` is
    injectable so orchestration logic can be unit-tested without a running
    Ollama server (see tests/test_orchestrator.py).

    Returns: {"reply": str, "recommendation": dict | None, "calculation": dict | None,
              "cohort_stats": dict | None, "institutions_lookup": dict | None}
    `calculation` carries the real compute_aggregate/check_eligibility
    results for this turn, independent of the model's own narration - see
    docs/evaluation.md Failure 3 for why this exists. `cohort_stats` is the
    same idea applied to analyze_outcomes (see Failure 9): its
    `data_source` field is the mandatory "this is synthetic demonstration
    data, not real" caveat, carried here from code so it's always present
    in the response regardless of whether the model's own reply text
    repeated it. `institutions_lookup` is the same idea applied to
    list_institutions (see Failure 12): its institutions_example is copied
    verbatim from programmes.json, carried here from code so it's available
    to the frontend even when the model's own reply names institutions that
    don't match it.
    """
    history = session_store.get_history(session_id)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [
        {"role": "user", "content": user_message}
    ]

    (
        final_response, recommendation, early_result,
        aggregate_result, eligibility_result, cohort_stats_result, institutions_lookup_result,
        institution_programmes_result, verified_institutions,
    ) = _drain(_resolve_tools(messages, chat_fn, session_id))
    calculation = _build_calculation(aggregate_result, eligibility_result)
    cohort_stats = _build_cohort_stats(cohort_stats_result)
    institutions_lookup = _build_institutions_lookup(institutions_lookup_result)
    institution_programmes = _build_institution_programmes(institution_programmes_result)

    if early_result is not None:
        session_store.append_message(session_id, "user", user_message)
        session_store.append_message(session_id, "assistant", early_result["reply"])
        early_result["calculation"] = calculation
        early_result["cohort_stats"] = cohort_stats
        early_result["institutions_lookup"] = institutions_lookup
        early_result["institution_programmes"] = institution_programmes
        early_result["unverified_institution_claims"] = detect_unverified_institution_claims(
            early_result["reply"], verified_institutions
        )
        early_result["eligibility_contradictions"] = detect_eligibility_contradictions(
            early_result["reply"], session_id
        )
        return early_result

    final_text = final_response["content"] or (
        "Here's my recommendation." if recommendation else ""
    )
    # Deterministic safety net for Failure 14 (docs/evaluation.md): the
    # model has been observed naming specific programmes at institutions
    # it never actually queried, across an entire structured answer, not
    # just one extra school. This scans the FINAL reply text itself,
    # independent of which tools the model chose to call, and flags any
    # institution named alongside degree-sounding language that wasn't
    # verified this turn via a real lookup_institution_programmes call.
    unverified_institution_claims = detect_unverified_institution_claims(
        final_text, verified_institutions
    )
    # Deterministic safety net for Failure 15 (docs/evaluation.md): the
    # model has been observed directly contradicting an already-computed
    # eligibility result. Unlike the check above, this has absolute ground
    # truth (the real saved calculation for this session) to compare
    # against, so it can flag a definite WRONG, not just "unverified".
    eligibility_contradictions = detect_eligibility_contradictions(final_text, session_id)

    session_store.append_message(session_id, "user", user_message)
    session_store.append_message(session_id, "assistant", final_text)

    return {
        "reply": final_text,
        "cohort_stats": cohort_stats,
        "institutions_lookup": institutions_lookup,
        "institution_programmes": institution_programmes,
        "unverified_institution_claims": unverified_institution_claims,
        "eligibility_contradictions": eligibility_contradictions,
        "recommendation": recommendation.model_dump() if recommendation else None,
        "calculation": calculation,
    }


def handle_turn_stream(
    session_id: str,
    user_message: str,
    chat_fn=ollama_client.chat,
    stream_fn=ollama_client.chat_stream,
):
    """Generator version of handle_turn, for Question 10. Yields event dicts:
        {"type": "progress", "tool": str, "message": str}
        {"type": "token", "text": str}
        {"type": "error", "message": str, "calculation": dict | None}   - replaces "done" on failure
        {"type": "done", "recommendation": dict | None, "calculation": dict | None,
         "cohort_stats": dict | None, "institutions_lookup": dict | None}

    `calculation` carries the real compute_aggregate/check_eligibility
    results for this turn (if either tool ran), independent of whatever the
    model said in its own reply - see docs/evaluation.md Failure 3.
    `cohort_stats` is the same idea for analyze_outcomes (Failure 9): its
    `data_source` field is the mandatory synthetic-data caveat, carried from
    code so it reaches the response even if the model's streamed text drops it.
    `institutions_lookup` is the same idea for list_institutions (Failure
    12): its institutions_example is copied verbatim from programmes.json,
    carried from code so a frontend can render the real list even if the
    model's streamed text names different institutions.

    `chat_fn` drives the (non-streaming) tool-decision rounds; `stream_fn`
    drives the genuinely-streamed final answer once no more tools are
    needed. Both are injectable for testing without live Ollama.
    """
    history = session_store.get_history(session_id)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history + [
        {"role": "user", "content": user_message}
    ]

    gen = _resolve_tools(messages, chat_fn, session_id)
    try:
        while True:
            yield next(gen)
    except StopIteration as stop:
        (
            final_response, recommendation, early_result,
            aggregate_result, eligibility_result, cohort_stats_result, institutions_lookup_result,
        institution_programmes_result, verified_institutions,
        ) = stop.value
    calculation = _build_calculation(aggregate_result, eligibility_result)
    cohort_stats = _build_cohort_stats(cohort_stats_result)
    institutions_lookup = _build_institutions_lookup(institutions_lookup_result)
    institution_programmes = _build_institution_programmes(institution_programmes_result)

    if early_result is not None:
        session_store.append_message(session_id, "user", user_message)
        session_store.append_message(session_id, "assistant", early_result["reply"])
        yield {
            "type": "error",
            "message": early_result["reply"],
            "calculation": calculation,
            "cohort_stats": cohort_stats,
            "institutions_lookup": institutions_lookup,
            "institution_programmes": institution_programmes,
            "unverified_institution_claims": detect_unverified_institution_claims(
                early_result["reply"], verified_institutions
            ),
            "eligibility_contradictions": detect_eligibility_contradictions(
                early_result["reply"], session_id
            ),
        }
        return

    if recommendation is not None and not (final_response and final_response["content"]):
        # Model went straight to submit_recommendation with no narrative -
        # nothing meaningful to stream token-by-token.
        final_text = "Here's my recommendation."
        yield {"type": "token", "text": final_text}
    else:
        final_text = ""
        try:
            for delta in stream_fn(messages, tools=ALL_TOOLS):
                final_text += delta
                yield {"type": "token", "text": delta}
        except LLMUnavailableError:
            session_store.append_message(session_id, "user", user_message)
            session_store.append_message(session_id, "assistant", FALLBACK_LLM_UNAVAILABLE)
            yield {"type": "error", "message": FALLBACK_LLM_UNAVAILABLE}
            return

    # Same Failure-14 safety net as handle_turn - see the comment there.
    unverified_institution_claims = detect_unverified_institution_claims(
        final_text, verified_institutions
    )
    # Same Failure-15 safety net as handle_turn - see the comment there.
    eligibility_contradictions = detect_eligibility_contradictions(final_text, session_id)

    session_store.append_message(session_id, "user", user_message)
    session_store.append_message(session_id, "assistant", final_text)

    yield {
        "type": "done",
        "recommendation": recommendation.model_dump() if recommendation else None,
        "calculation": calculation,
        "cohort_stats": cohort_stats,
        "institutions_lookup": institutions_lookup,
        "institution_programmes": institution_programmes,
        "unverified_institution_claims": unverified_institution_claims,
        "eligibility_contradictions": eligibility_contradictions,
    }
