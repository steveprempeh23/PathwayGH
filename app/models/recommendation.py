from typing import List, Literal

from pydantic import BaseModel, Field


class Recommendation(BaseModel):
    """The LLM's final answer must be coerced into this schema before it's
    shown to a student. This is the structured-output component required by
    Question 5 - the model's raw text is never trusted directly; it's parsed
    and validated against this schema, with a repair retry on failure (see
    app/llm orchestration logic, not yet built).
    """

    programme_category: str
    fit_reason: str = Field(description="Plain-language explanation of why this fits the student")
    confidence: Literal["high", "medium", "low"]
    caveats: List[str] = Field(
        default_factory=list,
        description="e.g. 'cutoff is an approximate band, not a verified current figure'",
    )
    sources: List[str] = Field(
        default_factory=list,
        description="Source URLs or document titles backing this claim; empty list is valid "
        "and means no retrieval was used for this particular claim (e.g. a pure "
        "calculator-tool result) - it must never be filled with an invented source.",
    )
