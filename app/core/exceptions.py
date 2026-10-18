class AdvisorError(Exception):
    """Base class for all anticipated failure modes in this app. Anything
    that reaches the API layer as this type gets a clear user-facing message;
    anything else is an unexpected exception and is handled separately."""


class LLMUnavailableError(AdvisorError):
    """Ollama is unreachable or returned an error. Never let this surface as
    a silent hang or a stack trace to the user."""


class RecommendationValidationError(AdvisorError):
    """The model's submit_recommendation arguments failed Pydantic validation
    twice (original attempt + one repair retry)."""


class RetrievalError(AdvisorError):
    """The vector store query failed (e.g. embedding call failed, store
    unreadable). The system must say it couldn't retrieve supporting
    information - never silently fall back to answering from the model's
    unguided pretrained knowledge on a factual question."""
