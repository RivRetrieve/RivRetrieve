# Germany PEGELONLINE (`de_pegelonline`) — provider integration

Associated issue:
[#1020](https://github.com/RivRetrieve/RivRetrieve/issues/1020)
("PEGELONLINE provider port: 5. Provider integration"). Executing and
verifying this vision completes #1020 only; it does not by itself deliver
verification ([#1021](https://github.com/RivRetrieve/RivRetrieve/issues/1021))
or user documentation ([#1022](https://github.com/RivRetrieve/RivRetrieve/issues/1022)).

Builds on the merged step-1 ([#1030](https://github.com/RivRetrieve/RivRetrieve/pull/1030)),
step-2 ([#1041](https://github.com/RivRetrieve/RivRetrieve/pull/1041)/[#1042](https://github.com/RivRetrieve/RivRetrieve/pull/1042)),
step-3 ([#1047](https://github.com/RivRetrieve/RivRetrieve/pull/1047)), and
step-4 ([#1074](https://github.com/RivRetrieve/RivRetrieve/pull/1074))
visions, all already implemented on `port/de-pegelonline`. The primary
research record is issue [#874](https://github.com/RivRetrieve/RivRetrieve/issues/874)
(live-verified 2026-11-17); this vision does not reproduce that evidence
beyond what's needed to act.

## Outcome

Make `de_pegelonline` callable end-to-end through the public API
(`rivretrieve.fetch(...)`, `rivretrieve.providers()`, etc.): register it as a
built-in `LiveStages` provider with a real packaged catalogue, so discovery,
retrieval, and parsing all work together rather than existing only as
directly-callable functions in tests. Per the issue's own instruction,
validate with one representative station/product end-to-end first, then
extend to the full five-product scope already established in steps 1-3.

Everything below is a concrete, already-evidenced wiring task. Precedent
from `ch_foen`, `lt_lhmt`, and `au_bom` (each went through this exact step
for their own ports) settles every structural question; this is not open
design.

## Split `fetch.py`'s decoding logic into a new `parse.py`

Confirmed during this grill: among every provider in this codebase that
actually fetches live over HTTP with `fetch`/`parse` engine stages (as
opposed to a bulk-download/compile provider like `ca_eccc`/`cl_dga`/
`pl_imgw`, or a catalogue-only one like `za_dws`), **all of them** split
`fetch.py` (request construction, response status handling) from a separate
`parse.py` (response body decoding into rows) — `ar_ina`, `at_ehyd`,
`au_bom`, `ba_fhmzbih`, `br_ana`, `ch_foen`, `co_ideam`, `cz_chmi`,
`dk_vanda`, `fi_syke`, `fr_hubeau`, `fr_hydroportail`, `lt_lhmt`, `no_nve`,
`pe_senamhi`, `th_thaiwater`, `usgs_nwis`. `de_pegelonline` is currently the
only exception, purely because step 4 didn't need the standalone `parse`
stage yet. Split it now to match the universal convention, not to be the
one outlier:

- Move `_parse_records`, `_failed_parsed`, `_numeric_or_none`, and
  `_TRM_PRODUCTS` from `fetch.py` into a new `parse.py` (`DE_PEGELONLINE_TRM_SCHEMA`
  itself is already defined in `annotations.py`; `parse.py` just imports it,
  the same way `fetch.py` currently does). `fetch.py` keeps request
  construction (`_local_offset_isoformat`, the `_acquire`/`fetch` loop) and
  imports the decoding functions from `parse.py`, matching
  `ch_foen/official_fetch.py` importing from `ch_foen/official_parse.py`.
- Add the standalone `parse(payload: Payload, config: ProviderConfig) ->
  ParsedSeries` entry point `parse.py` must expose for the shared engine's
  `ProviderStages` protocol (`driver.py`'s `provider.parse(payload, config)`
  call, used when reusing a cached/replayed payload rather than a fresh
  fetch-time interpretation — `driver.py` around its interpretation-slot
  reuse logic). Derive `(station, product)` from
  `payload.station_products[0]` rather than taking them as separate
  arguments, exactly as `ch_foen/official_parse.py`'s
  `_validated_route_coordinates` does; raise `FatalContractError` if
  `payload.station_products` doesn't contain exactly one pair, or if that
  product's coordinates don't match `config.products[product]`.
  `fetch.py`'s own inline call during `_acquire` keeps calling the same
  underlying decode function so a fresh fetch never redundantly re-decodes.

## Build and commit the packaged catalogue

Step 2 deliberately deferred committing `stations.parquet`/`products.parquet`/
etc. because they need `source_series.json`, which needs step 3's series
identities (now merged). `generate_catalogue.py`'s `write_catalogue()`
function already exists for exactly this moment — its own docstring says it
"exists for the step that has those available." This vision's job is to
actually call it and commit the result:

- Add a `describe_*` function (matching `at_ehyd/generate_catalogue.py`'s
  `describe_associations`, the established precedent for a bespoke-builder
  provider) that iterates every station × product row in the native table
  and calls `series.source_series(station_id, product_id, unit=...,
  equidistance=..., gauge_zero_unit=..., origin="catalogue")` to build the
  `SourceDescriptions` `write_catalogue()`/`build_catalogue_metadata()`
  needs for `source_series.json`.
- Call `origins.py`'s existing `build_acquisition_provenance(...)` to get
  the `AcquisitionProvenance` object, then `generate_catalogue.py`'s
  `build_catalogue(native_table, origins, acquisition_provenance=...,
  station_metadata=...)` and `write_catalogue(...)` to produce the full
  packaged catalogue directory (core tables plus `source_series.json`,
  `provenance.json`, `provenance_*.parquet`, `format.json`, `croissant.json`).
- Commit the result to `src/rivretrieve/_internal/providers/de_pegelonline/catalogue/`,
  replacing the currently-committed `native.parquet`-only state, matching
  every other `LiveStages` provider's already-committed catalogue directory
  (`ch_foen`, `lt_lhmt`, `at_ehyd`, etc. each have one).

## Register the provider

**Ordering dependency, not optional sequencing:** `register_manifest`
(`providers/registration.py`) loads every declared provider's packaged
catalogue artifact *before registering any of them*, by design (its own
docstring: "a missing or corrupt catalogue refuse[s] the manifest rather
than exposing a partial catalogue"). `tests/conftest.py`'s
`packaged_catalogue_inputs` fixture does the same for every
`ACQUISITION_PROVENANCE_ENROLLED_PROVIDERS` entry. This means adding
`"de_pegelonline"` to either list **before** the full packaged catalogue
(the previous section) is actually committed and loadable breaks
registration/discovery and that fixture for **every** built-in provider,
not just this one. The catalogue commit must land, and be verified loadable
(`load_packaged_catalogue_artifact`), before or atomically with — in the
same merged change as — these two additions; do not split them across
separately-landing PRs in a way that leaves either list pointing at a
provider whose catalogue isn't fully committed yet.

- Add `"de_pegelonline"` to `provider_manifest.py`'s `BUILTIN_PROVIDER_IDS`
  (alphabetically, between `"cz_chmi"` and `"dk_vanda"` — `"de_..."` sorts
  before `"dk_..."`).
- Add `"de_pegelonline"` to `catalogues/artifact.py`'s
  `ACQUISITION_PROVENANCE_ENROLLED_PROVIDERS` — a different list than the one
  step 2 already added it to (`catalogue_origins.py`'s
  `ORIGIN_GATE_ENROLLED_PROVIDERS`, already satisfied); this one gates
  `load_packaged_catalogue_artifact`'s requirement that a provenance file
  accompany the packaged catalogue once it's committed.
- Create `declaration.py`:
  ```python
  class _Stages:
      observation_source = "live"
      config = config()
      window_declarations = window_declarations()
      fetch = staticmethod(fetch)
      parse = staticmethod(parse)

  declaration = ProviderDeclaration(
      catalogue=Path(__file__).with_name("catalogue"),
      observations=LiveStages(stages=_Stages),
      required_credentials=(),
  )
  ```
  No `shared_acquisition_products` — each of the five products is an
  independent per-station×product×window acquisition (step 4's own
  decision), not a co-published response like `lt_lhmt`'s.

## Explicitly out of scope / excluded

- Verification against a comparison dataset, cache/store behavior checks,
  and catalogue-lineage verification are [#1021](https://github.com/RivRetrieve/RivRetrieve/issues/1021)'s
  job (step 6), not this vision's. This vision's own "working end-to-end"
  check is a representative smoke test, not the full verification pass.
- The provider documentation page is [#1022](https://github.com/RivRetrieve/RivRetrieve/issues/1022)'s
  job (step 7).
- No new annotation schemas, quantities, units, or vertical-reference logic
  — all already settled in steps 2-3; this vision only wires existing
  pieces together.

## Completion evidence and boundaries

Verify with a real end-to-end `rivretrieve.fetch(provider_id="de_pegelonline",
...)` call against one representative station/product (e.g. `HOFKIRCHEN`/`Q`,
the station used throughout #874's live verification), then extend to all
five products. Run `uv run pytest tests/test_de_pegelonline_*.py --logic-only`
plus the full suite (`uv run pytest --logic-only`) before calling this done,
and confirm no regression in the already-merged catalogue, series, and
fetch tests. Continue the private research record
(`research/de-pegelonline-source-access.md` in
[verification-evidence](https://github.com/RivRetrieve/verification-evidence))
rather than starting a parallel history.
