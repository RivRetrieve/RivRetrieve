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
- Full test suite: running when the implementation PR was opened. Final results will be recorded before delivery.

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
