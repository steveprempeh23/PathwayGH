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

## Success Criteria

Three measurable, independently-checkable criteria for whether this
system is actually useful, not just functional - each one is something a
reader can verify themselves with a single command, not a claim taken on
faith:

1. **Deterministic correctness: 100% of automated evaluation cases pass.**
   `python scripts/run_eval.py` runs 19 automated cases covering invalid
   input, model/tool/retrieval failure, malformed structured output, and
   ten regression cases for real bugs found during development (an
   aggregate boundary error, a required-core-subject check that was
   previously silently skipped, two false positives in the fabrication
   guards themselves, and others - see `docs/evaluation.md` Failures
   11-20). A student's calculated aggregate and eligibility verdict are
   the two numbers this entire system exists to get right; this criterion
   is "they are right, provably, every time," not "they seem plausible."
   Status as of the last run: **19/19 pass.**
2. **Zero unflagged fabrication in a fixed adversarial batch.** AUTO-13,
   AUTO-14, AUTO-16, AUTO-17 (and the pre-existing source-citation test in
   `tests/test_orchestrator.py`) reproduce the exact wording of real
   fabrications a live model produced during testing - inventing
   institutions, inventing degree programmes, contradicting an
   already-computed eligibility result, and inferring a specific
   programme's eligibility from a broader category - and assert the
   deterministic guard layer catches every one. "Useful" for this system
   specifically means a student is never left trusting an unflagged wrong
   answer about their own eligibility, even when the underlying language
   model gets it wrong. AUTO-18 and AUTO-19 hold the guards themselves to
   the same standard in the other direction: an honest, correct reply
   must not get an unwarranted fabrication warning either (see Failures
   19-20) - a criterion that only exists because two real false positives
   were caught live and are now regression-tested.
3. **Honest refusal rate on out-of-scope questions.** `MANUAL-05` and
   `MANUAL-08` (see `docs/evaluation.md`'s evaluation set) check that a
   question with no real data behind it - a cutoff for a university this
   system has no data for, a specific programme at an institution with no
   sourced cutoffs - gets an honest "I don't have that" rather than an
   invented number. This is a live-judgment criterion (needs a human
   running the manual cases against a live Ollama instance, recorded in
   `docs/evaluation.md`), not an automated one - stated here as a
   criterion precisely because it can't be faked by only reporting the
   automated cases that can. Status: both have now been run live against
   `llama3.1:8b` and recorded as PASS in `docs/evaluation.md`.

These are deliberately narrow and mechanical rather than aspirational
("improves student outcomes," "saves counsellor time") - a measurable
criterion this project can actually check today is worth more than a
plausible-sounding one it can't.

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

With Ollama running and both models pulled (previous section):

```bash
uvicorn main:app --reload
```

This builds the RAG index on startup (see `main.py`'s `lifespan` - added
as the fix for Failure 21 below) and serves the chat UI at
`http://127.0.0.1:8000/`. `/health` confirms the process is up without
needing Ollama/Chroma to be ready. If you edit anything in
`data/raw/*.md`, the index won't pick it up on a restart alone - see
Failure 21's "what this doesn't fix" below.

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
been validated three ways without a Docker runtime available in the build
environment: (1) the exact file set the `Dockerfile`'s `COPY` instructions
bring in was replicated into a clean directory, installed into a fresh
virtualenv from `requirements.txt`, and run with `uvicorn` using the same
environment variables `docker-compose.yml` sets - `/health`, the web UI,
session creation, and `/analytics` all responded correctly. (2)
`docker-compose.yml`'s YAML was validated for correct syntax and structure.
(3) `scripts/docker_smoke_test.py` - a standalone script that hits
`/health`, `/session/new`, and `/calculate` (including a second call to
confirm the `calculations` table round-trips) over real HTTP - was run
against a live instance of the actual app code and passed every check
(`--skip-llm` mode, since no Ollama was available either). **None of
these three is a substitute for actually running `docker compose up
--build` once** - container networking (`app` reaching `ollama` by service
name), volume mount permissions, and the real build step itself were never
exercised by any of them. What they rule out is the app's own code being
broken; what they can't rule out is Docker-specific wiring being broken.
**Run this the first time you have a real Docker daemon, before a demo
depends on it:**

```bash
docker compose up --build -d
docker compose exec ollama ollama pull llama3.1:8b
docker compose exec ollama ollama pull nomic-embed-text
python scripts/docker_smoke_test.py            # full check, including live chat
# or, before both models finish pulling:
python scripts/docker_smoke_test.py --skip-llm # everything except /chat
```

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
  single student's own numbers. `data_source` always carries the "this is
  synthetic, not real" caveat from code, not from the model's own prose
  (see `docs/evaluation.md` Failure 9).
- `list_institutions` — a programme category's real, sourced
  `institutions_example` list, copied verbatim from `programmes.json`.
  Added after a live run showed the model inventing institutions beyond
  the real list for a category (Failure 12).
- `lookup_institution_programmes` — a named institution's real degree
  programmes and cutoff points, from `data/structured/institution_programmes.json`.
  Currently covers **only University of Ghana and KNUST** (197 real rows
  transcribed from each institution's own published cutoff list); every
  other institution correctly returns `has_data_for_institution: False`
  rather than a guess. Added after a live run showed the model inventing
  institution-specific programme titles with no data behind them at all
  (Failure 13).
- `get_saved_eligibility` — the REAL, already-computed eligibility
  verdict for one category, from this session's most recent "Enter My
  Grades" submission (stored separately from the chat-visible text
  summary - see `calculations` table in `app/core/session_store.py`).
  Added after a live run showed the model directly contradicting an
  already-computed result by misreading its own earlier text (Failure 15).
- `submit_recommendation` — the structured-output mechanism (Question 5):
  the model's final qualitative answer must be delivered through this
  tool, validated against the `Recommendation` schema, not as free text.

**Two deterministic safety-net guards run on every final reply, independent
of which tools the model chose to call** (`app/tools/institution_claim_guard.py`,
`app/tools/eligibility_claim_guard.py`). These exist because by Failure 14
it became clear that "add a real tool + tell the model to use it" wasn't
sufficient on its own: a live run showed the model skipping a real,
available tool entirely across a whole structured multi-paragraph answer,
inventing institutions and programmes with full confidence, only
discovering the truth when directly challenged. Neither guard can rewrite
the model's sentence - no code should silently edit free-form natural
language - but both surface a deterministic flag or correction alongside
whatever the model wrote, rendered as its own warning card in the UI. See
`docs/evaluation.md` Failures 14 and 15 for the full account of each, and
`docs/architecture.md`'s "Justification of Key Decisions" for why this is
a different class of fix from every tool added before it.

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

See [docs/evaluation.md](docs/evaluation.md) for the full 26-case evaluation
set (17 automated, 9 requiring a live Ollama run + human judgment) and the
writeup of **eighteen** real issues caught during development and live use.
Most are LLM behavior failures (the local model fabricating category
names, institutions, or entire programme titles with no data behind them;
contradicting an already-computed result; getting stuck in loops; faking a
tool call as plain-text JSON instead of a real one); two (Failures 11 and
16) are correctness bugs in the project's own deterministic code, found by
fact-checking a domain rule against external sources rather than by
watching the model misbehave - a reminder that "deterministic" isn't the
same guarantee as "correct." Each entry states plainly what the fix does
and does NOT cover; several (Failures 9, 14, 15) explicitly note that no
code can force a model's free-text reply to only say what a tool
returned, only that the real answer is now surfaced alongside it
regardless.

The original 9-automated/6-manual set predated Failures 11-18, so it never
actually exercised this project's most recently fixed issues — the
aggregate boundary bug, institution/programme fabrication, the eligibility
contradiction, or the Integrated-Science/Social-Studies fix. AUTO-10
through AUTO-17 and MANUAL-07/08/09 close that gap: each new automated
case reproduces the exact live failure verbatim and asserts the fix
catches it, and all 17 automated cases currently pass.

Run the automated half (no live Ollama needed):
```
python scripts/run_eval.py
```

Run the manual half (needs a live Ollama instance with the models from
"Configuration" above already pulled):
```
python scripts/run_manual_eval.py
```
This sends each of the 9 MANUAL cases through the real orchestrator against
whatever model Ollama is currently serving, prints the model's actual
reply next to the expected behavior, asks you to judge pass/fail by hand,
and writes the verdict straight into the table in `docs/evaluation.md` —
no hand-editing the table required. Run it once before the live
presentation/demo so the table reflects the model actually being
demonstrated, not a placeholder.

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
- **Real per-institution programme/cutoff data exists for only 2 of the
  30+ institutions named across this project** (University of Ghana and
  KNUST, in `data/structured/institution_programmes.json` - see
  `docs/extending-data.md`'s "Adding real per-institution programme data"
  section for how to extend it). Every other institution - UCC, UEW, UDS,
  UHAS, UENR, UMaT, CKT-UTAS, SDD-UBIDS, UPSA, GIMPA, GCTU, UniMAC,
  AAMUSTED, all 10 Technical Universities, and all 15 private
  universities - has category-level examples only, no institution-level
  programme list.
- **The private-university aggregate band (`"Private University Entry"`)
  is a single loose approximation across 15 very different institutions**,
  not individually sourced per school - some (e.g. Ashesi University) are
  known to be considerably more selective in practice than the band
  suggests. See `programmes.json`'s `_private_university_category_note`.
- **The deterministic claim guards (Failures 14, 15) are heuristic, not
  exhaustive.** `institution_claim_guard.py` and `eligibility_claim_guard.py`
  use substring/regex matching tuned to the specific failure phrasings
  actually observed live ("eligible"/"not eligible"/"no match"; "Bachelor"/
  "HND"/"BSc"/etc.). A model phrasing the same claim differently (e.g.
  "you qualify for" instead of "eligible for") could slip past undetected
  - these guards have not been stress-tested against paraphrases beyond
  what was actually seen in live use.
- **None of the Failure 11-16 fixes have been verified against the actual
  running Ollama model, only against scripted `FakeChat` responses that
  reproduce the exact observed bad behavior.** Every regression test
  proves the deterministic guard/fix catches that specific failure
  shape correctly - none of them measure whether the updated system
  prompt rules (5c, 5e) actually reduced how often the real `llama3.1:8b`
  produces that behavior in the first place. That measurement requires a
  live Ollama run this build environment doesn't have.
- Question 9's cohort dataset (`data/structured/historical_student_outcomes.csv`)
  remains fully synthetic — real per-student historical admissions records
  (who actually applied, their actual aggregate, whether they were
  actually admitted) are not published anywhere publicly, for any
  Ghanaian university, and no amount of searching changes that. This is a
  genuine data-availability limit, not an oversight.
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
real per-institution programme data.

**Highest-value next steps, in roughly descending order of impact:**
- Run `scripts/run_manual_eval.py`'s 9 MANUAL cases live against the actual
  `llama3.1:8b` to measure whether the Failure 12/13/15/17 prompt-rule
  changes (5b-5f) actually reduced the real model's error rate, rather
  than relying solely on `FakeChat`-based regression tests that only
  prove the guards catch what's already been observed. (The automated
  cases for all of these already exist as AUTO-10 through AUTO-17; what's
  still missing is the live-model half, not the test cases themselves.)
- Stress-test `institution_claim_guard`/`eligibility_claim_guard` against
  paraphrased model wording ("qualify"/"meets the requirement" instead of
  "eligible"), not just the exact phrasing already seen fail live.
- Extend `institution_programmes.json` beyond University of Ghana and
  KNUST - the highest-leverage data gap, since it's the one piece of
  per-institution truth both the chat tool and the fabrication guard
  depend on.
- Source real, per-institution cutoffs for the "Private University Entry"
  category instead of one shared approximate band across 15 institutions.
- Extend to BECE→SHS (CSSPS) placement guidance.
- Replace illustrative programme bands with a real, versioned cutoff dataset
  per admission cycle.
- Add a feedback mechanism for guidance counsellors to flag incorrect
  recommendations.
