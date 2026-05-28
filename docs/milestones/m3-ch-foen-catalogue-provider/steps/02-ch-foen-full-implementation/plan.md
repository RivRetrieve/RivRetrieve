# 02-ch-foen-full-implementation Plan

## Amendment 1 — Path migration (post-6A blocker)

The original plan's package path `src/rivretrieve/providers/ch_foen/` collides with the public `rr.providers()` callable re-exported at `src/rivretrieve/__init__.py:5`. The executor stopped at checkpoint 6A on `TypeError: 'module' object is not callable`. All package paths and import targets in §3, §5, §6, and §7 are updated to use `src/rivretrieve/_internal/providers/ch_foen/` instead. No other plan content changes. See docs/discoveries.md D6.

## 1. Goal and scope

Ship `ch_foen` end-to-end as a catalogue-only provider in one coherent step.

At the end of this step:

- `rr.providers()` includes `"ch_foen"`.
- `rr.provider("ch_foen")` returns a Protocol-conformant handle whose seven public methods are reachable.
- `info()`, `products()`, `stations()`, and `station_products()` return real packaged `ch_foen` catalogue rows generated from the committed Existenz.ch hydro locations fixture.
- `row_annotation_schema()` and `series_annotation_schema()` return empty schema lists.
- `observations(...)` returns an `ObservationResult` with empty tables, provenance, no raw payload, and one `observations_not_yet_implemented` Issue with severity `error`. It must not raise `AttributeError`, `NotImplementedError`, or `IssuePolicyError` for any `on_issue` value.
- Global discovery functions include `ch_foen` packaged rows.
- `ch_foen` declares catalogue/live/observation capabilities honestly.

This step deliberately collapses scaffolding, generator, artifacts, provider module, lazy registration, placeholder observations, and capability declaration. The implementation order in §6 keeps intermediate state legible and testable.

Out of scope: real observations, top-level `rr.observations(...)`, `rr.map_stations()`, product dictionary edits, architecture edits, token-bearing runtime source, live network calls in tests, provider-port closeout docs beyond a stub, and M3 closeout `REPORT.md`.

## 2. API surface touched

Public surface changes expected:

- `rr.providers()` returns a list that includes `"ch_foen"`.
- `rr.provider("ch_foen")` exposes the existing seven `ProviderHandle` methods:
  - `info()` returns the `ProviderInfo` row from the packaged artifact.
  - `products()` returns real `ch_foen` product rows.
  - `stations()` returns real `ch_foen` station rows.
  - `station_products()` returns real `ch_foen` station-product availability rows.
  - `row_annotation_schema()` returns `[]`.
  - `series_annotation_schema()` returns `[]`.
  - `observations(...)` returns the placeholder `ObservationResult` described above.
- Global discovery functions include `ch_foen` rows:
  - `rr.stations()` gains `ch_foen` station rows.
  - `rr.products()` / `rr.product_info()` gain `ch_foen` product rows.
  - `rr.provider_info()` gains one `ch_foen` row.

No public signatures or public symbols change. `ProviderHandle` keeps the same seven-method shape from M2 and M3 step 01's alias annotations. No public type is added or promoted. The three `ChFoen*Metadata` Pydantic models and the provider module remain internal.

T117 / T119 / T120 expectations:

- T117 `tests/test_provider_handle.py::test_provider_handle_protocol_method_signatures_match_tracker` is invariant. It checks method shape and annotations only; `ch_foen` registration must not edit it.
- T119 `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface` is invariant. The package-root present set remains exactly `ProviderHandle`, `product_info`, `products`, `provider`, `provider_info`, `providers`, `stations`, plus `__version__`.
- T120 `tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion` is invariant. The new internal metadata models and provider module must not be added to the package root. Do not extend T120 with `ChFoen*` names as the primary control; those names live under `rivretrieve._internal.providers.ch_foen.metadata`, so package-root `hasattr(rivretrieve, "...")` would only test an unrealistic re-export. If a leak check is useful, add a separate test that imports `rivretrieve._internal.providers.ch_foen.metadata` and then asserts the same names are still absent from `rivretrieve`.
- Existing discovery tests that assert row counts over an empty or stub-only registry need targeted updates or new `ch_foen`-specific cases only where automatic default registration changes the expected rows. SHAPE assertions against `*_SCHEMA.polars_schema` remain invariant.

## 3. Data structures and types

### 3.1 ChFoenStationMetadata

Define in `src/rivretrieve/_internal/providers/ch_foen/metadata.py` as an internal Pydantic model with `extra="allow"` so source fields are not discarded.

Fields pinned from architecture.md §7 station catalogue common fields and the Existenz.ch fixture shape:

| Field | Type | Required | Source / use |
| --- | --- | --- | --- |
| `station_key` | `str` | yes | Outer payload key, e.g. `"2016"`; fixture stores station records under `payload` keys (thirdparty/RivRetrieve-Python @ origin/switzerland:tests/test_data/switzerland_metadata_locations.json:1). |
| `native_id` | `str` | yes | `details.id` normalized to string; legacy uses `details.get("id") or station_key`, strips it, and maps it to gauge ID (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:151-157, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:171-173). |
| `name` | `str` | yes | `details.name`; common `StationCatalog.name` (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:157). |
| `water_body_name` | `str | None` | yes, nullable | `details["water-body-name"]` or `details["water_body_name"]`; legacy maps this to river (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:152-158). |
| `water_body_type` | `str | None` | yes, nullable | Fixture `details["water-body-type"]`; retained in metadata, not common columns (thirdparty/RivRetrieve-Python @ origin/switzerland:tests/test_data/switzerland_metadata_locations.json:1). |
| `chx` | `float | None` | yes, nullable | Fixture Swiss coordinate x; retained in metadata. |
| `chy` | `float | None` | yes, nullable | Fixture Swiss coordinate y; retained in metadata. |
| `latitude` | `float` | yes | `details.lat`; common `StationCatalog.latitude` (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:159). |
| `longitude` | `float` | yes | `details.lon`; common `StationCatalog.longitude` (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:160). |
| `country` | `str` | yes | Constant `"Switzerland"` from legacy (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:42, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:163). |
| `source` | `str` | yes | Legacy source string (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:41, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:164). |
| `api_source` | `str | None` | yes, nullable | Top-level fixture `source` value. |
| `api_url` | `str | None` | yes, nullable | Top-level fixture `apiurl` value. |
| `open_data_url` | `str | None` | yes, nullable | Top-level fixture `opendata` value. |
| `license_url` | `str | None` | yes, nullable | Top-level fixture `license` value. |
| `elevation_m` | `float | None` | yes, nullable | Common `StationCatalog.elevation_m`; legacy sets altitude to `np.nan` because locations response does not provide it (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:161). |
| `drainage_area_km2` | `float | None` | yes, nullable | Common `StationCatalog.drainage_area_km2`; legacy sets area to `np.nan` (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:162). |

Common `STATION_CATALOG_SCHEMA` fields are generated as:

- `provider_id="ch_foen"`.
- `station_id=native_id`.
- `name=name`.
- `latitude=latitude`.
- `longitude=longitude`.
- `country="Switzerland"`, matching the legacy normalized metadata and avoiding an unscoped ISO-code normalization.
- `elevation_m=None`.
- `drainage_area_km2=None`.
- `start_date=None`.
- `end_date=None`.
- `metadata=<ChFoenStationMetadata.model_dump()>` JSON-encoded for artifact storage.

Drainage area and elevation are explicitly nullable in `STATION_CATALOG_SCHEMA`; this matches architecture.md §7 and M1/M3 step 01 schema contracts.

### 3.2 ChFoenProductMetadata

Define in `metadata.py`, internal Pydantic model, `extra="allow"`.

Fields:

| Field | Type | Required | Source / use |
| --- | --- | --- | --- |
| `legacy_variable` | `str` | yes | Legacy RivRetrieve variable constant name/value being translated. |
| `native_id` | `str` | yes | Provider-native product identifier used in `ProductCatalog.native_id`; use the preferred native field, while `parameters` preserves all fields. |
| `parameters` | `tuple[str, ...]` | yes | Legacy `VARIABLE_MAP[*]["parameters"]` (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:44-80). |
| `preferred_parameter` | `str` | yes | Legacy preferred field (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:45-79). |
| `fallback_parameter` | `str | None` | yes, nullable | Legacy fallback field where present (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:45-79). |
| `aggregate_daily` | `bool` | yes | Legacy flag distinguishing daily derived-in-fetcher behavior from raw instant behavior (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:49, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:55, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:61, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:67, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:73, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:79). |
| `legacy_unit` | `str` | yes | Human-readable unit from legacy class docstring. |
| `notes` | `str | None` | yes, nullable | Records semantic caveats such as parameter preference or daily aggregation source. |

The common `ProductCatalog` row fields must follow docs/product_dictionary.md exactly for canonical products:

- `product_id`: canonical ID from §3.4.
- `observed_property`: `discharge`, `stage`, or `water_temperature`.
- `frequency`: `daily` for daily means, `irregular` for instantaneous products.
- `statistic`: `mean` for daily means, `instantaneous` for instantaneous products.
- `period_type`: `interval` for daily means, `instant` for instantaneous products.
- `period_anchor`: `provider_defined` for daily means because anchoring is not proven by the catalogue fixture; `instant` for instantaneous.
- `unit`: `m3/s`, `m`, or `degC` per product dictionary spelling.
- `native_id`: preferred native parameter (`flow`, `height_abs`, or `temperature`).
- `derived`: `False`. Even though the legacy fetcher aggregates daily in client code, the catalogue step is not shipping RivRetrieve-derived products; product metadata records `aggregate_daily=True` as a legacy retrieval behavior to resolve in M4. If the executor believes daily products must be `derived=True`, stop and escalate because that would change product dictionary semantics for M3.
- `derivation_method`: `None`.
- `metadata`: JSON-encoded model dump.

### 3.3 ChFoenStationProductMetadata

Define in `metadata.py`, internal Pydantic model, `extra="allow"`.

Fields:

| Field | Type | Required | Source / use |
| --- | --- | --- | --- |
| `station_id` | `str` | yes | Native station ID. |
| `product_id` | `str` | yes | Canonical product ID. |
| `native_parameters` | `tuple[str, ...]` | yes | Product native parameter tuple from `ChFoenProductMetadata`. |
| `availability_source` | `str` | yes | `"provider_station_catalogue_assumption"`. The locations endpoint lists stations but not per-variable availability. |
| `availability_note` | `str` | yes | Explain that M3 materializes known provider station-product universe as `unknown`, not guaranteed observed data. |

Common `STATION_PRODUCT_CATALOG_SCHEMA` fields:

- `provider_id="ch_foen"`.
- `station_id=<station station_id>`.
- `product_id=<product product_id>`.
- `availability="unknown"`.
- `availability_reason="Existenz.ch locations catalogue does not expose per-variable station availability"`.
- `start_date=None`.
- `end_date=None`.
- `last_catalogue_check=<date generator ran or fixture snapshot date>`. The generator accepts or computes a release date and writes a `date`, not a datetime, to satisfy schema.
- `metadata=<ChFoenStationProductMetadata.model_dump()>` JSON-encoded.

This means `station_products` row count is `246 * 6 = 1476` unless the generator discovers a fatal mismatch before artifact creation.

### 3.4 Product vocabulary decision

Legacy `SwitzerlandFetcher` exposes variables through `VARIABLE_MAP` and returns them from `get_available_variables()` (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:44-95). The class docstring enumerates the supported variables and units (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:22-29).

Recommendation: all six map to canonical V1 product IDs. No `ch_foen`-specific product IDs and no dropped products in M3.

| Legacy variable | Legacy native fields | Classification | Product row |
| --- | --- | --- | --- |
| `constants.DISCHARGE_DAILY_MEAN` | `flow`, `flow_ls`; preferred `flow`, fallback `flow_ls`; daily aggregation true (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:45-50) | canonical V1 | `product_id="discharge_daily_mean"`, `observed_property="discharge"`, `frequency="daily"`, `statistic="mean"`, `period_type="interval"`, `period_anchor="provider_defined"`, `unit="m3/s"`, `native_id="flow"`. |
| `constants.DISCHARGE_INSTANT` | `flow`, `flow_ls`; preferred `flow`, fallback `flow_ls`; daily aggregation false (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:51-56) | canonical V1 | `product_id="discharge_instantaneous"`, `observed_property="discharge"`, `frequency="irregular"`, `statistic="instantaneous"`, `period_type="instant"`, `period_anchor="instant"`, `unit="m3/s"`, `native_id="flow"`. |
| `constants.STAGE_DAILY_MEAN` | `height_abs`, `height`; preferred `height_abs`, fallback `height`; daily aggregation true (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:57-62) | canonical V1 | `product_id="stage_daily_mean"`, `observed_property="stage"`, `frequency="daily"`, `statistic="mean"`, `period_type="interval"`, `period_anchor="provider_defined"`, `unit="m"`, `native_id="height_abs"`. |
| `constants.STAGE_INSTANT` | `height_abs`, `height`; preferred `height_abs`, fallback `height`; daily aggregation false (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:63-68) | canonical V1 | `product_id="stage_instantaneous"`, `observed_property="stage"`, `frequency="irregular"`, `statistic="instantaneous"`, `period_type="instant"`, `period_anchor="instant"`, `unit="m"`, `native_id="height_abs"`. |
| `constants.WATER_TEMPERATURE_DAILY_MEAN` | `temperature`; no fallback; daily aggregation true (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:69-74) | canonical V1 | `product_id="water_temperature_daily_mean"`, `observed_property="water_temperature"`, `frequency="daily"`, `statistic="mean"`, `period_type="interval"`, `period_anchor="provider_defined"`, `unit="degC"`, `native_id="temperature"`. |
| `constants.WATER_TEMPERATURE_INSTANT` | `temperature`; no fallback; daily aggregation false (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:75-80) | canonical V1 | `product_id="water_temperature_instantaneous"`, `observed_property="water_temperature"`, `frequency="irregular"`, `statistic="instantaneous"`, `period_type="instant"`, `period_anchor="instant"`, `unit="degC"`, `native_id="temperature"`. |

Dropped: none. `ch_foen`-specific product IDs: none. Intentional divergence from legacy: legacy variable names such as `DISCHARGE_INSTANT` are not carried forward as public product IDs because docs/product_dictionary.md already provides canonical opaque product IDs for these semantics.

### 3.5 Provider info row contract

ProviderInfo row fields must match `PROVIDER_INFO_CATALOG_SCHEMA`:

- `provider_id`: `"ch_foen"`.
- `name`: `"Swiss Federal Office for the Environment FOEN / BAFU"`, matching the legacy `SOURCE` string for parity (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:41).
- `live_stations`: `False`.
- `live_products`: `False`.
- `live_station_products`: `False`.
- `bulk_observations`: `"false"` because real observations are not implemented and there is no supported bulk observation capability yet.
- `catalogue_version`: the artifact generation date in `YYYY-MM-DD`, unless the source payload later exposes a stronger snapshot timestamp.
- `metadata`: JSON object string containing at least `{"source_url":"https://api.existenz.ch/apiv1/hydro/locations","legacy_source":"thirdparty/RivRetrieve-Python @ origin/switzerland"}` and no secrets.

All three live catalogue flags are `False` because the Existenz.ch hydro locations endpoint is queried by maintainer-only `generate_catalogue.py`, not by runtime provider catalogue methods. `bulk_observations` is effectively false in M3 because `observations()` is a placeholder. This is honest capability reporting and lets M2 live-routing return `live_catalogue_unsupported` without code changes.

## 4. Errors and failure modes

### 4.1 Fatal-raise paths

All fatal paths must subclass `FatalContractError` directly or through existing subclasses, and must not be routed through `apply_on_issue`.

Generator fatal paths:

- Unrecognized variable code while translating `VARIABLE_MAP` to product rows.
- Corrupt fixture: invalid JSON, missing top-level `payload`, non-object payload, or station record with malformed `details`.
- Missing required station fields: station ID, name, latitude, longitude.
- Missing required product metadata fields from the local product translation table.
- Missing required station-product fields during matrix construction.
- Network failure when the generator is intentionally run live by a maintainer.
- Live JSON decode failure or non-2xx response when run live.
- Artifact validation failure against `STATION_CATALOG_SCHEMA`, `PRODUCT_CATALOG_SCHEMA`, `STATION_PRODUCT_CATALOG_SCHEMA`, or `PROVIDER_INFO_CATALOG_SCHEMA`.

Runtime fatal paths:

- Corrupt packaged artifact at load time is delegated to `load_packaged_catalogue_artifact` / `packaged_catalogue_artifact_from_components` and existing `CorruptCatalogArtifactError` paths from M1/M2.
- Invalid catalogue `source` values remain existing `InvalidCatalogueSourceError`.
- Provider module import failure is not a normal `import rivretrieve` runtime concern because `ch_foen` is registered lazily from discovery/lookup code, not imported at package import. If lazy registration attempts to import the module and it fails, that is a packaging/deployment fatal and should surface directly, not as an Issue.

### 4.2 Issue-carrying paths

Observation placeholder:

- `observations_not_yet_implemented`, severity `error`, provider_id `ch_foen`, details including requested stations/products/start/end.
- The result contains the issue in `ObservationResult.issues`.
- Load-bearing compatibility decision: do not call `apply_on_issue` with the caller's `on_issue` for this placeholder, because current `apply_on_issue` raises `IssuePolicyError` under `on_issue="raise"` for severity `error`. The step requirement says the placeholder does not raise under any `on_issue` setting. If a reviewer requires literal `apply_on_issue(requested_policy)` here, stop: it contradicts the non-raising placeholder requirement and would require changing M2 issue-policy semantics.

Recoverable per-row generator issues:

- Default: none expected.
- Missing optional fixture fields that are explicitly nullable (`water_body_name`, `water_body_type`, `chx`, `chy`) may be accepted and recorded as `None` in metadata.
- Missing optional common fields (`elevation_m`, `drainage_area_km2`, `start_date`, `end_date`) are not issues; they are expected nulls.
- Incomplete input for required common fields is fatal, not recoverable.

### 4.3 Observations placeholder non-raise rule

`rr.provider("ch_foen").observations(...)` must not raise `AttributeError`, `NotImplementedError`, `ObservationsUnavailableError`, or `IssuePolicyError` for the placeholder path. The module must be registered so `_ProviderHandle.observations` passes the module-presence check, builds an `ObservationRequest`, calls `ch_foen_module.observations`, validates empty annotation tables against empty schemas, and returns normally.

## 5. Tests

### 5.1 Pydantic model validation tests

Tests import metadata models from `rivretrieve._internal.providers.ch_foen.metadata`.

- `test_ch_foen_station_metadata_validates_fixture_station`: happy-path station metadata from station `2016`.
- `test_ch_foen_station_metadata_allows_nullable_elevation_and_drainage_area`: explicit `None` handling.
- `test_ch_foen_product_metadata_validates_each_declared_product`: all six product metadata rows validate.
- `test_ch_foen_station_product_metadata_validates_unknown_availability_basis`: one station-product row validates with metadata note.

### 5.2 generate_catalogue.py tests

Tests import the generator from `rivretrieve._internal.providers.ch_foen.generate_catalogue`.

- `test_ch_foen_generator_uses_committed_fixture_without_network`: mocked HTTP response is `tests/test_data/switzerland_metadata_locations.json`.
- `test_ch_foen_generator_station_count_matches_legacy_fixture`: station count is `246` (thirdparty/RivRetrieve-Python @ origin/switzerland:tests/test_switzerland.py:36-39).
- `test_ch_foen_generator_station_2016_brugg_matches_legacy_fixture`: station `2016` exists and is named `Brugg`, river/water body `Aare`, lat `47.4825`, lon `8.1949` (thirdparty/RivRetrieve-Python @ origin/switzerland:tests/test_switzerland.py:40-45).
- `test_ch_foen_generator_handles_nullable_elevation_and_drainage_area`: generated station rows carry nulls accepted by `STATION_CATALOG_SCHEMA`.
- `test_ch_foen_generator_artifacts_validate_against_all_catalogue_schemas`: validates provider, product, station, and station-product artifacts against `PROVIDER_INFO_CATALOG_SCHEMA`, `PRODUCT_CATALOG_SCHEMA`, `STATION_CATALOG_SCHEMA`, and `STATION_PRODUCT_CATALOG_SCHEMA`.
- `test_ch_foen_generator_rejects_unknown_variable_code`: fatal path for vocabulary drift.
- `test_ch_foen_generator_rejects_corrupt_fixture`: fatal path for malformed fixture.

### 5.3 Provider module unit tests

Tests import the provider module from `rivretrieve._internal.providers.ch_foen.module`.

- `test_ch_foen_info_returns_provider_info`.
- `test_ch_foen_products_returns_packaged_products`.
- `test_ch_foen_stations_returns_packaged_stations`.
- `test_ch_foen_station_products_returns_packaged_availability`.
- `test_ch_foen_row_annotation_schema_is_empty`.
- `test_ch_foen_series_annotation_schema_is_empty`.

### 5.4 Lazy registration tests

Import-target verification uses `from rivretrieve._internal.providers.ch_foen import module as ch_foen_module`.

- `test_providers_includes_ch_foen_after_discovery_call`: `rr.providers()` includes `"ch_foen"`.
- `test_global_stations_include_ch_foen_rows`.
- `test_global_products_include_ch_foen_rows`.
- `test_provider_handle_station_products_returns_ch_foen_rows`: call `rr.provider("ch_foen").station_products()` and assert the provider-level rows include the expected `246 * 6 = 1476` unknown-availability matrix.
- `test_global_provider_info_includes_ch_foen_row`.

### 5.5 Observations placeholder test

- `test_ch_foen_observations_placeholder_returns_issue_result`: one `observations_not_yet_implemented` Issue with severity `error`.
- Empty `data` table uses `ObservationDataSchema`.
- Empty `row_annotations` table uses `RowAnnotationTableSchema`.
- Empty `series_annotations` table uses `SeriesAnnotationTableSchema`.
- Provenance is present with `source="placeholder"`, provider_id `ch_foen`, request fields, RivRetrieve version, and catalogue version.
- `raw is None`.
- Parametrized over `on_issue in ("warn", "raise", "ignore")`; none raises.

### 5.6 Capability test

- `test_ch_foen_provider_info_capabilities_are_declared_false`: `live_stations`, `live_products`, and `live_station_products` are `False`; `bulk_observations` reports no supported bulk observation capability.

### 5.7 source="live" routing test

- `test_ch_foen_live_products_unsupported_uses_m2_routing`.
- `test_ch_foen_live_stations_unsupported_uses_m2_routing`.
- `test_ch_foen_live_station_products_unsupported_uses_m2_routing`.

Each verifies `on_issue="warn"` returns an empty typed table plus `live_catalogue_unsupported`, `on_issue="raise"` raises `IssuePolicyError`, and `on_issue="ignore"` returns the issue silently. This should pass through the existing `CatalogueReader` capability-aware mechanism with no M2 code changes.

### 5.8 Negative controls preserved

- T117 signature shape invariant.
- T119 public surface invariant.
- T120 deferred-name absence invariant. Keep the package-root absence list stable unless an actual package-root leak vector appears; test `ChFoen*` non-leakage separately only after importing `rivretrieve._internal.providers.ch_foen.metadata`.
- Offline import invariant: `import rivretrieve` does not import `rivretrieve._internal.providers`, `rivretrieve._internal.providers.ch_foen`, `rivretrieve._internal.providers.ch_foen.module`, or `rivretrieve._internal.providers.ch_foen.generate_catalogue`.
- `uv run pytest` passes without network.

## 6. Files

The order below is the recommended implementation order. It keeps production runtime invisible until the metadata/generator/artifacts are validated, then wires module behavior, then registration and capability tests.

### 6A. Internal scaffolding

Files:

- `src/rivretrieve/_internal/providers/ch_foen/__init__.py`: empty marker.
- `src/rivretrieve/_internal/providers/ch_foen/metadata.py`: Pydantic models.
- `tests/test_ch_foen_metadata.py` or `tests/providers/ch_foen/test_metadata.py`: model tests.

Checkpoint:

- `uv run pytest`.
- `uv run ty check`.
- `git grep "ch_foen" src/rivretrieve` shows only package marker/metadata and no registration path.

### 6B. Fixture commit and generator skeleton

Files:

- `tests/test_data/switzerland_metadata_locations.json`: copied from `thirdparty/RivRetrieve-Python @ origin/switzerland:tests/test_data/switzerland_metadata_locations.json` using `git show` from `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python`.
- `src/rivretrieve/_internal/providers/ch_foen/generate_catalogue.py`: maintainer-only implementation. It can run offline from fixture and optionally live by explicit maintainer flag/path. It must not run at import.
- `tests/test_ch_foen_generate_catalogue.py`: generator tests.

Generator responsibilities:

- Load fixture JSON or live response.
- Validate top-level and station-level shape.
- Translate stations/products/station-products/provider info.
- Validate all generated tables against `*_SCHEMA`.
- Write artifact files when invoked as a script/module.

Checkpoint:

- Generator can be invoked manually against the fixture.
- Tests assert fixture facts: `246` stations and station `2016` named `Brugg`.
- Suite green.
- `generate_catalogue.py` is imported only by generator tests or explicit module execution.

### 6C. Run the generator and commit artifacts

Files:

- `src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json`.
- `src/rivretrieve/_internal/providers/ch_foen/catalogue/products.parquet`.
- `src/rivretrieve/_internal/providers/ch_foen/catalogue/stations.parquet`.
- `src/rivretrieve/_internal/providers/ch_foen/catalogue/station_products.parquet`.

The user prompt omitted `stations.parquet` from the file bullet but the artifact loader requires it, and M3 exit criteria require real station rows. Include it.

Checkpoint:

- `load_packaged_catalogue_artifact("src/rivretrieve/_internal/providers/ch_foen/catalogue")` succeeds.
- Artifacts validate against `STATION_CATALOG_SCHEMA`, `PRODUCT_CATALOG_SCHEMA`, `STATION_PRODUCT_CATALOG_SCHEMA`, and `PROVIDER_INFO_CATALOG_SCHEMA`.
- Suite green.

### 6D. Provider module functions

File:

- `src/rivretrieve/_internal/providers/ch_foen/module.py`.

Use `module.py`; architecture.md §9 names a provider runtime module shape but not a filename, and M2's tests-only convention uses a module object implementing `ProviderModule`. `module.py` gives lazy registration a single explicit binding point (`from rivretrieve._internal.providers.ch_foen import module as ch_foen_module`) while keeping `import rivretrieve._internal.providers.ch_foen` as a lightweight package import. Registration side effects are avoided by keeping registration in the discovery helper, not by filename choice.

Functions:

- `info()`.
- `products(...)`.
- `stations(...)`.
- `station_products(...)`.
- `row_annotation_schema()`.
- `series_annotation_schema()`.
- `observations(request, *, on_issue="warn")`.

Implementation:

- Catalogue functions delegate to `CatalogueReader` over the packaged artifact. Do not create a `ch_foen` reader.
- Artifact loading may be cached with a private zero-argument helper; it must be artifact-driven, not hardcoded station/product IDs.
- Row/series annotation schemas return empty lists.
- Observations placeholder builds empty `ObservationResult` tables and the Issue described in §4.2.

Checkpoint:

- Module is importable and unit-testable in isolation.
- Not registered yet.
- Suite green.

### 6E. Lazy registration

Files:

- Existing registration/discovery site, likely `src/rivretrieve/_internal/discovery.py`, plus a small private registration helper if needed.
- Potential new `src/rivretrieve/_internal/default_providers.py` if keeping discovery.py small is clearer.

Current M2/M3 code has a module-level `_registry` in `src/rivretrieve/_internal/registry.py`, public discovery functions in `src/rivretrieve/_internal/discovery.py`, and no production provider registration site yet. M2 step 05 established `ProviderRegistry.register(provider_id, packaged_artifact, provider_module=None)` and keyword registration via `provider_module=...`; tests import the stub module and pass it directly (M2 step 05 plan, §6 and §7).

Recommendation:

- Add a private idempotent `_ensure_default_providers_registered()` called at the start of `providers()`, `provider()`, `provider_info()`, `stations()`, `products()`, and `product_info()` in `src/rivretrieve/_internal/discovery.py`, or from a private helper those functions share.
- The helper locally imports `load_packaged_catalogue_artifact`, the `ch_foen` module via `from rivretrieve._internal.providers.ch_foen import module as ch_foen_module`, and the catalogue path only when first needed.
- It calls `_registry.register("ch_foen", artifact, provider_module=ch_foen_module)` using the M2 keyword parameter.
- It must be idempotent and must not clobber test registries.
- It must provide a private test-only disable contract for tests that need to exercise the raw singleton `_registry` without default providers. Recommendation: a private module flag in `rivretrieve._internal.discovery`, for example `_DEFAULT_PROVIDER_REGISTRATION_ENABLED = True`, checked by `_ensure_default_providers_registered()`. Tests may use `monkeypatch.setattr(rivretrieve._internal.discovery, "_DEFAULT_PROVIDER_REGISTRATION_ENABLED", False)` and then clear `_registry`. Do not expose this flag publicly.
- Update the current singleton-discovery tests deliberately:
  - `tests/test_discovery.py::test_providers_empty_registry_returns_empty_list` no longer represents public behavior after M3. Replace it with a default-provider test asserting `rr.providers() == ["ch_foen"]` after the autouse clear, or run the old empty-registry assertion only under the private disable fixture.
  - `tests/test_discovery.py::test_providers_sorted_independent_of_registration_order` must either expect `["a_provider", "ch_foen", "z_provider"]` after default registration, or disable default registration for that test and keep the old `["a_provider", "z_provider"]` assertion as a pure registry-ordering test.
  - `tests/test_discovery.py::test_provider_info_empty_registry_returns_schema_conformant_catalog_result` must be renamed/rescoped: public `rr.provider_info()` should include `ch_foen`; an empty provider-info result is now only an internal disabled-defaults test.
  - Any other exact global row-count assertions in `tests/test_discovery.py` must account for `ch_foen` rows or use the private disable fixture. Schema/SHAPE assertions remain unchanged.

Offline-import invariant:

- `import rivretrieve` must not call `_ensure_default_providers_registered()`.
- The first discovery/lookup call may import `rivretrieve._internal.providers.ch_foen.module`, but must never import `generate_catalogue.py`.

Checkpoint:

- `rr.providers()` includes `"ch_foen"`.
- Lazy-registration tests pass.
- Offline-import test passes.
- Global discovery tests pass.

### 6F. Capability declaration

Files:

- `src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json` if not already generated correctly.
- Capability-focused tests.

Set:

- `live_stations=false`.
- `live_products=false`.
- `live_station_products=false`.
- `bulk_observations="false"` for consistency with all-False capabilities.

Checkpoint:

- `source="live"` routing tests pass through M2 `CatalogueReader` without code changes.
- Full `uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`, and `uv run pytest` are green.

## 7. Open questions

Q1. Product vocabulary classification.

Recommendation: classify all six Swiss variables as canonical V1 products, as detailed in §3.4. No `ch_foen`-specific products and no dropped variables. The legacy exposes exactly discharge, stage, and water temperature daily mean/instant products (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:22-29, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:44-95), which are already in docs/product_dictionary.md.

Q2. Does `generate_catalogue.py` need `switzerland_sites.csv`?

Recommendation: no. The JSON fixture is sufficient for M3 catalogue generation because it contains the current Existenz.ch station payload with IDs, names, water body, type, Swiss coordinates, latitude, and longitude. The CSV is a cached derivative with the same normalized station facts and empty altitude/area columns (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/cached_site_data/switzerland_sites.csv:1-8). Commit the JSON fixture, not the CSV, because tests must mock the API response and generator behavior.

Q3. Annotation schemas empty in M3?

Recommendation: yes. Catalogue methods emit no row/series annotations, and the observations placeholder emits empty row and series annotation tables. Empty schemas are valid and enforce the inherited M2 always-on annotation validation rule: no annotations may be emitted until M4 declares them.

Q4. Capability flags all false?

Recommendation: yes for the three live catalogue flags and effectively false for bulk observations. Catalogue generation is maintainer-time, not runtime live support; observations are not implemented in M3.

Q5. Where does lazy registration live?

Recommendation: add an idempotent default-provider registration helper called by discovery functions in `src/rivretrieve/_internal/discovery.py`, or a helper imported by that file. There is no existing production registration site; M2 only established `_registry` and keyword `provider_module=...` registration in `src/rivretrieve/_internal/registry.py`. The lazy import target is `from rivretrieve._internal.providers.ch_foen import module as ch_foen_module`. This plugs in without breaking offline import because `src/rivretrieve/__init__.py` imports function objects only and does not execute discovery.

Q6. Where does the provider module file live?

Recommendation: `src/rivretrieve/_internal/providers/ch_foen/module.py`. Keep `__init__.py` empty. The M2 `ProviderModule` Protocol expects a module object with seven functions; it does not prescribe filename, and `module.py` makes the lazy-registration import target explicit without turning package import into provider-module import.

Q7. What runs the generator at release time?

Recommendation: `uv run python -m rivretrieve._internal.providers.ch_foen.generate_catalogue --fixture tests/test_data/switzerland_metadata_locations.json --out src/rivretrieve/_internal/providers/ch_foen/catalogue` is sufficient for M3. Document the maintainer command in step 03's provider port docs. No CLI hook or Makefile target is needed for this step.

Q8. Does M2 live-routing handle all-False capabilities?

Recommendation: yes. `CatalogueReader` reads `ProviderInfo.from_row(self.artifact.provider_info)`, checks the relevant `live_*` flag, and when false returns an empty typed table with `LiveCatalogueUnsupportedIssue` through `apply_on_issue`. No code change is needed for `ch_foen`.

Q9. T117/T119/T120 row-count expectations.

Recommendation:

- T117: no update.
- T119: no update.
- T120: no public-surface update. Do not add `ChFoen*` names to T120 as a substitute for real leak testing; they are not imported into `rivretrieve` unless someone adds an explicit re-export.
- Discovery tests that assert global row counts over `_registry` after discovery calls must account for default `ch_foen` registration. Tests built around fresh `ProviderRegistry` remain unchanged. SHAPE assertions using `*_SCHEMA.polars_schema` remain invariant.

Q10. Token handling for M3 step 02.

Recommendation: no token-bearing code in target runtime source, generator tests, or artifacts. M3 is catalogue-only and does not need the Influx token.

Q11. Does ProviderInfo.metadata need ch_foen-specific content?

Recommendation: yes, minimal non-secret content: source endpoint, legacy citation marker, generator input type, and fixture/source metadata URLs. Do not put station/product facts there; those belong in station/product metadata rows.

Q12. Token status upstream.

Current legacy `origin/switzerland` has `INFLUX_TOKEN` as a literal class attribute (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:40) and uses it in the Authorization header for observation downloads (thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:197-203). The commit message supplied by the orchestrator says the token is intentionally public. Document this as M4 background in step 03's `docs/provider_ports/ch_foen.md`, but do not relax M3 step 02: no token is carried forward because catalogue generation uses `METADATA_URL`, not the Influx observation API.

## 8. Deferrals

- Observation retrieval -> M4. M3 returns only the placeholder `ObservationResult`.
- Top-level `rr.observations(...)` -> M4.
- `rr.map_stations()` -> M5.
- Full `docs/provider_ports/ch_foen.md` content -> step 03. M3 step 02 may create only a stub if needed by tests or docs layout.
- Negative-control sweep extension beyond what step 02 needs to stay green -> step 03.
- M3 closeout `REPORT.md` -> step 03.
- Annotation IDs not yet emitted by `ch_foen` -> M4. M3 schemas remain empty.
- Token handling resolution -> M4. M3 records upstream token status only as background.
- Product dictionary expansion -> deferred unless coordinator authorizes a D6-style discovery; not needed for the six Swiss variables.

## 9. Stopping conditions for the executor

- Stop if fixture fields and architecture.md §7/§9 force a choice between common schema validity and source fidelity.
- Stop if any Swiss variable cannot be mapped cleanly to canonical V1 products without changing docs/product_dictionary.md.
- Stop if lazy registration requires importing `rivretrieve._internal.providers` or `rivretrieve._internal.providers.ch_foen.*` during `import rivretrieve`.
- Stop if satisfying lazy registration requires changing the M2 `ProviderRegistry.register(..., provider_module=...)` mechanism.
- Stop if `_ProviderHandle.observations` must be changed to support the placeholder. The M2 module-check-first dispatch should already support it.
- Stop if the placeholder can only be implemented by raising `NotImplementedError`, `AttributeError`, `ObservationsUnavailableError`, or `IssuePolicyError`.
- Stop if literal caller-policy `apply_on_issue` is required for the placeholder issue; current M2 semantics would raise under `on_issue="raise"` and contradict the step requirement.
- Stop if generated artifacts need hardcoded station/product IDs in runtime provider code.
- Stop if `source="live"` unsupported routing needs a `CatalogueReader` change.
- Stop if T117/T119/T120 SHAPE or public-surface invariants cannot be preserved.
- Stop if any checkpoint in §6 cannot keep `uv run pytest` green without network.
- Stop if legacy citations cannot be verified from `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python` via `git show origin/switzerland:...`.
