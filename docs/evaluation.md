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

### Failure 10: synthetic-data caveat dropped from cohort-statistics answers (observed live, Oct 2026)

**What happened:** a student asked for schools offering Physician
Assistantship and "what percentage I have of getting admission." No
`institutions_example` entry existed yet for that programme at the time,
and the model called `analyze_outcomes` with an unrelated category ("Open
Public-University Entry") rather than saying it had no matching data. It
then answered: *"the admission rate for the category... is 61.4%"* - with
no mention anywhere in the reply that the underlying dataset is synthetic
demonstration data, not real admissions records. `system_prompt.py` rule 5
requires that caveat "every time, not just the first" - the model simply
didn't include it this turn.

**Why this is the same failure shape as Failure 3, applied to a different
tool:** `analyze_outcomes`'s real result (`CohortStats.data_source`) always
*contains* the correct caveat - the tool was never the problem. The
failure is identical to Failure 3's: the model's own retelling of a
correct tool result silently dropped the one piece of it that mattered
most for the student not to be misled, and nothing forced it back in.
A bare, confident-sounding "61.4%" is also a worse failure than an
obviously-wrong number would be, for the same reason Failure 9's fabricated
citation was worse than a fabricated fact alone: it reads as more credible
than it is.

**Fix, same two layers as Failure 3/9 again:**
1. **Prompt-level** (already existed, rule 5): instructs the model to pass
   the caveat on every time. This alone clearly isn't sufficient - it's
   the same rule that was already in place when this failure happened live.
2. **Code-level, the one that actually holds regardless of prompt
   compliance** (`app/llm/orchestrator.py`): `_execute_tool` now returns
   the real `CohortStats` object as `extra["cohort_stats"]`, threaded
   through `_resolve_tools` exactly like `aggregate_result`/
   `eligibility_result` already were, and surfaced as a `cohort_stats`
   field on both `handle_turn`'s return dict and `handle_turn_stream`'s
   `"done"`/`"error"` events - independent of whatever the model's own text
   does or doesn't say. `app/api/schemas.py`'s `ChatResponse` gained a
   matching `cohort_stats: Optional[CohortStats]` field (without it,
   FastAPI's `response_model` would have silently stripped the fix back
   out of the actual API response - the same class of "real data computed
   correctly, then lost before reaching the user" bug this whole fix is
   about). The frontend (`static/index.html`) renders `cohort_stats` in
   its own small card, with `data_source` always shown in bold, the same
   way the calculation card already renders Failure 3's fix.

Verified with
`test_cohort_stats_carries_synthetic_caveat_even_when_model_narration_drops_it`
(`tests/test_orchestrator.py`): a fake model answers with a bare
percentage and zero mention of "synthetic" - the test asserts the model's
own reply text indeed omits it, then asserts `result["cohort_stats"]
["data_source"]` contains it anyway.

**What this doesn't fix:** it does not fix the separate problem in the
same live exchange - the model analyzing an unrelated category instead of
telling the student plainly that no cohort-statistics data exists yet for
Physician Assistantship. `analyze_outcomes` correctly raises `ValueError`
for an unknown *category name*, but "Physician Assistantship" was, at the
time, a real category with real (if initially empty) data, so nothing
rejected the call - the model simply chose the wrong `programme_category`
argument. That is a tool-selection mistake, not a data-loss bug, and
neither this fix nor the new `institutions_example` entries address it
directly; it would need either a stricter prompt instruction to match the
student's named programme before calling the tool, or a code-level check
that the requested programme name (e.g. extracted from the user's own
message) matches the category actually queried. Left as a known gap, not
claimed as fixed.

### Failure 11: "too good" an aggregate wrongly marked ineligible (real logic bug, not an LLM failure)

**What happened:** a student with aggregate 6 (an excellent WASSCE result -
lower is better in this system) was marked "Not eligible" for Physician
Assistantship / Allied Health, whose `aggregate_band` is `{best: 9, worst:
24}`. `app/tools/eligibility_checker.py`'s check was
`band["best"] <= aggregate <= band["worst"]` - a two-sided range check. But
`aggregate_band` represents the RANGE of real cutoffs observed across
institutions in a category, not a floor a student must clear from below:
`best` is the most competitive (lowest) cutoff seen, `worst` the least
competitive (highest). A student whose aggregate is better than even the
most competitive cutoff in the category clears every real cutoff in it and
must be eligible - there's no such thing as "too good" an aggregate in
WASSCE admissions.

**Why this stayed hidden until now:** every other category's test coverage
happened to use an aggregate at or above that category's `best` (e.g.
Medicine's existing test uses aggregate 8, inside its 6-10 band). Physician
Assistantship (`best`=9) was the first category whose `best` sat above a
commonly-tested low aggregate, which is what exposed it live.

**Fix:** `aggregate_eligible = aggregate <= band["worst"]` - drop the lower
bound entirely. Verified with
`test_aggregate_better_than_bands_best_is_still_eligible` and
`test_aggregate_worse_than_bands_worst_is_ineligible` in
`tests/test_eligibility_checker.py`.

**Not touched on purpose:** `scripts/generate_synthetic_outcomes.py` uses
the same two-sided-range idea to decide its synthetic admission flag, but
deliberately so - it needs students sampled on both sides of the band to
produce a realistic-looking distribution for Question 9's demo, and its own
docstring already states this is an arbitrary illustrative model, not a
claim about real eligibility rules. Only the real eligibility-determining
code path in `eligibility_checker.py` was wrong; the synthetic generator's
design choice is unrelated and was left alone.

### Failure 12: fabricated institutions beyond the real sourced list (observed live, Oct 2026)

**What happened:** a student asked "schools i am eligible for physician
assisantship". The real `institutions_example` for that category in
`programmes.json` is `["UHAS", "UDS"]` - two institutions. The model
answered with six: "University of Ghana (example institution), UCC, UDS,
UHAS, KNUST, UMaT". Four of those six were never in the real data for this
category at all.

**Why this happened despite Failure 7's existing prompt rule:** Failure 7
was "fixed" with a prompt instruction only (rule 5b: "NEVER name specific
schools... direct them back to those results... rather than inventing a
list yourself") - it never got the code-level enforcement that Failures 3,
9, and 11 all eventually needed. The chat model also had no tool that could
return `institutions_example` for a category; its only source for that data
was recalling/paraphrasing the "Aggregate:" table text injected into
conversation history several turns earlier (see Failure 8). A small local
model recalling a six-row table from several turns back, then quietly
padding it with plausible-sounding Ghanaian university names, is exactly
the failure mode the rest of this document already predicts for anything
left to model memory instead of a tool call.

**Fix, finally matching the code-level pattern the other failures needed:**
1. New tool `list_institutions` (`app/tools/programme_lookup.py`,
   `app/models/institutions.py`) - a deterministic, zero-LLM lookup that
   returns a category's real `institutions_example` copied verbatim from
   `programmes.json`. Added to `ALL_TOOLS`
   (`app/llm/tool_schemas.py`) so the chat model can actually call it.
2. `system_prompt.py` rules 5b/5c rewritten to instruct the model to call
   `list_institutions` for any "which schools" question - explicitly
   naming this live failure as the reason, and explicitly forbidding
   answering from memory of the earlier table even if the model believes
   it remembers correctly.
3. **The part that actually holds regardless of prompt compliance**
   (matching Failures 3/9/11): `_execute_tool` returns the real
   `InstitutionsLookup` object as `extra["institutions_lookup"]`, threaded
   through `_resolve_tools` exactly like `aggregate_result`/
   `eligibility_result`/`cohort_stats_result`, surfaced as an
   `institutions_lookup` field on `handle_turn`'s return dict and
   `handle_turn_stream`'s `"done"`/`"error"` events, added to
   `ChatResponse` in `app/api/schemas.py` (same FastAPI-silently-strips-it
   trap as Failure 9), and rendered as its own card in
   `static/index.html` - independent of whatever the model's own text
   says or adds.

Verified with
`test_institutions_lookup_carries_real_list_even_when_model_narration_invents_others`
(`tests/test_orchestrator.py`): a fake model's reply text names six
institutions including four fabricated ones - the test asserts the model's
own text does contain the fabrication, then asserts
`result["institutions_lookup"]["institutions_example"]` is exactly
`["UHAS", "UDS"]` regardless.

**What this doesn't fix:** nothing code-level stops the model's own reply
*text* from still naming extra institutions beyond what `list_institutions`
returned - there's no practical way to constrain free-form natural-language
output to only the words a tool call returned (the same honest gap already
noted in Failure 9's writeup). Giving the model a real tool and an explicit
instruction to use it makes the correct path easier and more available than
before, which should reduce this live model's tendency to pad from memory,
but it is not a guarantee for a small local model, and the regression test
above only proves the *deterministic field* is correct - it deliberately
does not (and cannot) assert the model's own prose is free of invented
names.

### Failure 13: fabricated institution-specific programme titles (observed live, Oct 2026)

**What happened:** a student asked what programmes they could do "at UG or
KNUST or other related fields." The model answered with a confident list:
"Bachelor of Medicine and Surgery at University of Ghana... Bachelor of
Medicine and Surgery at KNUST... at UCC... at UDS... at UHAS," plus
invented nursing programmes at all five, with no real data behind any of
it. `programmes.json` only ever had category-level `institutions_example`
lists ("which schools offer Medicine broadly") - it never had
institution-specific programme titles. The model filled that gap itself.

**Why this is the same failure shape as Failure 12, one level deeper:**
Failure 12 was the model inventing *which schools* belong to a category.
Failure 13 is the model inventing *which exact programmes* a specific
school runs - a more specific, more confident-sounding claim, and
therefore more misleading if wrong.

**Fix, same pattern as Failures 3/9/11/12 - code first, prompt second:**
1. The user supplied two real spreadsheets: University of Ghana's own
   official cut-off page (admissions.ug.edu.gh) and a KNUST cut-off list
   from a third-party site (ghanaunichecker.com, so flagged
   lower-confidence than UG's). Transcribed verbatim - including UG's
   compound cutoff values like "7(8)" and "16(24)M" - into
   `data/structured/institution_programmes.json`: 197 real rows (63 UG, 134
   KNUST).
2. New tool `lookup_institution_programmes`
   (`app/tools/institution_programme_lookup.py`,
   `app/models/institution_programmes.py`) - exact-match on institution
   name, optional keyword filter on programme name, returns real rows or
   `has_data_for_institution=False` for any institution without data
   (every institution except UG and KNUST, for now). Added to `ALL_TOOLS`.
3. `system_prompt.py` rule 5e: never name an institution-specific programme
   from memory; always call the tool first; say plainly when
   `has_data_for_institution` is `False` rather than filling the gap.
4. **The part that holds regardless of prompt compliance:** threaded
   through `orchestrator.py` exactly like `cohort_stats_result`/
   `institutions_lookup_result`, surfaced as `institution_programmes` on
   `handle_turn`/`handle_turn_stream`, added to `ChatResponse`
   (`app/api/schemas.py`), rendered as its own table card in
   `static/index.html` with the real `cutoff_display` value shown verbatim.

Verified with
`test_institution_programmes_carries_real_rows_even_when_model_narration_invents_others`
and `test_institution_programmes_no_data_flagged_honestly`
(`tests/test_orchestrator.py`).

**What this doesn't fix:** the same honest gap as Failure 12 - nothing
code-level stops the model's own reply *text* from still naming a
programme/institution pairing the tool never returned. And the coverage
itself is narrow: only 2 of the many institutions now in
`programmes.json` (UG and KNUST) have real per-programme data; every
other institution - including the entire new "Private University Entry"
category - still has none, and the tool is designed to say so plainly
rather than quietly degrade to a category-level guess.

### Addendum: correcting the user-supplied private-university list

Alongside Failure 13's fix, the user supplied a 37-school list (10 public
traditional, 10 public technical, 17 labelled "private") to add to the
data. Two of the 17 - University of Professional Studies, Accra (UPSA)
and Ghana Communication Technology University (GCTU) - are factually
PUBLIC Traditional Universities under GTEC's own classification (both
established by their own Acts of Parliament; already sourced and present
in this file's "Open Public-University Entry" category). They were
corrected rather than filed twice under conflicting statuses. The
remaining 15 were independently verified against GTEC's own
accredited-institutions list and multiple cross-referencing sources
before being added as a new "Private University Entry" category - not
accepted on the user's list alone, consistent with every other addition
in this file requiring its own citable source rather than inheriting
whatever confidence the person asking happened to have.

### Failure 14: model skips the tool entirely across a whole structured answer (observed live, Oct 2026)

**What happened:** Failure 13's fix added a real `lookup_institution_programmes`
tool and a prompt rule (5e) requiring the model to call it before naming
any programme at a named institution. A student then asked "list the
schools and programmes am eligible for" and got a full structured answer
with invented degree titles - "Bachelor of Arts, Bachelor of Social
Sciences, Bachelor of Education" at UCC, UEW, UDS, and AAMUSTED, none of
which have any programme data on file. The model never called the tool
once. On the next turn the student asked about Civil Engineering, and the
model answered with "HND in Civil Engineering" at **all 10** technical
universities - again, zero of which have any data (verified directly:
`lookup_institution_programmes("Accra Technical University")` returns
`has_data_for_institution: False`). Only on a third turn, when the student
asked "what is this HND in Civil Engineering", did the model finally call
the tool, discover nothing, and admit "I should not have mentioned it
earlier."

**Why this is a different failure from Failure 13, not just a repeat:**
every previous fix in this document (Failures 3, 9, 11, 12, 13) assumed
the model's prose might *add a little* on top of a correct tool call -
one extra school in an otherwise-real list, say. This is categorically
different: the model skipped the tool across an **entire** multi-paragraph
answer, for multiple institutions, with full confidence, and only checked
reality when directly challenged. A prompt rule and tool availability are
not remotely sufficient against that pattern for an 8B local model.

**Fix - the first in this project that doesn't correct a wrong value, but
flags an absence of verification:** `app/tools/institution_claim_guard.py`
scans the model's FINAL reply text (independent of which tools it chose
to call) for any of the institution names already on file
(`programme_lookup.all_known_institution_names()`) appearing alongside
degree-sounding language ("Bachelor", "HND", "BSc", "Diploma", "Doctor
of", etc.). Any institution flagged this way that was NOT verified this
turn via a real `lookup_institution_programmes` call returning
`has_data_for_institution=True` goes into a new `unverified_institution_claims`
field - threaded through `orchestrator.py`'s `_resolve_tools` (a new
`verified_institutions` set, populated whenever a real lookup succeeds),
surfaced on `handle_turn`/`handle_turn_stream`, added to `ChatResponse`,
and rendered in `static/index.html` as a prominent red warning banner -
shown FIRST, before the other (reassuring) cards.

Verified with
`test_unverified_institution_claims_flagged_when_model_never_calls_the_tool`
(reproduces the live failure verbatim: UCC and Accra Technical University
both get flagged with no tool call at all) and
`test_unverified_institution_claims_empty_when_tool_actually_verified_it`
(University of Ghana, correctly verified via a real tool call, is NOT
flagged even though its name and a degree keyword both appear in the
reply) in `tests/test_orchestrator.py`.

**What this doesn't fix, stated as plainly as the gap itself:** this
cannot rewrite or remove the model's fabricated sentence - "UCC: Bachelor
of Arts" still sits in the reply text exactly as the model wrote it. What
changes is that the reply is now accompanied by a deterministic, code-level
warning naming exactly which institutions in it are unverified, so the
student is not left to trust confident-sounding prose alone. This is a
containment measure, not a cure: the underlying cause - a small local
model not reliably following a "call the tool first" instruction - is a
known limitation of the model, not something any further prompt or even
tool design can fully close. A larger or better-instruction-tuned model
would likely need this safety net far less; it stays either way, because
"the model should behave better" is not a load-bearing assumption this
codebase makes anywhere else, and it shouldn't start here.

### Failure 15: model directly contradicts an already-computed eligibility result (observed live, Oct 2026)

**What happened:** a student with aggregate 6 and purely technical/
vocational electives (Technical Drawing, Applied Electricity,
Electronics) ran "Enter My Grades". The real, deterministic result
correctly marked "Engineering / Pharmacy / Actuarial Science" as **Not
eligible** (electives don't match - no Biology/Chemistry/Physics). Two
turns later, asked "where can i get civil engineering or architecture",
the model answered: "Based on the tool's output, you are eligible for the
category 'Engineering / Pharmacy / Actuarial Science'" - the exact
opposite of the real result, sitting in the same conversation.

**Why this is different in kind from Failures 12/13/14:** those were all
about the model inventing something with NO real data behind it
(institutions, programmes). This is the model having the correct answer
available - literally printed in the conversation two turns earlier - and
stating the opposite of it anyway. It is also the first of these failures
where chat genuinely had no deterministic tool it could have called: chat
has no access to compute_aggregate/check_eligibility at all (Failure 6),
so its only way to answer a follow-up eligibility question was ever going
to be rereading its own earlier text, and this is what happens when that
reread goes wrong.

**Fix - this one needed real session state, not just a better tool:**
1. `app/core/session_store.py` gained a second table, `calculations`,
   storing the REAL structured `AggregateResult`/`EligibilityResult` from
   a session's most recent `/calculate` call (`set_last_calculation`/
   `get_last_calculation`) - previously only the human-readable text
   summary was ever persisted (Failure 8's fix), which is exactly what
   the model was misreading.
2. `/calculate` (`app/api/routes.py`) now writes to this table alongside
   the existing text-summary history write.
3. New tool `get_saved_eligibility` (`app/tools/eligibility_status_lookup.py`,
   `app/models/eligibility_status.py`) lets the model check the REAL
   verdict for one category instead of recalling the table. Added to
   `ALL_TOOLS`; `system_prompt.py` rule 5c rewritten to require calling it
   before stating any eligibility verdict (it previously told the model
   it was fine to read eligibility off the earlier table from memory -
   that instruction was itself part of the bug).
4. **The part that holds regardless of whether the model calls the new
   tool - and the first guard in this project with absolute ground truth
   to compare against, not just "was something verified":**
   `app/tools/eligibility_claim_guard.py`'s `detect_eligibility_contradictions`
   scans the model's final reply text for any category name paired with
   eligibility language ("eligible" / "not eligible" / "no match"), and
   compares the claimed verdict against the real saved result for this
   session. A mismatch is a *definite* wrong answer, not merely
   unverified - Failure 14's guard could only ever say "we don't know if
   this is right" because there's no absolute ground truth for arbitrary
   institution/programme pairs; here there is. Threaded through
   `orchestrator.py`, surfaced as `eligibility_contradictions` on
   `handle_turn`/`handle_turn_stream`, added to `ChatResponse`, rendered
   in `static/index.html` as the most prominent warning in the UI -
   worded as a correction ("the reply said X, your actual result says
   Y"), shown before even the Failure-14 warning.

Verified with
`test_eligibility_contradiction_flagged_when_model_contradicts_real_result`
(reproduces the live failure verbatim and confirms the exact
category/model_said/actual values are captured),
`test_eligibility_contradiction_empty_when_model_states_the_truth`,
`test_eligibility_contradiction_empty_when_no_calculation_saved_yet`,
`test_get_saved_eligibility_tool_wired_through_orchestrator`, and
`test_get_saved_eligibility_no_calculation_yet_returns_error_not_exception`
in `tests/test_orchestrator.py`, plus
`test_calculate_with_session_id_persists_structured_result_for_failure_15`
in `tests/test_api.py` confirming the new table is actually written.

**What this doesn't fix:** same honest limit as Failure 14 - the
contradictory sentence still sits in the reply exactly as the model wrote
it; nothing rewrites it. What's different here is the response is no
longer just flagged "unverified" but corrected with the actual right
answer shown alongside it, because for this specific failure mode (unlike
institution/programme invention) the real answer was always one
`session_store` lookup away.

### Failure 16: third-core subject locked to track instead of best-of-two, and required_core silently never checked (found 22 Oct 2026, not an LLM failure)

**What happened:** the user asked a plain factual question - "does the
aggregate have to be 3 core subjects and 3 electives" - and cited sources
(ghanaunichecker.com, wassceexams.com, my-uniplan.com) describing the real
WAEC rule as: English + Core Mathematics + **whichever of Integrated
Science/Social Studies gives the better grade** + best 3 electives.
`GradeInput` only ever collected ONE of Integrated Science/Social Studies,
locked by the student's `track` (science -> Integrated Science always,
everything else -> Social Studies always) - never the better of the two.
WAEC's own published subject list (waecgh.org) confirms both are
mandatory "Core Subjects for the examination" for every candidate
regardless of track, so every real student has both grades; this schema
simply never asked for the one it had locked out.

**Why this is a different kind of failure from 3/9/11/12/13/14/15:** every
one of those was the chat model misbehaving around correct underlying
data. This is a bug in the deterministic calculation itself, found not by
watching the model fail but by a user fact-checking the domain rule
against external sources - a useful reminder that "deterministic" and
"correct" aren't the same guarantee, and that this project's own sourcing
discipline (check a claim against a named source before trusting it)
applies to the code's own domain logic too, not just to chat's claims
about schools.

**A second, related bug the fix surfaced while auditing the same code
path:** `programmes.json`'s `required_core` field (e.g. Medicine/Dentistry
requiring "Integrated Science" specifically, Business/Finance requiring
"Social Studies" specifically - itself correctly sourced data) was never
read by `check_eligibility` at all. A student could be marked eligible
for Medicine on aggregate and electives alone, with no check that their
actual Integrated Science grade was even a credit pass - and the
track-locked schema made this impossible to fix properly in the first
place, since a science-track student's Social Studies grade (needed to
check Business/Finance's requirement for them) was never collected
either.

**Fix - both bugs needed the same underlying data-collection change:**
1. `app/models/grading.py`: `GradeInput` now requires BOTH
   `integrated_science` and `social_studies` (removed the single
   track-locked `third_core`). `AggregateResult` gained `third_core_used`
   so the chosen subject is always visible, not silently decided.
2. `app/tools/aggregate_calculator.py`: the aggregate sum and credit gate
   now use whichever of the two has the better (lower) point value,
   regardless of track - ties break toward Integrated Science
   (documented, since WAEC itself doesn't publish a tie-break rule and a
   tie gives an identical aggregate either way). Both grades are always
   recorded in `subject_points`, even the unused one.
3. `app/models/eligibility.py` / `app/tools/eligibility_checker.py`: new
   `required_core_match` field and `_check_required_core` - actually
   reads `required_core`, checks it against the student's real grade in
   whichever specific subject it names (Integrated Science or Social
   Studies), independent of which one was used for the student's OWN
   aggregate. Categories with generic `required_core` wording (the two
   floor categories, HND) correctly stay `None` (unverifiable), never
   guessed either way. New `core_grades` parameter on `check_eligibility`
   is optional and defaults to `None` for backward compatibility -
   existing callers that don't supply it simply get `required_core_match
   = None`, not a behavior change forced on code that hasn't been
   updated to pass it.
4. `app/api/routes.py`: `/calculate` now passes the student's real
   Integrated Science AND Social Studies grades through to
   `check_eligibility`, not just whichever the old schema happened to
   collect.
5. `static/index.html`: the form now asks for both subjects as separate
   fields (previously one field, relabelled by track) and the results
   card shows which one was actually counted.

Verified with 6 new tests in `tests/test_aggregate_calculator.py`
(best-of-two selection working both directions - including a
non-science-track student whose Integrated Science beats their Social
Studies, and a science-track student whose Social Studies beats their
Integrated Science, each confirming track no longer dictates the
outcome) and 5 new tests in `tests/test_eligibility_checker.py`,
including the exact motivating scenario: a student whose electives and
aggregate both pass Medicine, but whose real Integrated Science grade is
an outright fail (F9), is correctly marked ineligible for Medicine
specifically (and the mirror case for Business/Social Studies) - while a
student with no `core_grades` supplied at all gets the same unverifiable
`None` every pre-existing caller already expected, confirmed not to
regress.

**What this doesn't fix:** `required_core`'s generic entries (e.g. the
two floor categories' "Integrated Science or Social Studies
(track-dependent)" wording) still aren't checked against anything
specific - that's correct behavior (nothing concrete to check), not a
remaining gap. The real remaining gap is the same one already true before
this fix: `required_core` only ever names Integrated Science, Social
Studies, English Language, or Core Mathematics across the whole file -
if a category's real admission requirement ever named a different
specific core subject, `_CHECKABLE_CORE_SUBJECTS` would need extending,
and nothing currently alerts anyone that it should be.

### Failure 17: category-level programme inference, numerically lucky but methodologically unsound (observed live, Oct 2026)

**What happened:** a student asked "can i do law." The model answered:
"Yes, you are eligible for the General Humanities / Social Sciences /
Education category, which includes law programmes... at institutions
such as the University of Ghana, UCC, UEW, UDS, or AAMUSTED." No tool was
called. Checking `institution_programmes.json` directly: Law IS real data
in this project - University of Ghana's "Bachelor of Laws" and KNUST's
"LLB Law" both have a real cutoff of **6**, far stricter than the broad
Humanities category's 6-24 band shown to the student. This particular
student's aggregate was exactly 6, so the answer was numerically correct
- by coincidence, not by checking.

**Why this is worse than it looks at first glance:** the same reasoning
pattern ("the category is eligible, so a programme under it should be
reachable too") would have confidently told a student with aggregate 15 -
comfortably "Eligible" for the broad category - that they could do Law,
when the real cutoff of 6 would have excluded them. A single correct
answer masked an unsound method that would fail the next student who
asked the same question with a worse (but still category-eligible)
aggregate. This is also the first failure in this project caught not by
an obviously wrong answer, but by independently verifying a *right*
answer's reasoning - worth noting for its own sake: "the output looks
correct" is not the same bar as "the output is correct for a sound
reason," and this project's sourcing discipline applies to checking its
own right answers, not only its obviously wrong ones.

**A second thing this exposed: a real gap in Failure 14's guard regex.**
`institution_claim_guard.py`'s keyword pattern matched "programme in" and
"course in" as fixed phrases - not the bare words "programme"/"programmes"
on their own. The actual live wording, "law programmes" / "a law
programme," matched neither. Directly tested: `detect_unverified_institution_claims`
returned an empty list for the exact live reply text before this fix.

**Fix:**
1. `app/tools/institution_claim_guard.py`'s `_DEGREE_KEYWORD_RE` widened to
   match the bare words `programmes?`, `courses?`, and `degree`, not just
   the fixed phrases "programme in"/"course in"/"degree in". Re-tested
   against the exact live reply: now correctly flags all five named
   institutions. Full test suite re-run to confirm this broadening
   introduced no new false positives against the existing battery (it
   did not - all pre-existing tests still pass unchanged).
2. New system prompt rule 5f: explicitly forbids inferring a named
   programme's eligibility from its broad category's eligibility alone,
   names this exact live case as the reason, and requires calling
   `lookup_institution_programmes` before naming any specific programme -
   whether or not it seems to obviously belong to an already-eligible
   category.
3. Regression test
   `test_category_level_programme_inference_flagged_despite_being_numerically_lucky`
   (`tests/test_orchestrator.py`) reproduces the live reply text verbatim
   and asserts all five named institutions are now flagged.
4. New automated eval case `AUTO-16` and manual case `MANUAL-09`
   (`scripts/run_eval.py`) - the same automated/manual split used for
   every prompt-rule fix in this project: the automated case proves the
   guard catches the scripted pattern; the manual case is what actually
   tells you whether the real model's reasoning improved.

**What this doesn't fix:** the underlying conflation - treating a
category-level band as if it were a specific programme's cutoff - is a
reasoning error, not a missing-data error. Widening the regex catches
more phrasings of the SYMPTOM (naming an unverified institution+programme
pair); it does not teach the model not to make the inference in the first
place. Rule 5f is a prompt-level attempt at that, with the same honest
limitation already stated for every other prompt rule in this document: a
small local model's compliance with it is probabilistic, not guaranteed,
which is exactly why the regex fix (point 1) exists as a backstop
independent of whether rule 5f actually works.

### Failure 18: a false contradiction, a false fabrication warning, and a genuinely new mismatch, all found while checking Failure 17's own fix (observed live, Oct 2026)

**What happened, in three parts:**

1. A student asked "What am I eligible for in KNUST." The model answered:
   "you are eligible for Private University Entry in KNUST, and Open
   Public-University Entry in KNUST. However, you are NOT eligible for
   Engineering / Pharmacy / Actuarial Science in KNUST." KNUST has never
   been in "Private University Entry"'s real `institutions_example` list
   - it is a public university. The eligibility-contradiction guard
   (Failure 15) then fired, but on the WRONG category: it reported
   "Private University Entry: the reply said 'not eligible', but your
   actual saved result says 'eligible'" - except the model never said
   "not eligible" for Private University Entry at all. It said "eligible"
   for it, correctly. The guard's fixed-character window (60 chars
   before, 160 after a category's mention) read far enough past "Private
   University Entry" to reach the NEXT sentence's real "NOT eligible,"
   which was actually about Engineering, and misattributed it.
2. Asked a follow-up ("what does this mean"), the model gave an
   appropriately cautious reply: it would "need to check the
   programme-specific data" and asked whether to check Law at KNUST. The
   institution-claim guard (Failure 14, widened in Failure 17 to match
   bare "programme(s)") flagged KNUST anyway - a direct, confirmed side
   effect of that widening: a reply making NO claim at all, explicitly
   deferring instead, still matched the keyword and got flagged as if it
   had fabricated something.
3. Checking what SHOULD have been flagged in the first reply - KNUST
   named under a category it was never in - revealed that **no existing
   guard checks this at all**. Failure 14's guard checks
   institution+programme pairs against `lookup_institution_programmes`.
   Failure 15's guard checks eligibility verdicts against the saved
   result. Neither checks whether a named institution actually belongs to
   a named category per `programmes.json`'s own `institutions_example` -
   a third, distinct kind of claim, and genuinely new.

**Why this is worth its own entry rather than three separate ones:** all
three were found in the course of checking one transcript, and the first
two are specifically about this project's own safety nets producing
*wrong* warnings, not missing real ones - the opposite failure mode from
everything documented so far. A false correction is its own kind of
damage: it teaches a reader to distrust the warning banners generally,
which undermines every genuine catch this document already describes.

**Fix for part 1 (false contradiction):**
`app/tools/eligibility_claim_guard.py`'s window-based matching was
replaced with sentence-scoped matching: reply text is split on
sentence-ending punctuation AND newlines (a bulleted, one-category-per-
line reply has no periods to split on at all), and verdict language is
only looked for in the SAME sentence/line as a category's mention, never
a fixed character range that can bleed into the next one. Re-tested
against the exact live reply: now returns `[]` (no false contradiction),
while the original Failure 15 case (a single-sentence contradiction) is
still caught correctly - confirmed directly, not assumed.

**Fix for part 2 (false fabrication warning):**
`app/tools/institution_claim_guard.py` gained a `_DEFERRAL_RE` check: if
the reply contains explicit deferral language ("would need to check,"
"would you like me to check," "I don't have that/specific/per-programme
data," "no data on file/yet," "can't/not able to confirm"), the guard
returns `[]` for the whole reply rather than flagging anything. Stated as
a limitation, not hidden: this is a whole-reply exclusion, so a message
that genuinely defers about one institution while fabricating about a
*different* one in the same reply would currently go unflagged for both
- accepted for now because the live case was a single, uniformly
cautious reply, and written down here rather than silently assumed away.

**Fix for part 3 (the genuinely new mismatch) - a new guard:**
`app/tools/institution_category_mismatch_guard.py`, using the same
sentence-scoped approach as the fix above: for each sentence, every known
institution mentioned is checked against every category also mentioned in
that sentence, using `programme_lookup.category_institutions_map()` (a
new helper exposing `programmes.json`'s own category -> real institutions
mapping). Any institution named under a category it is not actually in
gets flagged as `{"institution": ..., "category": ...}`. Threaded through
`orchestrator.py` as a third always-on guard alongside the other two,
surfaced as `institution_category_mismatches` on `handle_turn`/
`handle_turn_stream`, added to `ChatResponse`, rendered as its own red
correction card in `static/index.html`.

Verified with three new tests in `tests/test_orchestrator.py`:
`test_eligibility_contradiction_not_falsely_flagged_across_sentence_boundary`
(part 1 - reproduces the exact live reply, confirms no false
contradiction), `test_unverified_claims_not_falsely_flagged_when_model_explicitly_defers`
(part 2 - reproduces the exact live deferral reply, confirms no false
flag), and `test_institution_category_mismatch_flagged_for_knust_under_private_university_entry`
(part 3 - confirms KNUST is flagged for the wrong category and NOT
flagged for the category it actually belongs to). New eval case
`AUTO-17` added to `scripts/run_eval.py` for part 3.

**What this doesn't fix:** the sentence-scoping fix for part 1 assumes a
verdict for a category is stated in the same sentence as the category's
name - a reply structured as "Here are your results: Category A, Category
B, Category C. All three: eligible." (verdict in a trailing sentence
covering several categories at once) would not be caught by either the
old or the new approach, and remains a known gap. The deferral exclusion
for part 2 has the whole-reply limitation already stated above. The new
guard for part 3 only checks institutions and categories already known to
`programmes.json` - an institution or category name outside that set
(including any outright invented one) is a job for Failure 14's guard,
not this one.

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
