from typing import Dict, Optional

from pydantic import BaseModel


class CohortStats(BaseModel):
    """Deterministic aggregation over the synthetic cohort dataset. Every
    number here comes from pandas groupby/mean/median/min/max - never from
    the LLM - per the course's explicit rule: deterministic computation for
    anything calculable, LLM only for interpreting/explaining the result.
    """

    filter_programme_category: Optional[str]
    filter_track: Optional[str]
    sample_size: int
    mean_aggregate: float
    median_aggregate: float
    min_aggregate: int
    max_aggregate: int
    admission_rate_percent: float
    admission_rate_by_year: Dict[str, float]
    data_source: str
