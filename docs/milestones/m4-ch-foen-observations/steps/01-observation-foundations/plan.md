# 01-observation-foundations Plan

## 1. Goal and scope

Ship the inert observation foundations for M4 `ch_foen` retrieval without changing public observation-retrieval behavior.

This single step ships:

- `ch_foen` row and series annotation schema declarations for the annotation names step 02 will emit.
- Three legacy observation CSV fixtures under `tests/test_data/`, with legacy filenames preserved.
- Provider-internal observation scaffolding under `src/rivretrieve/_internal/providers/ch_foen/`: client shape, raw payload shape, issue-code constants, parser fatal-code constants, and a CSV-bytes parser that produces a structured intermediate.
- Fixture-backed parser tests that derive facts from fixture bytes.
- A recorded token-classification probe against legacy `origin/switzerland` evidence: the Influx token is still treated as a public service credential, so step 02 may embed the literal with a configuration override if it records no secret in provenance.

Out of scope:

- Replacing the M3 public-handle placeholder.
- Emitting annotations at runtime.
- 366-day windowing, live HTTP calls, retries, batching, or stitching.
- Flow-vs-`flow_ls` preference and conversion decisions in retrieval.
- Top-level `rr.observations(...)`.
- `provider.json` regeneration or `bulk_observations` capability changes.
- Provider-port REPORT updates.

At the end of this step, `rr.provider("ch_foen").observations(...)` still returns the M3 placeholder `ObservationResult` with `observations_not_yet_implemented`. The provider-handle annotation schema methods intentionally change from empty lists to declared schemas. T119/T120 stay unchanged.

## 2. API surface touched

Public package-root surface: **none**.

This step must not add `rr.observations`, re-export any `ChFoen*` type, edit public `ProviderHandle`, or add a public module path that shadows a package-root callable. The only allowed package-root change for the eventual executor commit is the mandatory patch version literal from `uv run bump-my-version bump patch`; no API-shape edit to `src/rivretrieve/__init__.py`.

Provider-handle public observation behavior remains unchanged: the public handle still validates request shape through M2 and then returns the M3 placeholder from `ch_foen.module.observations`, including empty observation and annotation tables. Provider-handle public annotation schema methods change return values from `[]` to the declared row/series schemas in §3.

Internal provider surface introduced or modified under `src/rivretrieve/_internal/providers/ch_foen/`:

- `module.py`
  - Modify only `row_annotation_schema()` and `series_annotation_schema()` to return non-empty `AnnotationSchema` declarations.
  - Do not change `observations(...)` routing or placeholder result behavior in this step.
- `observation_client.py`
  - Introduce `ChFoenObservationClient` as a provider-internal client shell.
- `raw_payload.py`
  - Introduce `ChFoenRawPayload` and small raw-call records.
- `issue_codes.py`
  - Introduce `ChFoenObservationIssueCodes` and fatal parser error-code constants.
- `parser.py`
  - Introduce CSV-bytes parser and parser intermediate dataclasses.

All new types remain importable only from `rivretrieve._internal.providers.ch_foen.*`.

## 3. Data structures and types

### Product IDs and source behavior pinned for this step

The packaged `ch_foen` `products.parquet` currently declares exactly these product IDs:

| product_id | native_id | observed_property | frequency | statistic | unit |
| --- | --- | --- | --- | --- | --- |
| `discharge_daily_mean` | `flow` | `discharge` | `daily` | `mean` | `m3/s` |
| `discharge_instantaneous` | `flow` | `discharge` | `irregular` | `instantaneous` | `m3/s` |
| `stage_daily_mean` | `height_abs` | `stage` | `daily` | `mean` | `m` |
| `stage_instantaneous` | `height_abs` | `stage` | `irregular` | `instantaneous` | `m` |
| `water_temperature_daily_mean` | `temperature` | `water_temperature` | `daily` | `mean` | `degC` |
| `water_temperature_instantaneous` | `temperature` | `water_temperature` | `irregular` | `instantaneous` | `degC` |

Annotation declarations must be consistent with those products and with legacy field behavior:

- `origin/switzerland:rivretrieve/switzerland.py:44-81` maps products to native fields: `flow`/`flow_ls`, `height_abs`/`height`, and `temperature`.
- `origin/switzerland:rivretrieve/switzerland.py:176-188` builds Flux queries against bucket `existenzApi`, measurement `hydro`, station `loc`, and `_field` filters.
- `origin/switzerland:rivretrieve/switzerland.py:252-261` prefers the configured native field over fallback by timestamp.
- `origin/switzerland:rivretrieve/switzerland.py:263-269` converts `flow_ls` by dividing by `1000.0`.
- `origin/switzerland:rivretrieve/switzerland.py:290-297` performs daily aggregation only after parsing, field preference, unit conversion, and sorting.

### Token-classification outcome

The legacy branch HEAD in the legacy checkout is `cd9b030 Restore public Switzerland token`. The planner probe confirms:

- `origin/switzerland:rivretrieve/switzerland.py:40` contains a literal `INFLUX_TOKEN`.
- `origin/switzerland:rivretrieve/switzerland.py:199-203` uses it as `Authorization: Token ...` for `application/csv` Flux queries.

Outcome: still a public service credential per M3 REPORT §7.2. Step 02 may use literal embedding plus an environment/configuration override for operators, but must not put the token into provenance, raw metadata, docs examples, generated artifacts, or tests. Step 01 records the mechanics only and does not embed the token in target code.

### Annotation schemas to declare

Row annotation IDs:

| annotation_id | value_type | source_field | Why step 02 will emit it |
| --- | --- | --- | --- |
| `native_field` | `string` | `_field` | Records the provider-native field that produced the canonical `value`: `flow`, `flow_ls`, `height_abs`, `height`, or `temperature`. |
| `native_unit` | `string` | `_field` | Records the unit of the returned native field before any conversion: `m3/s` for `flow`, `L/s` for `flow_ls`, `m` for stage fields, `degC` for temperature. |
| `converted_unit` | `string` | product catalogue `unit` | Records the canonical product unit used in `data.value`, especially `flow_ls` `L/s` to `m3/s`. |
| `source_endpoint_or_query` | `string` | Flux query / endpoint | Records the endpoint/query identity that produced the row without secrets. |
| `raw_value` | `float` | `_value` | Preserves the provider value before conversion when conversion or conflict handling changes `data.value`. |
| `alternative_native_field` | `string` | `_field` | Preserves the non-selected same-timestamp field when preferred/fallback overlap creates an alternative value. |
| `alternative_raw_value` | `float` | `_value` | Preserves the non-selected same-timestamp raw value for conflict/overlap handling. |
| `alternative_native_unit` | `string` | `_field` | Records the unit for `alternative_raw_value`. |

Series annotation IDs:

| annotation_id | value_type | source_field | Why step 02 will emit it |
| --- | --- | --- | --- |
| `preferred_source` | `string` | product metadata `preferred_parameter` | Records the configured preferred native field for the station-product request. |
| `fallback_source_used` | `boolean` | parsed native fields | Records whether fallback values contributed to the returned series. |
| `native_unit_returned` | `string` | parsed native fields | Records the native unit(s) actually present in the response. |
| `converted_unit` | `string` | product catalogue `unit` | Records the canonical unit returned in `ObservationResult.data`. |
| `returned_time_range_start` | `datetime` | `_time` | Records first parsed timestamp returned for the station-product series. |
| `returned_time_range_end` | `datetime` | `_time` | Records last parsed timestamp returned for the station-product series. |
| `resolved_timezone` | `string` | `_time` | Records that the CSV timestamps were parsed from explicit UTC `Z` timestamps. |
| `timezone_mismatch_flag` | `boolean` | `_time` | Records whether parsed timestamps contradicted the expected explicit UTC shape. |
| `provider_endpoint` | `string` | `INFLUX_URL` | Records the Influx query endpoint without token or authorization metadata. |
| `provider_query_fields` | `json` | Flux `_field` filter | Records requested native fields, e.g. `["flow", "flow_ls"]`, without the token. |

Do not declare quality-code annotations in this step; the legacy CSV fixtures do not expose quality fields, so declaring them would be speculative.

Native unit strings are not present as CSV columns. The `flow_ls -> L/s` and `flow -> m3/s` mapping is an inference from the legacy native field names plus the numeric `/ 1000.0` conversion at `origin/switzerland:rivretrieve/switzerland.py:263-269`, not a directly cited provider column.

### `ChFoenObservationClient`

File: `observation_client.py`.

Recommended shape: a small frozen dataclass-like client, not a public provider class and not part of the provider module contract.

Fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `endpoint` | `str` | Defaults to `https://influx.konzept.space/api/v2/query?org=api.existenz.ch`. |
| `token` | `str` | Required at construction; step 01 tests use fake values and do not embed the legacy literal. |
| `timeout_seconds` | `float` | Defaults to `60.0`, matching legacy line 209. |

Step 01 does not ship `max_window_days`, session injection, `build_flux_query`, or `fetch_csv`. Those belong with step 02's retrieval/windowing implementation. Step 01 client tests are constructor/redaction-shape tests only.

### `ChFoenRawPayload`

File: `raw_payload.py`.

Recommendation: use frozen dataclasses, not Pydantic. Rationale: raw payload is provider-private, carries bytes and Polars frames, does not need validation extras, and avoiding `extra="allow"` avoids D7 test-shape overhead.

Concrete shape:

| Type / field | Type | Meaning |
| --- | --- | --- |
| `ChFoenRawCsvResponse.csv_bytes` | `bytes` | Original response body for one provider call/window. |
| `ChFoenRawCsvResponse.endpoint` | `str` | Endpoint without token. |
| `ChFoenRawCsvResponse.query` | `str` | Flux query string without token. |
| `ChFoenRawCsvResponse.status_code` | `int | None` | HTTP status when live retrieval lands. |
| `ChFoenRawCsvResponse.retrieved_at` | `datetime | None` | Retrieval timestamp when live retrieval lands. |
| `ChFoenRawPayload.provider_id` | `ProviderId` | Always `ch_foen`. |
| `ChFoenRawPayload.responses` | `tuple[ChFoenRawCsvResponse, ...]` | One or more raw CSV responses. |
| `ChFoenRawPayload.parsed` | `pl.DataFrame | None` | Optional parser output snapshot for debug only. |

Step 02 can adapt this into the common `RawPayload` slot by storing bytes/content metadata if desired; cross-provider auditability must still come from data, annotations, provenance, and issues per architecture.md §12/§14.

### Parser intermediate

File: `parser.py`.

Recommendation: parser returns a frozen dataclass `ChFoenParsedObservationPayload` containing a Polars `DataFrame` plus parser issues, not a `LazyFrame`, not a row `NamedTuple`, and not Pydantic.

Rationale:

- Polars `DataFrame` matches architecture.md §12 and existing test utilities.
- The parser can validate concrete fixture bytes eagerly and fail fast before step 02 retrieval decisions.
- A `LazyFrame` would defer parse/schema failures too far.
- Per-row `NamedTuple` objects would make tests and step 02 aggregation less ergonomic.
- Pydantic adds little value for byte-to-table parsing and may trigger D7 if extras are allowed.

`ChFoenParsedObservationPayload` fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `records` | `pl.DataFrame` | Parsed long native records. |
| `source_columns` | `tuple[str, ...]` | CSV columns present in the payload. |
| `issues` | `tuple[Issue, ...]` | Recoverable parser issues only. |

`records` columns:

| Column | Type | Source |
| --- | --- | --- |
| `time` | `pl.Datetime(time_unit="us", time_zone="UTC")` | `_time`; parser preserves explicit UTC `Z` timestamps as UTC. |
| `station_id` | `str` | `loc`. |
| `native_field` | `str` | `_field`. |
| `native_value` | `float` | `_value`. |
| `measurement` | `str` | `_measurement`. |
| `window_start` | `pl.Datetime(time_unit="us", time_zone="UTC")` | `_start`. |
| `window_stop` | `pl.Datetime(time_unit="us", time_zone="UTC")` | `_stop`. |
| `table` | `int | None` | `table`. |

Parser does not decide product IDs, daily aggregation, field preference, fallback use, unit conversion, gap/overlap policy, or `on_issue` routing. It only surfaces raw records in a typed form step 02 can consume.

### `ChFoenObservationIssueCodes`

File: `issue_codes.py`.

Recommendation: define as a `StrEnum` or frozen constants class with exact string values. Keep strings stable because tests and downstream diagnostics assert `Issue.code`.

Recoverable Issue codes:

| Code | Used when | Step |
| --- | --- | --- |
| `observations_not_yet_implemented` | Transitional M3 placeholder code; public behavior remains through step 01. | existing / step 01 unchanged |
| `missing_data` | No rows for a requested station-product/time range after successful parsing. | step 02 |
| `partial_response` | Some requested station-products/windows succeed and others do not. | step 02 |
| `source_request_failed` | One provider call fails but bulk/partial response can continue. | step 02 |
| `gap` | Returned timestamps show a gap relative to expected product cadence/window. | step 02 |
| `overlap` | Multiple rows overlap for the same station/product/timestamp. | step 02 |
| `conflict` | Overlapping native fields disagree after preference/conversion rules. | step 02 |
| `unit_conversion_ambiguity` | Native field/unit cannot be converted deterministically. | step 02 |
| `timezone_ambiguity` | Timestamp lacks explicit offset or conflicts with expected UTC parsing. | step 01 parser can surface; step 02 routes |
| `invalid_timestamp` | `_time` cannot be parsed. | step 01 parser |
| `invalid_numeric_value` | `_value` cannot be parsed as numeric. | step 01 parser |

Fatal parser exception codes:

| Code | Used when | Step |
| --- | --- | --- |
| `malformed_csv` | CSV bytes cannot be decoded/read as Flux CSV. | step 01 parser |
| `missing_required_column` | Required Flux columns are absent. | step 01 parser |

The fatal parser exception type should expose the code string, for example as `.code`, but these fatal parser codes are not `Issue.code` values in step 01.

Do not introduce a `placeholder_removed` issue code. Removing the placeholder is a step 02 behavior transition, not a runtime data issue.

D7: no step-01 observation model should use Pydantic with `extra="allow"`. If the executor nevertheless introduces one, tests must use `Model.model_validate({...})` and inspect `model_extra`; constructor kwargs for extra fields are forbidden because `ty` rejects them.

D9: if parser code ever inspects JSON-loaded structures, use concrete `dict` / `list` checks. This CSV parser should not need `json.loads` at all.

## 4. Errors and failure modes

This step ships parser-level failures only. Public-handle observation calls still return the M3 placeholder issue and do not route parser failures through the handle.

Fatal parser failures:

- Bytes cannot be decoded as UTF-8 or compatible text: raise the fatal parser exception with code `malformed_csv`.
- CSV reader cannot parse the payload shape: raise the fatal parser exception with code `malformed_csv`.
- Required columns are absent: `_time`, `_value`, `_field`, `_measurement`, and `loc`: raise the fatal parser exception with code `missing_required_column`.
- Parsed table has schema violations that make the intermediate unusable.

Recoverable parser issues:

- Empty CSV payload or header-only CSV: return an empty `records` frame plus a `missing_data` issue.
- Rows with invalid `_time`: drop those rows and include `invalid_timestamp` if at least one valid row remains.
- Rows with invalid `_value`: drop those rows and include `invalid_numeric_value` if at least one valid row remains.
- Unknown native field: keep it in `records`; step 02 product matching decides whether it is relevant.
- Missing optional columns such as `_start`, `_stop`, or `table`: keep records with nulls if required columns are present and add a warning issue only if the field is needed for provenance.

Step 02 owns two-channel routing for the placeholder-to-real transition: fatal contract failures raise immediately; recoverable retrieval/data issues become `Issue` objects and respect `on_issue`. Step 01 must not alter `apply_on_issue`, public placeholder non-raise behavior, or public handle validation.

## 5. Tests

1. `test_ch_foen_row_annotation_schema_declares_m4_observation_names`
   - Assert `row_annotation_schema()` includes exactly the eight row IDs listed in §3 and each can round-trip through `AnnotationSchema.to_row()`.

2. `test_ch_foen_series_annotation_schema_declares_m4_observation_names`
   - Assert `series_annotation_schema()` includes exactly the ten series IDs listed in §3 and each can round-trip through `AnnotationSchema.to_row()`.

3. `test_ch_foen_observation_fixture_files_are_present`
   - Assert the three legacy filenames exist under `tests/test_data/` and are non-empty.

4. `test_ch_foen_parser_temperature_fixture_derives_native_records`
   - Read `switzerland_2016_temperature_20200101.csv`; assert derived facts from bytes: 287 data rows, station `2016`, native field `temperature`, measurement `hydro`, value range `6.5..6.77`, timestamp range `2020-01-01T00:00:00Z..2020-01-02T23:50:00Z`, query window `_start=2020-01-01T00:00:00Z`, `_stop=2020-01-03T00:00:00Z`.

5. `test_ch_foen_parser_discharge_fixture_derives_native_records`
   - Read `switzerland_2206_discharge_20250101.csv`; assert 144 data rows, station `2206`, native field `flow_ls`, measurement `hydro`, native unit mapping `L/s`, value range `14..15`, mean `14.944444444444` derived from bytes, timestamp range `2025-01-01T00:00:00Z..2025-01-01T23:50:00Z`.

6. `test_ch_foen_parser_stage_fixture_derives_native_records`
   - Read `switzerland_2282_stage_20250101.csv`; assert 141 data rows, station `2282`, native field `height_abs`, measurement `hydro`, native unit mapping `m`, value range `0.161..0.165`, timestamp range `2025-01-01T00:00:00Z..2025-01-01T23:50:00Z`.

7. `test_ch_foen_parser_rejects_missing_required_columns`
   - Provide minimal CSV bytes missing one required column and assert the parser raises the fatal parser exception with code `missing_required_column`.

8. `test_ch_foen_parser_reports_invalid_rows_as_recoverable_when_valid_rows_remain`
   - Provide small synthetic CSV bytes with one invalid `_value` or `_time` and one valid row; assert valid row remains and issue code is `invalid_numeric_value` or `invalid_timestamp`.

9. `test_ch_foen_raw_payload_preserves_bytes_and_redacts_auth`
   - Construct `ChFoenRawPayload` from fixture bytes and query metadata; assert raw bytes are preserved and no token/Authorization field is present.

10. `test_ch_foen_observation_issue_codes_cover_m4_codes`
    - Assert the issue-code type exposes the exact recoverable Issue code strings in §3, including existing `observations_not_yet_implemented`.

11. `test_ch_foen_parser_error_codes_cover_fatal_parser_codes`
    - Assert the fatal parser exception codes expose `malformed_csv` and `missing_required_column`.

12. `test_package.py::test_init_public_surface_exports_m2_provider_handle_surface` (T119)
    - Must remain unchanged and green.

13. `test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion` (T120)
    - Must remain unchanged and green; no `ChFoen*` leakage.

14. `test_import_rivretrieve_does_not_import_providers_stubs_or_generators`
    - Must still pass with new modules present; lazy registration remains via the M2 keyword route and package import must not import `ch_foen` runtime modules.

15. Existing public-handle placeholder tests
    - Must still assert the M3 placeholder result behavior; do not rewrite them to expect real data in this step.

## 6. Files

Implementation order must keep `uv run pytest` green without network at every checkpoint.

1. `tests/test_data/switzerland_2016_temperature_20200101.csv`
   - Add exact legacy fixture bytes from `origin/switzerland:tests/test_data/switzerland_2016_temperature_20200101.csv`.

2. `tests/test_data/switzerland_2206_discharge_20250101.csv`
   - Add exact legacy fixture bytes.

3. `tests/test_data/switzerland_2282_stage_20250101.csv`
   - Add exact legacy fixture bytes.

4. `src/rivretrieve/_internal/providers/ch_foen/issue_codes.py`
   - Add issue-code constants only. No imports from public root.

5. `src/rivretrieve/_internal/providers/ch_foen/raw_payload.py`
   - Add raw payload dataclasses. No behavior wiring.

6. `src/rivretrieve/_internal/providers/ch_foen/parser.py`
   - Add parser intermediate and CSV parser. Tests can import it directly.

7. `tests/test_ch_foen_observation_parser.py`
   - Add fixture-presence and parser tests from §5. At this point new parser code is tested but public handle still unchanged.

8. `src/rivretrieve/_internal/providers/ch_foen/observation_client.py`
   - Add constructor-only client scaffold. No network, session, windowing, or query-builder code.

9. `tests/test_ch_foen_observation_client.py`
   - Add only constructor/token-redaction tests that do not touch network.

10. Atomic annotation declaration checkpoint:
    - Update `src/rivretrieve/_internal/providers/ch_foen/module.py` only in `row_annotation_schema()` and `series_annotation_schema()`.
    - In the same checkpoint, update `tests/test_ch_foen_module.py` or add `tests/test_ch_foen_observation_annotations.py` so the M3 empty-schema assertions are replaced by exact declaration tests.
    - Keep placeholder observation assertions intact.
    - Do not run `uv run pytest` between the module edit and its paired test edit; the checkpoint is green only after both land together.

11. Existing negative controls
    - Run targeted controls: T119/T120, offline import, ch_foen placeholder tests.

12. Full verification
    - Run `uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`, and `uv run pytest`.

13. Version bump and commit
    - Run `uv run bump-my-version bump patch`.
    - Stage code, tests, fixtures, and version files.
    - Commit once, then tag `v$(uv run bump-my-version show current_version)`.

No file in `src/rivretrieve/_internal/providers/ch_foen/` may import `generate_catalogue.py` at runtime. No new file may be placed under `src/rivretrieve/providers/` or at package root.

## 7. Open questions

1. Exact row annotation IDs to declare.
   - Recommendation: declare only `native_field`, `native_unit`, `converted_unit`, `source_endpoint_or_query`, `raw_value`, `alternative_native_field`, `alternative_raw_value`, and `alternative_native_unit`. This covers source field/unit/conversion/provenance and conflict preservation required by architecture.md §12/§13/§17 without inventing quality annotations absent from the source.

2. Exact series annotation IDs to declare.
   - Recommendation: declare `preferred_source`, `fallback_source_used`, `native_unit_returned`, `converted_unit`, `returned_time_range_start`, `returned_time_range_end`, `resolved_timezone`, `timezone_mismatch_flag`, `provider_endpoint`, and `provider_query_fields`.

3. Exact `ChFoenObservationIssueCodes`.
   - Recommendation: use the exact recoverable Issue code table in §3. Include `observations_not_yet_implemented` for continuity, keep `malformed_csv` and `missing_required_column` as fatal parser exception codes, and do not introduce `placeholder_removed`; placeholder removal is not a runtime issue.

4. `ChFoenRawPayload` concrete shape.
   - Recommendation: frozen dataclasses preserving CSV bytes plus endpoint/query/status metadata and optional parsed frame. Do not use Pydantic and do not store a parsed dict; the source is CSV, and Polars is the useful typed representation.

5. Parser intermediate shape.
   - Recommendation: `ChFoenParsedObservationPayload(records: pl.DataFrame, source_columns: tuple[str, ...], issues: tuple[Issue, ...])`. This avoids shared backend-policy abstractions and lets step 02 consume native records directly.

6. Token-classification probe outcome.
   - Recommendation: proceed. The latest legacy evidence still classifies the token as public: branch HEAD `cd9b030 Restore public Switzerland token`, literal on `origin/switzerland:rivretrieve/switzerland.py:40`, Authorization header use on `origin/switzerland:rivretrieve/switzerland.py:199-203`. Step 02 may embed with override mechanics, but step 01 must not embed.

7. Fixture-fact assertions.
   - Recommendation: use the byte-derived facts in §5. Do not assert legacy wide-form pandas outputs. Native unit strings are not present as CSV columns; derive unit expectations from the native field mapping in the parser test helper (`temperature -> degC`, `flow_ls -> L/s`, `height_abs -> m`) and keep conversion decisions for step 02.

## 8. Deferrals

- Public handle real retrieval: step 02. Hard rationale: this step must preserve M3 placeholder behavior.
- Runtime annotation emission: step 02. Hard rationale: declarations can land now, but emitted annotation validation belongs with real retrieval.
- Two-channel issue routing for retrieval: step 02. Hard rationale: parser-local fatal/recoverable failures are not public-handle behavior yet.
- 366-day windowing and request decomposition: step 02. Hard rationale: parser tests use committed fixture bytes and must not require live fetcher execution.
- Flow-vs-`flow_ls` preference and unit conversion: step 02. Hard rationale: parser surfaces native fields and values; retrieval decides product-specific canonical values.
- Daily aggregation: step 02. Hard rationale: parser should not collapse raw records before retrieval policy is applied.
- Query construction, session injection, 366-day windowing, and live fetch: step 02. Hard rationale: step 01's client shell exists only to anchor credential/redaction shape; retrieval mechanics belong with the retrieval path.
- JSON encoding of emitted `provider_query_fields`: step 02. Hard rationale: step 01 declares the `json` series annotation only; step 02 must `json.dumps` values before they cross the `AnnotationTable` boundary, per D8-style asymmetric encoding lessons.
- Top-level `rr.observations(...)`: step 03. Hard rationale: wrapper must delegate to real provider retrieval, not the placeholder.
- Capability revision and `provider.json` regeneration: step 03. Hard rationale: step 01 does not change public observation capability.
- `docs/provider_ports/ch_foen.md` observation sections and M4 REPORT: step 03. Hard rationale: observation behavior is not live until step 02.
- `rr.map_stations`: M5. Hard rationale: tracker assigns it to M5.
- Additional providers or shared backend-policy abstraction: post-V1 unless architecture changes. Hard rationale: architecture.md §17 keeps backend policy provider-internal.

## 9. Stopping conditions for the executor

- Stop if any annotation ID cannot be tied to a value step 02 will actually emit.
- Stop if the Influx token is removed, rotated into a private placeholder, or no longer classified as public in the legacy source.
- Stop if fixture facts require running the legacy fetcher; derive only from committed CSV bytes.
- Stop if parser design forces a shared backend-policy abstraction.
- Stop if a timezone interpretation beyond explicit UTC `Z` parsing is required.
- Stop if any new file shadows a package-root public callable or adds a root public symbol.
- Stop if public-handle observation behavior changes from the M3 placeholder.
- Stop if `uv run pytest` cannot remain green without network after each §6 checkpoint.
- Stop if D7 is violated by testing `extra="allow"` Pydantic extras through constructor kwargs.
- Stop if D9 is violated by using abstract `Mapping` / `Sequence` checks against `json.loads` output.
- Stop if any token, Authorization header, or secret-like credential is committed in target code, tests, provenance, raw metadata, or docs.
