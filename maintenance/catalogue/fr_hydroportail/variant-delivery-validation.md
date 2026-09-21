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
- Full test suite and independent live public-path verification: running when the implementation PR was opened. Final results will be recorded before delivery.

The first in-progress full-suite run imported an earlier raw-only boundary test
before its explicit raw selection was added. The isolated current boundary probe
passes. This is a stale collected test, not a source or production failure.
