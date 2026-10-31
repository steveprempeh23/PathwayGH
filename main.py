import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse

from app.api.routes import router as api_router
from app.core.logging_config import setup_logging
from app.rag import retriever

setup_logging()
_logger = logging.getLogger("pathwaygh.startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Builds the RAG index on startup - previously, nothing in the app
    ever called retriever.build_index() at all (not here, not lazily in
    retrieve_context), so data/raw/*.md only ever got indexed if someone
    ran it manually once from a Python shell. That meant a fresh clone
    (or CI, or a grader's machine) would have an empty vector store and
    retrieve_context would always return zero results regardless of
    corpus content - indistinguishable from a genuine "nothing relevant
    found" case from the outside. build_index() is idempotent (won't
    re-embed if the collection already has content), so this is safe to
    call on every restart; it does NOT pick up edits to data/raw/*.md on
    an existing populated store - delete CHROMA_PERSIST_DIR (default
    data/chroma/) to force a full re-embed after editing the corpus.
    """
    try:
        count = retriever.build_index()
        _logger.info("RAG index ready: %d chunks indexed", count)
    except Exception as exc:  # noqa: BLE001 - startup must not crash if Ollama isn't up yet
        _logger.warning(
            "Could not build RAG index at startup (%s). retrieve_context will "
            "return RetrievalError until Ollama is reachable and the app is "
            "restarted, or build_index() is called manually.", exc,
        )
    yield


app = FastAPI(
    title="PathwayGH Advisor",
    description=(
        "RAG + tool-augmented advisor for SHS students navigating WASSCE "
        "aggregates and tertiary programme eligibility in Ghana."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router)

_STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/")
def serve_ui():
    """Serves the single-page chat UI. Deliberately not mounted as a
    StaticFiles directory at "/" - that would shadow the API routes above
    it. A single explicit route for the one HTML file keeps both the UI
    and the JSON API reachable without path conflicts.
    """
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/favicon.ico")
def favicon():
    """Browsers request this automatically for the tab icon. Without this
    route it 404s harmlessly (no functional impact), but that shows up as
    noise in every request log - a 204 is the correct, quiet response for
    "no icon, nothing wrong".
    """
    return Response(status_code=204)


@app.get("/health")
def health():
    """Basic liveness check - confirms the app process is up.

    Deliberately does not check Ollama/Chroma here; that belongs to a
    readiness check once those clients exist (app/core), so a slow model
    load doesn't make the app look dead to a container orchestrator.
    """
    return {"status": "ok"}
