# Slovenia `si_arso`: final review alignment and merge into `main`

Manual checks of Slovenia ARSO (`si_arso`) data on `port/si-arso` went smoothly,
and the provider's hydrological values, unit conversions, timezone handling, and
catalogue scope are already verified. Before merging into `main`, bring
`port/si-arso` up to date with recent engine improvements on `main` and with
repository-wide testing and documentation standards, re-verify the complete
provider end to end, and merge into `main` only after Thiago explicitly approves
in [#1040](https://github.com/RivRetrieve/RivRetrieve/issues/1040).

Delivering this vision, including the approved merge into `main`, completes
[Effort #1040](https://github.com/RivRetrieve/RivRetrieve/issues/1040) under
[Program #340](https://github.com/RivRetrieve/RivRetrieve/issues/340). Steps 1
through 7 (#1033 to #1039) are closed; their evidence and the latest Step 8
review guide are recorded in
[#1040](https://github.com/RivRetrieve/RivRetrieve/issues/1040#issuecomment-7143837705).

## Starting state and repository context

At the time of authoring:

- `RivRetrieve` `port/si-arso` is at `88346b14` (linearly rebased onto
  `0a26499e`, PR #1032 canonical ISO 8601 frequencies).
- `RivRetrieve` `origin/main` is at `0382dd8c`, adding `cl_dga` (#1044),
  `ee_est` (#1115), shared source request planning (#1094), station explorer v3
  catalogue (#1110), multi-timezone/regional sampling guidance (#1085), numeric
  overlap guidance for external dataset comparisons (#1097), and the documented
  Step 8 review gate (`0626a83d`). `main` currently has **21 providers in 20
  countries**, so adding `si_arso` brings the package to **22 providers in 21
  countries**.
- `RivRetrieve/verification-evidence` `port/si-arso` is at `27bcca2`, behind
  VE `origin/main` (`0da528c`), with a single merge conflict in
  `inventory/collections.json`.
- A trial merge of `port/si-arso` (`88346b14`) with `origin/main` (`0382dd8c`)
  conflicts only in routine cross-provider files: `README.md`,
  `tests/conftest.py`, `tests/test_catalogue_evidence.py`,
  `tests/test_catalogue_origin_certification.py`, `tests/test_frequency.py`,
  `tests/test_package.py`, `tests/test_station_metadata.py`, and
  `tests/test_station_metadata_areas.py`.

Already satisfied on `port/si-arso` (no rework needed):

- **Catalogue scope and metadata:** `619` river and canal gauges (`615`
  selectable, `5,628` series), `EPSG:3912 -> EPSG:4326` coordinate transform,
  and preserved `88888.88` / `99999.99` catchment sentinels.
- **External benchmark numeric overlap (#1097):**
  `research/si-arso-benchmark-comparison.md` (in `verification-evidence`)
  already reports exact overlapping non-null day counts (`18/18` WMO/GRDC gauges
  across `219,874` gauge-days; `7/7` WoKaS ARSO-ID gauges) and reports Caravan /
  GRDC-Caravan / LamaH-CE separately as `0` Slovenian stations.
- **Single-region temporal facts (#1085):** Slovenia is a single national
  timezone; ARSO `amp/` is fixed `CET` (`+01:00`) year-round and historical
  archive CSVs carry `time_zone="unknown"`.
- **Single-chunk archive & 1:1 station IDs:** `si_arso` uses
  `WindowGranularity("date")` (one `p_od_leto..p_do_leto` GET per requested
  window, not fixed-year chunking) and 1:1 four-digit `sifra` identifiers. It
  therefore does not need an `ObservationPlan.finalize` partial-chunk hook or
  multi-code station discovery.
- **`annotations.py` schema wording:**
  `src/rivretrieve/_internal/providers/si_arso/annotations.py` cites ARSO's
  official documentation without hardcoding a year cutoff.

## 1. Shared source request planning (#1094)

`si_arso` currently uses the legacy `shared_acquisition_products` declaration
(`src/rivretrieve/_internal/providers/si_arso/declaration.py` and
`SHARED_ACQUISITION_PRODUCTS` in `config.py`) and manual request grouping in
`src/rivretrieve/_internal/providers/si_arso/fetch.py`.

- Migrate `si_arso` to a `SiArsoRequestPlanner` implementing
  `SourceRequestPlanner` (following `LtLhmtRequestPlanner` and
  `EeEstRequestPlanner` on `main`), declare `request_planner` on `_Stages`, and
  remove `shared_acquisition_products` / `SHARED_ACQUISITION_PRODUCTS`.
- Keep single-pass `parse_group` decoding across co-published columns in each
  shared route (`b_oddo_CSV` daily `Q`/`H`/`T`, `b_eks_CSV` monthly min/max,
  and `amp/` `t_1`, `t_7`, `t_30`). Route direct `fetch()` calls through
  `execute_planned_acquisition` so direct `fetch()` and `driver.drive()` share
  one planning path.
- Add `--logic-only` planner tests exercising `driver.drive()` / `rr.fetch` end
  to end for:
  - whole-selection multi-product coalescing and single-pass `parse_group`
    decoding (one HTTP call and one decode per shared route);
  - partial cache reuse / mixed cache eligibility (when one product is already
    cached and a co-published product is uncached, the shared download updates
    only the uncached product and leaves the cached series and its vintage
    untouched);
  - shared transport failure accounting (one `call_id` attached to all affected
    `(station, product)` consumers) and per-column failure isolation (a
    malformed column fails only that product).

Internal planner helper structure and test fixture layout are left to the
implementing agent.

## 2. Value-based recorded replay tests (`docs/maintenance/testing.md`)

Follow the repository testing philosophy in
[`docs/maintenance/testing.md`](../../docs/maintenance/testing.md): recorded
replay tests must compare timestamps and values together against independently
read source values, and must not compute expected values or identities with
helper parsers or the code under test.

- Scope: `tests/test_si_arso_recorded_public.py` in `RivRetrieve` and
  `tests/source/test_si_arso_retrieval.py` in `verification-evidence`.
- Remove dynamic body-parsing helpers (`_decode_oddo_col`, `_decode_amp_col`)
  and replace count-only / `height > 0` / `min() < 0` checks with handwritten
  `(time, value)` pairs read directly from the retained captures. Row-count
  assertions may remain as additional checks.
- Together, the handwritten `(time, value)` assertions must cover every key
  behavior already exercised by the retained captures:
  - daily archive `Q`/`H`/`T` including `cm -> m` stage conversion and
    `Verificirani podatki` annotation (`1060` 2024 leap year);
  - monthly archive `eks` instantaneous min/max (`1060` 2024);
  - deep historical `1895` reach (`3660`);
  - negative gauge-zero stage (`1058`), zero discharge (`1030`), and ragged
    historical rows (`1020`);
  - operational `amp/` `t_1`, `t_7`, `t_30` cadences (`PT5M` / `PT10M` /
    `PT30M` / `PT1H`), fixed `+01:00` timestamps, `rr.to_utc()` conversion to
    `+00:00`, and `Začasni podatki` annotation;
  - `amp/` dash outage (`1312`) and deferred conductivity column (`7409`).
- Assert expected `published_id`, `series_id`, and `facts_id` as literal strings
  rather than constructing them with `source_series(...)`.
- All required captures are already retained in `verification-evidence`; no new
  live captures are needed. Choice of representative rows from each capture is
  left to the implementing agent.

## 3. Documentation accuracy (`docs/providers/si_arso.md` only)

Apply these two accuracy fixes in `docs/providers/si_arso.md` (without changing
`docs/maintenance/provider-ports.md` or other provider guides):

- **Archive table `variant` clarity:** In the **Validated historical archive**
  table, `variant` is `null` on all 9 archive products (`series.py`), so
  `rr.pick(sel, variant="Q_MIN")` or `variant="pretok (m3/s)"` matches nothing.
  Rename that table's `"Source field / variant"` column (for example to
  `"Native series code"` or `"Source column"`), state plainly that `variant` is
  `null` on archive products, and show the `published_id` form. Keep
  `"Source field / variant"` on the **Operational telemetry** table, where
  `variant` (`"operational_10min"`, `"operational_30min"`,
  `"operational_hourly"`) is populated and filterable.
- **Dated archive cutoff:** In the `Time and data status` section, date the
  `Verificirani podatki: quality-controlled archive records through 2024-12-31`
  bullet (as of `2026-11-23`) so it reads as a snapshot observation rather than
  a permanent cutoff.

Keep `tests/test_si_arso_documentation.py` aligned with the updated guide.

## 4. Branch integration, `verification-evidence`, and Step 8 approval gate

### `verification-evidence`
- Rebase `verification-evidence` `port/si-arso` onto VE `origin/main`
  (resolving `inventory/collections.json`), update
  `tests/source/test_si_arso_retrieval.py` for section 2 (and any `#1094`
  planner alignment if needed), and merge `port/si-arso` into VE `main` via PR.
- After `RivRetrieve` `port/si-arso` is updated and rebased, run the controlled
  `verify.py --catalogue-inputs` certification against the final rebased tip and
  merge the acceptance receipt into VE `main` via PR.

### `RivRetrieve`
- First, linearly rebase `port/si-arso` onto current `origin/main` (0 merge
  commits; push with `--force-with-lease`) so the `#1094` request-planning
  infrastructure (`request_planning.py`) is present on the branch, resolving
  cross-provider conflicts so `cl_dga`, `ee_est`, and `si_arso` are all
  represented (**22 providers / 21 countries**).
- Land the `#1094` planner, recorded replay test, and documentation updates on
  `port/si-arso` through a PR into `port/si-arso`. If `origin/main` advances
  before final certification, perform a final linear rebase onto `origin/main`
  (`--force-with-lease`) before recording the final acceptance receipt.
- Update and regenerate all cross-provider files that depend on the provider
  set:
  - script-regenerated artifacts: `docs/assets/coverage-map.png` and
    `docs/_generated/reference-tables.md`;
  - hand-updated prose and tests: `README.md` provider/country counts and table
    (**22 providers / 21 countries**), `docs/catalogue-provenance.md`
    (**23 enrolled providers** including deferred South Africa), and
    `tests/test_frequency.py`;
  - verify `docs/scripts/generate_station_catalogue.py` runs cleanly with the
    station explorer v3 catalogue (#1110).
- Rebuild `si_arso/catalogue/` through `verify.py --catalogue-inputs` only if
  required by provenance or origin certification after VE `main` merges;
  otherwise keep the certified catalogue intact.

### Full review and merge gate
After the rebase and VE receipt merge, perform a full review of the complete
`port/si-arso` branch (not just the fix diff) and verify all checks pass on the
final tip:

- `ruff format --check src tests scripts docs/scripts/coverage_map.py` and
  `ruff check src tests scripts docs/scripts/coverage_map.py`;
- `ty check src`;
- `scripts/generate_reference.py --check` and `scripts/check_lockfile_sources.py`;
- full `uv run pytest --logic-only`;
- required GitHub Actions CI checks;
- controlled `verify.py --catalogue-inputs` acceptance receipt recorded on
  `verification-evidence` `main` covering both the `si_arso` test suite and
  catalogue origin / descriptor / station-metadata certification (`-k si_arso`).

Post the complete verification summary and receipt links in
[#1040](https://github.com/RivRetrieve/RivRetrieve/issues/1040). **Do not open
or merge the final PR from `port/si-arso` into `main` until Thiago explicitly
approves in #1040.** Passing checks, closed Efforts #1033–#1039, or this vision
do not authorize the merge on their own. If anything changes after the review,
re-run checks and record a fresh receipt on the new tip before merging. Once
Thiago explicitly approves the final tip in `#1040`, open and merge the PR from
`port/si-arso` into `main` with a **merge commit**, verifying that the PR text
and merge payload contain no unintended closing keywords for issues other than
`#1040`.

## Out of scope

- Changing `si_arso` hydrological data behavior, unit conversions, timezone
  semantics, `annotations.py`, or station/series catalogue scope.
- Modifying `docs/maintenance/provider-ports.md` or other providers' guides.
- Capturing new live HTTP recordings unless an existing retained capture is
  proven insufficient.
