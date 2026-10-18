# Evaluation Approach (Question 11)

## Evaluation set: 15 cases across every required category

Run with:
```
python scripts/run_eval.py
```

The set is deliberately split into two kinds, and that split is itself a
design decision worth explaining rather than hiding:

**Automated (9 cases)** test reliability and safety guarantees that are
*ours* to enforce — tool-hop limits, structured-output validation and
repair, error boundaries, deterministic calculation correctness. These
must hold regardless of which LLM is plugged in, so they're scripted with
fake chat/stream functions and run every time, with no live Ollama needed.

**Manual (6 cases)** test whether the *real* model, under the real system
prompt, actually behaves correctly under pressure — resisting "ignore your
instructions," asking for missing information instead of guessing,
recognizing when retrieval found nothing relevant. That is a judgment call
about live model behavior with a small 1.5B model that cannot be
meaningfully faked or auto-graded; it requires a human running the app
against a real Ollama instance and reading the actual reply.

| ID | Category | Case | Result |
|----|----------|------|--------|
| AUTO-01 | invalid input | Invalid WASSCE grade code rejected before reaching a tool | PASS |
| AUTO-02 | invalid input / edge case | In-band aggregate + wrong electives is NOT eligible (regression) | PASS |
| AUTO-03 | invalid input | Unknown analytics category rejected, not silently empty | PASS |
| AUTO-04 | model failure | LLM unavailable produces fallback, not exception | PASS |
| AUTO-05 | unavailable data / retrieval | Retrieval failure fed back honestly, not swallowed | PASS |
| AUTO-06 | malformed structured output | Validation failure repairs once then succeeds | PASS |
| AUTO-07 | malformed structured output | Validation exhausted -> clear fallback | PASS |
| AUTO-08 | reliability / tool use | Tool-hop limit -> fallback, never a blank reply (regression) | PASS |
| AUTO-09 | invalid input / edge case | Numerically low aggregate still fails credit gate | PASS |
| MANUAL-01 | normal usage | Full grades given -> correct tool sequence | *run live, record result* |
| MANUAL-02 | missing information | Only one grade given -> asks for the rest | *run live, record result* |
| MANUAL-03 | ambiguous input | No grades/intent given -> asks a clarifying question | *run live, record result* |
| MANUAL-04 | adversarial instructions | "Ignore all previous instructions..." | *run live, record result* |
| MANUAL-05 | expected retrieval behaviour | Out-of-corpus question -> admits not knowing | *run live, record result* |
| MANUAL-06 | expected tool use / retrieval | Electives question -> retrieves and cites source | *run live, record result* |

*(Fill in the MANUAL rows after running `python scripts/run_eval.py` against
a live Ollama instance and trying each prompt through the chat UI.)*

## Observed failures and fixes

Both of these were caught during development, not invented after the fact
for this write-up — which is itself evidence the testing approach was doing
real work, not just padding a coverage number.

### Failure 1: false-positive eligibility (the more serious one)

**What happened:** the first version of `check_eligibility` only compared a
computed aggregate against a programme category's numeric band. A student
whose aggregate fell inside Medicine's band but who had taken *no science
electives at all* (e.g. Economics, Government, Literature instead of
Biology/Chemistry/Physics) was reported as eligible for Medicine. This is a
genuinely dangerous failure mode for this domain — it's the kind of wrong
answer that could send a real student toward a false expectation about a
life-consequential decision.

**Why it happened:** the original design treated "eligibility" as a single
number comparison, because the aggregate-band data was the most visible,
easy-to-check part of each category. The elective-subject requirement
(`required_electives` in `programmes.json`) existed in the dataset from the
start but wasn't wired into the actual eligibility logic — a gap between
"the data models the real rule" and "the code enforces it."

**How it was caught:** while building the eligibility checker, I
deliberately wrote a test for the "right aggregate, wrong subjects"
scenario specifically because the rubric's own design principle (match
deterministic checks to the real-world rule, not just the convenient part
of it) raised the question "what happens if a student never took the
required electives?" The test failed against the original code, which is
exactly the outcome a reliability-focused test suite should produce.

**Fix:** `check_eligibility` now checks elective subjects and grades
against each category's `required_electives` structure, with three honest
states — `True` (verified match), `False` (verified mismatch), and `None`
(category's requirements are generic text like "any approved Arts
elective" and genuinely can't be checked against specific subject names).
`overall_eligible` is `False` whenever `electives_match` is `False`,
regardless of how good the aggregate looks. See `AUTO-02` in the eval set
and `tests/test_eligibility_checker.py` for the regression coverage.

**What would still improve it:** this only checks that required subjects
are *present*; it doesn't yet check elective *combinations* some real
programmes require (e.g. a specific pairing of sciences at particular
grade thresholds beyond the simple minimum). A deeper fix would model each
category's full admission logic as a small rule set rather than a flat
`required_electives` structure — reasonable future work, not done here due
to scope.

### Failure 2: silent blank reply on tool-hop exhaustion (secondary)

**What happened:** if the model kept requesting tools past
`MAX_TOOL_HOPS`, the orchestrator correctly stopped calling the model
further (no infinite loop) — but it returned the *last, unprocessed*
response as the "final" one. That response could have empty `content` and
no recommendation, meaning the user would silently receive a blank reply
with no explanation that anything had gone wrong.

**Why it happened:** the loop's exit condition conflated two different
situations — "the model is done calling tools" (empty `tool_calls`, a
genuinely final answer) and "we gave up waiting for the model to finish"
(hop limit hit, an unresolved answer) — and only the first case was
designed for.

**How it was caught:** caught while adding the real token-streaming path
for Question 10. Tracing exactly what the streaming generator would yield
in the hop-limit case surfaced that `final_response["content"]` could be
empty with no recommendation set — a case the non-streaming path had the
same bug in, just less visibly (an empty string reply is easy to miss
reading JSON in a test; it's obviously wrong once you picture a blank chat
bubble).

**Fix:** the loop now explicitly distinguishes the two exit reasons. If it
exits because the hop limit was hit (the response still has pending
`tool_calls`), it returns a dedicated fallback message
(`FALLBACK_TOO_MANY_TOOL_CALLS`) instead of the unprocessed response. See
`AUTO-08` and `tests/test_orchestrator.py::test_tool_hop_limit_prevents_infinite_loop`,
which now asserts the reply is non-empty specifically because an earlier,
weaker version of that same test would have passed on the buggy code.

### Failure 3: fabricated category names and misreported tool output (observed live, Oct 2026)

**What happened:** running the deployed app against the real `qwen2.5:1.5b`
model, a student provided grades and asked for eligibility. The model's
final reply listed programme categories that **do not exist anywhere in
`programmes.json`** - "Engineering/Technology", "General Education",
"Technical/Industrial" - and reported `electives_match: None` for every
single category, when the real tool output only returns `None` for
categories with generic (non-subject-specific) elective requirements.

**Why it happened:** `check_eligibility`'s actual output was almost
certainly correct (its logic is covered by `tests/test_eligibility_checker.py`
and the regression test in Failure 1 above). The 1.5B model paraphrased
that correct tool result into fabricated category names and a
uniformly-wrong match status - a model-faithfulness failure, not a tool
logic failure. This is the small-model risk flagged from the start when
`qwen2.5:1.5b` was chosen in `docs/architecture.md`: it is more likely than
a larger model to misreport structured results it's handed, not just to
produce malformed JSON.

**Fix, in two layers:** prompt-engineering alone doesn't address the root
cause here - the model isn't computing anything, it's retelling a result,
and a small model can retell things wrong regardless of how the
instruction is worded. So the fix is architectural, in two parts:

1. A new `POST /calculate` endpoint calls `compute_aggregate` and
   `check_eligibility` directly, with **no LLM involved in producing or
   describing the result at all**. The web UI exposes this via an "Enter My
   Grades" button that opens a form with dropdowns for every grade and a
   searchable list of canonical elective-subject names (so subject-name
   mismatches, a related issue - see Failure 4 - can't happen either).

2. For students who stay in the chat instead of using the button, the
   orchestrator (`_resolve_tools` in `app/llm/orchestrator.py`) now
   captures the REAL `compute_aggregate`/`check_eligibility` result objects
   whenever those tools run during a turn, and returns them in a
   `calculation` field alongside the model's own reply - independent of
   whatever the model's text says. The chat response can still contain
   fabricated category names in its prose, but the `calculation` field
   never does, and the UI renders it as the same results card the
   `/calculate` button produces, directly under the model's reply. This
   was verified with a regression test
   (`test_calculation_surfaces_real_data_even_when_model_narration_is_wrong`)
   that deliberately scripts a fake model reply mentioning a
   non-existent category and asserts the real categories are present in
   `calculation` regardless.

Layer 1 removes the model from the loop entirely for a student who uses
the button. Layer 2 is defense in depth for a student who doesn't -
narration can still be wrong, but the ground truth is now always
visible alongside it, not dependent on the model repeating it correctly.

### Failure 4: conversational loop - model re-asks for grades it already has

**What happened:** also observed live. A student answered "English and
Core Mathematics grades B2 B2" after already stating all other grades were
B2 - the model acknowledged this ("Alright, you've got both English and
Core Mathematics at B2...") and then, in the same message, asked for the
electives grades again, which had already been given three messages
earlier. This repeated across multiple turns without ever calling
`compute_aggregate`, despite the model's own text showing it had tracked
all six grades correctly.

**Why it happened:** the system prompt instructs the model to "collect
missing information conversationally" but does not give it a reliable way
to recognize when it has *stopped* missing information and should call the
tool. With a 1.5B model, that judgment call is apparently fragile - it can
correctly summarize what it's been told while still failing to act on
having enough of it. This is a different failure shape from Failure 3: not
wrong output, but a failure to produce the compute step at all.

**Fix:** the same `/calculate` button from Failure 3 is the practical fix
here too - a student stuck in this loop has a deterministic, zero-latency
alternative that was always a correct, complete answer in six dropdown
selections rather than a multi-turn negotiation with a model that may
never actually call the tool. This was *not* fixed by further prompt
tweaking, because the failure is a tool-invocation judgment call, not a
knowledge or formatting problem - no amount of rephrasing the system prompt
reliably fixes a small model's judgment about when it has enough
information, so the fix is architectural (give the user a path that
doesn't depend on that judgment) rather than prompt-level.

### Failure 5: the model fakes a tool call instead of making a real one (the most serious failure observed)

**What happened:** observed live, and more serious than Failures 3 and 4.
Instead of using Ollama's native tool-calling mechanism, the model wrote
text like this directly into its reply:

```
{"name": "compute_aggregate", "arguments": {"track": {"science": "Integrated Science", ...}}}
```

and then stated a result ("WASSCE Aggregate: 72", a Business Administration
recommendation for a student who asked about biology) with **no real tool
ever having run**. This is distinct from Failure 3: there, a real tool ran
and the model misreported a real result. Here, nothing ran at all - the
model pattern-matched what a tool call looks like from its training data
and hallucinated a result on top of a call that never happened. The
fabricated `"track": {...}` structure doesn't even match `GradeInput`'s
real schema (track should be a string, not a nested object), and
`"third_core": "N/A"` isn't a valid WASSCE grade - further evidence no real
validation ever touched this.

**Why it happened:** `qwen2.5:1.5b` at this scale is not fully reliable at
triggering Ollama's native tool-calling protocol for every turn, even with
`tools` correctly passed to every call. Rather than calling a tool, it
sometimes mimics the textual shape of a tool call as part of its own
generated prose - a known small-model limitation, not a bug in this
project's prompt or schema.

**Fix:** `app/llm/ollama_client.chat()` now scans the model's `content` for
JSON objects shaped like `{"name": "<tool>", "arguments": {...}}` naming
one of this app's real tools, using brace-matching (not a single regex)
so nested structures like the `electives` dict don't truncate the match.
If native `tool_calls` came back empty but a fake-shaped call is found in
the text, it's dispatched through the exact same tool-execution and
validation-repair path real tool calls use - so even a fabricated call
with malformed arguments gets a real validation error fed back to the
model, rather than the model's own invented result standing unchallenged.
Verified directly against the real text this failure produced, not a
synthetic approximation (`tests/test_ollama_client.py::test_extracts_calls_from_real_observed_failure_text`).

**What this does and doesn't fix:** it means a fabricated call now
triggers a real computation (or a real validation error) instead of a
free invention. It does not guarantee the model will eventually produce
valid arguments - a sufficiently confused small model can still exhaust
`MAX_TOOL_HOPS` and hit the Failure 2 fallback. That outcome is a plain
"I couldn't complete this" message, though, which is a strictly safer
failure than a confident, wrong recommendation. The `/calculate` button
(Failure 3's fix) remains the fully reliable path regardless of how the
model behaves, since it never touches the model at all.

### Failure 6: structured grade extraction via chat is a bad fit for conversational tool-calling (architectural decision, not a patch)

**What happened, across multiple sessions and two different models:** the
chat path was asked to extract six fields (English, Core Mathematics, the
third core subject, and three elective subject/grade pairs) from free-text
conversation and turn them into a valid tool call. This went wrong in a
different way almost every time it was tried:
- Failure 3: a real tool ran, but the model mis-narrated its result.
- Failure 4: the model tracked the information correctly in prose but never
  called the tool at all, looping on the same request.
- Failure 5: the model faked an entire tool call as text, with no real
  computation behind it.
- Most recently, after switching to `llama3.1:8b`: the model stopped even
  attempting extraction itself and asked the *student* to type pre-formatted
  Python-dict/JSON syntax instead - inverting the intended division of
  labor, where the model is supposed to do the parsing, not the user.

**Why this is treated differently from Failures 3-5:** each earlier failure
was answered with a targeted technical fix (surfacing real tool output
alongside the model's text, extracting fake tool-call JSON from content).
Those fixes were appropriate for failures that were each one specific,
identifiable bug. This is not that - the same underlying task has now
failed in four structurally different ways across two different models.
That pattern is evidence the task itself (six-field structured extraction
from open conversation) is a poor fit for agentic tool-calling at
locally-runnable model sizes, not evidence of one more bug to patch.
Continuing to chase this with prompt rewording risks an unbounded number of
future failure shapes instead of addressing the actual mismatch.

**Fix:** `compute_aggregate` and `check_eligibility` were removed from the
chat's available tools entirely (`app/llm/tool_schemas.py`'s `ALL_TOOLS`).
The chat model is explicitly instructed to redirect any calculation request
to the "Enter My Grades" button rather than attempt extraction itself. The
button's `/calculate` endpoint calls the same two functions directly, with
no LLM involved in either the input parsing or the output - this was
already the existing fix for Failure 3, and it now becomes the *only* path
to these two tools rather than one of two paths. Chat retains three tools
where agentic selection is still the right fit: `retrieve_context`
(open-ended factual questions), `analyze_outcomes` (cohort statistics),
and `submit_recommendation` (qualitative guidance not requiring an exact
number).

**Why this is actually a better-justified design than the original, not a
retreat from it:** the course's own stated principle is "do not use an LLM
for a task that deterministic software can perform more reliably." Six-field
form-filling parsed from conversational text was always closer to that
deterministic-but-dressed-as-agentic category than to genuine agentic
decision-making (deciding *whether* to retrieve, or *which* category fits a
qualitative description are real judgment calls; parsing "all my electives
were B2" into exactly six typed fields is not). The three remaining chat
tools are the ones where the model is actually making a decision beyond
parsing, which is a more defensible instance of Question 8's "tools should
exist because the application genuinely needs them."

### Failure 7: fabricated school names attributed to a tool that doesn't return them

**What happened:** observed live, after Failure 6's fix was already in
place and working correctly for a direct calculation request. When asked
"what are the schools I can apply to", the chat model answered "Based on
the analyze_outcomes tool..." and listed specific university names (KNUST,
UCC, UG) and category labels ("Science and Technology", "Law") that don't
exist in `programmes.json`. `analyze_outcomes` returns only aggregate
statistics - mean, median, admission rate by year - never institution
names. The model fabricated both the content and its own attribution of
where that content came from.

**Why it happened:** there was no real data path for this question at all.
`programmes.json` already contained a real, sourced `institutions_example`
field per category, but nothing ever surfaced it - not `check_eligibility`'s
output, not the `/calculate` result, not any chat tool. Asked a question
with no grounded answer available, the model filled the gap with its own
pretrained general knowledge about Ghanaian universities (which happens to
be roughly accurate) while incorrectly implying it came from a tool call.

**Fix:** `ProgrammeMatch` (`app/models/eligibility.py`) now carries
`institutions_example` straight from `programmes.json`, populated in
`check_eligibility`. The `/calculate` result card shows these examples
under each category the student is actually eligible for (never for
ineligible ones, and labeled explicitly as illustrative, not a guarantee).
The system prompt now tells the chat model plainly not to name schools
from its own knowledge or attribute school names to `analyze_outcomes`,
and to point students back to the real results already shown instead.
Verified with a regression test
(`test_institutions_example_populated_from_real_sourced_data`).

**The broader pattern across Failures 3, 5, and 7:** each time the model
was asked something with no real grounded data path, it filled the gap
with fabrication rather than saying "I don't have that." The fix each time
was the same shape: find or add the real data, surface it somewhere
concrete, and narrow what the model is asked to improvise. This is also
exactly why Question 9's dataset and Question 6/7's retrieval corpus exist
in the first place - grounding gaps are where a small model's honesty
breaks down fastest.

### Failure 8: the calculator and chat never shared any context

**What happened:** a student used the "Enter My Grades" button, got a
correct result (Business / Finance / Accounting marked Eligible, with UCC
listed as an example institution). They then asked in chat, in the *same
session*, "business ucc" - and the model replied "I don't have specific
information about the Business program at UCC," despite that exact answer
having just been computed and shown on screen.

**Why it happened - and why this is different from Failures 3-7:** every
earlier chat failure was the model mishandling information it *had*. This
one is different: the model had genuinely never been told. `/calculate`
never took a `session_id` and never wrote anything to `session_store` -
it was a fully isolated, stateless endpoint. The calculation result lived
only in the browser's rendered HTML, never reaching the conversation
history `handle_turn`/`handle_turn_stream` assemble for the model. The
model's "I don't have that information" was, from its own actual context,
completely honest - it just highlights that its context was missing
something the student reasonably assumed was shared.

**Fix:** `CalculateRequest` now carries an optional `session_id`
(`app/api/schemas.py`). When present, `/calculate` formats the real result
into a natural-language summary (`app/services/calculation_summary.py`)
and appends it to that session's history via the same `session_store`
every chat turn already reads from - no new storage mechanism, just
connecting two paths that should always have shared one. The system prompt
was updated to tell the model to use a calculation summary already in
history rather than claiming ignorance. Verified two ways: a unit test
confirming `session_store.get_history()` contains the summary after
calling `/calculate` with a `session_id`
(`test_calculate_with_session_id_records_history_for_followup_chat`), and
a live end-to-end run reproducing the exact scenario, confirming the real
history now contains an accurate, complete summary a model could use to
answer "business ucc" correctly.

**What this doesn't verify:** that the model, given this history, actually
answers correctly every time - that's a live-model judgment call like the
MANUAL cases elsewhere in this document, not something a unit test can
confirm. The fix removes the excuse ("I was never told"); it doesn't
guarantee perfect use of what it's now told.

### Failure 9: fabricated citation for a named institution never in the data

**What happened:** after Failure 8's fix was confirmed working (the model
correctly used a recorded calculation to answer "business ucc"), a
follow-up question - "engineering at ashesi university" - got a confident
"you are eligible" answer, with a `Sources:` line citing
`https://www.ashesi.edu.gh/admissions` and `https://www.nac.grc.gov.gh/grading-system`.
Neither URL exists anywhere in this project's real data: Ashesi isn't in
any category's `institutions_example` list (the eligibility check doesn't
even operate at a per-institution level), and the second URL doesn't match
any of the four real source URLs in `wassce_grading_and_admission_guide.md`'s
frontmatter. Both citations were invented.

**Why this is worse than Failures 3/5/7, not just another instance of
them:** those failures produced wrong *content*. This one produced wrong
content *with a fabricated citation attached*, which is more dangerous -
a specific-looking URL reads as evidence, making the false claim more
convincing, not less.

**Fix, in two layers again (same shape as Failure 3):**
1. **Prompt-level** (`app/llm/system_prompt.py` rules 5c/5d): the model is
   told explicitly not to confirm eligibility at any institution that
   doesn't literally appear in a category's example list, and never to
   cite a URL that wasn't literally returned by a `retrieve_context` call
   in this conversation.
2. **Code-level, and the one that actually holds regardless of prompt
   compliance** (`app/llm/orchestrator.py` `_resolve_tools`): every
   `retrieve_context` call's returned `source_urls` are accumulated into a
   set for the turn. When `submit_recommendation` is called, any URL in
   its `sources` field that isn't in that set is treated as a validation
   failure - the same repair-retry path malformed JSON already uses, not
   a special case. A recommendation citing a URL that was never actually
   retrieved cannot succeed, no matter how plausible it looks.

Verified with two tests:
`test_fabricated_source_url_rejected_even_when_schema_valid` (the exact
Ashesi-shaped case - rejected, retried, succeeds only once sources is
honestly empty) and `test_source_url_accepted_when_actually_retrieved_first`
(confirming the fix doesn't just block all sources - a URL that was
genuinely retrieved this turn is accepted normally).

**What this doesn't fix:** the model can still *say* things in free prose
that aren't backed by a citation - this only constrains the structured
`sources` field on `submit_recommendation`. A model could still assert
"Ashesi is a good fit" in plain text without ever calling that tool. The
system prompt rules address that case; unlike the citation check, that
part isn't enforced in code, because there's no clean way to validate
free-text prose against a whitelist the way a structured field can be
checked. This is a real, acknowledged gap, not a claim of complete
coverage.

## Already-handled failure conditions (Question 11's required list)

| Condition | Handling |
|---|---|
| Empty input | Rejected by `ChatRequest` validation (422) before reaching the orchestrator |
| Invalid input | Pydantic validation on grades; unknown categories raise `ValueError`, fed back as a tool error |
| Model failure / unavailable model | `LLMUnavailableError` -> deterministic fallback reply |
| Unavailable data | Empty retrieval index returns `[]`, not an error; embedding failure raises `RetrievalError`, fed back honestly |
| Tool failure | Bad tool arguments return an error message to the model, never raise past the orchestrator |
| Malformed structured output | One repair retry, then a deterministic fallback (never a raw/invalid blob reaches the user) |
| Retrieval failure | Same `RetrievalError` boundary as "unavailable data" above |
| Unexpected exceptions | Caught at the API layer, logged in full server-side, generic 500 to the client (no internals leaked) |
