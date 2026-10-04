# Reject false native metadata provenance

Related issue: https://github.com/RivRetrieve/RivRetrieve/issues/493

## Outcome and scope

Reject explicit station metadata that claims historical-native support but differs
from the corresponding native projection. A matching column name must never be
sufficient to establish where a published value came from.

This work addresses #493 only. Do not resume or extend the metadata redesign in
#484 and #490. Do not regenerate provider products, acquire new source material,
change metadata presentation, or perform unrelated cleanup. Preserve existing
source declarations and exposure semantics. The owner will tell the paused agent
which bug-fix PR merged; no additional resumption workflow is required.

Both this vision and the subsequent bug-fix PR target
`feat/source-faithful-metadata`. The defect was introduced in its unmerged commit
`8a33fcc0e8ef72c51e9047778efb791e99ca76b8`. At investigation time, `main` was
`ff78a5ab8532f9593ba507e522c97cecebeec42c` and did not accept explicit station
metadata projections. Do not import the unfinished feature into `main` to make a
standalone fix apply. Publication of this vision does not resume #484 or #490;
the bug-fix PR must merge first.

## Failure and evidence

The original station table can contain `name = "Station river"` while a
supplementary site source contains `name = "Site river"`. Both columns are named
`name`. If the supplementary declaration omits `source_facts`, publication checks
that the original table has that column but never compares its value. It accepts
the site value and assigns historical-native support to it. The value might be a
valid source fact, but its claimed lineage is false.

The following evidence was collected with synthetic inputs at the affected commit.
It does not establish acceptance of genuine provider inputs.

- `tests/test_catalogue_build_provenance.py::_scoped_metadata_publication` provides
  this exact pair of values and distinct source scopes. The positive test
  `test_explicit_projection_keeps_scoped_sources_and_their_own_acquisitions`
  correctly assigns `source.site` to the site value.
- Keeping its projection and publication arguments unchanged, but replacing the
  second field with `dataclasses.replace(fields[1], source_facts=())`, incorrectly
  succeeds. The emitted `metadata.water_body_name.site.name` binding then has
  only `native.latitude` as its external input. That fact name is the synthetic
  fixture's historical-native support, not a claim about a real latitude source.
- Further synthetic publication probes accepted a changed native-supported name,
  a changed value-to-`source_null` state, an elevation value of `4.0` against native
  `3.0`, `Float32` against native `Float64`, a datum code of `4` against native `3`,
  `Int32` against native `Int64` for the datum, and a null datum against native `3`.
  A unit conflicting with its field declaration was already rejected.
- `uv run pytest --logic-only tests/test_catalogue_build_provenance.py -q` passed
  all 117 tests, with one rdflib deprecation warning. Existing negative coverage
  changes the supplementary field name to an absent column, so it misses the
  same-name/different-value defect.

The investigation did not change source files, access private material, or accept
regenerated products.

## Required behavior

For every emitted, exposed row whose `MetadataField.source_facts` is empty,
publication must establish exact agreement with the native projection for that
station and declared field. Agreement includes scalar value and type, state,
unit, and datum association, including the native datum value and type where a
datum field is declared. Resolve station identity using the existing declared
identity conversion. Comparing unrelated stations or only matching column names
is insufficient.

Raise `FatalContractError` before publication when this contract fails. Do not
silently correct, drop, coerce, or relabel a conflicting row. A differing
supplementary value must have explicit source facts that satisfy the existing
adopted-source checks. Additional semantic or datum support must not bypass
validation of a value that still claims historical-native support.

Keep legitimate native-backed explicit projections and explicitly supported
supplementary projections working. Preserve per-station exposure:

- `source_null` means a field is exposed but its value is null. Keep its field,
  type, unit and applicable datum/support information.
- `no_metadata` means the role has no exposed metadata for that station.
- An unexposed supplementary field contributes no invented null row.
- Do not require every declared field at every station or compare the entire
  explicit frame against a complete native-only projection. Preserve the current
  global field-declaration checks rather than relaxing them as part of this fix.

Keep source values unchanged. Do not infer units or datum meanings, convert
values, choose preferred sources, or strengthen this into a redesign of the
supplementary-source evidence model.

## Relevant code and regression coverage

At the affected commit:

- `src/rivretrieve/_internal/catalogues/publication.py`,
  `build_catalogue_metadata`, lines 99–115, validates the supplied frame,
  declarations and native column existence without comparing native values.
- `_bind_catalogue_build_inputs`, particularly `supported_inputs` around lines
  354–358, selects historical-native support when `source_facts` is empty. The
  same fallback supports value and datum bindings.
- `src/rivretrieve/_internal/catalogues/station_metadata.py`,
  `build_station_metadata`, already defines native identity conversion, scalar
  encoding, dtype, state, unit and datum projection. `validate_metadata_fields`
  checks declarations but does not compare rows with native contents.
- `src/rivretrieve/_internal/station_metadata.py`, `source_metadata_frame`,
  validates row shape, role coverage, scoped uniqueness and state rules.

Choose a focused implementation at the publication validation boundary. Reuse
existing projection semantics where practical; the internal comparison mechanism
is not prescribed.

Add regression coverage that fails on the affected commit and passes after the
fix. Include the exact same-name/different-value reproduction, native scalar/type
and state mismatches, datum value/type/null mismatches, and station-specific
matching. Retain or extend positive controls for exact native matches, exposed
native nulls, explicit adopted supplementary sources, scoped fields, and
station-specific non-exposure. Existing unit/declaration and source-adoption
rejections must remain effective. Use the simplest sufficient shared tests;
do not expand into unrelated provider-specific work.

Run affected source-independent tests and checks proportionate to the changed
boundary, following `AGENTS.md` and `docs/maintenance/testing.md`. Review the diff
for bug-only scope. Synthetic tests establish the library contract, not genuine
source acceptance. Apply `docs/maintenance/evidence.md` if the implementation
changes governing claims or source bindings and requires full genuine-input
checks. Report unavailable mandatory evidence as blocked; do not substitute
synthetic or derived inputs for originals. Do not acquire new material or change
provider products under this vision.

Success means the previously accepted false-lineage cases fail with
`FatalContractError`, valid publication and exposure behavior remain intact, and
the focused bug-fix PR is merged into `feat/source-faithful-metadata`.
