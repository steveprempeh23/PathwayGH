Replace the existing section in docs/extending-data.md:

## Adding real per-school data (a bigger undertaking - not done yet)

with:

## Adding real per-school data

`data/structured/institutions.json` now has a first pass at this: 114 real,
named Ghanaian SHS, each with its GES category (A/B/C) and a `source_url`
pointing at the specific Wikipedia article or YEN.com.gh/GhResults.com
category listing that stated it. Loaded via
`app/tools/institution_lookup.py` (`load_institutions()`,
`schools_by_region()`, `schools_by_category()`), tested in
`tests/test_institution_lookup.py`.

**What this is:** a sourced directory of which schools exist and their GES
resourcing tier (A/B/C), covering 12 of 16 regions (see the dataset's
`_coverage_note` for the 4 regions - Western North, Oti, Savannah, North
East - not yet sourced).

**What this still is NOT, deliberately:** per-school programme offerings or
per-school aggregate cutoffs. Those need the same real, school-by-school
sourcing work the original note below described, and still aren't done.
Do not add them by estimating - follow the same `confidence`/`source_url`
discipline already in this file, or leave the field out.

**Not wired into chat.** Per Failure 6 in `docs/evaluation.md`, this project
already has evidence that free-text-parsed tools fail in several different
ways on this chat model. If you expose school lookup to chat, make it a
structured, non-free-text path (e.g. a dropdown/filter on the `/calculate`
results card), not a new chat tool the model parses text into.

**Extending it further:**

1. Add entries to `ENTRIES` in the (throwaway) build script this pass used,
   or just append objects directly to `data/structured/institutions.json`
   following the existing shape - `name`, `region`, `ges_category`,
   `confidence`, `source_url`, plus optional `gender`/`town`/
   `accommodation` only where your source actually states them.
2. Update `_coverage_note` if you add a previously-missing region, and
   remove the `test_known_coverage_gaps_are_absent` guard for that region.
3. Re-run `pytest tests/test_institution_lookup.py`.
4. Programme offerings and per-school cutoffs are still the real bottleneck
   described below - budget that as research, not a quick JSON edit.
