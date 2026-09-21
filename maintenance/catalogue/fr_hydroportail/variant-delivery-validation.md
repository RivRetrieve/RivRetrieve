# HydroPortail variant validation

## Scope

Four source-published station-own selectors are supported for both Q and H:
`raw`, `validated`, `pre_validated_and_validated`, and `most_valid`.
Raw source and physical-facts IDs are unchanged. Existing exports keep their
original null variant until new acquisition supplies current definitions.
No corrected-only or pre-validated-only series, preferred default, local status
filter, or public API was added.

Historical availability rows and acquisition provenance remain byte-identical.
Their reasons explicitly describe raw observations. Other selectors remain
selectable without historical availability assertions. Inventory snapshots remain
incomplete: static supported mappings do not certify exhaustive current source
inventory. Explicit covered members can reuse cache; unrestricted acquisition
requests all supported selectors again.

## Requirements and proof

| Requirement | Tests or evidence |
|---|---|
| Q/H discovery and individual selection | `test_public_discovery_exposes_all_source_variants`; catalogue generation tests |
| Exact outgoing selector, units, UTC labels, empty envelopes | `test_recorded_source_variant_public_path` (16 cases); independent source recordings/report |
| Overlapping source values retain identities | `test_recorded_unrestricted_overlaps_keep_source_identities` (Q/H) |
| No fallback; null, absent, empty, failed remain distinct | `test_null_absent_empty_and_failed_variants_remain_distinct` |
| Every empty selector validates full envelope | `test_empty_variant_checks_envelope_identity` (48 cases) |
| Subset then unrestricted acquisition and explicit cache reuse | `test_subset_cache_cannot_satisfy_all_variants_and_identical_rows_stay_distinct` |
| Real pre-change raw cache, result export, selection export | `test_pre_variant_cache_and_exports_do_not_settle_expanded_scope`; retained legacy artifacts from 910d6ee |
| Native s/q/m/c bytes and exported results | Publisher receipt byte equality and bundle assertions in variant tests |
| Raw witness scope and IDs remain unchanged | Catalogue generation tests and existing raw boundary probes |
| Fatal internal contract remains fatal | `test_unknown_payload_product_is_fatal_contract_error` |
| Fresh source behavior | `tests/test_data/fr_hydroportail_variants/REPORT.md`, 32 exact Q/H responses plus form/scripts |

## Regression sequence

Actual pre-change discovery, explicit-selection and legacy-cache failure stdout
is in adjacent `*.red.txt` files. `variant-test-validation.md` records commands
and artifact capture. During implementation, an invalid internal payload product
initially raised `KeyError` before the shared parser could enforce its contract.
`contract.red.txt` records the failing direct parser regression;
`contract.green.txt` records the same test passing with `FatalContractError`.

## Validation status

- Offline source verification: 38 response/request hashes and 32 recorded source envelopes passed.
- Catalogue generation: 20 tests passed.
- Legacy artifact extended regression: passed.
- Genuine recorded selector/public overlap cases: 18 passed.
- Ruff lint, format check and `uv run ty check src`: passed.
- Existing raw witness suite: 31 passed, 2 existing openpyxl warnings.
- Independent live public path: 10 public fetches and 16 successful source calls passed for unrestricted and individual Q/H selectors. Only existing informational licence/citation unknown notices returned.
- Fresh parallel full suite: 4,036 passed, 1 existing private-evidence skip, 5 failures in 854.03 seconds. The failures were one outdated wheel source-series count and four offline builds missing `uv-build` in the relocated cache. The full original stdout is preserved in repository-local `.worktrees/evidence/hydroportail-implementation-validation/full-suite-initial.txt`; this report records its exact command and summary.
- The wheel count now checks all 12,818 station/quantity pairs times four variants and their exact selector set. No production code changed.
- A real `uv build --force-pep517 --wheel` populated the repository-owned cache. Offline packaging commands remain unchanged; their focused rerun is recorded below.
- A clean complete suite on the final target remains the root delivery audit gate.

The first in-progress full-suite run imported an earlier raw-only boundary test
before its explicit raw selection was added. The isolated current boundary probe
passes. This is a stale collected test, not a source or production failure.

## Compact evidence and additional checks

All original source bodies and direct-window recordings are retained losslessly
in `source-captures.tar.xz` (54 members). Test-consumed padded recordings remain
plain files. Independent live provenance, receipts and frames are retained in
`public-path.tar.xz` (57 members). Archive/member lengths and hashes are explicit
in `evidence-archives.json`; the archive test passed both archives. The offline
source verifier re-passed all 38 captures and 32 observation envelopes after
repackaging. See `PUBLIC_PATH_REPORT.md` for live methodology and its two
verifier-only preliminary interruptions.

Additional existing regression expectations were updated after targeted failures:
five measurement-cell tests now explicitly select their original raw witness, and
one normalized-metadata test expects four inspection rows with all four selectors.
Their unchanged checks retain native null/absent/invalid-cell semantics and raw
provenance. Actual before/after outputs are adjacent `raw-cells.*.txt` and
`metadata-rows.*.txt`. Post-update results: 5 passed and 1 passed respectively.

Independent review focused validation: 102 tests passed (variant, fatal-contract
and catalogue suites). Production remained unchanged during evidence compaction.

## Full-suite diagnosis and packaging rerun

Command: `uv run --extra map --with pytest-xdist --with geopandas --with matplotlib pytest -n4 -q`.
Result: 4,036 passed, 1 skipped, 5 failed, 79 warnings in 854.03 seconds.
The skip is the existing Thaiwater controlled-private-body acceptance test.
Failures: `test_wheel_carries_every_manifest_catalogue` had the old raw-only
series count; both `test_distribution_keeps_only_runtime_catalogues` cases and
both `test_distributions_exclude_local_files` cases lacked the offline build
backend in the fresh repository-owned cache. No source/provider failure occurred.

After the test-only count correction and an online build to populate the cache:

```sh
uv run --extra map --with pytest-xdist --with geopandas --with matplotlib pytest -n4 -q \
  tests/test_packaging_carries_catalogues.py \
  tests/test_packaging_excludes_catalogue_build_inputs.py
```

Result: **6 passed in 43.32 seconds**, including all five formerly failing
cases and packaging controls. Their offline build commands are unchanged.
Ruff lint/format, `uv run ty check src`, and the actual wheel build pass.
No production code changed after the independent full-diff acceptance of
`c2a5795ef77b17d267769f8a6b421e682e353b9e`. The final test-only delta is reviewed
separately. The root delivery audit will run the clean complete suite on the
final target; this report does not describe the historical failed run as passing.
