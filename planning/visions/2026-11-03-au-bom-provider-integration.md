# Australia BoM provider integration

Make BoM observations available through RivRetrieve's public selection,
retrieval and cache interfaces under `au_bom`. Deliver the agreed scope for
[Effort #647](https://github.com/RivRetrieve/RivRetrieve/issues/647) (step 5
of the [provider-port guide](../../docs/maintenance/provider-ports.md)) and
[Program #334](https://github.com/RivRetrieve/RivRetrieve/issues/334),
combined into one PR, following `at_ehyd`'s own step-5 precedent (PR #676).

Work targets `port/au-bom` and leaves `main` unchanged until final review
([#650](https://github.com/RivRetrieve/RivRetrieve/issues/650)) approves
merging. Full-provider verification against genuine retained public-API
captures stays in [#648](https://github.com/RivRetrieve/RivRetrieve/issues/648);
the dedicated provider documentation page stays in
[#649](https://github.com/RivRetrieve/RivRetrieve/issues/649). This step does
not defer the checks needed to establish correct public integration itself.

## Build on the delivered provider work

At this revision, #643 through #646 are complete: the packaged catalogue
supports offline discovery of 8,120 river-gauge stations across 18 admitted
products; `series.py` resolves the duplicate-`ts_id` identity question;
`config.py`/`fetch.py`/`parse.py` implement the actual KiWIS request/response
handling. `declaration.py` still declares `CatalogueOnly()`, leaving public
observation retrieval disabled — switching that is this step's actual work.

## Deliver working public retrieval

Connect `config()`, `window_declarations()`, `SHARED_ACQUISITION_PRODUCTS`,
`fetch` and `parse` to `LiveStages` in `declaration.py`, with
`required_credentials=()`, mirroring `lt_lhmt`'s and `at_ehyd`'s own
`_Stages` class shape exactly. Reuse shared discovery, transport, unit
conversion, clipping, assembly, receipt recording and local-store machinery
across all 18 products, with `fetch.py`'s one shared `getTimeseriesList`
lookup per station covering every one of them at once.

Update the repository-wide capability contracts so they reflect live
`au_bom` retrieval:

- `docs/_generated/reference-tables.md` (`scripts/generate_reference.py`):
  `au_bom`'s observation kind changes from `catalogue-only` to `live`.
- `docs/scripts/coverage_map.py` and `docs/assets/coverage-map.png`: `au_bom`
  moves from `PLANNED_COUNTRY` to `PROVIDER_COUNTRY` (`"AUS"`), and the map
  regenerates to show Australia implemented rather than planned.
- Root `README.md`'s provider table: adds Australia / Bureau of Meteorology
  (BoM) / `au_bom` / 8,120 stations / Open access, and updates the count
  sentence from "thirteen different providers in twelve countries" to
  "fourteen different providers in thirteen countries". Unlike `at_ehyd`'s or
  `ch_foen`'s rows, `au_bom`'s packaged `stations.parquet` is already scoped
  to the fully selectable river-gauge set (8,120 of 8,120) — #644's
  `river_gauge_native_table()` already did this narrowing at catalogue-build
  time, so no "retains X, Y selectable" caveat sentence is needed here the
  way those two providers' rows have one.

Also corrects a now-stale claim: #644's packaged `catalogue/provider.json`
states `"bulk_observations": "false: ... observation retrieval is
unavailable"`, written when `au_bom` was `CatalogueOnly`. That claim is false
once this step ships. `generate_catalogue.py`'s `build_provider_info()` and
the already-published `catalogue/provider.json` both get the corrected text,
describing the real mechanism this step and #646 actually built: a shared
per-station `getTimeseriesList` lookup across every requested product, a
station's duplicate `ts_id` for one product combined into one
`getTimeseriesValues` call, and HTTP 500 retried by the shared transport
before being reported as a recoverable issue. This is a direct text
correction using the already-reviewed, already-published build inputs from
#644 — not new research, and not a full catalogue rebuild from fresh
evidence. Extending `tests/test_catalogue_origin_certification.py`'s
all-provider rebuild-from-retained-inputs comparison to include `au_bom`
remains #648's job: `au_bom` is not yet one of that test's parametrized
cases, for any provider, confirmed by reading the file directly.

## Preserve source meaning and selection semantics end to end

Public retrieval must preserve the facts #645 and #646 already established:

- Convert discharge from `m3/s` (native `cumec`) and preserve stage (`m`) and
  water temperature (`degC`, native `°C`) with no conversion factor —
  confirmed in #646 via `admission()` returning `factor=1.0` for all three.
- Preserve the `+10:00` time zone on every row, and the genuine published
  null found live during #646 (a timestamp with no value), rather than
  dropping or zeroing it.
- Surface a station's duplicate `ts_id` for one product as two distinct
  `series_id` under the public API, never picking a winner — confirmed with
  a public, synthetic two-`ts_id` test below (one `SUCCESS`, one `EMPTY`),
  mirroring `usgs_nwis`'s identical native-duplicate-identity precedent.
- Emit one `info`-severity issue per non-`quality-A` row (`source.quality_code`,
  per #646's `jp_mlit`-style design) without ever filtering the value itself.
- Report `NO_MATCH` when a station's `getTimeseriesList` lookup does not
  resolve a requested product's `ts_id`, and report a transport failure as
  an `error`-severity issue, both through the public `rr.fetch` surface, not
  only through the internal `fetch()`/`parse()` unit tests #646 already has.

**A real selection-level finding from writing these tests:** `au_bom`'s
catalogue cannot pre-resolve a `series_id` the way `at_ehyd`'s
`Messstellen/info`-derived file numbers can, because `au_bom`'s series
identity is only known once a live response names a concrete `ts_id` (#645).
An explicit `series_id` restriction built from catalogue-level identities
therefore matches nothing once a real fetch resolves its own, different
`series_id` from the live `ts_id` — confirmed directly: a test restricting a
selection by catalogue `series_id` returned zero rows with a
"no source series matches" warning. Selecting by physical predicates
(`quantity`, `frequency`, `statistic`) works instead, with one caveat:
discharge's `24HR` and `09HR` daily means share identical
`quantity="discharge", frequency="daily", statistic="mean"` predicates (#645
deliberately left `day_definition` unestablished in `PhysicalFacts`, so
nothing distinguishes them at that level), so a predicate-only selection is
ambiguous between them. Stage has no `09HR` sibling, so its daily mean is
unambiguous and is what this step's public tests select by. This is a real,
user-facing limitation worth naming plainly in #649's documentation: picking
a specific discharge daily-mean series by physical predicates alone cannot
distinguish `24HR` from `09HR` today.

## Verification and handoff

- Offline discovery (`rr.find`, `rr.pick`, `rr.series`, `rr.metadata`,
  `rr.describe`) stays network-free after `LiveStages` registration.
- `tests/test_au_bom_public.py` (new): public synthetic integration tests
  through `rr.find`/`rr.pick`/`rr.fetch`, covering unit conversion, the
  duplicate-`ts_id` split, the quality-code issue, `NO_MATCH`, and a reported
  transport failure — all without credentials, matching `au_bom`'s
  `required_credentials=()`.
- Genuine recorded public replay (`at_ehyd`'s equivalent
  `tests/test_at_ehyd_recorded_public.py`, exercising retained real HTTP
  captures through the public API) is **not** delivered in this PR. It needs
  genuine retained captures through the private archive's restricted
  coordinator-gated intake process, consistent with every other
  genuine-evidence requirement flagged throughout this port (#644's
  `RetainedInputReceipt` path, #648's governing tests). This is named
  explicitly as #648's work, not silently skipped.
- `uv run ruff check`, `uv run ty check src` and `uv run pytest --logic-only`
  all pass with no regressions.

Post a concise scope-and-delivery update on #647. Close #647 once this PR is
merged, matching the pattern used for Efforts #643 through #646.
