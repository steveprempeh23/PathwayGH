# Prompt Engineering: Three Variants, Discussed (Question 3)

Run with:
```
python scripts/prompt_experiment.py
```

This is real output from a live run against `llama3.1:8b` on 30/31 Oct 2026
(3 runs per case, 3 motivating cases per variant - small-sample numbers,
discussed as such below, not treated as statistically conclusive). The
three variants are not academic alternatives - they are three real points
in this project's own history: **V1** is roughly where the system prompt
started (closer to "trust the model's own judgment"), **V2** is what is
actually deployed right now, and **V3** is a stricter, more structured
rewrite tried specifically in response to Failure 15 (the live eligibility
contradiction). The three motivating cases are drawn directly from real
failures caught during development, not invented for this experiment:

- **Failure-15 case**: a student with purely technical electives asks
  about Engineering - they are genuinely *not* eligible, and this is the
  exact scenario that produced the real Failure 15/MANUAL-07 contradiction.
- **PA case**: a strong science student asks about Physician
  Assistantship - genuinely eligible, included as a sanity check that
  tightening the prompt doesn't break the easy, correct case.
- **Business/Medicine case**: a Business-track student asks about
  Medicine - genuinely *not* eligible on wrong electives, a second
  adversarial-adjacent case distinct from Failure 15's.

## Raw results

| metric | V1_weak_memory_based | V2_current_deployed | V3_stricter_structured |
|---|---|---|---|
| accuracy (contradiction-free rate) | 0.667 | 0.556 | 0.667 |
| consistency (agreement with per-case majority) | 1.0 | 0.889 | 0.778 |
| avg verbosity (words) | 63.7 | 56.0 | 104.1 |
| structure rate (uses a list) | 0.222 | 0.111 | 0.333 |
| hedge/caveat-language rate | 0.444 | 0.222 | 0.556 |

Per-case breakdown (contradiction-free runs out of 3):

| case | V1 | V2 | V3 |
|---|---|---|---|
| Failure-15 (technical electives -> Engineering) | 0/3 | 0/3 | 1/3 |
| PA (strong science -> PA, genuinely eligible) | 3/3 | 3/3 | 3/3 |
| Business/Medicine (wrong electives -> Medicine) | 3/3 | 2/3 | 2/3 |

## Discussion, by dimension

**Accuracy.** V1 and V3 tie at 0.667, both ahead of the currently
*deployed* V2 at 0.556 - the honest, slightly uncomfortable finding of
this experiment is that the prompt actually in production is not the most
accurate of the three in this test. The reason isn't that V2 is poorly
written; it's that none of the three variants solve the case that matters
most. **All three variants fail the Failure-15 case the majority of the
time** (0/3, 0/3, 1/3) - the exact scenario a real student hit live. V3's
single success out of nine attempts across the three variants on this
case is not evidence that stricter prompting solves it; it's evidence
that prompting alone gets this case right by chance roughly as often as
not. This is the central reason `eligibility_contradictions` exists as a
*deterministic* guard (Failure 15, AUTO-14) layered on top of all three
prompts, rather than this project trying to prompt its way to reliability
on this specific failure mode. No prompt variant here is good enough to
remove that guard.

**Consistency.** V1 is perfectly consistent (1.0 - every run within a case
agreed with that case's majority answer), V2 is close (0.889), V3 is the
least consistent (0.778). This is a meaningful trade-off against V3's
slightly better accuracy: V3's extra structure and verbosity don't make it
more *reliable* run-to-run, they just happen to land on the right answer
marginally more often on average. A system that is consistently wrong is
arguably easier to catch and fix than one that is inconsistently wrong -
worth weighing if V3 or similar were ever considered as a replacement for
V2.

**Structure.** V3 (0.333) produces a literal list noticeably more often
than V1 (0.222) or V2 (0.111), which tracks with V3's explicit
instruction to format eligibility answers with a structured
`[VERIFIED: ...]`-style prefix. More structure did not translate into
better accuracy on the case that actually matters (Failure-15), only on
verbosity and hedge rate (below) - structure and correctness are not the
same axis here.

**Hallucination.** None of the three variants' observed failures in this
experiment were outright invented institutions or programmes - the
contradiction-rate failures are a different, narrower failure mode:
stating an eligibility *verdict* that contradicts an already-computed,
real saved result (Failure 15's specific pattern), not fabricating a fact
that was never computed at all (Failure 12/13/14's pattern, which the
institution-claim guard covers separately). This experiment is deliberately
scoped to the eligibility-contradiction failure mode specifically, since
that's what motivated writing V3 in the first place - it does not
re-test the institution/programme fabrication patterns, which are
covered by AUTO-11 through AUTO-14 instead.

**Tone.** V3's mandated `[VERIFIED: ...]` prefix (visible in its higher
structure rate and much higher verbosity below) does make replies read
more mechanically - closer to a form being filled out than a conversation.
For a tool a 15-18 year-old is meant to actually use and trust, V1 and
V2's more conversational tone is arguably a real usability advantage that
this experiment's accuracy numbers don't capture at all; reading V3's
actual replies rather than only its summary statistics, the stricter
format does cost something in approachability without buying enough
accuracy improvement on the case it was meant to fix to justify that cost.

**Verbosity.** V3 averages 104.1 words, nearly double V1 (63.7) and
V2 (56.0). Combined with the tone finding above, this is the clearest
single number showing V3's cost: almost twice the length for a
marginal (one extra success out of nine attempts) accuracy gain on the
one case it was designed to fix.

**Usefulness.** Read against Question 3's own instruction not to simply
say "one was better": none of V1, V2, or V3 is unambiguously the right
choice on every axis. V1 is the most *consistent* and ties for most
*accurate*, but was an earlier, less deliberately-engineered prompt than
V2. V2 (deployed) is the most *concise* and has a reasonable hedge rate,
but is not the most accurate or consistent of the three here. V3 is
marginally more accurate on the hardest case and more thorough, at a real
cost in verbosity, tone, and consistency. **The actual decision this
project made - keep V2 deployed, and rely on the deterministic
`eligibility_contradictions` guard rather than switching prompts - is
supported by this data, but not because V2 "won."** It's supported because
no prompt variant tested gets the Failure-15 case right reliably enough to
be trusted alone, so the right fix was architectural (a guard that catches
the error after the fact, regardless of which of these three prompts
produced it) rather than searching for a fourth prompt variant that might
perform marginally better on a nine-run sample.

## Limitations of this experiment itself

- Nine runs per variant (3 cases x 3 repeats) is a small sample. A
  single-run difference (e.g. V1's 3/3 vs V2's 2/3 on the Business/Medicine
  case) moves the aggregate accuracy numbers by over 10 percentage points -
  these are directionally informative, not statistically rigorous.
- "Accuracy" here specifically means "contradiction-free against the
  eligibility-contradiction failure mode," not overall correctness on
  every possible question type - see the Hallucination section above for
  what this experiment deliberately does not cover.
- All three variants were tested against the same live `llama3.1:8b`
  model; a different model could rank these three prompts differently,
  since some of the observed difference (verbosity, structure rate) comes
  from how literally this specific model follows an explicit formatting
  instruction, which varies by model.
