from typing import List, Optional

from pydantic import BaseModel


class InstitutionProgrammeRow(BaseModel):
    """One real, sourced programme row for a named institution - copied
    verbatim from institution_programmes.json, never generated. See
    docs/evaluation.md Failure 13 for the live case (model inventing
    "Bachelor of Medicine and Surgery at UDS") this exists to fix."""

    institution: str
    college_or_category: Optional[str] = None
    programme: str
    cutoff_display: Optional[str] = None
    fee_paying_cutoff_display: Optional[str] = None
    level: Optional[str] = None
    subject_requirements: Optional[str] = None
    notes: Optional[str] = None
    confidence: str
    source_url: str


class InstitutionProgrammeLookup(BaseModel):
    institution: str
    keyword: Optional[str] = None
    matches: List[InstitutionProgrammeRow]
    total_available_for_institution: int
    has_data_for_institution: bool
    """False means this institution has NO per-programme data on file yet -
    the caller must say so plainly rather than inventing programme names."""
