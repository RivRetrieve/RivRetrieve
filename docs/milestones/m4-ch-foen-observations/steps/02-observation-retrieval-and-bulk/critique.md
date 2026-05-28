# 02-observation-retrieval-and-bulk Critique

## Verdict

SEND BACK TO PLANNER.

The plan is largely architecturally sound — two-channel routing, vocabulary boundary, network isolation, provenance secret boundary, and inherited patterns all hold. Two findings push the verdict back to the planner instead of dispatching with minors folded:

1. The legacy citation for instant filtering is to the wrong line range, and the same wrong range is repeated in two places. Per D10 reviewer guidance ("upgrade to Major only if the cited line is actually wrong"), a misciation by ~32 lines is Major.
2. The D8 asymmetric-encoding generator-side coverage is partial: three D8 round-trip tests are listed, but three more declared annotation columns with asymmetric encodings (boolean → "true"/"false" Utf8, datetime → ISO Utf8, and the under-specified `native_unit_returned` shape) have no explicit generator-side test. M4 step 02 is the load-bearing first generator of these encodings; partial D8 coverage at this hand-off is the exact failure mode D8 was logged to prevent.

Neither finding requires an architecture decision or a vocabulary expansion, so this is not an ESCALATE. The corrections are straight planner edits — fix the line range and add the four-or-five generator-side D8 tests / pin the under-specified shape — and the plan can dispatch on the next pass.

## Major findings

**M1. Legacy citation for instant filtering points to docstring, not code.**

Plan §1 (line 32) and Plan §7 question 7 both cite `cd9b030:rivretrieve/switzerland.py:316-319` for the instant filtering rule. I ran `git -C /Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python show cd9b030:rivretrieve/switzerland.py | awk 'NR>=310 && NR<=354'` and confirmed:

- Lines 316-319 are the docstring of `get_data(...)` describing the `start_date` / `end_date` arguments. They contain no filtering logic.
- The actual instant filtering code is at lines 348-352:
  ```
  348:         start_dt = pd.to_datetime(start_date)
  349:         end_dt = pd.to_datetime(end_date)
  350:         if "instantaneous" in variable or "hourly" in variable:
  351:             end_dt = end_dt + pd.Timedelta(days=1)
  352:             return df[(df.index >= start_dt) & (df.index < end_dt)]
  ```

The captured *fact* (instant filtering returns all samples in `[start, end + 1 day)`) is correct. The cited line range is wrong by ~32 lines. Per D10: "upgrade to Major only if the cited line is actually wrong" — this is "actually wrong," not "doesn't name the legacy-checkout path." Major.

Fix: replace both occurrences of `cd9b030:rivretrieve/switzerland.py:316-319` with `cd9b030:rivretrieve/switzerland.py:348-352` (or `:350-352` if you want only the if-block).

**M2. D8 generator-side coverage is partial: three columns have round-trip tests; at least three more declared annotation columns with the same asymmetric encoding shape have none.**

Plan §3 spells out the asymmetric-encoding contract explicitly: "Annotation table values are `Utf8` in M2. Datetime/boolean/json value types are schema declarations, not native Polars value dtypes at the table boundary." That means *every* annotation whose step-01 declared `value_type` is not `string` is an asymmetric-encoding column with the same D8 obligation as `provider_query_fields`. Step 01's declared annotations (verified against `src/rivretrieve/_internal/providers/ch_foen/module.py:68-183`) include these non-`string` value types that this step is the first to emit:

| annotation_id | declared value_type | encoded as | Generator-side D8 test in plan? |
|---|---|---|---|
| `raw_value` | `float` | Utf8 | not listed |
| `alternative_raw_value` | `float` | Utf8 | not listed |
| `fallback_source_used` | `boolean` | Utf8 (`"true"`/`"false"`) | not listed |
| `timezone_mismatch_flag` | `boolean` | Utf8 (`"true"`/`"false"`) | not listed |
| `returned_time_range_start` | `datetime` | Utf8 ISO | partial via test 25 (UTC normalization in data/annotations) |
| `returned_time_range_end` | `datetime` | Utf8 ISO | partial via test 25 |
| `provider_query_fields` | `json` | Utf8 JSON | test 23 |
| `value` (data column, not annotation) | float | Float64 | test 24 (flow_ls conversion); test 25 (UTC timestamp) |

Plan §5 lists generator-side tests 23 (JSON), 24 (flow_ls conversion in `value`), 25 (UTC normalization). It does NOT list a generator-side round-trip for the boolean-as-string serialization, nor an explicit ISO-string round-trip for the datetime annotations distinct from the `data.time` UTC normalization (test 25 talks about result data/annotations as one item, which under-specifies whether ISO encoding into the annotation Utf8 column is exercised).

Additionally Plan §3 leaves `native_unit_returned` shape under-specified ("JSON string or comma-separated stable string of inferred native units seen. Use one shape and test it.") — that decision is exactly the kind of shape-pin the planner should make, not the executor, because it's the asymmetric-encoding contract that downstream readers will depend on.

Per D8 verbatim: "for every catalogue/result column with an asymmetric encoding (anything where loader semantics differ from raw parquet type), verify the GENERATOR side serializes correctly." Step 02 IS the first generator of observation annotations and is the high-risk surface D8 explicitly named: "Candidate columns to audit proactively in M4: anything in observation results with JSON-encoded annotations, timestamp columns with timezone normalization, etc."

Fix: add explicit generator-side tests (or extend the existing ones) for:

- boolean-encoded annotations (`fallback_source_used`, `timezone_mismatch_flag`) → exact `"true"`/`"false"` Utf8 values;
- datetime-encoded annotations (`returned_time_range_start`/`_end`) → exact ISO 8601 Utf8 with explicit `Z`;
- float-encoded annotations (`raw_value`, `alternative_raw_value`) → confirm representation choice (cast-to-string vs JSON number-as-string) and pin it;
- `native_unit_returned` → planner picks JSON-array string OR comma-separated string and pins it in §3, then the test asserts that exact shape.

## Minor findings

**m1. §4 doesn't name the all-transport-calls-fail outcome.** §4 covers "one window fails, another succeeds" with `SOURCE_REQUEST_FAILED` + `PARTIAL_RESPONSE`. It also covers "all windows technically succeed but no rows survive filtering" with `MISSING_DATA`. The case "every transport call fails" is unspecified. Two reasonable behaviors are: (a) `SOURCE_REQUEST_FAILED` per failed call + `MISSING_DATA` at request level, no `PARTIAL_RESPONSE` (because nothing partial succeeded), with a well-formed empty `ObservationResult`; (b) raise. Architecture §15 says "recoverable provider/data problems return partial results with issues by default," which argues for (a). Pin (a) in §4, then keep `on_issue="raise"` as the user-side knob.

**m2. Plan §5 test 1 doesn't pin numeric converted-range expectation for station 2206.** Step 01 execution.md §4 records the 2206 fixture native-value range as `14..15` L/s with mean `14.944444444444`. After multiplying by `0.001`, canonical `value` should be `0.014..0.015` m³/s and mean `0.014944444444`. Test 1 says "converts L/s to `m3/s`" but doesn't pin the numeric range. Pin it (range bounds and mean), otherwise the conversion-factor regression risk slips past the test.

**m3. Recommendation in §3 for the token embedding is "hybrid": embed the legacy literal as a private module constant.** That's defensible per step 01's token-classification probe. But the plan should add a concrete safeguard test that the token literal does not appear in any committed file under `tests/`. Step 01's executor confirmed the three CSV fixtures don't contain the token (legacy response bodies don't carry auth), but the safeguard against future leakage isn't a written test. Plan §5 tests 17/18 cover provenance/raw-metadata but not "no token under `tests/`." Add a global token-literal absence test under `tests/`, parameterized on the literal source, to keep §9's stopping condition enforced by code.

**m4. `provider_query_fields` JSON shape recommended in §3 includes `range_start`/`range_stop`.** These are window-level facts, but `provider_query_fields` is a series-level annotation. For multi-window requests the series-level annotation will need to represent multiple windows. Plan §3 silently shows a single window's range in the example. Decide and pin: does the series-level `provider_query_fields` represent the full requested span (then drop per-window seams from the example), or does it list per-window range pairs (then declare it as an array-of-objects)? Right now an executor would have to guess.

**m5. §6 step 5 only allows changing `ChFoenObservationParserError` base from `ValueError` to `FatalContractError`.** Confirmed safe against existing parser tests (they catch by class name, not `ValueError`), but the plan should note this explicitly so the executor doesn't preemptively add a `(ValueError, FatalContractError)` bridge "for safety."

**m6. §3 "ChFoenObservationClient" table changes the `token` field type from step 01's required `str` to `str | None` and adds three new fields (`transport`, `endpoint`, `timeout_seconds` already existed).** This is a meaningful re-shaping of a step 01 artifact. Step 01 tests built clients with `token="..."`. Plan §6 step 3 says to update those tests, but does not explicitly mention removing the now-stale "token=required" assertion or asserting the new field-resolution order (env → embedded → constructor override). Spell that out so the executor doesn't add a redundant `__post_init__` check that fights the optional.

**m7. §3 "Provider response contains a native unit/field combination where a deterministic conversion cannot be chosen from provider evidence" → `UNIT_CONVERSION_AMBIGUITY`.** The ch_foen native-field set is finite and known (`flow`, `flow_ls`, `height_abs`, `height`, `temperature`). The `flow_ls` conversion is the only conversion in scope. It's hard to construct a real condition that produces this issue *from the provider*; in practice the only path is "synthetic-only test." Plan §5 test 13 acknowledges this as synthetic. Cross-reference §4 to §5 test 13 explicitly so the executor doesn't think there's a real provider-side branch to write.

## Nits

**n1. §1 line 28** has stylistic redundancy: "Legacy N x M execution is independent per gauge/variable through `_download_data(gauge_id, variable, ...)` at `cd9b030:rivretrieve/switzerland.py:190-218`, not a multi-station or multi-product batched Flux query." The double-negative phrasing is fine but the citation `190-218` should be checked — verified at lines 190-218; the citation IS correct.

**n2. §3 ChFoenObservationClient table** uses `Callable[[ChFoenTransportRequest], ChFoenTransportResponse] | None` with the `|` union. Confirm the project's typing convention (PEP 604 unions are present in step 01 code, so this is consistent). Fine.

**n3. §7 question 11** mentions deleting `OBSERVATIONS_NOT_YET_IMPLEMENTED`. Confirmed: `src/rivretrieve/_internal/providers/ch_foen/issue_codes.py:7` carries the placeholder. Plan §6 step 8 atomically removes the enum entry, switches `module.observations` to delegate, and updates `tests/test_ch_foen_module.py`. Coherent.

**n4. §3 product policy table includes a "Native unit strings are inferred from field names" footnote.** Match the step 01 parser-helper inferences: `flow -> m3/s`, `flow_ls -> L/s`, `height_abs -> m`, `height -> m`, `temperature -> degC`. The plan also has the same set in §3 prose. Consistent.

## Lens-by-lens summary

- L1 (scope completeness): ✅ — every M4-tracker behavior is addressed: single + bulk × single + multi product, windowing, stitching, preference + conversion, daily aggregation, instant filtering, structured Issues, sanitized provenance, all step-01 annotations emitted.
- L2 (scope over-reach): ✅ — `rr.observations` wrapper, T119/T120 changes, `provider.json` regeneration, port-doc updates, M5 work all explicitly deferred.
- L3 (citation verification — generic): ✅ — verified line ranges 40, 43, 44-81, 176-188, 190-218, 252-261, 263-269, 290-297. All correct. The exception is the instant filtering range (M1 above).
- L4 (test coverage adequacy): ❌ — three D8 generator-side tests but at least four asymmetric-encoded annotations without explicit generator-side coverage (M2 above); no numeric converted-range pin in test 1 (m2 above); no token-literal absence test under `tests/` (m3 above).
- L5 (error handling completeness): ✅ — failure-mode table covers missing_data, partial_response, gap, overlap, conflict, unit_conversion_ambiguity, timezone_ambiguity each routed exactly once, fatal contract failures separated. One gap (all-transport-fail unspecified — m1 above), not blocking.
- L6 (open question rigor): ✅ — Q3 (flow preference) cites lines 252-261 verified; Q4 (conversion factor) cites lines 263-269 verified; Q5 (window seam dedup) cites legacy `_split_windows` behavior consistent with lines 176-188 and 190-218; Q6 (daily aggregation) cites lines 290-297 verified; Q7 (instant filtering) cites wrong line range (M1). Recommendations are evidence-backed except Q7's line range.
- L7 (deferral hygiene): ✅ — every §8 deferral is named with a hard rationale; the `bulk_observations` capability deferral to step 03 is honest because the descriptive flag should follow tested behavior, not lead it.
- L8 (implementation order): ✅ — §6 ordering keeps `uv run pytest` green at each checkpoint; step 8 (placeholder-removal + module delegation + test rewrite) is correctly marked atomic, not abused to hide a green-failure gap. New retrieval tests at step 7 use injected transport against retrieval.py directly without touching module.observations.
- L9 (stopping conditions adequacy): ✅ — §9 names live-network temptation, parser-extension creep, product-vocabulary drift, secret leakage, two-channel mis-routing, shared-backend-abstraction creep, timezone interpretation escalation, multi-endpoint stitching escalation.
- L10 (architecture commitment compliance): ✅ — no shared backend-policy abstraction, no RivRetrieve-derived products, no wide-form helpers, no vocabulary broadening, no secret leakage in provenance, no public type promotion, lazy-import preservation explicit.
- L11 (speculative abstraction check): ✅ — new types are all ch_foen-internal frozen dataclasses (`ChFoenProductPolicy`, `ChFoenTimeWindow`, `ChFoenProviderCall`, `ChFoenTransportRequest`, `ChFoenTransportResponse`, additional `ChFoenRawCsvResponse` fields). None are shared.
- L_two_channel: ✅ — placeholder-transition incident analysis is correct: §4 table assigns every M4-named failure mode to exactly one channel; M3 `OBSERVATIONS_NOT_YET_IMPLEMENTED` is deleted (not aliased — coherent because the placeholder code path is removed, not preserved as an alternative recoverable provider condition); `on_issue="raise"` is correctly described as "construct Issue first, `apply_on_issue` raises `IssuePolicyError`" without converting the runtime condition into a fatal.
- L_inherited_patterns: ✅ — lazy provider import, provider-internal types, two-channel routing, on_issue policy, always-on annotation-name validator, no public type promotion, no shared backend abstraction, atomic green-state checkpoints, generator-side asymmetric-encoding obligations (D8), and `dict`/`list` for json walks (D9) all preserved.
- L_legacy_citation_fidelity: ❌ — eight legacy citations spot-checked via `git -C /Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python show cd9b030:rivretrieve/switzerland.py`. Seven correct (40, 43, 44-81, 176-188, 190-218, 252-261, 263-269, 290-297). One wrong by ~32 lines (instant filtering 316-319 → actual 348-352; M1 above).
- L_vocabulary_boundary: ✅ — `polars.read_parquet` against `src/rivretrieve/_internal/providers/ch_foen/catalogue/products.parquet` enumerates exactly `discharge_daily_mean`, `discharge_instantaneous`, `stage_daily_mean`, `stage_instantaneous`, `water_temperature_daily_mean`, `water_temperature_instantaneous`. Plan §3 product-policy table emits exactly that set. No silent broadening; no annotation disguised as a new product.
- L_offline_invariant_explicit: ✅ — new modules live under `_internal/providers/ch_foen/` (already excluded by `test_import_rivretrieve_does_not_import_providers_stubs_or_generators`). Default HTTP transport is constructed lazily at fetch time (no module-level `httpx.Client(...)`). Test 27 explicitly proves no test reaches the default transport.
- L_asymmetric_encoding_round_trip: ❌ — three asymmetric-encoded columns covered (provider_query_fields JSON, flow_ls value conversion, UTC timestamp), at least three more uncovered (boolean → "true"/"false" Utf8 for `fallback_source_used` and `timezone_mismatch_flag`, datetime → ISO Utf8 for `returned_time_range_start`/`_end`, float-as-Utf8 for `raw_value`/`alternative_raw_value`). `native_unit_returned` shape is under-specified. M2 above.
- L_D7_probe: NA — plan §3 explicitly says "no new Pydantic model should use `extra="allow"`" and recommends frozen dataclasses / typed Polars frames. No D7 trigger surface.
- L_D9_probe: NA — plan §3 says "This step should only need JSON serialization for annotations, not JSON provider parsing." No `json.loads` walk introduced; D9 not invoked.
- L_network_isolation: ✅ — transport injection on `ChFoenObservationClient`, default transport guarded by test 27 (monkeypatch default HTTP function to raise on touch). Test 26 proves the injected transport path. M2 step 05 pattern preserved.
- L_unit_conversion_round_trip: ✅ (factor + annotation) / ❌ (numeric pin) — factor `0.001` cited from `cd9b030:rivretrieve/switzerland.py:263-269` (verified), `native_unit=L/s` and `converted_unit=m3/s` annotations declared. Numeric converted-range expectation on the 2206 fixture is not pinned in test 1 (m2 above).
- L_window_stitching_dedup: ✅ — Plan §3 pins dedup by `(station_id, product_id, time)` after transformation; plan §7 question 5 pins partial-failure rule (per-window `SOURCE_REQUEST_FAILED` + request-level `PARTIAL_RESPONSE`); seam overlap is structurally avoided because Flux `stop` is exclusive and adjacent day windows begin at the next midnight.
- L_token_embedding: ✅ — Plan §3 explicitly enumerates the forbidden locations (repr, raw payload metadata, provenance, issues, logs, fixtures, URL/query strings). Token may appear only in `Authorization` header and `ChFoenObservationClient.token`. Hybrid embedding (env override + embedded literal + constructor override) is structurally sound.
- L_provenance_secret_boundary: ✅ — Plan §3 names the §14 boundary explicitly: URL has no `Authorization` query parameter, so provenance records sanitized endpoint/query/timestamps/status without needing to strip URL credentials. Plan §4 fatal-table entry "Provenance/raw metadata would include token or Authorization header" pins a defense-in-depth redaction assertion.

## Adversarial probes attempted

- Ran `git -C /Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python show cd9b030:rivretrieve/switzerland.py | awk 'NR>=<a> && NR<=<b>'` for each cited line range: 40, 43, 44-81 (verified ends at line 81), 176-188 (verified `_build_flux_query`), 190-218 (verified `_download_data`), 252-261 (verified `_apply_parameter_preference`), 263-269 (verified `_convert_units` flow_ls `/1000.0`), 290-297 (verified daily floor + groupby mean), 316-319 (CONTRADICTED — docstring text, actual code at 348-352).
- Ran `uv run python -c "import polars as pl; print(pl.read_parquet('src/rivretrieve/_internal/providers/ch_foen/catalogue/products.parquet').select('product_id').to_series().to_list())"` and confirmed the six declared product IDs match the plan's policy table exactly.
- Read `src/rivretrieve/_internal/registry.py:80-113` and confirmed the dispatch order: module-presence → `ObservationRequest.from_inputs` → provider module call → `validate_annotation_names` for row and series. Plan §2 line 42 preserves this order verbatim.
- Read `src/rivretrieve/_internal/providers/ch_foen/observation_client.py:1-19` to confirm the step-01 frozen `ChFoenObservationClient(token: str, endpoint: ..., timeout_seconds: ...)` shape. Plan §3 modifies `token` to `str | None` and adds `transport`, requiring §6 step 3 to refresh tests; flagged as m6.
- Read `src/rivretrieve/_internal/providers/ch_foen/issue_codes.py:1-23` to confirm `OBSERVATIONS_NOT_YET_IMPLEMENTED` exists and `SOURCE_REQUEST_FAILED`, `MISSING_DATA`, `PARTIAL_RESPONSE`, `GAP`, `OVERLAP`, `CONFLICT`, `UNIT_CONVERSION_AMBIGUITY`, `TIMEZONE_AMBIGUITY`, `INVALID_TIMESTAMP`, `INVALID_NUMERIC_VALUE` are present.
- Read `src/rivretrieve/_internal/providers/ch_foen/parser.py:32-35` to confirm `ChFoenObservationParserError` currently subclasses `ValueError`. Plan §6 step 5 changes the base to `FatalContractError`; checked `tests/test_ch_foen_observation_parser.py` and confirmed tests catch the class by name, not by `ValueError`, so the inheritance flip is safe.
- Grepped for `class FatalContractError` in `src/rivretrieve/_internal/issues.py` — confirmed at line 31, alongside `InvalidObservationRequestError`, `ObservationsUnavailableError`, `ObservationDataSchemaError`, `AnnotationSchemaViolationError`, `IssuePolicyError`. Plan §4 fatal-table routes each fatal mode to a real existing or planned subclass.
- Read `src/rivretrieve/_internal/issues.py:76-89` to confirm `apply_on_issue` behavior: warning/error issues warn-on-`"warn"` and raise-on-`"raise"`, info issues never raise. Plan §4 placeholder-transition note ("provider constructs the recoverable `Issue` objects first, then `apply_on_issue` raises `IssuePolicyError`") matches this contract.
- Read `src/rivretrieve/_internal/providers/ch_foen/module.py:68-183` to enumerate step-01-declared annotation IDs and value_types. Cross-checked against Plan §3 row/series annotation emission tables: every declared annotation is on a plan emission path; no emission for an undeclared annotation. The declared `value_type`s expose the asymmetric-encoding obligation that anchors M2.
- Read `tests/test_offline_import.py` to confirm the offline invariant guard: `rivretrieve._internal.providers` must not be in `sys.modules` after `import rivretrieve`. Plan's new modules live under that path and thus inherit the guard.
- Traced each generator-side asymmetric-encoding column from the plan's pipeline through to the `AnnotationTable` boundary: confirmed that `provider_query_fields` test 23 covers JSON serialization, `data.value` test 24 covers flow_ls conversion before result construction, `data.time` test 25 covers UTC normalization, but boolean/datetime/float Utf8 serialization for annotation values has no explicit generator-side coverage (M2 above).
- Searched the plan text for the token literal (`0yLbh-D7RMe1sX1iIudFel8CcqCI8sVfuRTaliUp56MgE6kub8-nSd05_EJ4zTTKt0lUzw8zcO73zL9QhC3jtA==`): not present in `plan.md`. No fixture filename in the plan carries the token literal; the three CSV fixtures (`switzerland_2016_temperature_20200101.csv`, `switzerland_2206_discharge_20250101.csv`, `switzerland_2282_stage_20250101.csv`) are response-body bytes, not request-header carriers.
