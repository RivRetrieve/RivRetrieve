# 02-observation-retrieval-and-bulk Plan

## 1. Goal and scope

Replace the M3 `ch_foen` observation placeholder with the real provider-handle retrieval path in one commit. This step covers every public-handle request shape already normalized by M2:

- single station x single product,
- multiple stations x single product,
- single station x multiple products,
- multiple stations x multiple products as the full N x M cross-product.

The public provider-handle observation signature does not change. The implementation behind `rr.provider("ch_foen").observations(...)` changes from the placeholder `ObservationResult` to real retrieval, parsing, product resolution, native-field preference, unit conversion, daily aggregation / instant filtering, 366-day window decomposition, stitching, annotations, provenance, raw payload retention, and structured recoverable issues.

This step does not add the package-root `rr.observations(...)` wrapper; that is step 03. It also does not regenerate `provider.json`, change descriptive `bulk_observations` capability flags, expand T119/T120, update `docs/provider_ports/ch_foen.md`, add `rr.map_stations`, add a shared backend-policy abstraction, compute RivRetrieve-derived products from higher-frequency data, add wide-form pandas export, broaden the V1 product vocabulary, or add a second provider.

Legacy evidence is read from the D10 checkout:

```bash
git -C /Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python show cd9b030:rivretrieve/switzerland.py
```

Key citations:

- Public service token literal exists in legacy at `cd9b030:rivretrieve/switzerland.py:40`.
- Product/native-field map is `cd9b030:rivretrieve/switzerland.py:44-81`.
- 366-day maximum is `cd9b030:rivretrieve/switzerland.py:43`.
- Flux query shape and exclusive `stop` are `cd9b030:rivretrieve/switzerland.py:176-188`.
- Legacy N x M execution is independent per gauge/variable through `_download_data(gauge_id, variable, ...)` at `cd9b030:rivretrieve/switzerland.py:190-218`, not a multi-station or multi-product batched Flux query.
- Preferred/fallback same-timestamp ranking is `cd9b030:rivretrieve/switzerland.py:252-261`.
- `flow_ls` conversion divides by `1000.0` at `cd9b030:rivretrieve/switzerland.py:263-269`.
- Daily aggregation is floor-to-day mean at `cd9b030:rivretrieve/switzerland.py:290-297`.
- Instant products return all samples in `[start, end + 1 day)` at `cd9b030:rivretrieve/switzerland.py:348-352`.

## 2. API surface touched

Public surface:

- No public signature changes.
- No package-root `rr.observations(...)` wrapper in this step.
- No public type promotion and no public export of `ChFoen*` types.
- T119/T120 remain unchanged except for continuing to pass after the version bump required by project policy.
- `_ProviderHandle.observations(...)` dispatch order remains unchanged from M2 step 05: module-presence check first, then `ObservationRequest.from_inputs(...)`, then provider module call, then always-on annotation-name validation. This step must not invert that order.

Provider-module surface:

- `src/rivretrieve/_internal/providers/ch_foen/module.py`
  - Replace placeholder implementation in `observations(request, *, on_issue="warn")`.
  - Keep `info()`, packaged catalogue methods, `row_annotation_schema()`, and `series_annotation_schema()` signatures unchanged.
  - Remove placeholder result behavior and its placeholder provenance source.

New internal modules under `src/rivretrieve/_internal/providers/ch_foen/`:

- `query.py`
  - Product-to-native-field policy, Flux query construction, 366-day window decomposition, and sanitized query metadata helpers.
- `retrieval.py`
  - End-to-end request orchestration: N x M decomposition, per-window calls, parser invocation, stitching, issue accumulation, provenance assembly, and `ObservationResult` construction.
- `transform.py`
  - Product resolution, preferred/fallback native-field selection, unit conversion, daily aggregation, instant filtering, duplicate/overlap/conflict handling, gap checks, and annotation row generation.

Existing internal modules modified:

- `observation_client.py`
  - Add transport injection and real fetch behavior.
- `raw_payload.py`
  - Extend field-level raw response metadata if needed, while keeping credentials out.
- `parser.py`
  - Keep the step-01 native-record shape. Only change fatal parser exception inheritance if needed so parser contract failures subclass `FatalContractError`.
- `issue_codes.py`
  - Remove `OBSERVATIONS_NOT_YET_IMPLEMENTED`; keep only runtime recoverable observation/parser issue codes.

## 3. Data structures and types

This step remains pinned to architecture.md §11 request normalization, §12 long-form result shape, §13 declared annotations, §14 provenance without secrets, §15 two-channel issue policy, §16 time/unit representation, and §17 provider-internal stitching.

No new Pydantic model should use `extra="allow"`. If an executor introduces one anyway, D7 applies: tests for extras must use `Model.model_validate({...})` and inspect `model_extra`, never constructor kwargs. The recommended internal types below are frozen dataclasses or typed Polars frames, so D7 should not trigger.

Any `json.loads` walk must use concrete `dict` / `list` checks, not `Mapping` / `Sequence`, per D9. This step should only need JSON serialization for annotations, not JSON provider parsing.

### Product policies

Products are read from `src/rivretrieve/_internal/providers/ch_foen/catalogue/products.parquet`; the executor must stop if any parsed/resolved product ID is outside this set.

| product_id | native fields | preferred | fallback | frequency/statistic | canonical unit |
| --- | --- | --- | --- | --- | --- |
| `discharge_daily_mean` | `flow`, `flow_ls` | `flow` | `flow_ls` | daily / mean | `m3/s` |
| `discharge_instantaneous` | `flow`, `flow_ls` | `flow` | `flow_ls` | irregular / instantaneous | `m3/s` |
| `stage_daily_mean` | `height_abs`, `height` | `height_abs` | `height` | daily / mean | `m` |
| `stage_instantaneous` | `height_abs`, `height` | `height_abs` | `height` | irregular / instantaneous | `m` |
| `water_temperature_daily_mean` | `temperature` | `temperature` | none | daily / mean | `degC` |
| `water_temperature_instantaneous` | `temperature` | `temperature` | none | irregular / instantaneous | `degC` |

Native unit strings are inferred from field names plus legacy conversion behavior; they are not provider CSV columns. Use `flow -> m3/s`, `flow_ls -> L/s`, `height_abs -> m`, `height -> m`, and `temperature -> degC`. `flow_ls` values are multiplied by `0.001` to populate canonical discharge in `m3/s`; this matches the product catalogue unit for discharge and legacy division by `1000.0`.

### `ChFoenObservationClient`

Modify the constructor-only shell into a frozen dataclass with field-level contract:

| Field | Type | Meaning |
| --- | --- | --- |
| `token` | `str | None` | Optional override. If `None`, resolve from `CH_FOEN_INFLUX_TOKEN`, then fallback to the embedded public service credential. |
| `endpoint` | `str` | Defaults to `https://influx.konzept.space/api/v2/query?org=api.existenz.ch`. |
| `timeout_seconds` | `float` | Defaults to `60.0`, matching legacy POST timeout at line 209. |
| `transport` | `Callable[[ChFoenTransportRequest], ChFoenTransportResponse] | None` | Optional injected offline transport. `None` uses the real HTTP implementation. |

New frozen internal transport dataclasses:

| Type / field | Type | Meaning |
| --- | --- | --- |
| `ChFoenTransportRequest.endpoint` | `str` | Influx query endpoint, no token in URL. |
| `ChFoenTransportRequest.query` | `str` | Flux query string, no token. |
| `ChFoenTransportRequest.headers` | `dict[str, str]` | Includes Authorization at runtime only; never copied to provenance/raw metadata. |
| `ChFoenTransportRequest.timeout_seconds` | `float` | Request timeout. |
| `ChFoenTransportResponse.content` | `bytes` | CSV response bytes. |
| `ChFoenTransportResponse.status_code` | `int | None` | Provider HTTP status if available. |
| `ChFoenTransportResponse.retrieved_at` | `datetime` | UTC timestamp captured by client/transport. |

Recommendation for token embedding: hybrid. Embed the legacy public service credential as a private module constant for out-of-box parity with legacy line 40, but let `CH_FOEN_INFLUX_TOKEN` and explicit constructor `token=` override it. The token may appear only in the Authorization header and in `ChFoenObservationClient.token`; it must not be rendered by `__repr__`, copied to `ChFoenRawPayload` metadata, copied to `ObservationProvenance`, included in issues, logged, placed in fixtures, or inserted into URL/query strings. Since the URL has no auth query parameter, arch §14's secret/provenance boundary is not forced beyond the existing rule: provenance stores endpoint/query after explicit token stripping.

Token resolution order is explicit: constructor `token=` wins when non-`None`; otherwise use `CH_FOEN_INFLUX_TOKEN` if set; otherwise use the embedded public service credential. Existing step-01 tests that asserted a required `token: str` constructor field must be refreshed: `token` is now optional for default operation, and tests must assert this resolution order instead of adding a redundant required-token `__post_init__` guard.

Recommendation for network bypass: transport injection. Tests pass a deterministic callable that returns fixture bytes or raises controlled exceptions. This survives parallel pytest because no global monkeypatch or shared HTTP adapter is mutated. M2 step 05 observation tests used a registered stub provider and spies rather than network monkeypatching; transport injection preserves the same local dependency-injection shape while exercising the real provider pipeline.

### Query and window types

New frozen dataclasses:

| Type / field | Type | Meaning |
| --- | --- | --- |
| `ChFoenProductPolicy.product_id` | `str` | One of the six packaged product IDs. |
| `ChFoenProductPolicy.native_fields` | `tuple[str, ...]` | Fields used in the Flux `_field` filter. |
| `ChFoenProductPolicy.preferred_field` | `str` | Preferred field. |
| `ChFoenProductPolicy.fallback_field` | `str | None` | Fallback field, if any. |
| `ChFoenProductPolicy.canonical_unit` | `str` | Product catalogue unit. |
| `ChFoenProductPolicy.aggregate_daily` | `bool` | Whether to floor to day and mean. |
| `ChFoenProductPolicy.instant` | `bool` | Whether to return all instant samples. |
| `ChFoenTimeWindow.start` | `datetime` | Inclusive UTC-normalized window start. |
| `ChFoenTimeWindow.end` | `datetime` | Inclusive user-facing window end for day decomposition. |
| `ChFoenTimeWindow.query_stop` | `datetime` | Exclusive Flux stop. For day windows this is `end + 1 day` at `00:00:00Z`. |
| `ChFoenProviderCall.station_id` | `str` | Requested station. |
| `ChFoenProviderCall.product_id` | `str` | Requested product. |
| `ChFoenProviderCall.window` | `ChFoenTimeWindow` | Window for this call. |
| `ChFoenProviderCall.native_fields` | `tuple[str, ...]` | Fields requested. |
| `ChFoenProviderCall.query` | `str` | Flux query, no token. |

Window decomposition follows legacy `_split_windows`: if the request spans more than 366 calendar days, create inclusive day windows of at most 366 days, then advance the next window to the day after the previous window end. Flux itself uses exclusive `stop`, so adjacent windows do not overlap at the query boundary for day-normalized requests. Stitching still deduplicates by `(station_id, product_id, time)` after transformation; if duplicates carry identical canonical values emit `overlap`, if values differ emit `conflict` and preserve the non-selected value in row annotations.

### Raw payload

Keep `ChFoenRawPayload` provider-private. It may include raw bytes because the user explicitly exempted raw bytes from the token-literal scan, but this provider's CSV bytes should not contain the token. Field-level additions may be made:

| Type / field | Type | Meaning |
| --- | --- | --- |
| `ChFoenRawCsvResponse.csv_bytes` | `bytes` | Raw CSV body. |
| `ChFoenRawCsvResponse.endpoint` | `str` | Endpoint without credentials. |
| `ChFoenRawCsvResponse.query` | `str` | Query without credentials. |
| `ChFoenRawCsvResponse.status_code` | `int | None` | HTTP status. |
| `ChFoenRawCsvResponse.retrieved_at` | `datetime | None` | UTC retrieval timestamp. |
| `ChFoenRawCsvResponse.station_id` | `str | None` | Requested station for this payload. |
| `ChFoenRawCsvResponse.product_id` | `str | None` | Requested product for this payload. |
| `ChFoenRawCsvResponse.window_start` | `datetime | None` | Inclusive window start. |
| `ChFoenRawCsvResponse.window_end` | `datetime | None` | Inclusive window end. |

### Parser intermediate consumed

Consume the step-01 parser shape unchanged:

| Column | Type | Source |
| --- | --- | --- |
| `time` | `pl.Datetime(time_unit="us", time_zone="UTC")` | `_time`. |
| `station_id` | `str` | `loc`. |
| `native_field` | `str` | `_field`. |
| `native_value` | `float` | `_value`. |
| `measurement` | `str` | `_measurement`. |
| `window_start` | `pl.Datetime(time_unit="us", time_zone="UTC")` | `_start`. |
| `window_stop` | `pl.Datetime(time_unit="us", time_zone="UTC")` | `_stop`. |
| `table` | `int | None` | `table`. |

If a new field seems necessary, stop and request a step-01 amendment. Do not silently extend the parser output.

### ObservationResult columns populated

`ObservationResult.data` uses the existing M2 envelope and exactly these columns:

| Column | How ch_foen populates it |
| --- | --- |
| `time` | UTC timestamp from parser; daily products use floored day timestamp after aggregation, instant products preserve all parsed sample times that pass filtering. |
| `station_id` | Requested station ID / parser `station_id` after filtering to the request. |
| `product_id` | Requested packaged product ID resolved before transformation. |
| `value` | Canonical float after preferred/fallback choice, `flow_ls` conversion if applicable, and daily mean aggregation if applicable. |

`row_annotations` uses the existing M2 long annotation table. Emit every step-01 row annotation on real or synthetic paths:

| Annotation | Value |
| --- | --- |
| `native_field` | Native field selected for the canonical value. |
| `native_unit` | Inferred native unit for selected native field. |
| `converted_unit` | Product catalogue canonical unit. |
| `source_endpoint_or_query` | Sanitized endpoint/query identifier for the row's provider call. |
| `raw_value` | Provider `_value` before conversion/aggregation/conflict handling, encoded with `format(value, ".15g")`. For daily means, emit the aggregate pre-conversion daily raw mean tied to the daily row so row annotations stay one-to-one with canonical rows. |
| `alternative_native_field` | Non-selected same-timestamp field when overlap/conflict occurs. |
| `alternative_raw_value` | Non-selected same-timestamp raw value, encoded with `format(value, ".15g")`. |
| `alternative_native_unit` | Native unit for the non-selected field. |

`series_annotations` emits every step-01 series annotation for each station-product that reaches the retrieval pipeline:

| Annotation | Value |
| --- | --- |
| `preferred_source` | Product policy preferred native field. |
| `fallback_source_used` | Lowercase `"true"` / `"false"` string value in the annotation table, based on whether fallback rows contributed. |
| `native_unit_returned` | JSON-array string of sorted unique inferred native units seen, e.g. `["L/s"]` or `["L/s","m3/s"]`. |
| `converted_unit` | Product catalogue canonical unit. |
| `returned_time_range_start` | First returned canonical timestamp as ISO 8601 string with explicit `Z`. |
| `returned_time_range_end` | Last returned canonical timestamp as ISO 8601 string with explicit `Z`. |
| `resolved_timezone` | `UTC` for explicit provider `Z` timestamps parsed as UTC. |
| `timezone_mismatch_flag` | Lowercase `"false"` on normal fixture paths; lowercase `"true"` on synthetic ambiguity paths. |
| `provider_endpoint` | Influx endpoint without Authorization/token. |
| `provider_query_fields` | JSON-encoded object, described below. |

Annotation table values are `Utf8` in M2. Datetime/boolean/json/float value types are schema declarations, not native Polars value dtypes at the table boundary. Generator-side encoding is part of this step's contract:

- boolean annotations use exact lowercase strings `"true"` and `"false"`;
- datetime annotations use UTC ISO 8601 strings ending in `Z`;
- json annotations use `json.dumps(..., sort_keys=True, separators=(",", ":"))`;
- float annotations `raw_value` and `alternative_raw_value` use a canonical decimal string from `format(value, ".15g")`, so tests can parse them back to the expected float without depending on Polars display formatting.

### `provider_query_fields` JSON shape

JSON-encode before constructing `AnnotationTable`, per execution.md §8 and D8. Recommended shape:

For a one-window request, the encoded JSON object has this shape:

```json
{
  "bucket": "existenzApi",
  "measurement": "hydro",
  "station_id": "2206",
  "product_id": "discharge_instantaneous",
  "native_fields": ["flow", "flow_ls"],
  "preferred_field": "flow",
  "fallback_field": "flow_ls",
  "windows": [
    {
      "range_start": "2025-01-01T00:00:00Z",
      "range_stop": "2025-01-02T00:00:00Z"
    }
  ]
}
```

For multi-window requests, `windows` contains one object per provider call window in execution order. The annotation remains series-level while still representing the full decomposed request.

Do not include endpoint tokens, Authorization headers, environment-variable names with values, or raw response bytes. Generator-side serialization tests must build this object from the provider pipeline and assert the emitted annotation value is already a JSON string that round-trips with `json.loads`.

## 4. Errors and failure modes

This is the load-bearing section. Fatal contract failures raise directly and never call `apply_on_issue`. Recoverable provider/data problems become `Issue` objects with `ChFoenObservationIssueCodes` and are routed exactly once through `apply_on_issue(issues, on_issue)` in `retrieval.py` after partial `ObservationResult` assembly.

### Fatal contract failures

| Failure | FatalContractError subclass and direct raise call site |
| --- | --- |
| Provider has no observation module registered | Existing `ObservationsUnavailableError` from `_ProviderHandle.observations(...)` before request construction; unchanged. |
| Missing `start` | Existing `InvalidObservationRequestError` from `ObservationRequest.from_inputs(...)` called by `_ProviderHandle.observations(...)`; provider module not called. |
| Missing `end` | Existing `InvalidObservationRequestError` from `ObservationRequest.from_inputs(...)`; provider module not called. |
| Empty/malformed `stations` or `products` input | Existing `InvalidObservationRequestError` from `ObservationRequest.from_inputs(...)`; provider module not called. |
| Requested product ID is not in packaged `products.parquet` or product policy table | `InvalidObservationRequestError` raised directly by `query.resolve_product_policy(...)` before transport calls. |
| Parser sees malformed CSV bytes | Change/keep `ChFoenObservationParserError` as a `FatalContractError` subclass with `.code == "malformed_csv"`, raised directly by `parse_ch_foen_observation_csv(...)`. |
| Parser sees missing required Flux CSV columns | `ChFoenObservationParserError(FatalContractError)` with `.code == "missing_required_column"`, raised directly by `parse_ch_foen_observation_csv(...)`. |
| Native field maps to no known unit/conversion rule in code | `FatalContractError` or `ObservationDataSchemaError` raised directly by `transform.convert_units(...)`; this is implementation drift, not provider ambiguity. |
| Transformed result violates `ObservationDataSchema` | Existing `ObservationDataSchemaError` from `ObservationResult` construction. |
| Annotation table has wrong columns/dtypes | Existing `AnnotationSchemaViolationError` from `AnnotationTable` construction. |
| Retrieval emits undeclared row/series annotation | Existing `AnnotationSchemaViolationError` from `_ProviderHandle.observations(...)` always-on `validate_annotation_names(...)`. |
| Provenance/raw metadata would include token or Authorization header | `FatalContractError` raised by a local redaction assertion in provenance/raw assembly before returning. |
| `on_issue` value is outside `OnIssue` contract | Existing issue-policy behavior; do not create a ch_foen issue. |

### Recoverable issues

| Runtime condition | ChFoenObservationIssueCodes value and `apply_on_issue` route |
| --- | --- |
| Empty successful CSV / parser returns no records for a requested station-product-window | `MISSING_DATA`; parser may emit it and retrieval scopes it with station/product/window details before `apply_on_issue` in `retrieval.observations_for_request(...)`. |
| All windows for one station-product succeed technically but no rows remain after station/product/field filtering | `MISSING_DATA`; raised as an `Issue` by `transform.resolve_series(...)`, routed by retrieval. |
| One station-product-window transport call fails while at least one other requested unit succeeds | `SOURCE_REQUEST_FAILED` for the failed call and `PARTIAL_RESPONSE` for the overall request; caught in `retrieval.fetch_call(...)`, accumulated, then routed by retrieval. |
| Every transport call fails | `SOURCE_REQUEST_FAILED` for each failed call plus request-level `MISSING_DATA`; no `PARTIAL_RESPONSE` because nothing succeeded. Return a well-formed empty `ObservationResult` by default and let `on_issue="raise"` raise through `apply_on_issue`. |
| One station-product-window parser returns recoverable row drops (`invalid_timestamp`, `invalid_numeric_value`) | Existing parser issue codes are retained, scoped with station/product/window by retrieval, and routed by retrieval. |
| Requested N x M result has at least one successful station-product and at least one failed/missing station-product/window | `PARTIAL_RESPONSE`; retrieval emits a request-level issue and returns a well-formed partial `ObservationResult`. |
| Expected daily product has missing days inside the requested range after aggregation | `GAP`; `transform.detect_gaps(...)` emits issue. Do not fill values. |
| Expected instant product has a provider-declared window gap detectable from adjacent 366-day windows or missing returned range | `GAP`; emit only when there is concrete window/range evidence, not merely irregular sampling. |
| Duplicate `(station_id, product_id, time)` rows with the same canonical value after stitching | `OVERLAP`; `transform.stitch_series(...)` drops duplicates deterministically and emits issue. |
| Duplicate `(station_id, product_id, time)` rows with different canonical values, or preferred/fallback native fields disagree at the same timestamp | `CONFLICT`; preferred value wins, alternatives are preserved in row annotations, and issue is routed. |
| Provider returns both preferred and fallback fields in one window | If preferred rows exist for a timestamp, preferred wins for that timestamp. If preferred exists anywhere in the window but fallback covers timestamps preferred lacks, fallback may fill those timestamps; emit `OVERLAP` when both fields share timestamps and `fallback_source_used=true` when fallback contributes. If values disagree at shared timestamps after conversion, also emit `CONFLICT`. |
| Provider response contains a native unit/field combination where a deterministic conversion cannot be chosen from provider evidence | `UNIT_CONVERSION_AMBIGUITY`; emitted by `transform.convert_units(...)`, row is dropped or series omitted rather than guessed, then routed. The finite real ch_foen field set makes this synthetic-only in step 02; see test 13. |
| Timestamp lacks explicit offset, cannot be confirmed as UTC, or parser detects a mismatch with expected explicit `Z` source shape | `TIMEZONE_AMBIGUITY`; emitted by parser/transform and routed. If this requires choosing a new arch §16 interpretation, stop and escalate instead. |

Placeholder transition:

- Delete `ChFoenObservationIssueCodes.OBSERVATIONS_NOT_YET_IMPLEMENTED`.
- Delete or rewrite placeholder tests that asserted `observations_not_yet_implemented`.
- Do not alias it to another runtime code. The placeholder path is removed and should be unreachable; keeping an alias would make a removed implementation state look like a valid recoverable provider condition.

`on_issue="raise"` behavior: the provider still constructs the recoverable `Issue` objects first, then `apply_on_issue` raises `IssuePolicyError` for warning/error issues. This is the required two-channel conversion; it does not turn the original runtime condition into a fatal contract failure.

## 5. Tests

1. `test_ch_foen_observations_2206_discharge_fallback_converts_to_m3s`: public handle, fixture transport returns station 2206 `flow_ls`; result uses `discharge_instantaneous`, converts L/s to `m3/s`, pins value range `0.014..0.015` and mean `0.014944444444`, and emits fallback/unit annotations.
2. `test_ch_foen_observations_2282_stage_instant_returns_all_samples`: public handle, fixture transport returns station 2282 `stage_instantaneous`; all instant samples in the requested window are returned.
3. `test_ch_foen_observations_2016_temperature_daily_mean`: public handle, fixture transport returns station 2016 temperature; `water_temperature_daily_mean` emits one daily mean row.
4. `test_ch_foen_observations_multi_station_single_product_bulk`: two stations with one product produce the long-form union and per-series annotations.
5. `test_ch_foen_observations_single_station_multi_product_bulk`: one station with two products produces independent station-product series.
6. `test_ch_foen_observations_cross_product_bulk`: multiple stations x multiple products execute as the full N x M cross-product and preserve request order only where contractually needed.
7. `test_ch_foen_observations_decomposes_over_366_days_and_stitches`: synthetic range longer than 366 days yields multiple calls, seam stitches with no duplicate timestamps and no gap.
8. `test_ch_foen_row_annotations_all_declared_ids_are_emitted`: fixture/synthetic paths collectively emit the eight declared row annotation IDs and no others.
9. `test_ch_foen_series_annotations_all_declared_ids_are_emitted`: fixture/synthetic paths collectively emit the ten declared series annotation IDs and no others.
10. `test_ch_foen_overlap_annotation_and_issue`: synthetic duplicate same-value seam emits `overlap` plus alternative row annotations where applicable.
11. `test_ch_foen_conflict_annotation_and_issue`: synthetic preferred/fallback disagreement emits `conflict` and preserves alternative raw value/unit/field annotations.
12. `test_ch_foen_gap_issue`: synthetic daily missing date emits `gap`.
13. `test_ch_foen_unit_conversion_ambiguity_issue`: synthetic unknown native field/unit condition emits `unit_conversion_ambiguity`.
14. `test_ch_foen_timezone_ambiguity_issue`: synthetic timestamp without explicit offset or mismatch emits `timezone_ambiguity`; stop instead if this would force a new arch §16 interpretation.
15. `test_ch_foen_missing_data_issue`: successful empty fixture response emits `missing_data`.
16. `test_ch_foen_partial_failure_returns_well_formed_result`: one station-product-window succeeds and another transport call fails; returned `ObservationResult` is valid and has `source_request_failed` plus `partial_response`.
17. `test_ch_foen_all_transport_calls_fail_returns_empty_with_issues`: every injected call fails; result is empty/well-formed with `source_request_failed` issues and request-level `missing_data`, not `partial_response`.
18. `test_ch_foen_provenance_contains_sanitized_calls`: provenance has per-call endpoint/query/timestamps/status codes, request, RivRetrieve version, and catalogue version, with no token literal or Authorization header.
19. `test_ch_foen_raw_payload_metadata_is_sanitized`: raw metadata/query fields contain no token literal, while raw bytes are permitted by the question's explicit exception.
20. `test_ch_foen_tests_tree_does_not_contain_public_token_literal`: scan committed files under `tests/` and assert the embedded public token literal is absent.
21. `test_ch_foen_missing_start_raises_before_provider_execution`: negative control; public handle raises `InvalidObservationRequestError` directly and injected transport is not called.
22. `test_ch_foen_missing_end_raises_before_provider_execution`: same for `end`.
23. `test_ch_foen_undeclared_annotation_emission_raises_directly`: synthetic module/path emits an undeclared annotation and `_ProviderHandle` raises `AnnotationSchemaViolationError`, not `IssuePolicyError`.
24. `test_ch_foen_on_issue_raise_converts_recoverable_issue`: recoverable ch_foen issue with `on_issue="raise"` raises `IssuePolicyError` containing the structured issue.
25. `test_ch_foen_provider_query_fields_generator_serializes_json`: generator-side D8 test; emitted `provider_query_fields` is compact sorted JSON, includes a `windows` array, and round-trips to the expected object.
26. `test_ch_foen_boolean_annotations_generator_serializes_utf8`: generator-side D8 test; `fallback_source_used` and `timezone_mismatch_flag` emit exact lowercase `"true"` / `"false"` strings.
27. `test_ch_foen_datetime_annotations_generator_serializes_iso_z`: generator-side D8 test; `returned_time_range_start` and `returned_time_range_end` emit exact ISO 8601 UTC strings ending in `Z`.
28. `test_ch_foen_float_annotations_generator_serializes_decimal_utf8`: generator-side D8 test; `raw_value` and `alternative_raw_value` emit canonical `format(value, ".15g")` strings that parse back to expected floats.
29. `test_ch_foen_native_unit_returned_generator_serializes_json_array`: generator-side D8 test; `native_unit_returned` emits the pinned compact JSON-array string of sorted unique units.
30. `test_ch_foen_flow_ls_generator_converts_value_before_result`: generator-side D8 test; pipeline emits canonical `value` in `m3/s`, not loader-side conversion only.
31. `test_ch_foen_timestamp_generator_normalizes_utc`: generator-side D8 test; pipeline emits UTC-normalized timestamp values in result data.
32. `test_ch_foen_observation_client_uses_injected_transport`: injected transport records request endpoint/query/headers and returns fixture bytes; no network call is made.
33. `test_ch_foen_observation_client_default_transport_is_not_used_in_tests`: monkeypatch default HTTP function to raise if touched during test suite.
34. `test_ch_foen_observation_client_token_resolution_order`: constructor token overrides env, env overrides embedded public credential, and `token=None` is accepted.
35. `test_ch_foen_observations_not_yet_implemented_code_removed`: issue enum no longer exposes the placeholder code and placeholder module test is gone/replaced.
36. `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface` (T119) unchanged.
37. `tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion` (T120) unchanged.
38. `tests/test_offline_import.py::test_import_rivretrieve_does_not_import_providers_stubs_or_generators` still passes.
39. Full `uv run pytest` must pass without network because every retrieval test uses injected transport and the default transport is guarded against accidental use.

Use `polars.testing.assert_frame_equal` / `assert_series_equal` for complex Polars result comparisons.

## 6. Files

Implementation order must keep `uv run pytest` green without network at each checkpoint unless explicitly marked atomic.

1. Add `src/rivretrieve/_internal/providers/ch_foen/query.py`.
   - Product policies, product lookup against packaged products, Flux query builder, sanitized query fields, and 366-day window decomposition.
   - Add focused unit tests that do not touch `module.observations`.
2. Modify `src/rivretrieve/_internal/providers/ch_foen/observation_client.py`.
   - Add transport request/response dataclasses, env/constructor/default token resolution, injected transport, default HTTP transport, and redacted repr.
   - Tests use fake tokens and injected transport only.
3. Modify `tests/test_ch_foen_observation_client.py`.
   - Cover defaults, redaction, injected transport, token-resolution order, and no token in repr/request metadata assertions.
   - Remove stale "token is required" expectations from the constructor-only shell tests; `token=None` is now the default-operation path.
4. Modify `src/rivretrieve/_internal/providers/ch_foen/raw_payload.py`.
   - Add station/product/window metadata fields if needed. Keep all metadata sanitized.
5. Modify `src/rivretrieve/_internal/providers/ch_foen/parser.py` if needed.
   - Only allowed change is making `ChFoenObservationParserError` subclass `FatalContractError`; do not change emitted record columns.
   - Existing parser tests catch `ChFoenObservationParserError` by class name rather than `ValueError`, so do not add a compatibility bridge or dual inheritance just for tests.
6. Add `src/rivretrieve/_internal/providers/ch_foen/transform.py`.
   - Implement field filtering, preference/fallback, conversion, aggregation, instant filtering, stitching, gap/overlap/conflict detection, and annotation generation.
   - Add transform tests using parser fixture outputs and synthetic Polars frames.
7. Add `src/rivretrieve/_internal/providers/ch_foen/retrieval.py`.
   - Implement request decomposition, transport invocation, parser integration, issue scoping/routing through `apply_on_issue`, provenance, raw payload assembly, and `ObservationResult` construction.
   - Add retrieval tests with injected transport.
8. Atomic placeholder-removal checkpoint:
   - Modify `src/rivretrieve/_internal/providers/ch_foen/issue_codes.py` to remove `OBSERVATIONS_NOT_YET_IMPLEMENTED`.
   - Modify `src/rivretrieve/_internal/providers/ch_foen/module.py` to delegate `observations(...)` to `retrieval.retrieve_observations(...)`.
   - Modify `tests/test_ch_foen_module.py` to delete placeholder assertions and assert real fixture-backed behavior or module delegation.
   - These edits are coupled because changing either side alone creates a red test state.
9. Add `tests/test_ch_foen_observations.py`.
   - Public-handle fixture tests, bulk shapes, partial failure, all-fail behavior, provenance, token-literal absence under `tests/`, annotation coverage, D8 generator-side encoding tests, and negative controls.
10. Extend `tests/test_ch_foen_observation_parser.py` only if needed for timezone ambiguity or fatal parser inheritance.
11. Keep `tests/test_ch_foen_generate_catalogue.py` unchanged except for ensuring full-suite offline behavior still passes; no live network.
12. Run gates: `uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`, `uv run pytest`.
13. Apply mandatory patch version bump with `uv run bump-my-version bump patch`, stage version files with plan/code, commit, and tag per AGENTS.md. Version-literal edits to `src/rivretrieve/__init__.py` are allowed; API-shape edits are not.

## 7. Open questions

1. Token embedding mechanism.
   - Recommendation: hybrid embedded public service credential plus `CH_FOEN_INFLUX_TOKEN` and constructor override. Legacy line: `cd9b030:rivretrieve/switzerland.py:40`. This preserves out-of-box legacy behavior while keeping the token out of provenance by construction: provenance records only sanitized endpoint/query/call metadata, never headers or `client.token`.
2. Network bypass strategy.
   - Recommendation: transport injection on `ChFoenObservationClient`. It survives parallel pytest, avoids global monkeypatch state, and aligns with M2 step 05's local stub/spy approach for observation dispatch.
3. Flow vs `flow_ls` preference policy.
   - Recommendation: preferred is `flow`; fallback is `flow_ls`. Legacy `cd9b030:rivretrieve/switzerland.py:252-261` chooses preferred per timestamp by rank. This step should use that rule: when both appear at the same timestamp, `flow` wins. If `flow` appears for some timestamps and `flow_ls` fills others in the same window, fallback contributes for missing preferred timestamps and `fallback_source_used=true`.
4. `flow_ls` unit conversion factor and resulting unit string.
   - Recommendation: multiply by `0.001` (`L/s -> m3/s`), from legacy division at `cd9b030:rivretrieve/switzerland.py:263-269`. Product catalogue confirms discharge unit `m3/s`.
5. 366-day window decomposition.
   - Recommendation: inclusive day windows of at most 366 days, Flux `stop` exclusive at the following midnight, then deduplicate by `(station_id, product_id, time)` during stitching. If one window fails and another succeeds, emit `source_request_failed` for the window and request-level `partial_response`; emit `gap` only when the returned successful windows prove a missing time range in the stitched series.
6. Daily aggregation rule.
   - Recommendation: mean after native-field filtering, preferred/fallback choice, unit conversion, duplicate handling, and sorting. Legacy floors to day and groups mean at `cd9b030:rivretrieve/switzerland.py:290-297`. This applies to all three daily products.
7. Instant filtering rule.
   - Recommendation: return all instant samples in the requested interval, not the most recent sample. Legacy filters instant variables to `df.index >= start_dt` and `< end_dt + 1 day` at `cd9b030:rivretrieve/switzerland.py:348-352`.
8. Timezone interpretation.
   - Recommendation: parser and canonical observation timestamps are UTC for explicit provider `Z` timestamps. This confirms, rather than extends, architecture.md §16 because the provider supplies explicit UTC offsets and step 01 already parses `pl.Datetime(time_unit="us", time_zone="UTC")`. `resolved_timezone` is `UTC`; `timezone_mismatch_flag` differs only on synthetic ambiguity paths. Stop if a fixture lacks an offset and a new interpretation is required.
9. ObservationResult column set.
   - Recommendation: exactly M2 columns `time`, `station_id`, `product_id`, `value`; sources listed in §3. Provider-scoped rows do not include `provider_id`.
10. `provider_query_fields` JSON encoding shape.
    - Recommendation: compact sorted JSON object in §3 with bucket, measurement, station/product, native fields, preferred/fallback, and a `windows` array of range start/stop pairs. Generator-side test asserts serialization before `AnnotationTable` construction per D8.
11. M3 `observations_not_yet_implemented` issue code.
    - Recommendation: delete, not alias. The placeholder is removed and no runtime path should report "not yet implemented" after this step.
12. Multi-station x multi-product execution strategy.
    - Recommendation: N x M independent transport calls, each decomposed into windows. Legacy exposes `_download_data(gauge_id, variable, ...)` per gauge and variable at `cd9b030:rivretrieve/switzerland.py:190-218`; there is no legacy batched Flux query. A later optimization can batch only with new evidence and tests.

## 8. Deferrals

- Package-root `rr.observations(...)`: step 03. Hard rationale: wrapper must delegate to the real provider path after this step lands and should not be mixed with placeholder removal.
- T119/T120 expansion: step 03. Hard rationale: root public surface does not change in step 02.
- `provider.json` regeneration / descriptive `bulk_observations` capability update: step 03. Hard rationale: this step proves behavior first; capability description follows.
- `docs/provider_ports/ch_foen.md` observation sections: step 03. Hard rationale: provider-port docs should describe the landed retrieval path after tests stabilize.
- Shared backend-policy abstraction: post-V1 unless architecture changes. Hard rationale: architecture.md §17 explicitly keeps stitching provider-internal for V1.
- RivRetrieve-derived products: deferred. Hard rationale: architecture.md §11 says product filters are catalogue products, not instructions to compute new statistics; missing source products emit issues.
- Wide-form pandas export: post-V1. Hard rationale: architecture.md §12 minimum export is long-form.
- Broad V1 product-vocabulary expansion: deferred. Hard rationale: artifact-driven product IDs only.
- `rr.map_stations`: M5. Hard rationale: outside observation retrieval.
- Additional providers: post-V1 unless architecture changes.

## 9. Stopping conditions for the executor

- Stop if a fatal contract failure would be routed through `apply_on_issue`, or a recoverable provider/data issue would be raised directly as a fatal.
- Stop if any step-01 annotation declaration has no honest runtime path to emit in this step; remove via amendment or implement the path.
- Stop if retrieval emits any annotation not declared in step 01.
- Stop if product resolution yields a product ID outside `products.parquet`.
- Stop if any token/Authorization value lands in provenance, raw metadata, log text, exception text, committed fixture, or test expected data.
- Stop if any test or `generate_catalogue.py` requires live network.
- Stop if the bulk path seems to require a shared backend-policy abstraction.
- Stop if timezone handling requires choosing an interpretation for timestamps without explicit offset.
- Stop if multi-endpoint stitching beyond the single Influx endpoint is forced.
- Stop if provenance needs an auth-bearing URL for debugging; redact or escalate.
- Stop if the plan touches package-root API shape, T119/T120 expectations, `_ProviderHandle` dataclass fields/order, or `ProviderRegistry` beyond existing dispatch.
- Stop if work drifts into `rr.map_stations`, station mapping, V1 closeout, or a second provider.
- Stop if an implementation checkpoint cannot keep `uv run pytest` green without network; re-cut as an explicitly atomic checkpoint before proceeding.
