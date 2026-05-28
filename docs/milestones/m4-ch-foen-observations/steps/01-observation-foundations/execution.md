# 01-observation-foundations Execution

## 1. What Landed

- `tests/test_data/switzerland_2016_temperature_20200101.csv` - committed exact legacy temperature Flux CSV fixture bytes.
- `tests/test_data/switzerland_2206_discharge_20250101.csv` - committed exact legacy discharge Flux CSV fixture bytes.
- `tests/test_data/switzerland_2282_stage_20250101.csv` - committed exact legacy stage Flux CSV fixture bytes.
- `src/rivretrieve/_internal/providers/ch_foen/issue_codes.py` - added recoverable observation issue-code enum and fatal parser-code enum.
- `src/rivretrieve/_internal/providers/ch_foen/raw_payload.py` - added frozen raw CSV response and raw payload dataclasses.
- `src/rivretrieve/_internal/providers/ch_foen/parser.py` - added CSV-bytes parser, typed parsed-payload dataclass, UTC datetime normalization, recoverable row-drop issues, and fatal parser exception codes.
- `tests/test_ch_foen_observation_parser.py` - added fixture-presence, parser fixture-fact, fatal parser-code, recoverable parser-issue, raw payload, and issue-code tests.
- `src/rivretrieve/_internal/providers/ch_foen/observation_client.py` - added constructor-only client shell with endpoint, token, timeout, and redacted repr.
- `tests/test_ch_foen_observation_client.py` - added constructor/default and token-redaction tests.
- `src/rivretrieve/_internal/providers/ch_foen/module.py` - changed only row and series annotation schema methods to return the M4 observation declarations.
- `tests/test_ch_foen_module.py` - replaced empty annotation schema assertions with exact row/series declaration tests while preserving placeholder observation behavior tests.
- `src/rivretrieve/__init__.py` and `pyproject.toml` - patch-bumped version from `0.1.18` to `0.1.19`.

## 2. Test Count Delta and Negative Controls

- Starting point: 374 tests passing.
- End of implementation before version bump: 385 tests passing.
- Delta: +11 tests.
- T119 `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface`: passed.
- T120 `tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion`: passed.
- Offline import `tests/test_offline_import.py::test_import_rivretrieve_does_not_import_providers_stubs_or_generators`: passed.
- Placeholder control `tests/test_ch_foen_module.py::test_ch_foen_observations_placeholder_returns_issue_result`: passed for `warn`, `raise`, and `ignore`.

## 3. Token-Probe Outcome

The local repository did not have an `origin/switzerland` ref, so I used the legacy checkout cited by the critique at `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python`.

- `git log origin/switzerland --oneline -1` returned `cd9b030 Restore public Switzerland token`.
- `origin/switzerland:rivretrieve/switzerland.py:40` still declares `INFLUX_TOKEN`.
- `origin/switzerland:rivretrieve/switzerland.py:199-203` still builds the Authorization and CSV Flux request headers.
- Related legacy mechanics were confirmed at lines 44-81 for `VARIABLE_MAP`, 176-188 for Flux query construction, 252-261 for preferred/fallback field selection, 263-269 for `flow_ls` conversion, and 290-297 for daily aggregation.

Outcome matches the plan: token status remains the M3 public service credential classification. Step 01 did not embed the token in target code, tests, fixtures, raw metadata, or provenance.

## 4. Fixture-Fact Assertions

- Temperature fixture: implemented plan facts exactly: 287 parsed rows, station `2016`, native field `temperature`, measurement `hydro`, native unit mapping `degC`, value range `6.5..6.77`, timestamp range `2020-01-01T00:00:00Z..2020-01-02T23:50:00Z`, `_start=2020-01-01T00:00:00Z`, `_stop=2020-01-03T00:00:00Z`.
- Discharge fixture: implemented plan facts exactly: 144 parsed rows, station `2206`, native field `flow_ls`, measurement `hydro`, native unit mapping `L/s`, value range `14..15`, mean `14.944444444444`, timestamp range `2025-01-01T00:00:00Z..2025-01-01T23:50:00Z`.
- Stage fixture: implemented plan facts exactly: 141 parsed rows, station `2282`, native field `height_abs`, measurement `hydro`, native unit mapping `m`, value range `0.161..0.165`, timestamp range `2025-01-01T00:00:00Z..2025-01-01T23:50:00Z`.

The native unit checks remain parser-test helper derivations from native field names, not CSV column facts.

## 5. Annotation IDs Declared

Row annotation IDs declared exactly as planned:

`native_field`, `native_unit`, `converted_unit`, `source_endpoint_or_query`, `raw_value`, `alternative_native_field`, `alternative_raw_value`, `alternative_native_unit`.

Series annotation IDs declared exactly as planned:

`preferred_source`, `fallback_source_used`, `native_unit_returned`, `converted_unit`, `returned_time_range_start`, `returned_time_range_end`, `resolved_timezone`, `timezone_mismatch_flag`, `provider_endpoint`, `provider_query_fields`.

Each declaration round-trips through `AnnotationSchema.to_row()` / `AnnotationSchema.from_row()`.

## 6. Tactical Fixes

- Used the critique-cited legacy checkout for token probing and fixture extraction because this repo lacked the `origin/switzerland` ref.
- Added a blank-required-row filter in the parser because the legacy CSV fixtures contain trailing blank lines; without it, Polars preserves a null row that would produce false invalid-row issues.
- Represented the parser records schema as `pl.Schema` rather than a plain dict so `ty` accepts the `DataFrame.cast(...)` call.
- Narrowed the discharge mean test value to `float` before `math.isclose(...)` so `ty` can verify the assertion.

## 7. New Discoveries

No D10+ discovery candidate was found, and no update to `docs/discoveries.md` was made.

## 8. Next Step Notes

- The parser returns native long records only: `time`, `station_id`, `native_field`, `native_value`, `measurement`, `window_start`, `window_stop`, and `table`.
- Step 02 still owns product resolution, preferred/fallback selection, unit conversion, daily aggregation, gap/overlap/conflict policy, public result construction, and runtime annotation emission.
- `provider_query_fields` is declared as a `json` annotation; step 02 should JSON-encode emitted values before they cross the `AnnotationTable` boundary.
- `ChFoenRawPayload` preserves bytes and endpoint/query metadata only; it intentionally has no Authorization or token field.
