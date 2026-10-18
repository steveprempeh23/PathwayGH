# PathwayGH Advisor

A RAG- and tool-augmented advisor that helps Ghanaian SHS students understand
their WASSCE aggregate and which tertiary programme categories they're
plausibly eligible for — grounded in real WAEC/GTEC admission guidance rather
than an LLM's unguided recollection of cutoffs.

Built for DSA5202 (Special Topics in Data Science), Academic City University
College, 2025/2026.

## The Problem

JHS/SHS students in Ghana make consequential school/programme decisions with
scattered, hard-to-parse information (WAEC grading rules, aggregate
calculation, programme-specific cutoffs), and guidance counsellors are
stretched across hundreds of students. See [docs/architecture.md](docs/architecture.md)
for the full problem statement, intended users, and limitations.

## The Proposed Solution

A conversational advisor that:
- Calculates a student's WASSCE aggregate deterministically (never guessed by
  the LLM).
- Checks that aggregate against programme-category eligibility bands.
- Answers "why"-type questions (e.g. "what electives does Business need?")
  using retrieval over a real, cited WAEC/GTEC admission guide — not from the
  model's pretrained knowledge.
- Explicitly says when it doesn't know something, rather than inventing a
  cutoff.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full diagram,
component walkthrough, state/memory location, error-handling boundaries, and
justification of each major decision (model choice, retrieval vs.
long-context, deterministic tools vs. LLM arithmetic).

## Technology Choices

| Component       | Choice                  | Why (short form — full justification in architecture.md) |
|------------------|-------------------------|-------------------------------------------------------------|
| LLM              | `llama3.1:8b` (Ollama)  | Local, private; Ollama's most mature native tool-calling support (see architecture.md for the model-switch history) |
| Embeddings       | `nomic-embed-text`      | Lightweight, better retrieval quality than smallest alternatives |
| Vector store     | ChromaDB                | Simple, embeddable, no separate server needed |
| API              | FastAPI                 | Async, native Pydantic integration for structured-output validation |
| Session state    | SQLite                  | Durable across restarts, real "reset" semantics |
| Validation       | Pydantic                | Schema-enforced structured output, not trusted model text |

## Installation

**Requires Python 3.11 or 3.12.** Python 3.13/3.14 are too new for some of
this project's dependencies to have prebuilt Windows wheels yet - pip falls
back to compiling from source, which fails without a configured MSVC build
toolchain. Check your version with `python --version` before installing;
on Windows, if you have multiple Pythons installed, use the `py` launcher
to pick one explicitly, e.g. `py -3.12 -m venv venv`. If you don't have
Python 3.12 and don't want to go to python.org, `winget install -e --id
Python.Python.3.12` or the Microsoft Store both work.

**On Python 3.12, `chromadb` must be allowed to resolve to its current
1.x line, not pinned to the exact 0.5.x version this project was built
against.** `requirements.txt` intentionally uses `chromadb>=0.5.7` rather
than `==0.5.7`: version 0.5.x depends on a separate `chroma-hnswlib`
package that has no prebuilt Windows wheel and fails to compile without
MSVC, while chromadb's 1.x line dropped that dependency entirely and ships
real Windows wheels. This was found and fixed on a real Windows machine,
not just assumed - the full test suite (48 tests) and the build check pass
unmodified against chromadb 1.5.9, confirming no breaking API changes hit
this project's actual usage despite the major version jump.

```bash
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env
```

## Configuration

See `.env.example`. No API keys are required — all inference is local via
Ollama. Pull the required models before first run:

```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

## Running Locally

> TODO — add once main.py has the full API wired up.

```bash
uvicorn main:app --reload
```

## Running with Docker

```bash
cp .env.example .env    # required - docker-compose.yml expects this file to exist
docker compose up --build
docker compose exec ollama ollama pull llama3.1:8b
docker compose exec ollama ollama pull nomic-embed-text
```

Then open http://localhost:8000.

**Design note on the `data/` volume mount:** `docker-compose.yml` bind-mounts
`./data:/code/data`, which means the host's `data/` directory takes
precedence over the copy baked into the image at build time. This is
deliberate for development - it lets you edit `data/structured/*.json` or
the RAG source markdown and see the change on restart without rebuilding
the image. The `Dockerfile`'s `COPY data/ ./data` still matters for a
standalone `docker build` + `docker run` without compose (no bind mount in
that case, so the baked-in copy is what actually runs).

**Verification status, stated plainly:** this Dockerfile/compose setup has
been validated two ways without a Docker runtime available in the build
environment: (1) the exact file set the `Dockerfile`'s `COPY` instructions
bring in was replicated into a clean directory, installed into a fresh
virtualenv from `requirements.txt`, and run with `uvicorn` using the same
environment variables `docker-compose.yml` sets - `/health`, the web UI,
session creation, and `/analytics` all responded correctly. (2)
`docker-compose.yml`'s YAML was validated for correct syntax and structure.
**Neither of these is a substitute for actually running `docker compose up
--build` once** - container networking (`app` reaching `ollama` by service
name), volume mount permissions, and the real build step itself still need
a genuine Docker run before you rely on this for the demo.

## RAG Design

**Source corpus — two documents, each with its own distinct citations:**
- `data/raw/wassce_grading_and_admission_guide.md` — WAEC grading rules
  and general GTEC/University-of-Ghana admission guidance.
- `data/raw/recent_cutoff_examples_2026_2027.md` — specific, dated
  cut-off point examples for the 2026/2027 admission cycle (University of
  Ghana and KNUST), sourced from real published figures, including an
  explicit note on a real case where two sources reported different
  numbers for the same programme and cycle.

Every claim in both is traceable to a cited URL in its own YAML
frontmatter — kept as separate files specifically so one document's
citations never get attributed to the other's content (see
`docs/extending-data.md`'s guidance on this, and
`tests/test_rag.py::test_second_source_document_has_its_own_distinct_source_urls`
for the regression test proving it).

**Chunking (`app/rag/chunker.py`):** splits on markdown headings first, so a
chunk never straddles two unrelated sections (e.g. the credit-gate rule
never gets merged with the aggregate-bands table). Any section longer than
800 characters is further split with a 150-character overlap, so a fact
sitting near a chunk boundary isn't lost. Every chunk carries the
frontmatter's `source_urls` and document title forward — provenance is
attached at chunking time, not reconstructed later. On the current source
document this produces 9 chunks.

**Known limitation, stated plainly:** provenance is at document level, not
per-claim — the source doc's frontmatter lists its URLs once for the whole
file, so every chunk from it inherits the same four URLs rather than a
single URL pinned to the specific sentence it came from. Fine for one
source document; would need per-section citation metadata if more source
documents with mixed/overlapping URLs were added.

**Embedding:** `nomic-embed-text` via Ollama (see `app/llm/ollama_client.py`
`embed()`). The embedding function is always passed in as a parameter
(`embed_fn`) rather than hardcoded inside the vector store — this is what
makes `app/rag/vector_store.py` and `retriever.py` unit-testable with a
fake embedding function in `tests/test_rag.py`, without a live Ollama
server.

**Vector store:** ChromaDB, one collection (`admission_guide`), persisted to
`CHROMA_PERSIST_DIR`. `retriever.build_index()` is idempotent — it won't
re-embed and re-store everything on every app restart unless called with
`force=True`.

**Retrieval → generation flow:** the LLM decides when to retrieve via the
`retrieve_context` tool (see Tool Design) rather than retrieval running
automatically on every turn — this keeps retrieval scoped to questions that
actually need it (e.g. "what electives does Business need?") instead of
firing on turns like "my Core Maths grade is B2," which need the calculator
tool, not the guide. The system prompt instructs the model to cite the
`source_urls` a retrieval call returns, and to say explicitly when
`retrieve_context` returns no match or an error, rather than falling back to
its own unguided recollection of a cutoff or rule — this is the direct
implementation of Question 6's "must not pretend supporting evidence exists
when it cannot retrieve it."

**Unverified against the real embedding model:** everything above is
verified with a fake, deterministic embedding function in tests — that
confirms the chunking/storage/ranking *logic* works, not that
`nomic-embed-text` actually surfaces the best-matching passage for a real
student question. That check still needs to be run manually once against a
live Ollama instance before relying on this for the demo.

## Tool Design

**Available to the chat model (`app/llm/tool_schemas.py` `ALL_TOOLS`):**
- `retrieve_context` — searches the WASSCE admission guide. The model
  decides when a question is factual enough to need it (e.g. "what
  electives does Business need?"), rather than answering from memory.
- `analyze_outcomes` — deterministic cohort statistics (mean/median/trend)
  over the synthetic demonstration dataset. The model decides when a
  question is asking about aggregated/historical patterns rather than a
  single student's own numbers.
- `submit_recommendation` — the structured-output mechanism (Question 5):
  the model's final qualitative answer must be delivered through this
  tool, validated against the `Recommendation` schema, not as free text.

**Deliberately NOT available to the chat model:** `compute_aggregate` and
`check_eligibility`. These exist as real, tested functions
(`app/tools/aggregate_calculator.py`, `app/tools/eligibility_checker.py`)
and are used directly by the `/calculate` endpoint with zero LLM
involvement - but are not offered to the chat model as tools. This was a
late, evidence-driven decision: extracting six fields (three core grades,
three elective subject/grade pairs) from free-text conversation via
agentic tool-calling failed in four different ways across two different
local models during live testing (see `docs/evaluation.md` Failure 6 for
the full account) - fabricated results, stuck loops, faked tool-call JSON,
and the model asking the user to type pre-formatted dict syntax instead of
parsing it. Rather than keep patching new failure shapes, the task was
moved entirely to a deterministic form (the "Enter My Grades" button),
consistent with the course's own stated principle that deterministic tasks
belong in code, not LLM judgment.

## Evaluation Approach

See [docs/evaluation.md](docs/evaluation.md) for the full 15-case evaluation
set (9 automated, 6 requiring a live Ollama run + human judgment) and the
writeup of eight real failures caught during development and live use — a
false-positive eligibility bug, a silent-blank-reply bug on tool-hop
exhaustion, the small model fabricating programme category names in a live
chat, the model getting stuck re-asking for grades it already had, the
model faking an entire tool call in plain text with no real computation
behind it, the architectural decision to remove structured grade
extraction from chat's tools entirely after it failed in four different
ways across two different models, the model fabricating school names
attributed to a tool that never returns them, and the calculator and chat
never sharing any context at all — with how each was found and addressed.

Run the automated half:
```
python scripts/run_eval.py
```

## Known Limitations

- Programme cutoff data is a mix: `approximate_band` entries are general
  guidance ranges, while `verified_examples` entries (see
  `data/structured/programmes.json` and
  `data/raw/recent_cutoff_examples_2026_2027.md`) are real, dated,
  specifically-cited figures from the 2026/2027 admission cycle — but
  still secondary-source reporting on university-published numbers, not a
  live CSSPS/university feed, and real sources were found to disagree by
  a point even for the same programme and cycle. Neither kind is a
  guarantee for a future cycle.
- Question 9's cohort dataset (`data/structured/historical_student_outcomes.csv`)
  remains fully synthetic — real per-student historical admissions records
  (who actually applied, their actual aggregate, whether they were
  actually admitted) are not published anywhere publicly, for any
  Ghanaian university, and no amount of searching changes that. This is a
  genuine data-availability limit, not an oversight; see
  `docs/extending-data.md`'s "Adding real per-school data" section.
- Scope is WASSCE→tertiary guidance only; BECE→SHS placement (CSSPS) was
  deliberately excluded for this build (see architecture.md scoping note).
- Structured-output validation failures (from `submit_recommendation`) are
  still possible with any locally-runnable model and are handled via one
  repair retry, then a deterministic fallback.
- Chat cannot calculate a student's aggregate or check eligibility - this
  was tried via agentic tool-calling and failed in four different ways
  across two models during live testing (see `docs/evaluation.md` Failure
  6); the "Enter My Grades" button is the only path to an exact result.

## Future Improvements

See [docs/extending-data.md](docs/extending-data.md) for a concrete,
step-by-step guide to adding programme categories, RAG source content, and
(as a larger, properly-scoped undertaking) real per-school data.

- Extend to BECE→SHS (CSSPS) placement guidance.
- Replace illustrative programme bands with a real, versioned cutoff dataset
  per admission cycle.
- Add a feedback mechanism for guidance counsellors to flag incorrect
  recommendations.
- Build a real per-school dataset with sourced, school-specific cutoffs
  (see docs/extending-data.md's "Adding real per-school data" section for
  why this is scoped out as a research task, not a quick coding addition).
