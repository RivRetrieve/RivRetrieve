# Australia BoM rebuild certification

Closes [Effort #695](https://github.com/RivRetrieve/RivRetrieve/issues/695)
under [Program #334](https://github.com/RivRetrieve/RivRetrieve/issues/334):
`au_bom` was the one enrolled provider missing from
`tests/test_catalogue_origin_certification.py::test_native_composition_root_rebuilds_committed_artifacts_without_network`,
a gap named and deliberately deferred during Effort #648. Work targets
`port/au-bom` and leaves `main` unchanged.

## What was missing, and why

`src/rivretrieve/_internal/providers/au_bom/generate_catalogue.py` had a
`read_catalogue_sources()` that read retained captures directly, without
verification, and no CLI `main()` — unlike every other enrolled provider.
The catalogue that already shipped (Effort #644) was built once, correctly,
through an uncommitted ad hoc script, not through this module. Closing the
gap needed two things, done together since one could not be verified without
the other:

1. A real CLI `main()` on `generate_catalogue.py`, and `read_catalogue_sources()`
   rewritten to the `ch_foen` shape: real `RetainedInputReceipt` verification
   (`verify_retained_input_files`), a real `AcquisitionProvenance` built from
   the selection file's now-complete fields, and a cross-check that the native
   table recomputed from the 3 station-list captures agrees byte-for-byte with
   the separately retained, receipt-verified `native_table` member.
2. A completed selection declaration at
   `maintenance/catalogue/au_bom/official/catalogue.json` (in
   `verification-evidence`, delivered in a paired PR there). A draft of this
   file already existed at `declarations/au_bom/catalogue.json` — committed
   incidentally alongside an unrelated USGS commit, never moved to the path
   this code already expected — with the 25 captures but missing
   `publication_acquisitions`, `source_bindings` and `statements`, exactly the
   gap #695 named.

## Two real bugs found while making this work, not introduced by it

Running the completed pipeline against the real retained files (fetched
genuinely via `archive fetch` against collections
`au_bom-catalogue-2026-11-02-v1` and `au_bom-catalogue-native-2026-11-03-v1`,
already registered since #648) reproduced the already-shipped catalogue
byte-for-byte except for `provenance_external_inputs.parquet` (and the files
that embed it, `provenance.json` and `croissant.json`). The cause:
`src/rivretrieve/_internal/providers/au_bom/origins.py`'s
`NATIVE_TABLE_ACQUISITION_IDS` listed the three station-list **recording**
ids, not the one real **acquisition** id (`station_lists`) that
`publication_acquisitions` actually declares. `select_catalogue_build_inputs()`
could never have resolved against the recording ids; the original ad hoc
script evidently never exercised this exact path, so the error went
unnoticed until this effort tried to.

Fixed `NATIVE_TABLE_ACQUISITION_IDS = ("station_lists",)`. This is a real
content correction, not a cosmetic one: it changes which source facts the
`metadata.station_name.station_name` transformation is shown to depend on
(now both `source.station.station_list` and
`source.station.georefsystem_documented`, matching what the `station_lists`
acquisition's own `FactBinding` already declares — previously only the
first). The shipped `provenance.json`, `provenance_external_inputs.parquet`
and `croissant.json` are refreshed in this PR to reflect the fix; every other
shipped file (`products.parquet`, `stations.parquet`, `station_products.parquet`,
`provenance_facts/bindings/acquisitions/binding_facts.parquet`,
`source_series.json`, `series_claims.parquet`, `station_metadata.parquet`,
`provider.json`, `format.json`) is confirmed byte-identical, unaffected.

A second, cosmetic issue was found and corrected in `tests/_provenance.py`:
`au_bom`'s own selection-file declaration
(`maintenance/catalogue/au_bom/official/catalogue.json`) needed an entry in
that test helper's `private_declarations` map (self-mapped, since au_bom's
"public" declaration path and its real archive path are now the same string),
matching the existing pattern used for every other provider's own private
declaration file there. Without it, `test_historical_projection_preserves_sources_and_validates_metadata[au_bom]`
would fail to recognise the already-correct `verification-evidence`
attribution on that declaration.

## What was deliberately not changed

- `CATALOGUE_BUILD_DECLARATIONS`'s `"maintenance/catalogue/station_metadata/review.json"`
  path looked like a third bug at first (the real file lives at
  `declarations/station_metadata/review.json`) but is not one: every
  provider's build declares this same "public" path, and
  `tests/_provenance.py`'s `private_declarations` map already translates it
  to the real path for every provider, `au_bom` included once registered
  there. `AuthoredDeclarationInput.consumer_path` (what the build looks up)
  and `.declaration.repository_path` (the real git identity) are
  deliberately separate fields for exactly this reason.
- The station metadata path (`station_name` projected directly from the
  native table, no supplementary source) needed no change to
  `build_catalogue`/`write_catalogue`'s signatures: `station_metadata=None`
  already means "build from `native_table` by the shared implementation",
  which is what `au_bom` already did.

## Verification

- `build_acquisition_provenance()`, called directly with the completed
  selection file's new fields, reproduces the shipped `provenance.json`'s
  exact claims (fact universe, fact bindings, source records), modulo
  `build_inputs` and `metadata.*` facts.
- The full `read_catalogue_sources → build_catalogue → write_catalogue`
  pipeline, run against the genuinely retained captures (fetched via
  `archive fetch`, not assumed), reproduces all 15 shipped catalogue files;
  the 3 that legitimately changed are refreshed in this PR and documented
  above.
- `uv run pytest --logic-only -q`: full suite passes.
- `tests/test_catalogue_origin_certification.py::test_native_composition_root_rebuilds_committed_artifacts_without_network[au_bom]`
  and `::test_each_provider_build_enforces_the_origin_gate[au_bom-stations]`
  both pass locally against a self-built `RetainedInputReceipt` and
  `CatalogueBuildInputs` (real file hashes from the genuinely retained
  evidence, not committed anywhere) — this is not the reviewed coordinator's
  own signed receipt, so these tests still need that receipt, regenerated to
  include `au_bom`'s new consumer paths, to actually run in CI.
- `tests/source/test_au_bom_catalogue.py` (already written during #644,
  previously unable to run for want of these files) passes against the
  genuinely retained evidence once materialised at
  `maintenance/catalogue/au_bom/official/*`.
- `uv run ruff check` and `uv run ty check` clean on every changed file; the
  5 pre-existing `ty check` findings in `tests/test_catalogue_origin_certification.py`
  (loose `partial()`/`object`-typed returns, present on `port/au-bom` before
  this change) are unrelated and untouched.
