# m4-s1 implementation plan — fetch exact selections with singular provenance

Pinned implementation base: `1b903fa1b88522cbf2f441d080a414d17f5056cb`.

This plan is self-contained for a zero-context, network-disabled executor. Do not read or depend on the vision directory. All repository facts below were checked against the pinned ref. `docs/adr/0016-a-requested-window-is-wall-clock.md` exists at that ref. ADR-0019 and ADR-0020 do **not** exist at that ref (the tracked ADR sequence ends at 0018), so do not cite or attempt to read them; the operative behavior they would have supplied is written out below.

## 1. Objective

Add two public functions without disturbing the legacy public API:

```python
fetch(selection, *, start, end) -> ObservationResult
fetch_by_provider(selection, *, start, end) -> dict[str, ObservationResult]
```

`fetch` retrieves the exact sorted `(provider_id, station_id, product_id)` series in one non-empty, single-provider RivRetrieve selection. `fetch_by_provider` partitions a selection only on `provider_id` and returns one provider-scoped result per selected provider. Neither function accepts `raw` or `on_issue` in this step.

The new route must reuse the existing observation engine and preserve all of its contracts: wall-clock request endpoints, closed endpoints, rejection of endpoints carrying a zone, the exact five-column observation frame, and the exact four-member `ObservationResult`. It must not turn sparse selected series into a station-by-product Cartesian product, and it must never merge data from different providers into one provider-free observation frame.

Keep every current public name. At this step the full public-name set becomes exactly:

```python
{
    "ProviderHandle",
    "RawMode",
    "as_frame",
    "fetch",
    "fetch_by_provider",
    "find",
    "from_frame",
    "map_stations",
    "observations",
    "pick",
    "product_info",
    "products",
    "provider",
    "provider_info",
    "providers",
    "stations",
    "to_utc",
}
```

## 2. Semantics to implement

### 2.1 Public signatures and boundary validation

Implement these exact signatures in `rivretrieve._internal.discovery` and re-export them from `rivretrieve`:

```python
def fetch(selection: _Selection, *, start: object, end: object) -> ObservationResult: ...

def fetch_by_provider(
    selection: _Selection,
    *,
    start: object,
    end: object,
) -> dict[str, ObservationResult]: ...
```

`selection` is positional-or-keyword and required. `start` and `end` are required keyword-only arguments. There is no `raw`, `on_issue`, `source`, `bbox`, `record_covers`, `provider`, `stations`, or `products` parameter on either new function.

Call the existing `rivretrieve._internal.selection._require_selection` before reading `.series` or `.empty_reason`. Any non-RivRetrieve value must raise exactly:

```text
selection must be a RivRetrieve selection
```

No coercion from a Polars frame, sequence, tuple, mapping, or lookalike object is permitted; callers already have `from_frame` for the frame boundary.

The public functions do not expose the unresolved `raw=` and `on_issue=` controls. Internally, call the legacy handle with `raw=RawMode.OMIT` and `on_issue="ignore"` for every exact series request, assemble the final provider result, then apply the existing default warning policy once to that final result with `apply_on_issue(result.issues, "warn")`. This retains the existing default behavior without settling m5's public-control decision. `RawMode` itself remains public and unchanged for the legacy API.

### 2.2 `fetch`: pre-lookup guards

After type validation and before `_provider_lookup`, `_ProviderHandle.observations`, `driver.drive`, or `ProviderStages.fetch` can be reached:

1. If `selection.series == ()`, raise `EmptySelectionError`, an internal `FatalContractError` subclass defined in `rivretrieve._internal.discovery`. Store the identical reason object on `error.reason`; require `error.reason is selection.empty_reason`. The selection invariant already guarantees a concrete `_EmptyReason` for every empty selection. Format its fields deterministically in this exact message shape:

   ```text
   fetch() cannot retrieve an empty selection: code='CODE', provider_ids=PROVIDER_IDS_REPR, station_ids=STATION_IDS_REPR, product_ids=PRODUCT_IDS_REPR, published_products=PUBLISHED_PRODUCTS_REPR
   ```

   For the acceptance selection, the complete expected text is:

   ```text
   fetch() cannot retrieve an empty selection: code='no_catalogue_edge', provider_ids=('usgs_nwis',), station_ids=('station-2',), product_ids=('level_max',), published_products=('level_hourly',)
   ```

2. Otherwise derive provider ids from the already sorted selection series and retain first occurrence order. Because selection keys sort first on `provider_id`, this is sorted provider order. If there is more than one provider, raise `MultiProviderSelectionError`, another internal `FatalContractError` subclass. Store the exact tuple on `error.provider_ids`. The exact acceptance message is:

   ```text
   fetch() requires one provider; selection contains providers ('ca_eccc', 'usgs_nwis'). Use fetch_by_provider() for multi-provider selections.
   ```

3. Only after both guards pass, resolve the one provider through the existing `_provider_lookup` seam and dispatch its exact selected series.

These guards are atomic: an invalid empty or mixed call produces zero provider lookups, zero handle observation calls, zero driver calls, zero provider-stage fetch calls, and zero transport/source calls. Do not validate the requested window first; the retained empty or mixed-selection diagnosis wins before any provider or observation path work.

### 2.3 Exact sparse routing

For a provider-scoped tuple of sorted `_Series`, route each series independently through the existing handle:

```python
handle.observations(
    stations=series.station_id,
    products=series.product_id,
    start=start,
    end=end,
    on_issue="ignore",
    raw=RawMode.OMIT,
)
```

Do this once per selected series, in selection order. Never combine independently derived station and product sets in one legacy request. For selected keys

```python
(
    ("usgs_nwis", "station-1", "level"),
    ("usgs_nwis", "station-2", "level_hourly"),
)
```

the only allowed legacy/stage axes are exactly:

```python
[
    (("station-1",), ("level",)),
    (("station-2",), ("level_hourly",)),
]
```

There must be no request for `("station-1", "level_hourly")` or `("station-2", "level")`, and there must not be one call with `stations=("station-1", "station-2")` and `products=("level", "level_hourly")`.

This approach deliberately leaves `engine.ObservationRequest`, `driver.ProviderStages.fetch`, both registered provider fetch implementations, and all provider module signatures unchanged.

### 2.4 Merge only within one provider

Add a private helper in `discovery.py` whose denotation is recorded in its docstring as:

```text
provider result merge : NonEmptyTuple[ObservationResult] × SelectedSeries → ObservationResult
```

Merge the per-series results for one provider as follows:

- Concatenate `result.data` frames in selected-series order with Polars. Each input is already schema-validated by `ObservationResult`; construction of the final `ObservationResult` validates the merged frame again.
- Keep the columns in exactly this order and never add `provider_id`:

  ```python
  ("time", "time_zone", "station_id", "product_id", "value")
  ```

- Use the first per-series result's immutable provenance as the provider-scoped base. Replace only its `request` value with the exact provider-scoped selected-series receipt described below. Its `source`, `provider_id`, `catalogue_version`, `license`, `citation`, `requested_at`, and every other field remain singular values. Do not combine provenance across providers.
- Concatenate stage/parse/convert issues in request order. The legacy handle appends the two provider-level informational issues `provenance.license_not_established` and `provenance.citation_not_established` on every individual request; retain each distinct provider-level provenance issue only once in the merged provider result, while retaining all non-provenance issues even if their values happen to compare equal. After the merge, call `apply_on_issue(..., "warn")` once.
- Construct one `RawPayload` with the provider id from the result provenance and the ordered concatenation of all per-series raw entries. In this step all entries are empty because the public functions force `RawMode.OMIT`, but implement the merge without changing the `RawPayload(provider_id, entries)` shape.
- Construct and return exactly one `ObservationResult(data=..., provenance=..., issues=..., raw=...)`.

The selected-series provenance receipt is exactly:

```python
{
    "series": [
        {"station_id": SERIES_1_STATION, "product_id": SERIES_1_PRODUCT},
        {"station_id": SERIES_2_STATION, "product_id": SERIES_2_PRODUCT},
    ],
    "start": NORMALIZED_START_ISO,
    "end": NORMALIZED_END_ISO,
}
```

Use the normalized `start` and `end` already present in the first legacy result's provenance request; do not parse or normalize endpoints a second way. For the sparse acceptance case the complete value is:

```python
{
    "series": [
        {"station_id": "station-1", "product_id": "level"},
        {"station_id": "station-2", "product_id": "level_hourly"},
    ],
    "start": "2026-01-01T00:00:00",
    "end": "2026-01-01T23:59:59.999999",
}
```

This preserves the existing endpoint behavior because each request still passes through `ObservationRequest.from_inputs`:

- naive `datetime` values and ISO-like strings are wall-clock values;
- a bare start date expands to `00:00:00` and a bare end date expands to `23:59:59.999999`;
- start and end are closed endpoints;
- explicit midnight remains midnight rather than expanding to the day's end;
- start after end raises `InvalidObservationRequestError("requested window start must not be after end")`;
- a zone-aware datetime or offset-bearing ISO string is refused before `ProviderStages.fetch`;
- the exact offset-bearing-string error for the acceptance input is:

  ```text
  start must be wall-clock time without a time zone; remove it with `start = datetime.fromisoformat(start).replace(tzinfo=None)`.
  ```

### 2.5 `fetch_by_provider`

Validate the selection type first. Partition `selection.series` only on `provider_id`, preserving the selection's sorted provider order and the station/product order within each provider. Return a normal insertion-ordered `dict[str, ObservationResult]` whose keys are those provider ids.

For a non-empty selection, resolve and fetch each provider separately using the same exact-series helper as `fetch`; never concatenate results across providers. A failure in one provider remains a failure of the call under the existing loud-failure rules; do not invent batch isolation or a partial-return carrier.

For an empty, valid RivRetrieve selection, there are zero selected providers: return exactly `{}` without provider lookup, stage calls, source calls, warnings, or loss-concealing placeholder results. `fetch` remains the operation that raises with the retained empty reason.

Every returned provider result must satisfy all of these at once:

- `tuple(type(result).model_fields) == ("data", "provenance", "issues", "raw")`;
- `result.provenance.provider_id == ProviderId(mapping_key)`;
- `result.provenance.license` and `.citation` are exactly that provider's packaged values;
- every entry in `result.provenance.request["series"]` belongs to that provider's partition;
- `result.raw.provider_id == ProviderId(mapping_key)`;
- `tuple(result.data.columns) == ("time", "time_zone", "station_id", "product_id", "value")`;
- `"provider_id" not in result.data.columns`.

### 2.6 Legacy behavior remains present

Do not alter `observations`, `provider`, `_ProviderHandle.observations`, `LegacyObservationRequest`, `driver.drive`, `ProviderStages`, `ObservationDataSchema`, `ObservationResult`, `ObservationProvenance`, `RawPayload`, either registered provider, or their signatures. The legacy separate station/product axes keep their existing behavior until m9; the new exact routing is confined to `fetch` and `fetch_by_provider`.

Do not change selection construction or its edge semantics. An edge still exists iff `availability != "unavailable"`; `"unknown"` is an edge and `"unavailable"` is absent. `_Selection` remains frozen, slotted, method-free, sorted and unique at `(provider_id, station_id, product_id)` grain, and carries `_EmptyReason` iff empty.

## 3. Write-set

The complete tracked write-set is exactly these four repository-relative paths:

1. `src/rivretrieve/_internal/discovery.py`
   - Import `_EmptyReason`, `_Series`, and `_require_selection` from `selection`; import `FatalContractError`, `apply_on_issue`, and the observation result/provenance/raw types needed to assemble a final result.
   - Define internal `EmptySelectionError` and `MultiProviderSelectionError` with the attributes and exact messages above.
   - Add `fetch`, `fetch_by_provider`, provider partitioning, exact per-series dispatch, provider-only merge, provenance-request replacement, provenance-issue de-duplication, raw-entry concatenation, and final default issue-policy application.
   - Leave every existing discovery function and alias in place, especially `_provider_lookup`, because both legacy tests and the new pre-lookup assertions use that seam.

2. `src/rivretrieve/__init__.py`
   - Re-export `fetch` and `fetch_by_provider` from `rivretrieve._internal.discovery`.
   - Make no other export or version change.

3. `tests/test_fetch.py` (new)
   - Add the complete offline recording stages and tests specified in sections 5 and 6.
   - Reuse `stub_packaged_catalogue_artifact_rich` from tracked `tests/conftest.py`; do not add binary, JSON, CSV, SQLite, or network fixtures.

4. `tests/test_package.py`
   - Update only `test_init_public_surface_exports_m2_provider_handle_surface`'s exact expected set by inserting `"fetch"` and `"fetch_by_provider"` into the full set quoted in section 1.
   - Keep its `source_metadata` absence assertion and all other assertions unchanged.

No other tracked or untracked path belongs to the implementation write-set. In particular, do not modify `CONTEXT.md` or create an ADR: this step applies the already-established Selection, Requested window, Native time, Issue, Raw, License, Citation, Provider, Engine, and Stage meanings without introducing a new domain meaning, and the strict task boundary forbids domain-document edits.

## 4. Existing assertions affected

### Updated explicitly

- `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface` is the only existing assertion whose expected value must change. Replace its exact public-name set with the complete 17-name set in section 1. Do not rename the test in this step even though its historical name mentions m2.

### Proven untouched

No existing callable is removed or re-parameterized, so no other existing expected value changes. Keep these direct regression assertions byte-for-byte unchanged and require them to pass in the full suite:

- `tests/test_observations_wrapper.py::test_observations_wrapper_delegates_to_provider_handle`
- `tests/test_observations_wrapper.py::test_observations_wrapper_forwards_default_on_issue`
- `tests/test_observations_wrapper.py::test_observations_wrapper_requires_core_keywords`
- `tests/test_internal_registry.py::test_registry_passes_widened_fetch_window_and_preserves_requested_provenance`
- `tests/test_internal_registry.py::test_registry_reads_packaged_license_and_citation_into_observation_provenance`
- `tests/test_internal_registry.py::test_registry_null_license_and_citation_are_silent_info_issues`
- `tests/test_internal_registry.py::test_registry_preserves_explicit_midnight_end`
- `tests/test_internal_registry.py::test_public_observations_converter_leak_raises_fatal_contract_error_naming_row`
- `tests/test_internal_registry.py::test_public_observations_exclusive_stop_source_keeps_reading_at_closed_requested_end`
- `tests/test_internal_registry.py::test_public_observations_parameterless_fixed_span_returns_rows_and_undercoverage_issue`
- `tests/test_internal_registry.py::test_registry_rejects_zone_carrying_endpoint_before_fetch`
- `tests/test_internal_registry.py::test_registry_engine_module_warns_for_accumulated_issue`
- `tests/test_internal_registry.py::test_registry_engine_module_raises_for_accumulated_issue`
- `tests/test_internal_observations.py::test_observation_request_normalizes_typed_temporal_inputs`
- `tests/test_internal_observations.py::test_observation_request_rejects_reversed_normalized_window`
- `tests/test_internal_observations.py::test_observation_request_rejects_zone_carrying_datetime_with_fix`
- `tests/test_internal_observations.py::test_observation_request_rejects_offset_bearing_iso_string_with_fix`
- `tests/test_internal_observations.py::test_observation_data_schema_rejects_provider_id_column_as_extra_under_raise`
- `tests/test_internal_observations.py::test_observation_result_constructs_with_exact_field_set`
- `tests/test_internal_conversion.py::test_convert_instant_window_is_closed_at_both_endpoints`
- `tests/test_internal_driver.py::test_drive_plans_each_requested_product_and_passes_immutable_keyed_renderings`
- `tests/test_internal_driver.py::test_drive_default_omit_never_constructs_raw_source_call`
- `tests/test_internal_driver.py::test_drive_clips_unknown_zone_instants_at_both_closed_edges_without_warning`
- `tests/test_usgs_nwis_observations.py::test_usgs_nwis_registry_dispatch_uses_engine_driver`
- `tests/test_usgs_nwis_observations.py::test_usgs_nwis_bare_date_returns_full_local_day_for_instant_product`
- `tests/test_ca_eccc_observations.py::test_ca_eccc_registry_dispatch_uses_engine_driver`

`tests/test_selection.py::test_selection_function_signatures_exclude_unshipped_capabilities` is also unchanged: it inspects only `find`, `pick`, `as_frame`, and `from_frame`, so the new fetch window parameters do not enter its combined parameter set. All remaining existing tests are proven untouched by the four-path write-set: their production targets and expected data do not change, and the full `uv run pytest` gate must pass without editing, deleting, loosening, skipping, or xfail-marking any of them.

## 5. Authored data

All new test data is in `tests/test_fetch.py`; there are no new fixture files. Quote and implement it exactly.

### 5.1 Offline catalogue inputs

For each of provider ids `"ca_eccc"` and `"usgs_nwis"`, use the existing `stub_packaged_catalogue_artifact_rich(provider_id)` fixture. Its complete logical rows needed by these tests are:

```python
provider_info = {
    "provider_id": provider_id,
    "name": f"{provider_id} Provider",
    "live_stations": False,
    "live_products": False,
    "live_station_products": False,
    "bulk_observations": "none",
    "catalogue_version": "2026.01",
    "license": None,
    "citation": None,
}

products = [
    {
        "provider_id": provider_id,
        "product_id": "level",
        "observed_property": "water_level",
        "frequency": "daily",
        "statistic": "mean",
        "period_type": "calendar_day",
        "period_anchor": "UTC",
        "unit": "m",
        "native_id": "WATER_LEVEL",
    },
    {
        "provider_id": provider_id,
        "product_id": "flow",
        "observed_property": "discharge",
        "frequency": "daily",
        "statistic": "mean",
        "period_type": "calendar_day",
        "period_anchor": "UTC",
        "unit": "m3/s",
        "native_id": "FLOW",
    },
    {
        "provider_id": provider_id,
        "product_id": "level_hourly",
        "observed_property": "water_level",
        "frequency": "hourly",
        "statistic": "instantaneous",
        "period_type": "instant",
        "period_anchor": "UTC",
        "unit": "m",
        "native_id": "WATER_LEVEL_HOURLY",
    },
    {
        "provider_id": provider_id,
        "product_id": "level_max",
        "observed_property": "water_level",
        "frequency": "daily",
        "statistic": "max",
        "period_type": "calendar_day",
        "period_anchor": "UTC",
        "unit": "m",
        "native_id": "WATER_LEVEL_MAX",
    },
]

stations = [
    {
        "provider_id": provider_id,
        "station_id": "station-1",
        "latitude": 46.2,
        "longitude": 7.1,
        "crs": "unknown",
    },
    {
        "provider_id": provider_id,
        "station_id": "station-2",
        "latitude": 47.1,
        "longitude": 8.3,
        "crs": "unknown",
    },
]

station_products = [
    {
        "provider_id": provider_id,
        "station_id": "station-1",
        "product_id": "level",
        "availability": "available",
        "availability_reason": None,
        "published_record_start_date": date(2020, 1, 1),
        "published_record_end_date": None,
        "last_catalogue_check": date(2026, 1, 1),
    },
    {
        "provider_id": provider_id,
        "station_id": "station-1",
        "product_id": "flow",
        "availability": "unknown",
        "availability_reason": "not_catalogued",
        "published_record_start_date": None,
        "published_record_end_date": None,
        "last_catalogue_check": date(2026, 1, 1),
    },
    {
        "provider_id": provider_id,
        "station_id": "station-2",
        "product_id": "level_hourly",
        "availability": "available",
        "availability_reason": None,
        "published_record_start_date": date(2021, 1, 1),
        "published_record_end_date": None,
        "last_catalogue_check": date(2026, 1, 1),
    },
    {
        "provider_id": provider_id,
        "station_id": "station-2",
        "product_id": "level_max",
        "availability": "unavailable",
        "availability_reason": "derived_not_supported",
        "published_record_start_date": None,
        "published_record_end_date": None,
        "last_catalogue_check": date(2026, 1, 1),
    },
]
```

Use `dataclasses.replace` to give each returned artifact a copied `provider_info` dictionary with these exact provider-distinguishing values before registration:

```python
{
    **artifact.provider_info,
    "license": f"https://licenses.test/{provider_id}",
    "citation": f"Citation {provider_id}",
}
```

Disable default registration with `monkeypatch.setattr(discovery, "_DEFAULT_PROVIDER_REGISTRATION_ENABLED", False)`, register both artifacts into the existing global `_registry`, and pass their recording stages through `engine_provider_module`. The autouse fixture in `tests/conftest.py` clears that registry before and after each test.

### 5.2 Recording provider stages

The fake is entirely in memory and performs no file or network access. Give each provider-stage object:

```python
observation_source = f"recording://{provider_id}"
zone = ZoneValue("+00:00")
```

Its complete `ProviderConfig` is exactly:

```python
ProviderConfig(
    zone=ZoneValue("+00:00"),
    products={
        ProductId("level"): ProductConfig(
            coordinates=SourceCoordinates("level"),
            unit=Unit.M,
            semantics=Instant(),
        ),
        ProductId("flow"): ProductConfig(
            coordinates=SourceCoordinates("flow"),
            unit=Unit.M3_S,
            semantics=Instant(),
        ),
        ProductId("level_hourly"): ProductConfig(
            coordinates=SourceCoordinates("level_hourly"),
            unit=Unit.M,
            semantics=Instant(),
        ),
        ProductId("level_max"): ProductConfig(
            coordinates=SourceCoordinates("level_max"),
            unit=Unit.M,
            semantics=Instant(),
        ),
    },
    cache=None,
)
```

The complete `ProductWindowDeclarations` value maps all four products to this exact declaration:

```python
ProductWindowDeclarations(
    {
        ProductId(product_id): WindowDeclaration(
            WindowGranularity("date"),
            WindowRenderingVocabulary.DATE,
            StopConvention.INCLUSIVE,
        )
        for product_id in ("level", "flow", "level_hourly", "level_max")
    }
)
```

`fetch` must append `(stations, tuple(str(product) for product in products))` to a mutable `calls` list and return `WithIssues(value=(payload,), issues=())`, where `payload` is this complete value for the one station/product pair:

```python
Payload(
    source_coordinates=config.products[products[0]].coordinates,
    station_products=((stations[0], products[0]),),
    fetch_window=fetch_window,
    content=f"{provider_id}|{stations[0]}|{products[0]}".encode(),
    origin=SourceCallOrigin(
        UnknownOriginFact(),
        UnknownOriginFact(),
        UnknownOriginFact(),
        UnknownOriginFact(),
        UnknownOriginFact(),
        UnknownOriginFact(),
        UnknownOriginFact(),
    ),
)
```

Here `fetch_window` on the right is the `FetchWindow` argument supplied to the fake stage. `parse` splits the content as `parsed_provider_id, station_id, product_id = payload.content.decode().split("|")` and returns this complete frame through `WithIssues(value=rows, issues=())`:

```python
pl.DataFrame(
    {
        "station_id": [station_id],
        "product_id": [product_id],
        "time": [datetime(2026, 1, 1, 12, 0)],
        "value": [VALUES[(parsed_provider_id, station_id, product_id)]],
        "time_zone": ["+00:00"],
    },
    schema=RowsSchema.polars_schema,
)
```

Use this complete value table:

```python
VALUES = {
    ("ca_eccc", "station-1", "level"): 10.0,
    ("ca_eccc", "station-2", "level_hourly"): 20.0,
    ("usgs_nwis", "station-1", "level"): 30.0,
    ("usgs_nwis", "station-2", "level_hourly"): 40.0,
}
```

No other key is used. Both fake `fetch` and fake `parse` return `WithIssues(..., issues=())`.

### 5.3 Selections, errors, frames, and receipts

The empty selection input is exactly:

```python
empty = rr.find(
    provider="usgs_nwis",
    station="station-2",
    product="level_max",
)
```

Its reason is exactly:

```python
_EmptyReason(
    code="no_catalogue_edge",
    provider_ids=("usgs_nwis",),
    station_ids=("station-2",),
    product_ids=("level_max",),
    published_products=("level_hourly",),
)
```

The mixed selection input is exactly `rr.find(product="level")`, with keys:

```python
(
    ("ca_eccc", "station-1", "level"),
    ("usgs_nwis", "station-1", "level"),
)
```

The sparse single-provider selection is exactly:

```python
sparse = rr.pick(
    rr.find(provider="usgs_nwis"),
    station=["station-1", "station-2"],
    product=["level", "level_hourly"],
)
```

with keys:

```python
(
    ("usgs_nwis", "station-1", "level"),
    ("usgs_nwis", "station-2", "level_hourly"),
)
```

For `start="2026-01-01", end="2026-01-01"`, its exact expected data frame is:

```python
pl.DataFrame(
    {
        "time": [datetime(2026, 1, 1, 12, 0), datetime(2026, 1, 1, 12, 0)],
        "time_zone": ["+00:00", "+00:00"],
        "station_id": ["station-1", "station-2"],
        "product_id": ["level", "level_hourly"],
        "value": [30.0, 40.0],
    },
    schema=ObservationDataSchema.polars_schema,
)
```

Its exact provenance values are:

```python
source = "recording://usgs_nwis"
provider_id = ProviderId("usgs_nwis")
catalogue_version = "2026.01"
license = "https://licenses.test/usgs_nwis"
citation = "Citation usgs_nwis"
request = {
    "series": [
        {"station_id": "station-1", "product_id": "level"},
        {"station_id": "station-2", "product_id": "level_hourly"},
    ],
    "start": "2026-01-01T00:00:00",
    "end": "2026-01-01T23:59:59.999999",
}
```

Its other exact result values are:

```python
issues = ()
raw = RawPayload(provider_id=ProviderId("usgs_nwis"), entries=())
model_fields = ("data", "provenance", "issues", "raw")
fetch_calls = [
    (("station-1",), ("level",)),
    (("station-2",), ("level_hourly",)),
]
```

For the mixed selection passed to `fetch_by_provider`, require keys `("ca_eccc", "usgs_nwis")` and these complete provider frames:

```python
expected_by_provider = {
    "ca_eccc": pl.DataFrame(
        {
            "time": [datetime(2026, 1, 1, 12, 0)],
            "time_zone": ["+00:00"],
            "station_id": ["station-1"],
            "product_id": ["level"],
            "value": [10.0],
        },
        schema=ObservationDataSchema.polars_schema,
    ),
    "usgs_nwis": pl.DataFrame(
        {
            "time": [datetime(2026, 1, 1, 12, 0)],
            "time_zone": ["+00:00"],
            "station_id": ["station-1"],
            "product_id": ["level"],
            "value": [30.0],
        },
        schema=ObservationDataSchema.polars_schema,
    ),
}
```

For each `provider_id`, require the complete provider-specific values:

```python
result.provenance.source == f"recording://{provider_id}"
result.provenance.provider_id == ProviderId(provider_id)
result.provenance.catalogue_version == "2026.01"
result.provenance.license == f"https://licenses.test/{provider_id}"
result.provenance.citation == f"Citation {provider_id}"
result.provenance.request == {
    "series": [{"station_id": "station-1", "product_id": "level"}],
    "start": "2026-01-01T00:00:00",
    "end": "2026-01-01T23:59:59.999999",
}
result.issues == ()
result.raw == RawPayload(provider_id=ProviderId(provider_id), entries=())
tuple(result.data.columns) == ("time", "time_zone", "station_id", "product_id", "value")
"provider_id" not in result.data.columns
```

Use `polars.testing.assert_frame_equal(actual, expected, check_exact=True)` for every complete frame assertion.

## 6. Acceptance criteria

Add these tests to `tests/test_fetch.py`, using the exact data above. Each command is executable offline.

1. Empty reason and zero calls:

   ```bash
   uv run pytest tests/test_fetch.py::test_fetch_rejects_reason_carrying_empty_selection_before_lookup_or_fetch -q
   ```

   Expected: pass. Assert `error.reason is empty.empty_reason`, the exact empty error text in section 2.2, `provider_lookups == []`, and both recording stages' `calls == []`. Also assert `rr.fetch_by_provider(empty, start="2026-01-01", end="2026-01-01") == {}` while lookups and calls remain empty.

2. Mixed-provider guard and deterministic diagnosis:

   ```bash
   uv run pytest tests/test_fetch.py::test_fetch_rejects_mixed_provider_selection_before_lookup_or_fetch -q
   ```

   Expected: pass. Assert the exact mixed keys and exact error text in sections 2.2 and 5.3, `error.provider_ids == ("ca_eccc", "usgs_nwis")`, `provider_lookups == []`, and both recording stages' `calls == []`.

3. Exact sparse routing and merged single-provider result:

   ```bash
   uv run pytest tests/test_fetch.py::test_fetch_routes_only_selected_sparse_series -q
   ```

   Expected: pass. Assert the exact sparse keys, two-call list, complete frame, complete provenance receipt, singular provider/license/citation, empty issues, empty provider-scoped raw payload, and four-member result values in section 5.3.

4. One singular result per provider:

   ```bash
   uv run pytest tests/test_fetch.py::test_fetch_by_provider_returns_one_singular_result_per_provider -q
   ```

   Expected: pass. Assert exact mapping key order, exact per-provider call lists, both complete frames, all per-provider provenance/raw values, exact four-member result shape, exact five-column data shape, and absence of a data `provider_id` column.

5. Input type and public signatures:

   ```bash
   uv run pytest tests/test_fetch.py::test_fetch_functions_require_rivretrieve_selection_and_defer_request_controls -q
   ```

   Expected: pass. For both functions, passing `object()` raises `TypeError` with exactly `selection must be a RivRetrieve selection` before provider lookup. Assert parameter names exactly `("selection", "start", "end")`, required positional-or-keyword `selection`, required keyword-only `start` and `end`, and absence of `raw` and `on_issue`.

6. ADR-0016 rejection through the new route:

   ```bash
   uv run pytest tests/test_fetch.py::test_fetch_refuses_zone_carrying_endpoint_before_stage_fetch -q
   ```

   Expected: pass. A one-series `usgs_nwis` selection called with `start="2026-01-01T00:00:00+00:00"` and `end="2026-01-01"` raises `InvalidObservationRequestError` with the exact text in section 2.4 and leaves the recording stage's `calls == []`.

7. Exact package surface:

   ```bash
   uv run pytest tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface -q
   ```

   Expected: pass with exactly the 17 names in section 1; `source_metadata` and m7's `map` remain absent, while all m9-owned legacy names remain present.

8. Legacy engine and requested-window regression:

   ```bash
   uv run pytest tests/test_observations_wrapper.py tests/test_internal_registry.py tests/test_internal_observations.py tests/test_internal_conversion.py tests/test_internal_driver.py tests/test_usgs_nwis_observations.py tests/test_ca_eccc_observations.py -q
   ```

   Expected: pass without modifying any assertion named in section 4. This is the direct evidence that the legacy observation API, engine, five-column frame, four-member result, closed endpoint behavior, date expansion, explicit-midnight behavior, and zone refusal remain intact.

## 7. Gate commands

Run every gate after implementation and test edits, and before the one commit, verbatim and in this exact order:

```bash
uv sync
uv run ruff format
uv run ruff check --fix
uv run ty check src
uv run pytest
uv build
```

Expected observations:

- `uv sync` completes from the existing lock without changing `pyproject.toml` or `uv.lock`.
- `uv run ruff format` exits 0; it rewrites files in place when needed, so inspect the resulting diff. Do not substitute `--check` for this required gate.
- `uv run ruff check --fix` exits 0 with no remaining diagnostics; inspect any automatic edits before proceeding.
- `uv run ty check src` reports success. The scope is exactly `src`.
- `uv run pytest` passes the entire baseline plus the new tests. The only skips are the two pre-existing missing-folium skips at `tests/test_map_stations.py:179` and `tests/test_map_stations.py:190`; do not introduce another skip or xfail. The pinned baseline is `1643 passed, 2 skipped`, so any failure is caused by this change and must be fixed rather than waived.
- `uv build` succeeds for both distribution artifacts without a version change.

`uv` opens `~/.cache/uv` for write on every invocation. In the executor environment, `~/.config/uv/uv.toml` is expected to point `cache-dir` at a warm shared cache below `$TMPDIR`, which the sandbox permits. If a gate fails with `Failed to initialize cache` or `Operation not permitted (os error 1)`, report that the configuration is missing or the temporary cache was purged; do not change project dependency files or replace `uv`.

## 8. Constraints and prohibitions

- Work from exact ref `1b903fa1b88522cbf2f441d080a414d17f5056cb`. Read tracked files from that ref when reconciling any worktree difference.
- Plan and implement only m4-s1. The graph has one node and no dependency edge inside m4.
- Keep the implementation write-set to the four paths in section 3. If evidence forces another tracked path, stop and report that this plan's write-set is invalid rather than silently widening it.
- Do not modify `src/rivretrieve/_internal/selection.py`, `registry.py`, `observations.py`, `engine.py`, `driver.py`, provider files, catalogues, or fixtures. Exact per-series calls make those changes unnecessary.
- Do not modify `CONTEXT.md` or any file in `docs/adr/`. The canonical project terms are already sufficient, and ADR-0019/0020 are absent at the pinned ref.
- Do not add `raw=` or `on_issue=` to either new public signature and do not decide `RawMode`'s fate. That is m5.
- Do not delete or modify any legacy public name: `ProviderHandle`, `provider`, `observations`, `stations`, `provider_info`, `product_info`, `map_stations`, and the current `products` remain.
- Add only `fetch` and `fetch_by_provider`. Do not add m7's `map`, m8's rejected `source_metadata`, `CatalogSource`, public result/error/carrier classes, or any other export.
- Do not add a `provider_id` column to observation data. The exact frame remains `time | time_zone | station_id | product_id | value`.
- Do not merge frames, provenance, issues, or raw payloads across providers. The output unit of `fetch_by_provider` is a provider-keyed result.
- Do not change the existing observation engine's Cartesian legacy request semantics globally. Avoiding Cartesian expansion is a property of the new selection route.
- Do not alter `published_record_start_date` or `published_record_end_date`, and do not restore bare canonical `start_date` or `end_date`. Provider-native and local/request variable spellings that already use start/end remain untouched.
- Do not add bounding-box search, `record_covers`, `source="live"`, a coverage snapshot, harmonised station-name or river-name search, a chained query language, PyPI publication, documentation authoring, provider porting, or any decision about native tables in wheels.
- Do not install folium or any dependency. There is no network and folium's two existing skips are expected.
- Use `uv` exclusively. Do not use `pip`, Poetry, Conda, or pip-tools.
- Do not edit `pyproject.toml` or `uv.lock`; they are tracked and already synchronized.
- `tests/typecheck/nominal_window_misuse.py` is an intentional negative type-check fixture asserted by `tests/test_internal_engine_contracts.py`. Do not repair, suppress, or edit it, and do not widen `uv run ty check src` to include it.
- Do not add `noqa`, type-ignore workarounds, skips, xfails, fallback values, or catch/log/continue behavior to force a gate green.
- Do not edit any field under `stated` in `.pce/repository-contract.json`.
- Require no version bump and no tag. `src/rivretrieve/__init__.py` remains `__version__ = "0.1.49"`, and project metadata remains unchanged.
- Preserve the not-touched fence exactly: no source/test/fixture beyond the section-3 write-set, no catalogue artifact, no vision/graph/review artifact, no domain document, no dependency file, no build artifact added to git, and no publication action.

## 9. Executor policies

- Produce exactly **one conventional commit**, after all six gates pass. Use this exact subject:

  ```text
  feat: fetch exact catalogue selections
  ```

- Before committing, inspect `git diff --check`, `git diff --stat`, and `git status --short`; the tracked diff must contain exactly the four write-set paths.
- Create `pr-body.md` at the worktree root only after the implementation is complete. Leave it **untracked** and do not include it in the commit. Its exact contents are:

  ```markdown
  ## Summary

  - add single-provider `fetch` with pre-I/O empty and mixed-selection guards
  - route sparse selected series without station-product Cartesian expansion
  - add provider-partitioned `fetch_by_provider` with singular provenance and raw identity
  - preserve the legacy observation surface and request semantics

  ## Validation

  - `uv sync`
  - `uv run ruff format`
  - `uv run ruff check --fix`
  - `uv run ty check src`
  - `uv run pytest`
  - `uv build`
  ```

- Do not create a branch as part of execution unless the orchestrator has already placed the worktree on the intended branch. This step is destined for `pce/the-surface-is-three-verbs-and-a-selection/milestone-4` as one squash-merged pull request, but the executor must not push.
- No tag, no push, no release, no version change, and no attribution footers. In particular, do not add `Co-authored-by`, `Signed-off-by`, assistant attribution, or similar commit-message trailers.
- Gates run **before** the commit. If formatting or lint fixing changes a file, review it and rerun the required sequence as needed before committing.
- After the commit, `git status --short` should show only `?? pr-body.md`; all tracked work must be committed and no other untracked file may remain.
