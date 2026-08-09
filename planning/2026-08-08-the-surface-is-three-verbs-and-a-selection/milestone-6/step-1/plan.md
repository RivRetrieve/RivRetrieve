# m6-s1 implementation plan: convert established observation zones to UTC row by row

Implementation baseline: `4b16c5749817787b56f3ac54233c78529fb2a0ab`.

## 1. Objective

Add the public function `rivretrieve.to_utc(result)` as a pure transformation from one `ObservationResult` to a new `ObservationResult`. For every row whose published `time_zone` is an established IANA identifier or strict fixed offset, replace the native naive wall clock with the exact corresponding naive UTC wall clock and replace that row's `time_zone` with `+00:00`. Preserve row order, column order, values, station/product identities, provenance, issues, and raw payload. Refuse the whole transformation before converting any row when one or more rows have `time_zone == "unknown"`, and report the singular provider from `result.provenance.provider_id` plus the exact affected-row count.

## 2. Semantics to implement

### Public operation and carrier

- Add exactly this public callable shape:

  ```python
  def to_utc(result: ObservationResult) -> ObservationResult:
  ```

- Export it from the package root so callers use `rivretrieve.to_utc(result)` or `from rivretrieve import to_utc`.
- `to_utc` returns a new `ObservationResult`; it does not mutate the input object or its `data` frame.
- `ObservationResult` remains exactly these four members, in this order:

  ```text
  data
  provenance
  issues
  raw
  ```

- Preserve `provenance`, `issues`, and `raw` unchanged. The new result may be made with `result.model_copy(update={"data": converted_data})` so the three non-data members remain the same values and objects.
- Preserve the observation frame as exactly the provider-free ADR-0006 schema, including this exact order and these dtypes:

  ```python
  pl.Schema(
      {
          "time": pl.Datetime(),
          "time_zone": pl.Utf8,
          "station_id": pl.Utf8,
          "product_id": pl.Utf8,
          "value": pl.Float64,
      }
  )
  ```

  `value` remains nullable. No sixth column is permitted. In particular, do not add `provider_id`; the diagnostic provider is `result.provenance.provider_id`.
- Preserve the input `time` column's Polars time unit while removing any timezone from its dtype; the result is a naive `pl.Datetime` column. Ordinary canonical input at the baseline is `datetime[μs]`, so the authored expected frames below use `ObservationDataSchema.polars_schema` and therefore `datetime[μs]`.
- Preserve row order. Replacing `time` and `time_zone` must leave the exact column order `time`, `time_zone`, `station_id`, `product_id`, `value`.
- An empty valid result contains no `unknown` rows and returns a new, schema-identical empty result.

### Atomic unknown-zone refusal

- Before converting any timestamp, count all rows for which the exact string in `time_zone` is `unknown`.
- `time_zone == "unknown"` is the only rejection condition for valid `ObservationResult` rows whose zone values satisfy the existing `ZoneValue` domain.
- If the count is nonzero, raise `FatalContractError` and return no result. Use this exact message, including quoting and plural `rows`:

  ```text
  Cannot convert 2 observation rows for provider 'ca_eccc' to UTC because time_zone is 'unknown'
  ```

  The implementation must format the same template for any count and provider:

  ```python
  f"Cannot convert {unknown_count} observation rows for provider {str(result.provenance.provider_id)!r} to UTC because time_zone is 'unknown'"
  ```

- The count is the affected-row count, not a distinct-station, distinct-product, or distinct-zone count.
- Atomic means the complete unknown-row preflight happens before the per-row conversion helper is called. Mixed established and unknown rows must not yield a partially converted frame and must leave `result.data` unchanged.

### Row-by-row conversion

- Convert each row from the wall-clock fields in its own `time` value and its own published `time_zone`. Do not choose one zone for the result, station, product, provider, or span.
- A station or product span may contain several distinct offsets or identifiers. That is ordinary input, must be converted row by row, and must not be rejected.
- For a strict fixed offset `±HH:MM`, construct the corresponding fixed-offset `tzinfo`, attach it to that row's naive wall clock, convert to `datetime.UTC`, and remove `tzinfo` from the converted datetime. Examples fixed by this plan:

  ```text
  2026-01-01 00:15:00 at +05:30 -> 2025-12-31 18:45:00 with +00:00
  2026-01-01 00:15:00 at -03:30 -> 2026-01-01 03:45:00 with +00:00
  ```

- For an IANA identifier, use `zoneinfo.ZoneInfo` for that exact identifier, attach it to that row's wall clock, convert to `datetime.UTC`, and remove `tzinfo`. Do not replace or promote the identifier before conversion. Examples fixed by this plan:

  ```text
  2026-01-15 12:00:00 at Europe/Zurich -> 2026-01-15 11:00:00 with +00:00
  2026-07-15 12:00:00 at Europe/Zurich -> 2026-07-15 10:00:00 with +00:00
  ```

- Validate/dispatch established zone strings with the existing `ZoneValue` domain rather than introducing a second syntax. At the baseline `ZoneValue` admits an IANA identifier, a strict `±HH:MM` offset including `+00:00`, or `unknown`.
- After conversion, every row has the literal `+00:00` in `time_zone`, including input rows already at `+00:00`.
- Do not sort, group, join, deduplicate, filter, aggregate, or otherwise change rows.

### Forbidden inference and data access

- Promote no fixed offset to an IANA identifier. In particular, never infer an IANA zone from `-05:00`; several zones share that offset and ADR-0005 forbids filling source silence by derivation.
- Never inspect a station's catalogue row, the USGS committed native table, provider configuration, station metadata, or `tz_cd` to perform conversion.
- Never use the provider's zone as a replacement for a row's published zone.
- USGS parsing already stamps every row with that payload timestamp's own offset and normalises `Z` to `+00:00`; do not change the parser in this step.
- Established baseline facts: `src/rivretrieve/_internal/providers/usgs_nwis/catalogue/native.parquet` has 26,258 rows and exactly six `tz_cd` values (`AKST`, `CST`, `EST`, `HST`, `MST`, `PST`). `src/rivretrieve/_internal/providers/usgs_nwis/catalogue/stations.parquet` has only `provider_id`, `station_id`, `latitude`, `longitude`, and `crs`; it has no zone column. Neither artifact participates in `to_utc`.
- ADR-0007's prose contains stale USGS `tz_cd` counts relative to the packaged native artifact. Do not edit that ADR in this step.

### Module denotation

The new module must begin with this denotation line as its module docstring, satisfying the repository design doctrine:

```python
"""to_utc : ObservationResult → ObservationResult (pure)."""
```

Keep all path/config/environment/catalogue authority out of this module. It receives exactly one already-parsed `ObservationResult` and performs no I/O.

## 3. Write-set

This is the complete write-set. Create or modify no other tracked or untracked implementation/test file.

1. `src/rivretrieve/_internal/utc.py` — create the pure `to_utc` implementation, atomic unknown preflight, row-wise fixed-offset/IANA conversion helpers, exact diagnostic, naive UTC frame reconstruction, and the required denotation docstring.
2. `src/rivretrieve/__init__.py` — add `from rivretrieve._internal.utc import to_utc as to_utc`. Do not change `__version__`.
3. `tests/test_utc.py` — create focused public-function tests for fixed offsets, IANA conversion, four-member preservation, atomic unknown refusal, and the source-shaped USGS DST-boundary case.
4. `tests/test_data/usgs_nwis_07374000_iv_00060_2023-03-12-dst.json` — create the complete synthetic source-shaped USGS fixture quoted in section 5.
5. `tests/test_package.py` — update the exact root-public-surface assertion to include `to_utc` and directly establish that the imported public name is the package attribute.

No file is generated by a gate. Formatting changes to any file outside this write-set indicate unintended drift and must be reverted without destructive Git commands.

## 4. Existing assertions affected

### Update explicitly

- `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface` is the sole existing assertion whose expected value changes. Keep the function name unless a rename is needed solely for clarity, add `to_utc` to the exact `module_defined_names` set, import `to_utc` from `rivretrieve`, and assert:

  ```python
  assert rivretrieve.to_utc is to_utc
  ```

  The complete expected public-name set after this step is:

  ```python
  {
      "ProviderHandle",
      "RawMode",
      "map_stations",
      "observations",
      "product_info",
      "products",
      "provider",
      "provider_info",
      "providers",
      "stations",
      "to_utc",
  }
  ```

### Prove untouched

- `tests/test_package.py::test_version` remains untouched: version policy is NONE, so `pyproject.toml`, `uv.lock`, and `src/rivretrieve/__init__.py::__version__` stay at `0.1.49`.
- `tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion` remains untouched. `to_utc` is not in its deferred-name list, and none of the listed deferred types/errors are promoted.
- `tests/test_internal_observations.py::test_observation_data_schema_accepts_canonical_long_table` remains untouched. The operation changes values inside `time`/`time_zone`, not the five-column schema.
- `tests/test_internal_observations.py::test_observation_data_schema_accepts_native_datetime_without_utc_mandate` remains untouched. Native observation results remain the default; UTC is an explicit derived operation.
- `tests/test_internal_observations.py::test_observation_data_schema_rejects_provider_id_column_as_extra_under_raise` remains untouched. The converted frame gains no `provider_id` column.
- `tests/test_internal_observations.py::test_observation_result_constructs_with_exact_field_set` remains untouched. `ObservationResult.model_fields` stays exactly `("data", "provenance", "issues", "raw")`.
- `tests/test_usgs_nwis_parse.py::test_parse_fixture_preserves_wall_clock_offset_and_ignores_cst_trap` remains untouched. Parsing continues returning native wall clocks and payload offsets; UTC conversion happens only after the caller invokes `to_utc`.
- `tests/test_usgs_nwis_parse.py::test_parse_normalizes_z_to_representable_positive_zero_offset` remains untouched. `ZoneValue("+00:00")` remains valid and `ZoneValue("Z")` remains invalid because parsing performs the existing normalisation.
- `tests/test_usgs_nwis_observations.py::test_usgs_nwis_registry_dispatch_uses_engine_driver` remains untouched, including its native `2023-01-01 00:00:00` / `-06:00` expected row. Public `observations(...)` does not start converting implicitly.
- `tests/test_usgs_nwis_observations.py::test_usgs_nwis_bare_date_returns_full_local_day_for_instant_product` remains untouched, including all 96 native `-06:00` rows.
- `tests/test_domain_context.py::test_native_time_is_the_ordered_five_column_observation_frame` remains untouched. This step adds an explicit derived operation and does not redefine the native result.
- `tests/test_provider_architecture_contracts.py` remains untouched. The new operation is provider-free and belongs under `src/rivretrieve/_internal/`, not any provider module; no provider runtime-file inventory changes.

All other existing tests are untouched because `to_utc` is additive and is not called by existing retrieval, parsing, conversion, assembly, registry, catalogue, or provider paths.

## 5. Authored data

All authored fixtures, frames, identifiers, preserved members, and diagnostics are fixed here. Do not substitute different dates, zones, station IDs, product IDs, values, or messages.

### Shared non-data members for focused constructed results

In `tests/test_utc.py`, build the fixed-offset, IANA, and unknown cases with these exact values (a helper may accept the frame and provider ID):

```python
provenance = ObservationProvenance(
    source="live",
    provider_id=ProviderId("provider-a"),
    metadata='{"trace":"kept"}',
)
issues = (
    Issue(
        severity="warning",
        code="source.note",
        message="Source note preserved",
        details={"row": 1},
        provider_id=ProviderId("provider-a"),
    ),
)
origin = SourceCallOrigin(
    url="https://example.invalid/observations",
    request_parameters={"station": "station-1"},
    status_code=200,
    retrieved_at=datetime(2026, 8, 8, 10, 30, tzinfo=UTC),
    content_type="application/json",
    source_path=UnknownOriginFact(),
    query=UnknownOriginFact(),
)
raw = RawPayload(
    provider_id=ProviderId("provider-a"),
    entries=(RawSourceCall(content=b'{"source":"fixture"}', origin=origin),),
)
```

Construct each `ObservationResult` with its exact frame plus these members. For the unknown test only, replace both `provenance.provider_id`, `issues[0].provider_id`, and `raw.provider_id` with `ProviderId("ca_eccc")`; the other values remain identical.

### Fixed-offset input and expected frame

Input:

```python
pl.DataFrame(
    {
        "time": [datetime(2026, 1, 1, 0, 15), datetime(2026, 1, 1, 0, 15)],
        "time_zone": ["+05:30", "-03:30"],
        "station_id": ["station-1", "station-1"],
        "product_id": ["flow", "flow"],
        "value": [1.25, None],
    },
    schema=ObservationDataSchema.polars_schema,
)
```

Expected:

```python
pl.DataFrame(
    {
        "time": [datetime(2025, 12, 31, 18, 45), datetime(2026, 1, 1, 3, 45)],
        "time_zone": ["+00:00", "+00:00"],
        "station_id": ["station-1", "station-1"],
        "product_id": ["flow", "flow"],
        "value": [1.25, None],
    },
    schema=ObservationDataSchema.polars_schema,
)
```

Assert with `polars.testing.assert_frame_equal(converted.data, expected, check_exact=True)`. Also assert the original input frame is still exactly the input above; `converted is not result`; `converted.data is not result.data`; `converted.provenance is result.provenance`; `converted.issues is result.issues`; `converted.raw is result.raw`; and:

```python
assert tuple(type(converted).model_fields) == ("data", "provenance", "issues", "raw")
assert converted.data.columns == ["time", "time_zone", "station_id", "product_id", "value"]
assert converted.data.schema == ObservationDataSchema.polars_schema
```

### IANA input and expected frame

Input:

```python
pl.DataFrame(
    {
        "time": [datetime(2026, 1, 15, 12, 0), datetime(2026, 7, 15, 12, 0)],
        "time_zone": ["Europe/Zurich", "Europe/Zurich"],
        "station_id": ["station-iana", "station-iana"],
        "product_id": ["level", "level"],
        "value": [2.5, 3.5],
    },
    schema=ObservationDataSchema.polars_schema,
)
```

Expected:

```python
pl.DataFrame(
    {
        "time": [datetime(2026, 1, 15, 11, 0), datetime(2026, 7, 15, 10, 0)],
        "time_zone": ["+00:00", "+00:00"],
        "station_id": ["station-iana", "station-iana"],
        "product_id": ["level", "level"],
        "value": [2.5, 3.5],
    },
    schema=ObservationDataSchema.polars_schema,
)
```

Assert exact frame equality. This test covers both standard and daylight-saving rules for the exact same IANA identifier without replacing that identifier with a fixed station-wide offset before conversion.

### Unknown-zone input, exact error, and atomicity probe

Input:

```python
pl.DataFrame(
    {
        "time": [
            datetime(2026, 1, 1, 0, 0),
            datetime(2026, 1, 1, 1, 0),
            datetime(2026, 1, 1, 2, 0),
        ],
        "time_zone": ["+02:00", "unknown", "unknown"],
        "station_id": ["station-known", "station-unknown-1", "station-unknown-2"],
        "product_id": ["flow", "flow", "level"],
        "value": [10.0, 11.0, 12.0],
    },
    schema=ObservationDataSchema.polars_schema,
)
```

The provider is exactly `ProviderId("ca_eccc")`. Monkeypatch `rivretrieve._internal.utc._convert_wall_clock` to a probe that records or raises if called. Invoke the public `rivretrieve.to_utc(result)` and assert the helper was never called. Assert `FatalContractError` with exact string equality, not a regex fragment:

```text
Cannot convert 2 observation rows for provider 'ca_eccc' to UTC because time_zone is 'unknown'
```

After the exception, assert exact frame equality between `result.data` and an untouched clone of the input frame. No converted result exists.

### Complete USGS DST fixture

Create `tests/test_data/usgs_nwis_07374000_iv_00060_2023-03-12-dst.json` with exactly this complete UTF-8 JSON content and a trailing newline. It is a deliberately constructed source-shaped fixture, not a claimed live capture:

```json
{
  "name": "ns1:timeSeriesResponseType",
  "value": {
    "queryInfo": {
      "queryURL": "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=07374000&startDT=2023-03-12&endDT=2023-03-12&parameterCd=00060",
      "criteria": {
        "locationParam": "ALL:07374000",
        "variableParam": "00060",
        "timeParam": {
          "beginDateTime": "2023-03-12T00:00:00.000",
          "endDateTime": "2023-03-12T23:59:59.999"
        },
        "parameter": []
      },
      "note": []
    },
    "timeSeries": [
      {
        "sourceInfo": {
          "siteName": "Mississippi River at Baton Rouge, LA",
          "siteCode": [
            {
              "value": "07374000",
              "network": "NWIS",
              "agencyCode": "USGS"
            }
          ],
          "timeZoneInfo": {
            "defaultTimeZone": {
              "zoneOffset": "-06:00",
              "zoneAbbreviation": "CST"
            },
            "daylightSavingsTimeZone": {
              "zoneOffset": "-05:00",
              "zoneAbbreviation": "CDT"
            },
            "siteUsesDaylightSavingsTime": true
          }
        },
        "variable": {
          "variableCode": [
            {
              "value": "00060",
              "network": "NWIS",
              "vocabulary": "NWIS:UnitValues"
            }
          ],
          "variableName": "Streamflow, ft3/s",
          "noDataValue": -999999.0
        },
        "values": [
          {
            "value": [
              {
                "value": "100.0",
                "qualifiers": [
                  "P"
                ],
                "dateTime": "2023-03-12T01:30:00.000-06:00"
              },
              {
                "value": "101.0",
                "qualifiers": [
                  "P"
                ],
                "dateTime": "2023-03-12T03:30:00.000-05:00"
              }
            ]
          }
        ],
        "name": "USGS:07374000:00060:"
      }
    ]
  }
}
```

In `test_to_utc_usgs_dst_boundary_uses_each_payload_offset_without_catalogue`, read those bytes and pass them through the existing `usgs_nwis.parse.parse` using these exact tags and config:

```python
station_products = (("07374000", ProductId("discharge_instantaneous")),)
provider_config = ProviderConfig(zone=ZoneValue("unknown"), products={})
```

Construct the parser input exactly as follows; each `UnknownOriginFact()` is a separate value:

```python
origin = SourceCallOrigin(
    UnknownOriginFact(),
    UnknownOriginFact(),
    UnknownOriginFact(),
    UnknownOriginFact(),
    UnknownOriginFact(),
    UnknownOriginFact(),
    UnknownOriginFact(),
)
payload = Payload(
    SourceCoordinates(object()),
    (("07374000", ProductId("discharge_instantaneous")),),
    _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2023, 3, 12, 0, 0)),
        WindowEndpoint.from_datetime(datetime(2023, 3, 12, 23, 59, 59, 999999)),
    ),
    fixture_bytes,
    origin,
)
parsed = parse(payload, ProviderConfig(zone=ZoneValue("unknown"), products={}))
```

The parser's exact native frame, reordered into observation-schema order, must be:

```python
pl.DataFrame(
    {
        "time": [datetime(2023, 3, 12, 1, 30), datetime(2023, 3, 12, 3, 30)],
        "time_zone": ["-06:00", "-05:00"],
        "station_id": ["07374000", "07374000"],
        "product_id": ["discharge_instantaneous", "discharge_instantaneous"],
        "value": [100.0, 101.0],
    },
    schema=ObservationDataSchema.polars_schema,
)
```

Build its `ObservationResult` with:

```python
provenance=ObservationProvenance(source="live", provider_id=ProviderId("usgs_nwis"))
issues=()
raw=RawPayload(
    provider_id=ProviderId("usgs_nwis"),
    entries=(RawSourceCall(content=fixture_bytes, origin=origin),),
)
```

Before calling `to_utc`, monkeypatch both `CatalogueReader.read_stations` and `load_packaged_catalogue_artifact` to raise `AssertionError("to_utc consulted the catalogue")` if called. The exact converted frame is:

```python
pl.DataFrame(
    {
        "time": [datetime(2023, 3, 12, 7, 30), datetime(2023, 3, 12, 8, 30)],
        "time_zone": ["+00:00", "+00:00"],
        "station_id": ["07374000", "07374000"],
        "product_id": ["discharge_instantaneous", "discharge_instantaneous"],
        "value": [100.0, 101.0],
    },
    schema=ObservationDataSchema.polars_schema,
)
```

Assert both native and converted frames with `polars.testing.assert_frame_equal(..., check_exact=True)`. Also assert:

```python
assert set(native.data["time_zone"].to_list()) == {"-06:00", "-05:00"}
assert native.data["time_zone"].to_list() == ["-06:00", "-05:00"]
assert "CST" not in native.data["time_zone"].to_list()
assert "CDT" not in native.data["time_zone"].to_list()
assert converted.data["time_zone"].to_list() == ["+00:00", "+00:00"]
assert converted.provenance is native.provenance
assert converted.issues is native.issues
assert converted.raw is native.raw
```

The two offsets belong to one station/product span. Success without an exception is the required evidence that distinct offsets are not a rejection condition and neither offset was promoted to an IANA identifier.

## 6. Acceptance criteria

Run these focused checks while developing; each command has one exact expected observation.

1. Public export:

   ```bash
   uv run pytest tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface
   ```

   Expected: `1 passed`; the exact public-name set includes only the prior ten names plus `to_utc`, and `rivretrieve.to_utc is to_utc`.

2. Fixed offsets and four-member preservation:

   ```bash
   uv run pytest tests/test_utc.py::test_to_utc_fixed_offsets_converts_row_by_row_and_preserves_result_members
   ```

   Expected: `1 passed`; the two fixed-offset rows equal the exact frame in section 5, the input is unchanged, the output is new, column order/schema stay exact, and provenance/issues/raw are preserved.

3. IANA rules:

   ```bash
   uv run pytest tests/test_utc.py::test_to_utc_iana_identifiers_use_zone_rules
   ```

   Expected: `1 passed`; the January Zurich row becomes `11:00`, the July Zurich row becomes `10:00`, and both zone cells become `+00:00`.

4. Unknown atomic refusal:

   ```bash
   uv run pytest tests/test_utc.py::test_to_utc_unknown_zones_refuse_atomically_with_provider_and_count
   ```

   Expected: `1 passed`; the exact `ca_eccc`/two-row message is raised, the per-row helper is never called, the source frame is unchanged, and no result is returned.

5. USGS DST boundary:

   ```bash
   uv run pytest tests/test_utc.py::test_to_utc_usgs_dst_boundary_uses_each_payload_offset_without_catalogue
   ```

   Expected: `1 passed`; parsing yields `01:30/-06:00` and `03:30/-05:00`, conversion yields `07:30/+00:00` and `08:30/+00:00`, the catalogue-failure probes are not called, and neither `CST` nor `CDT` appears in observation rows.

6. Focused acceptance set:

   ```bash
   uv run pytest tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface tests/test_utc.py
   ```

   Expected: `5 passed`.

The final full-suite gate must report the green baseline `1622 passed, 2 skipped` plus the four newly authored `tests/test_utc.py` test functions; the existing public-surface test is updated rather than added. No failure, error, xfail, or new skip is acceptable.

## 7. Gate commands

Run every command from the repository root, after implementation and before the single commit, verbatim and in this required order:

```bash
uv sync
uv run ruff format
uv run ruff check --fix
uv run ty check src
uv run pytest
uv build
```

Required observations: every command exits 0; `uv sync` reports no lockfile change; formatting/lint leave only intended write-set changes; typecheck is scoped to `src`; the full suite has no failure; and the wheel/sdist build succeeds. If `ruff format` or `ruff check --fix` changes a file outside the write-set, restore that unintended change without using `git reset --hard` or `git checkout --` and rerun the ordered gates from the start.

## 8. Constraints and prohibitions

### Scope fence: explicitly not touched

- Do not modify `CONTEXT.md`, any `docs/adr/*.md`, any `.pce/*` field/file, any planning/vision/graph/review artifact, any provider implementation, any existing provider fixture, any catalogue generator, or any packaged `*.parquet`/`provider.json` artifact.
- Do not modify `pyproject.toml` or `uv.lock`; add no dependency. Python's standard-library `datetime`, `timezone`/`UTC`, and `zoneinfo.ZoneInfo` plus existing Polars are sufficient.
- Do not change `ObservationResult`, `ObservationProvenance`, `ObservationDataSchema`, `ZoneValue`, the engine's `RowsSchema`/`CanonicalRowsSchema`, parsing, assembly, registry, discovery, retrieval defaults, issue policy, or catalogue APIs.
- Do not add a `provider_id` observation column or any extra result member.
- Do not change USGS `parse`, its provider zone (`unknown`), its payload-offset handling, or its `Z` normalisation.
- Do not consult, edit, or regenerate the USGS native/canonical catalogue. Do not use `tz_cd`, station geometry, provider configuration, or an inferred station zone.
- Do not edit ADR-0007 to reconcile its stale prose counts.
- Do not add fallback behavior for `unknown`; do not drop unknown rows; do not partially convert; do not warn and continue.
- Do not reject a multi-offset station/product/result span.
- Do not normalize fixed offsets into IANA identifiers or IANA identifiers into fixed offsets before conversion.
- Do not implement any other milestone or vision Scope-Out item: no bounding box, no `record_covers`, no shipped `source="live"`, no coverage snapshot, no harmonised name/river search, no chained query language, no PyPI publication, no documentation authoring, no provider porting, and no decision about whether native tables ship in the wheel.
- The step is repeatable. Retain this not-touched fence and the exact expected values in section 5 through implementation and review; do not replace them with a pre-derived design-correctness argument.

### Binding environment hazards (verbatim)

1. "uv opens ~/.cache/uv/sdists-v9/.git for write on EVERY invocation, so no uv command can run under a sandbox that denies writes there. pce measures stated gates under a Seatbelt profile whose only writable roots are the repository root and the platform temporary directory, and the codex sandbox allows workdir, /tmp and $TMPDIR; neither allows ~/.cache. The machine therefore carries ~/.config/uv/uv.toml setting cache-dir to a warm shared cache under $TMPDIR, which both sandboxes permit. Measured: all five stated gates green in a cold fresh worktree with network denied. If a gate fails with 'Failed to initialize cache' / 'Operation not permitted (os error 1)', that config is missing or the temp cache was purged; recreate it and re-warm with uv sync --reinstall outside any sandbox. Do not point cache-dir inside the repository: uv warns it may be included in distributions and every fresh worktree starts cold with no network."
2. "Mutation testing must set PYTHONDONTWRITEBYTECODE=1 and pytest -p no:cacheprovider: same-size edits written within one mtime second collide under CPython (mtime, size) pyc invalidation and produce a false killed result."
3. "A full-suite run inside a git archive extraction shows a spurious extra failure in tests/test_ch_foen_generate_catalogue.py because that test shells out to git show HEAD: and an extraction is not a repository."
4. "The default-branch gate baseline is fully green as of the commit that introduced this file, and pce contract check aborts on the first red gate. Any red gate an executor observes is therefore caused by its own change and must be fixed, not tolerated against a historical baseline. The previous run's red baseline (a B905 at br_ana/generate_catalogue.py:507, an invalid-argument-type at br_ana/generate_catalogue.py:623, and an unresolved-import of tqdm at jp_mlit/generate_catalogue.py:202) was closed in that same commit; tqdm is now a declared dev dependency, so the deliberately-optional import at jp_mlit/generate_catalogue.py:202 resolves for ty while its try/except ImportError still governs runtime."
5. "tests/typecheck/nominal_window_misuse.py is an INTENTIONAL negative type-check fixture asserted by tests/test_internal_engine_contracts.py. It is excluded from the stated typecheck gate because that gate is scoped to src. Whole-project uv run ty check therefore reports it and must never be used as the gate. Never repair or suppress that fixture."
6. "uv run ruff format is the stated format gate and rewrites files in place rather than reporting; it exits 0 even when it reformats. Use uv run ruff format --check to observe drift without mutating the tree."

### Binding gate ordering (verbatim)

1. "uv sync before format before lint before typecheck before test; uv build last"

### Binding lockfile rule (verbatim)

1. "uv.lock is tracked and must stay synchronized with pyproject.toml; uv sync reports 0 changes at this baseline"

The baseline is fully green (`1622 passed, 2 skipped`). Any red gate is caused by this change and must be fixed, never waived or described as pre-existing.

## 9. Executor policies

- Implement this step as exactly ONE conventional commit on the worktree for the pull request into `pce/the-surface-is-three-verbs-and-a-selection/milestone-6`.
- Use this exact conventional commit subject:

  ```text
  feat: convert established observation zones to UTC
  ```

- Run all gates in section 7 before creating the commit.
- Write the pull-request body to `pr-body.md` at the worktree root and leave it UNTRACKED. Do not commit `pr-body.md`. The PR body should summarize the public `to_utc` behavior, atomic unknown refusal, row-wise fixed-offset/IANA conversion, preservation guarantees, DST fixture evidence, and the six green gate commands.
- Create no tag.
- Do not push.
- Add no attribution footers (`Co-authored-by`, `Signed-off-by`, or similar).
- Do not edit any field under `stated` in `.pce/repository-contract.json`.
- Version policy is NONE: require no version bump and no tag.
