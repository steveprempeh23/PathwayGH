"""Tool definitions passed to Ollama's tool-calling API.

Two are real actions (compute_aggregate, check_eligibility) backed by the
deterministic tools in app/tools. The third, submit_recommendation, is the
structured-output enforcement mechanism for Question 5: its parameter schema
IS the Recommendation Pydantic model's schema, generated directly rather than
hand-duplicated, so the tool definition can't silently drift from the model
that actually validates it.
"""

from app.models.grading import GradeInput
from app.models.recommendation import Recommendation

COMPUTE_AGGREGATE_TOOL = {
    "type": "function",
    "function": {
        "name": "compute_aggregate",
        "description": (
            "Calculate a student's WASSCE aggregate from six subject grades. "
            "ALWAYS use this tool for aggregate arithmetic - never compute or "
            "estimate the aggregate yourself from grades in conversation."
        ),
        "parameters": GradeInput.model_json_schema(),
    },
}

CHECK_ELIGIBILITY_TOOL = {
    "type": "function",
    "function": {
        "name": "check_eligibility",
        "description": (
            "Check which programme categories a computed aggregate and set of "
            "elective subjects/grades are eligible for. ALWAYS use this tool "
            "instead of recalling or guessing a cutoff from memory."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "aggregate": {"type": "integer", "description": "Result from compute_aggregate"},
                "track": {"type": "string", "enum": ["science", "non_science"]},
                "electives": {
                    "type": "object",
                    "description": "Map of elective subject name to WASSCE grade, e.g. {'Biology': 'B2'}",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["aggregate", "track", "electives"],
        },
    },
}

RETRIEVE_CONTEXT_TOOL = {
    "type": "function",
    "function": {
        "name": "retrieve_context",
        "description": (
            "Search the WASSCE grading and admission guide for relevant passages. "
            "ALWAYS use this before answering a factual question about grading "
            "rules, core/elective requirements, or admission bands - never answer "
            "such questions from memory alone."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"}
            },
            "required": ["query"],
        },
    },
}

ANALYZE_OUTCOMES_TOOL = {
    "type": "function",
    "function": {
        "name": "analyze_outcomes",
        "description": (
            "Get deterministic cohort statistics (mean/median/min/max aggregate, "
            "admission rate, year-over-year trend) from the synthetic demonstration "
            "dataset. Use this for questions like 'what's the typical aggregate for "
            "Business?' or 'has the admission rate for Medicine changed over time?'. "
            "ALWAYS clarify to the student that this is illustrative/synthetic data, "
            "not real historical admissions records - the tool result's data_source "
            "field says so explicitly; include that caveat in your answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "programme_category": {
                    "type": "string",
                    "description": "Optional - filter to one programme category",
                },
                "track": {
                    "type": "string",
                    "enum": ["science", "business", "arts", "general", "technical"],
                    "description": "Optional - filter to one track",
                },
            },
        },
    },
}

LIST_INSTITUTIONS_TOOL = {
    "type": "function",
    "function": {
        "name": "list_institutions",
        "description": (
            "Get the REAL, sourced example institutions for one programme "
            "category, copied verbatim from programmes.json. ALWAYS call this "
            "when asked 'which schools', 'list eligible schools', or similar - "
            "even if you believe you remember the institutions from an earlier "
            "'Aggregate:' table in this conversation. You have been observed, "
            "live, inventing institutions (e.g. naming University of Ghana, UCC, "
            "KNUST for a category whose real list is only UHAS and UDS) when "
            "answering from memory instead of calling this tool - see "
            "docs/evaluation.md Failure 12. Never name an institution that this "
            "tool did not return for that category."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "programme_category": {
                    "type": "string",
                    "description": "Exact category name, e.g. 'Physician Assistantship / Allied Health'",
                },
            },
            "required": ["programme_category"],
        },
    },
}

LOOKUP_INSTITUTION_PROGRAMMES_TOOL = {
    "type": "function",
    "function": {
        "name": "lookup_institution_programmes",
        "description": (
            "Get REAL, sourced degree programmes and cutoff points for one "
            "NAMED institution, copied verbatim from institution_programmes.json. "
            "ALWAYS call this before naming any specific programme at a specific "
            "institution (e.g. 'Bachelor of Medicine and Surgery at UDS') - you "
            "have been observed, live, inventing institution-specific programme "
            "titles with no real data behind them - see docs/evaluation.md "
            "Failure 13. Only University of Ghana and KNUST have real data in "
            "this tool so far; for every other institution it will return "
            "has_data_for_institution=False - when that happens, say plainly "
            "you don't have per-programme data for that institution yet, never "
            "invent programme names to fill the gap. UG's data comes from UG's "
            "own official admissions page; KNUST's comes from a third-party "
            "site, so treat KNUST's confidence field accordingly."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "institution": {
                    "type": "string",
                    "description": "Exact institution name, e.g. 'University of Ghana' or 'KNUST'",
                },
                "keyword": {
                    "type": "string",
                    "description": "Optional substring to filter programme names, e.g. 'medicine' or 'engineering'",
                },
            },
            "required": ["institution"],
        },
    },
}

SUBMIT_RECOMMENDATION_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_recommendation",
        "description": (
            "Submit your final recommendation to the student once you have "
            "enough information (aggregate computed, eligibility checked). "
            "This is how your answer is delivered - do not just describe the "
            "recommendation in plain text, call this tool with it."
        ),
        "parameters": Recommendation.model_json_schema(),
    },
}

# compute_aggregate and CHECK_ELIGIBILITY_TOOL are deliberately NOT offered
# to the chat model. See docs/evaluation.md Failure 6: across two different
# local models, extracting six fields (English, Core Maths, third core,
# three electives + grades) from free-text conversation via agentic
# tool-calling proved unreliable in several distinct ways - fabricated
# results, stuck loops, faked tool-call JSON, and finally the model asking
# the USER to supply pre-formatted dict syntax instead of doing extraction
# itself. This is treated as a structural mismatch between the task and
# conversational tool-calling at locally-runnable model sizes, not a prompt
# wording problem to keep patching. The deterministic /calculate endpoint
# (app/api/routes.py) and its "Enter My Grades" form are the only path to
# these two tools now; the two schema definitions above are kept in this
# file for reference and because app/api/routes.py's /calculate endpoint
# calls the underlying compute_aggregate/check_eligibility functions
# directly (not through tool-calling at all).
ALL_TOOLS = [
    RETRIEVE_CONTEXT_TOOL,
    ANALYZE_OUTCOMES_TOOL,
    LIST_INSTITUTIONS_TOOL,
    LOOKUP_INSTITUTION_PROGRAMMES_TOOL,
    SUBMIT_RECOMMENDATION_TOOL,
]
