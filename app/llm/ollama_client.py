"""Thin wrapper around the `ollama` package. This is deliberately the only
module in the codebase that imports `ollama` directly - everything else
(orchestrator, tests) depends on the `chat()` function signature here, not
on the library. That makes it possible to test orchestration logic with a
fake chat function, without a running Ollama server (see tests/test_orchestrator.py).
"""

import json
import os
import re

import ollama

from app.core.exceptions import LLMUnavailableError

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "llama3.1:8b")

_client = ollama.Client(host=OLLAMA_HOST)

_KNOWN_TOOL_NAMES = {
    "compute_aggregate",
    "check_eligibility",
    "retrieve_context",
    "analyze_outcomes",
    "submit_recommendation",
}


def _extract_fallback_tool_calls(content: str) -> list[dict]:
    """Observed live with qwen2.5:1.5b (see docs/evaluation.md Failure 5):
    instead of using Ollama's native tool-calling, the model sometimes
    writes a fake tool-call-shaped JSON object directly into its own text
    content, then hallucinates a result as if that fake call had actually
    run. Native tool_calls stays empty in this case - the model never
    triggers the real mechanism, it just mimics what a call looks like.

    This scans `content` for {"name": "<known_tool>", "arguments": {...}}
    objects and returns them in the same normalized shape real tool_calls
    use, so the orchestrator can dispatch them for real instead of trusting
    the model's own fabricated narration of what they returned.

    Uses brace-matching rather than a single regex, because `arguments` can
    contain nested objects (e.g. the `electives` dict) that a non-greedy
    regex can't correctly bound. Unknown tool names and malformed JSON are
    silently skipped - never trusted blindly. Duplicate identical blocks
    (the model repeated itself verbatim in the observed case) are deduped.
    """
    calls = []
    seen = set()
    for match in re.finditer(r'\{\s*"name"\s*:\s*"(\w+)"', content):
        name = match.group(1)
        if name not in _KNOWN_TOOL_NAMES:
            continue

        start = match.start()
        depth = 0
        end = None
        for i in range(start, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            continue  # unbalanced braces - likely truncated, skip rather than guess

        try:
            obj = json.loads(content[start:end])
        except json.JSONDecodeError:
            continue

        if obj.get("name") not in _KNOWN_TOOL_NAMES:
            continue

        dedup_key = json.dumps(obj, sort_keys=True)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        calls.append({"name": obj["name"], "arguments": obj.get("arguments", {})})

    return calls


def chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """Calls the chat model once. Returns a plain dict with at least
    {"role": "assistant", "content": str, "tool_calls": list[dict] | None}
    so callers never need to know about ollama-library-specific response
    objects.

    Raises:
        LLMUnavailableError: on any connection/runtime failure talking to
            Ollama (server down, model not pulled, etc.) - this is the error
            boundary named in docs/architecture.md for "LLM unavailable".
    """
    try:
        response = _client.chat(model=CHAT_MODEL, messages=messages, tools=tools or [])
    except Exception as exc:  # ollama raises its own error types; normalize all of them
        raise LLMUnavailableError(
            f"Could not reach model '{CHAT_MODEL}' at {OLLAMA_HOST}: {exc}"
        ) from exc

    message = response.get("message", response) if isinstance(response, dict) else response.message

    tool_calls = getattr(message, "tool_calls", None) or (
        message.get("tool_calls") if isinstance(message, dict) else None
    )
    normalized_tool_calls = []
    for tc in tool_calls or []:
        fn = getattr(tc, "function", None) or tc.get("function", {})
        name = getattr(fn, "name", None) or fn.get("name")
        arguments = getattr(fn, "arguments", None) or fn.get("arguments", {})
        normalized_tool_calls.append({"name": name, "arguments": arguments})

    content = getattr(message, "content", None) or (
        message.get("content") if isinstance(message, dict) else ""
    )
    content = content or ""

    if not normalized_tool_calls:
        fallback_calls = _extract_fallback_tool_calls(content)
        if fallback_calls:
            normalized_tool_calls = fallback_calls
            # The fake-JSON text isn't a meaningful message to show the
            # user - it's a malformed stand-in for a real tool call we're
            # about to dispatch for real. Drop it rather than showing raw
            # JSON blocks in the chat.
            content = ""

    return {
        "role": "assistant",
        "content": content,
        "tool_calls": normalized_tool_calls,
    }


def chat_stream(messages: list[dict], tools: list[dict] | None = None):
    """Yields text deltas (str) as the model generates its response, via
    Ollama's stream=True. Used ONLY for the final narrative answer once the
    tool-calling decision loop is done - see orchestrator.py's module
    docstring for why decision rounds stay non-streaming.

    Raises:
        LLMUnavailableError: on connection failure, whether it happens on
            the initial request or partway through iterating the stream
            (e.g. the connection drops mid-generation).
    """
    try:
        stream = _client.chat(model=CHAT_MODEL, messages=messages, tools=tools or [], stream=True)
        for chunk in stream:
            message = chunk.get("message", chunk) if isinstance(chunk, dict) else chunk.message
            content = getattr(message, "content", None) or (
                message.get("content") if isinstance(message, dict) else ""
            )
            if content:
                yield content
    except LLMUnavailableError:
        raise
    except Exception as exc:
        raise LLMUnavailableError(
            f"Could not stream from model '{CHAT_MODEL}' at {OLLAMA_HOST}: {exc}"
        ) from exc


def embed(text: str) -> list[float]:
    """Separate from chat() since it uses a different model (EMBED_MODEL).
    Used by app/rag once that module exists; defined here now so the RAG
    layer has a stable interface to build against.
    """
    embed_model = os.environ.get("EMBED_MODEL", "nomic-embed-text")
    try:
        response = _client.embeddings(model=embed_model, prompt=text)
    except Exception as exc:
        raise LLMUnavailableError(
            f"Could not reach embedding model '{embed_model}' at {OLLAMA_HOST}: {exc}"
        ) from exc
    return response["embedding"] if isinstance(response, dict) else response.embedding
