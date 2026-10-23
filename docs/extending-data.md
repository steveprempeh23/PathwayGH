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
1. Run `python scripts/build_check.py` - it asserts the current category
   count (`check_datasets_load`, 9 as of the Private University Entry /
   Physician Assistantship additions); update that number once you've
   added one.
2. Add a test case in `tests/test_eligibility_checker.py` exercising the
   new category, the way every existing category already has coverage.
3. If the category's `required_core` names a specific subject (Integrated
   Science or Social Studies, not generic "...track-dependent" wording),
   confirm `app/tools/eligibility_checker.py::_CHECKABLE_CORE_SUBJECTS`
   already covers it - it does for those two, but would need extending if
   a category ever named a different specific core subject (see
   `docs/evaluation.md` Failure 16).
4. Update `tests/test_api.py`'s hardcoded category-name set and
   `tests/test_data_analysis.py`'s hardcoded row count (`5 years * N
   categories * 12 students`) - both assert exact counts/sets that a new
   category changes. `scripts/run_eval.py` does NOT need updating for a
   new category (it doesn't hardcode category counts), but DOES need
   updating if you change `GradeInput`'s shape (see Failure 16's fix for
   an example of a schema change that broke it).
5. Consider regenerating the synthetic cohort dataset
   (`python scripts/generate_synthetic_outcomes.py`) so Question 9's
   analysis tool has rows for the new category too - it reads
   `programme_categories` directly, so this is automatic once the JSON is
   updated, but re-run the script to actually produce the new CSV rows.

**Before adding institutions to a category's `institutions_example`,
verify their public/private status yourself - don't trust a label just
because it's handed to you.** The "Private University Entry" category
exists because a user-supplied list of 17 "private" universities turned
out to include two (UPSA, GCTU) that are legally PUBLIC under GTEC's own
2026 classification, established by their own Acts of Parliament -
caught only because each one was independently cross-checked against
GTEC's own accredited-institutions list before being filed (see
`docs/evaluation.md`'s addendum after Failure 13). The same discipline
applies to every institution name added anywhere in this file, not just
new categories.

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

## Adding real per-institution programme data (the mechanism now exists - UG and KNUST are done, everything else isn't)

As of Failure 13's fix, there IS a per-institution entity with its own
real programmes and cutoffs: `data/structured/institution_programmes.json`,
queried by `app/tools/institution_programme_lookup.py`
(`lookup_institution_programmes`, exposed to chat). It currently has 197
rows across exactly 2 institutions - University of Ghana (63 rows, from
UG's own official admissions page) and KNUST (134 rows, from a
third-party site, flagged lower-confidence). Every other institution
anywhere in `programmes.json`'s `institutions_example` lists - UCC, UEW,
UDS, UHAS, UENR, UMaT, CKT-UTAS, SDD-UBIDS, UPSA, GIMPA, GCTU, UniMAC,
AAMUSTED, all 10 Technical Universities, and all 15 private universities
- has ZERO rows here. `lookup_institution_programmes` returns
`has_data_for_institution: False` for all of them, correctly, rather than
guessing.

**To add another institution:**

1. **Source a real spreadsheet or published list** for that institution's
   own cutoff points - its own official admissions page if possible (like
   UG's), a third-party aggregator if not (like KNUST's, but mark
   `confidence: "third_party_source"` and say so explicitly, same as
   KNUST).
2. **Transcribe it verbatim** into the same row shape already in
   `institution_programmes.json` (`institution`, `college_or_category`,
   `programme`, `cutoff_display`, `level`, `confidence`, `source_url`,
   plus `fee_paying_cutoff_display`/`subject_requirements`/`notes` where
   the source actually has them) - don't normalize or "clean up" a messy
   source value like UG's `"16(24)M"` into a single number; preserve it
   and let the reader see the real source text. A one-off transcription
   script (pandas reading the raw spreadsheet, writing the JSON) is the
   right tool for this, not manual JSON editing for more than a handful
   of rows.
3. **No code changes needed** - `lookup_institution_programmes` and
   `list_institutions` both already read whatever's in the data files;
   adding rows is purely a data change.
4. **Update `institution_programmes.json`'s own `_coverage_note`** to
   remove the institution from the "has no data" list.
5. Re-run `pytest tests/` - nothing should break from adding rows alone,
   but add a test exercising the new institution's data the way
   `test_institution_programmes_carries_real_rows_even_when_model_narration_invents_others`
   does for UG.

**Why this is still a real bottleneck, not a code gap:** most Ghanaian
institutions don't publish a clean, citable, machine-readable cutoff list
the way UG does. Budget finding one per institution as a research task,
same as this file already said before Failure 13 - the difference now is
there's a working end-to-end mechanism (data file → tool → chat →
deterministic rendering → fabrication-guard backstop) ready to receive
real data the moment someone sources it, instead of nothing at all.

**The fabrication-guard backstop (`app/tools/institution_claim_guard.py`,
see Failure 14) only knows about institutions already in
`programme_lookup.all_known_institution_names()`** - i.e. institutions
that appear in SOME category's `institutions_example` in `programmes.json`.
An institution that exists in the real world but isn't named anywhere in
this project's data yet can't be flagged if the chat model mentions it,
simply because the guard has no way to know it should be checking that
name at all. Adding an institution to a category's `institutions_example`
(the earlier section of this file) is what makes the guard aware of it -
a reason to do that step even before sourcing per-programme data for it.
