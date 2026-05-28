# 03-live-source-capability-routing Execution

## 1. What shipped

- Commit: this commit; final SHA reported in executor handoff because embedding the SHA in the committed file would change the SHA.
- Tag: `v0.1.11`
- Version: `0.1.10` -> `0.1.11`
- Test count: started from 150 passing; final `uv run pytest` collected 185 items and passed. The T28-T45 logical test inventory was added; parametrization expands the pytest item count.
- Scope: provider-level catalogue `source="live"` now routes by live capability while preserving packaged catalogue behavior and public API shape.

## 2. Files added / modified

- Added: `docs/milestones/m2-discovery-and-observation-contracts/steps/03-live-source-capability-routing/execution.md`
- Modified: `src/rivretrieve/_internal/issues.py`
- Modified: `src/rivretrieve/_internal/catalogue_reader.py`
- Modified: `tests/test_internal_issues.py`
- Modified: `tests/conftest.py`
- Modified: `tests/test_internal_catalogue_reader.py`
- Modified: `tests/test_package.py`
- Modified: `pyproject.toml`
- Modified: `src/rivretrieve/__init__.py`

## 3. Test enumeration T28-T45

- T28 PASS: `test_catalogue_reader_packaged_products_unchanged_by_live_capability`, `tests/test_internal_catalogue_reader.py:265`
- T29 PASS: `test_catalogue_reader_packaged_stations_unchanged_by_live_capability`, `tests/test_internal_catalogue_reader.py:276`
- T30 PASS: `test_catalogue_reader_packaged_station_products_unchanged_by_live_capability`, `tests/test_internal_catalogue_reader.py:287`
- T31 PASS: `test_catalogue_reader_live_products_warn_returns_empty_result_with_issue`, `tests/test_internal_catalogue_reader.py:298`
- T32 PASS: `test_catalogue_reader_live_stations_warn_returns_empty_result_with_issue`, `tests/test_internal_catalogue_reader.py:310`
- T33 PASS: `test_catalogue_reader_live_station_products_warn_returns_empty_result_with_issue`, `tests/test_internal_catalogue_reader.py:322`
- T34 PASS: `test_catalogue_reader_live_products_raise_wraps_unsupported_issue`, `tests/test_internal_catalogue_reader.py:334`
- T35 PASS: `test_catalogue_reader_live_stations_raise_wraps_unsupported_issue`, `tests/test_internal_catalogue_reader.py:343`
- T36 PASS: `test_catalogue_reader_live_station_products_raise_wraps_unsupported_issue`, `tests/test_internal_catalogue_reader.py:352`
- T37 PASS: `test_catalogue_reader_live_products_ignore_returns_issue_without_warning`, `tests/test_internal_catalogue_reader.py:361`
- T38 PASS: `test_catalogue_reader_live_stations_ignore_returns_issue_without_warning`, `tests/test_internal_catalogue_reader.py:373`
- T39 PASS: `test_catalogue_reader_live_station_products_ignore_returns_issue_without_warning`, `tests/test_internal_catalogue_reader.py:385`
- T40 PASS: `test_catalogue_reader_invalid_source_remains_direct_fatal_for_all_methods`, `tests/test_internal_catalogue_reader.py:401`
- T41 PASS: `test_catalogue_reader_invalid_source_ignores_capability_and_on_issue`, `tests/test_internal_catalogue_reader.py:415`
- T42 PASS: `test_catalogue_reader_live_capable_products_raise_defensive_fatal_for_every_on_issue`, `tests/test_internal_catalogue_reader.py:433`
- T43 PASS: `test_catalogue_reader_live_capable_stations_raise_defensive_fatal_for_every_on_issue`, `tests/test_internal_catalogue_reader.py:444`
- T44 PASS: `test_catalogue_reader_live_capable_station_products_raise_defensive_fatal_for_every_on_issue`, `tests/test_internal_catalogue_reader.py:455`
- T45 PASS: `test_catalogue_reader_live_products_invalid_filter_remains_direct_fatal`, `tests/test_internal_catalogue_reader.py:465`

## 4. Negative-control inventory

- T40/T41: invalid source remains a direct `InvalidCatalogueSourceError`, independent of method, live capability, and `on_issue`; `_issue_policy_error_chain(exc) == []`.
- T42-T44: live-capable defensive route raises direct `LiveCatalogueRoutingNotImplementedError` for every `on_issue in ("warn", "raise", "ignore")`; `_issue_policy_error_chain(exc) == []`.
- T45: products-only filter precedence holds. `source="live"` plus malformed product filter raises direct `FatalContractError` before live-unsupported issue routing.
- T23: `LiveCatalogueUnsupportedIssue` and `LiveCatalogueRoutingNotImplementedError` are absent from public surface at `tests/test_package.py:18`; T22 present-set was unchanged.
- T24: offline import remains clean at `tests/test_offline_import.py:7`.
- T25: stub catalogue functions still raise `NotImplementedError` at `tests/test_internal_provider_module.py:37`.

## 5. Deviations from plan

No behavioral deviations from plan section 6.

The final pytest item count is 185 rather than a literal 168 because the plan also required focused issue-class unit tests, T10/T11 invalid-source preservation, and parametrized T40-T44 matrices. The logical T28-T45 inventory is exactly 18 tests.

## 6. Surprises

- Pydantic v2 frozen subclass behavior matched the reviewer check: `LiveCatalogueUnsupportedIssue` is an `Issue` subclass and inherits frozen model semantics.
- `apply_on_issue` already matched the plan's warning semantics: `warnings.warn(issue.message, RuntimeWarning, stacklevel=2)` under `on_issue="warn"`.
- No D3 candidate was discovered.

## 7. Ready for step 04

Ready. Step 03 keeps public surface unchanged, preserves offline import, and leaves live-capable catalogue routing as an explicit defensive fatal for later implementation.
