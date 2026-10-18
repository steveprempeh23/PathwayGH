# Extending the Dataset: More Programmes, More Schools

This is a practical how-to, not architecture documentation - see
`docs/architecture.md` for the system design and `docs/evaluation.md` for
why certain honesty rules exist. Follow the rules below *because* of the
failures documented there (especially Failures 3, 5, and 7) - skipping
them is how this project's fabrication problems happened in the first
place.

## The one rule that matters more than any schema detail

**Never add a number, a cutoff, or a school name you haven't actually
sourced.** Every existing entry in `programmes.json` has a `confidence`
field (`verified_example` or `approximate_band`) and most have
`_source_urls` in the file header. If you add a new category or school and
you're estimating rather than citing something real, mark it clearly
(`"confidence": "approximate_band"`, or a `_note` explaining it's a rough
placeholder) rather than letting it sit next to sourced data looking
equally authoritative. This project's whole credibility argument rests on
that distinction being real, not decorative.

## Adding a new programme category

Edit `data/structured/programmes.json`. Each entry in
`programme_categories` needs:

```json
{
  "category": "Nursing / Allied Health",
  "example_programmes": ["BSc Nursing", "BSc Midwifery"],
  "aggregate_band": {"best": 6, "worst": 20},
  "confidence": "approximate_band",
  "required_core": ["English Language", "Core Mathematics", "Integrated Science"],
  "required_electives": {"type": "all_of", "options": ["Biology", "Chemistry"]},
  "elective_min_grade": "C6",
  "institutions_example": ["University of Ghana", "KNUST"],
  "track": "science"
}
```

Field notes:
- Subject names in `required_electives.options` must exactly match a
  canonical name a student could actually submit. The web UI's elective
  dropdowns (`ELECTIVES_BY_PROGRAMME` in `static/index.html`) are the
  single source of truth for what those canonical names look like for
  each SHS programme - if you add a new required elective name here, also
  add it to that lookup (or an existing one already covers it), or a
  student picking from the dropdown will never be able to match it.
- `required_electives.type` is either `"all_of"` (every listed subject
  required) or `"choose_n"` (pick `n` of `options`) - see the existing
  General Science or Business entries for `choose_n` with the
  `also_required`/`plus_additional` extras, and see
  `app/tools/eligibility_checker.py::_check_electives` for exactly how
  each shape is interpreted. If your new category's requirements don't fit
  either shape, you'll need to extend that function too, not just the
  JSON - don't write a structure the code can't read.
- If `required_electives.options` contains generic text ("any approved
  elective") rather than specific subject names, the checker correctly
  reports `electives_match: None` (unverifiable) rather than guessing -
  this is intentional, not a bug to work around.
- `institutions_example` is what now reaches the chat and the `/calculate`
  card (see Failure 7's fix) - only list schools you can actually point to
  a source for.

After adding a category:
1. Run `python scripts/build_check.py` - it asserts 7 categories currently
   (`check_datasets_load`); update that number once you've added one.
2. Add a test case in `tests/test_eligibility_checker.py` exercising the
   new category, the way every existing category already has coverage.
3. Consider regenerating the synthetic cohort dataset
   (`python scripts/generate_synthetic_outcomes.py`) so Question 9's
   analysis tool has rows for the new category too - it reads
   `programme_categories` directly, so this is automatic once the JSON is
   updated, but re-run the script to actually produce the new CSV rows.

## Adding sourced facts to the RAG corpus

`data/raw/wassce_grading_and_admission_guide.md` is what `retrieve_context`
searches. To add a new fact (e.g. detail on a category you just added):

1. Add a new `##` section to the markdown file, or extend an existing one.
   The chunker (`app/rag/chunker.py`) splits on headings, so a new `##`
   becomes its own retrievable chunk.
2. Update the file's YAML frontmatter `source_urls` if the new content
   comes from different sources than what's already listed - currently
   every chunk in this file inherits the *same* source list (a known
   coarse-grained limitation noted in the README's RAG Design section). If
   you're adding content from a genuinely different source, consider
   starting a second markdown file in `data/raw/` instead, so its chunks
   carry their own distinct `source_urls` rather than incorrectly
   inheriting this file's.
3. Rebuild the index: `python -c "from app.rag.retriever import build_index; print(build_index(force=True))"`
   - `force=True` is required, since `build_index()` is otherwise idempotent
   and won't re-embed unless told to.
4. Test retrieval manually once Ollama is running:
   `python -c "from app.rag.retriever import retrieve; print(retrieve('your test query'))"`

## Adding real per-school data (a bigger undertaking - not done yet)

Right now, "schools" only exist as the flat `institutions_example` list
per category - there's no per-school entity with its own cutoffs, its own
programme list, or its own admission cycle data. Building that properly
would need:

1. **A new dataset**, e.g. `data/structured/institutions.json`, with one
   entry per school: name, which programme categories it actually offers,
   and (only if genuinely sourced) its own specific cutoffs separate from
   the category-level `approximate_band`. Follow the same
   `confidence`/`_source_urls` discipline as `programmes.json` - most
   school-specific current cutoffs are not public in a clean, citable
   form, so expect most entries to be `approximate_band` or omitted rather
   than invented.
2. **A new deterministic tool** (`app/tools/`) querying that dataset,
   mirroring `eligibility_checker.py`'s structure - and a decision on
   whether to expose it to chat (per Failure 6's reasoning, probably
   *not* as a free-text-parsed tool; more likely as another `/calculate`-
   style deterministic lookup, or a dropdown of categories on the results
   card linking to a school list).
3. **Real sourcing work** - this is the actual bottleneck, not the code.
   Each school's current admission requirements would need to come from
   that school's own published guidance, not estimated. Budget this as a
   research task, not a coding task.

This is scoped out deliberately rather than built hastily - a half-sourced
schools database would be a worse failure mode than the current honest gap
("we don't have that, here are illustrative examples"), per exactly the
reasoning in Failure 7.
