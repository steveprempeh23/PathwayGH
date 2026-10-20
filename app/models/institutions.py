from typing import List

from pydantic import BaseModel


class InstitutionsLookup(BaseModel):
    """Deterministic, real-data answer to "which schools for category X" -
    see docs/evaluation.md Failure 12. institutions_example is copied
    verbatim from programmes.json, never generated or paraphrased.
    """

    category: str
    institutions_example: List[str]
    confidence: str
