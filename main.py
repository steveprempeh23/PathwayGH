from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse

from app.api.routes import router as api_router
from app.core.logging_config import setup_logging

setup_logging()

app = FastAPI(
    title="PathwayGH Advisor",
    description=(
        "RAG + tool-augmented advisor for SHS students navigating WASSCE "
        "aggregates and tertiary programme eligibility in Ghana."
    ),
    version="0.1.0",
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
