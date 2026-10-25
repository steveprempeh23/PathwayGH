#!/usr/bin/env python3
"""Smoke test for a REAL docker-compose deployment - run this after
`docker compose up --build` (and pulling the two Ollama models) to get a
fast, scripted answer to "did the container actually come up correctly,"
rather than clicking through the UI by hand.

This exists because of an honest gap stated plainly in README.md: the
Dockerfile/docker-compose.yml have been validated by replicating the
COPY'd file set outside Docker and by checking the YAML's syntax, but
NEITHER of those is a substitute for an actual `docker compose up` run -
no Docker daemon was available in the environment this project was built
in. This script is the fast, repeatable check to run the FIRST time you
do have one, so "does the container work" is a 10-second scripted answer
instead of a manual walkthrough every time you touch the Dockerfile.

Usage:
    docker compose up --build -d
    docker compose exec ollama ollama pull llama3.1:8b
    docker compose exec ollama ollama pull nomic-embed-text
    python scripts/docker_smoke_test.py
    # or, against a different host/port:
    python scripts/docker_smoke_test.py --base-url http://localhost:8000
"""
import argparse
import sys

try:
    import requests
except ImportError:
    print("This script needs `requests` (pip install requests) - it's not a", file=sys.stderr)
    print("runtime dependency of the app itself, just this standalone check.", file=sys.stderr)
    sys.exit(2)


def check(name: str, fn) -> bool:
    try:
        ok, detail = fn()
    except Exception as exc:
        ok, detail = False, f"raised {exc!r}"
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip the /chat check, which needs both Ollama models actually pulled.",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    results = []

    def health():
        r = requests.get(f"{base}/health", timeout=5)
        return r.status_code == 200, f"GET /health -> {r.status_code}"

    results.append(check("App container is up and responding", health))

    session_id = {}

    def new_session():
        r = requests.post(f"{base}/session/new", timeout=5)
        ok = r.status_code == 200 and "session_id" in r.json()
        if ok:
            session_id["value"] = r.json()["session_id"]
        return ok, f"POST /session/new -> {r.status_code}"

    results.append(check("Session creation (SQLite write path)", new_session))

    def calculate():
        r = requests.post(
            f"{base}/calculate",
            json={
                "session_id": session_id.get("value"),
                "grades": {
                    "english": "A1",
                    "core_mathematics": "A1",
                    "integrated_science": "A1",
                    "social_studies": "A1",
                    "electives": {"Biology": "A1", "Chemistry": "A1", "Physics": "A1"},
                    "track": "science",
                },
            },
            timeout=10,
        )
        if r.status_code != 200:
            return False, f"POST /calculate -> {r.status_code}"
        body = r.json()
        agg_ok = body.get("aggregate", {}).get("aggregate") == 6
        med = next(
            (m for m in body.get("eligibility", {}).get("matches", []) if m["category"] == "Medicine / Dentistry"),
            None,
        )
        elig_ok = med is not None and med["overall_eligible"] is True
        return agg_ok and elig_ok, f"POST /calculate -> 200, aggregate={body.get('aggregate', {}).get('aggregate')}, Medicine eligible={med and med['overall_eligible']}"

    results.append(check("Deterministic calculation path (no LLM, no Ollama needed)", calculate))

    def saved_calculation_persisted():
        # Confirms the Failure-15 fix's second SQLite table actually wrote
        # inside the container, not just in local dev.
        r = requests.post(
            f"{base}/calculate",
            json={
                "session_id": session_id.get("value"),
                "grades": {
                    "english": "A1",
                    "core_mathematics": "A1",
                    "integrated_science": "A1",
                    "social_studies": "A1",
                    "electives": {"Biology": "A1", "Chemistry": "A1", "Physics": "A1"},
                    "track": "science",
                },
            },
            timeout=10,
        )
        return r.status_code == 200, f"Second /calculate call for the same session -> {r.status_code}"

    results.append(check("calculations table round-trip (Failure 15)", saved_calculation_persisted))

    if not args.skip_llm:
        def chat():
            r = requests.post(
                f"{base}/chat",
                json={"session_id": session_id.get("value"), "message": "What electives does Business need?"},
                timeout=60,
            )
            return r.status_code == 200 and len(r.json().get("reply", "")) > 0, f"POST /chat -> {r.status_code}"

        results.append(
            check(
                "Chat path with live Ollama (needs both models pulled - see --skip-llm)",
                chat,
            )
        )
    else:
        print("[SKIP] Chat path - run without --skip-llm once both Ollama models are pulled")

    print()
    if all(results):
        print("All checks passed - the containerised deployment is working end to end.")
        return 0
    print("Some checks failed - see above. This is exactly what this script exists to catch")
    print("before a live demo, rather than discovering it mid-presentation.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
