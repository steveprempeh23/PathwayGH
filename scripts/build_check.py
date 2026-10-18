#!/usr/bin/env python3
"""Sanity check: does every module import cleanly, and does the app wire
together end to end? Deliberately separate from "is Ollama actually
running" - that's a live-dependency check, not a build check, and the two
failure modes need different responses (fix code vs. start a service).

Run: python scripts/build_check.py
"""

import sys
import traceback
from pathlib import Path

# Running this as `python scripts/build_check.py` puts scripts/ itself on
# sys.path, not the project root - add the root explicitly so `app` and
# `main` resolve the same way they would under uvicorn/pytest from the root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _step(label: str, fn):
    print(f"[ ] {label}", end=" ... ", flush=True)
    try:
        fn()
    except Exception:
        print("FAILED")
        traceback.print_exc()
        return False
    print("ok")
    return True


def check_imports():
    import app.core.exceptions  # noqa: F401
    import app.core.grading_data  # noqa: F401
    import app.core.session_store  # noqa: F401
    import app.models.eligibility  # noqa: F401
    import app.models.grading  # noqa: F401
    import app.models.recommendation  # noqa: F401
    import app.tools.aggregate_calculator  # noqa: F401
    import app.tools.eligibility_checker  # noqa: F401
    import app.rag.chunker  # noqa: F401
    import app.rag.vector_store  # noqa: F401
    import app.rag.retriever  # noqa: F401
    import app.llm.ollama_client  # noqa: F401
    import app.llm.tool_schemas  # noqa: F401
    import app.llm.system_prompt  # noqa: F401
    import app.llm.orchestrator  # noqa: F401


def check_main_app_loads():
    import main  # noqa: F401

    assert main.app.title == "PathwayGH Advisor"


def check_tool_schemas_match_models():
    from app.llm.tool_schemas import ALL_TOOLS

    names = {t["function"]["name"] for t in ALL_TOOLS}
    # compute_aggregate and check_eligibility are deliberately NOT in this
    # set - see docs/evaluation.md Failure 6 and app/llm/tool_schemas.py's
    # ALL_TOOLS comment for why they were removed from the chat's tools.
    assert names == {
        "retrieve_context",
        "analyze_outcomes",
        "submit_recommendation",
    }, f"unexpected tool set: {names}"


def check_datasets_load():
    from app.core.grading_data import POINTS
    from app.tools.eligibility_checker import _PROGRAMMES

    assert len(POINTS) == 9, "expected 9 WASSCE grades"
    assert len(_PROGRAMMES) == 7, "expected 7 programme categories"


def check_chunking_runs_on_real_source():
    from pathlib import Path

    from app.rag.chunker import chunk_document

    path = Path("data/raw/wassce_grading_and_admission_guide.md")
    chunks = chunk_document(path)
    assert len(chunks) > 0


def check_health_endpoint():
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def check_ollama_reachability():
    """This one is EXPECTED to fail in environments without a running
    Ollama server reachable at OLLAMA_HOST (e.g. this build sandbox, CI).
    Reported separately from the checks above - failure here is not a
    code/build problem."""
    from app.llm.ollama_client import chat

    chat([{"role": "user", "content": "ping"}])


def main_check() -> int:
    required = [
        ("Module imports", check_imports),
        ("main.py app loads", check_main_app_loads),
        ("Tool schema names match orchestrator expectations", check_tool_schemas_match_models),
        ("Structured datasets load (9 grades, 7 programmes)", check_datasets_load),
        ("Chunker runs on real source document", check_chunking_runs_on_real_source),
        ("/health endpoint responds", check_health_endpoint),
    ]

    results = [_step(label, fn) for label, fn in required]

    print()
    print("--- Live dependency check (informational only, not a build failure) ---")
    print("[ ] Ollama reachable at OLLAMA_HOST", end=" ... ", flush=True)
    try:
        check_ollama_reachability()
        print("ok")
    except Exception as exc:
        print("FAILED")
        print(f"    reason: {exc}")
        print(
            "    (expected if Ollama isn't running/reachable from this environment - "
            "run this script again on the machine that will actually run the app)"
        )

    print()
    if all(results):
        print("BUILD CHECK: PASSED (core app wiring is sound)")
        return 0
    else:
        print("BUILD CHECK: FAILED (see errors above)")
        return 1


if __name__ == "__main__":
    sys.exit(main_check())
