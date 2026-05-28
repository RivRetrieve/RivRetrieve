# RivRetrieve Architecture

This document is the living architecture contract for the provider-based RivRetrieve redesign. It crystallizes the proposal in [docs/design/provider-redesign.md](docs/design/provider-redesign.md) into decisions that implementation agents can plan against.

This is not user documentation and it is not a provider-porting rulebook. It defines the shared harness: provider discovery, provider handles, catalogue artifacts, catalogue schemas, request/result types, provenance, issues, annotations, errors, and maintainer catalogue generation.

Future changes should come from implementation or provider-port experience. Keep provider-specific complexity inside providers. Promote a concept into the shared harness only when concrete porting pain shows that the harness needs to own it.

## 0. Document Roles and Change Process

The design document [docs/design/provider-redesign.md](docs/design/provider-redesign.md) is the upstream proposal and rationale. This document is the current implementation contract. It may be more specific than the proposal when open questions have been resolved.

Supporting documents have separate responsibilities:

- `architecture.md`: shared living harness and architecture contract.
- `docs/design/provider-redesign.md`: source proposal and rationale.
- `docs/product_dictionary.md`: canonical product vocabulary.
- `docs/provider_ports/<provider_id>.md`: provider-specific port notes and pain points.

Provider ports must follow this architecture unless concrete provider evidence shows the contract is wrong or incomplete. Provider-local pain belongs in the provider port notes. Shared harness, type, validation, provenance, issue-policy, or public-behavior pain may update this document. Product vocabulary changes belong in the product dictionary.

Do not add speculative shared abstractions. Add shared harness concepts only when required by the source proposal, a resolved architecture decision, or concrete provider-port evidence.

## 1. Architectural Goals

RivRetrieve moves from country fetcher classes to provider-based data access.

The old abstraction was one class per country, such as `USAFetcher` or `CanadaFetcher`. The new abstraction is one provider per data source/API, such as `usgs_nwis`, `uk_ea`, `uk_nrfa`, or `ch_foen`. A provider is the boundary where identifiers, metadata conventions, product availability, response formats, units, quality flags, and provider-specific quirks live.

The harness standardizes:

- how providers are discovered,
- how station/product catalogues are exposed,
- how observation requests are shaped,
- how observation results are returned,
- how provider-native metadata is preserved,
- how issues and provenance are reported.

The harness does not standardize:

- provider API internals,
- provider quality-code meanings,
- provider-native metadata fields beyond a small common core,
- cross-provider station deduplication,
- provider-specific rules that have not yet proven common.

V1 is river-gauge scalar time series only. Initial canonical observed properties are `discharge`, `stage`, and `water_temperature`. Rating curves, cross sections, profiles, gridded data, catchment rainfall, precipitation, meteorological variables, and other structured or non-river products are out of scope for the V1 canonical product vocabulary.

## 2. Provider Identity

Provider ID is the public and internal identifier for a data source.

Decision:

- Provider IDs use `snake_case`.
- Provider IDs identify a source or agency rather than a country when possible.
- The provider ID should match the provider package/module name.
- Users should not need a second spelling such as `usgs-nwis`.

Examples:

```text
usgs_nwis
uk_ea
uk_nrfa
ch_foen
```

Station IDs remain provider-native. A user calling `rr.provider("usgs_nwis").observations(...)` passes USGS station IDs, not RivRetrieve-prefixed station IDs.

Global tables use `(provider_id, station_id)` as the station key. `station_id` alone is not globally unique.

## 3. Public API Surface

The public API starts with discovery:

```python
import pandas as pd
import rivretrieve as rr

rr.providers()
rr.provider_info()
rr.stations()
rr.products()
rr.product_info()
rr.map_stations()
```

Global discovery functions combine packaged catalogues from installed providers. They are offline and do not call provider APIs. V1 does not include a global live discovery mode that calls every provider.

`rr.map_stations()` renders the same packaged station catalogue as a map. It is a view over catalogue data, not a separate metadata source.

Provider-specific access starts with a provider handle:

```python
usgs = rr.provider("usgs_nwis")

usgs.info()
usgs.products()
usgs.stations()
usgs.station_products()
```

The object returned by `rr.provider()` is typed against a public `typing.Protocol`. The protocol is the public interface for IDE autocomplete and type checking. Provider implementations may remain function-based internally.

Observation retrieval uses one request shape:

```python
result = usgs.observations(
    stations="07374000",
    products="discharge_daily_mean",
    start=pd.Timestamp("2020-01-01"),
    end=pd.Timestamp("2020-12-31"),
)
```

Bulk retrieval uses the same method:

```python
result = usgs.observations(
    stations=["07374000", "02471078"],
    products=["discharge_daily_mean", "stage_instantaneous"],
    start=pd.Timestamp("2020-01-01"),
    end=pd.Timestamp("2020-12-31"),
)
```

Public observation calls are keyword-only. `stations` and `products` accept a single string or a sequence; the harness normalizes them to lists.

`start` and `end` are required in V1. Provider defaults vary too much, and silent defaults can create unexpectedly large requests. Public methods may accept timestamp-like inputs, including ISO strings, but internal `ObservationRequest` objects contain typed temporal values.

The top-level convenience function is only a wrapper:

```python
rr.observations(
    provider="usgs_nwis",
    stations="07374000",
    products="discharge_daily_mean",
    start=pd.Timestamp("2020-01-01"),
    end=pd.Timestamp("2020-12-31"),
)
```

It must delegate to:

```python
rr.provider("usgs_nwis").observations(...)
```

and must not duplicate provider lookup, validation, or retrieval logic.

## 4. Packaged Catalogue Architecture

The packaged catalogue is the default metadata source and the foundation of discovery.

Decision:

- RivRetrieve ships provider catalogue artifacts with the package.
- Normal discovery reads those artifacts.
- Normal discovery must work offline.
- Packaged catalogue reads must not call provider APIs.
- Packaged catalogues are maintainer-owned release artifacts.
- Users do not update packaged catalogues during normal use.

The packaged catalogue tier includes:

- provider metadata,
- product catalogues,
- station catalogues,
- known station-product availability.

The package should be useful immediately after installation:

```python
rr.provider_info()
rr.stations()
rr.products()
```

These calls describe the catalogue snapshot installed with RivRetrieve. They are not live queries against every provider.

Catalogue refresh is a release-time maintainer workflow. Maintainers regenerate provider catalogue artifacts, validate them, commit/package them, and publish a new release.

For V1, catalogue artifacts are packaged inside the wheel. If actual catalogue sizes prove too large, a later architecture revision may move them to release assets with checksum verification and local caching.

## 5. Live Catalogue Queries

The provider redesign proposal made end-user live catalogue refresh out of scope. We keep that decision: users do not refresh or mutate the packaged catalogue.

However, reviewer feedback and the grilling session added a separate capability: users may explicitly ask a provider for live/source catalogue metadata through the same logical catalogue interfaces.

Decision:

- Catalogue methods default to `source="packaged"`.
- `source="packaged"` reads release artifacts and is offline.
- `source="live"` explicitly calls the provider/source when supported.
- Live catalogue results never mutate packaged catalogues.
- Unsupported live catalogue calls return a normal result shape with a warning issue.

Examples:

```python
provider.stations()                       # packaged
provider.stations(source="packaged")       # packaged
provider.stations(source="live")           # provider/source query, if supported
```

The same source model applies to:

```python
provider.products(...)
provider.station_products(...)
```

This keeps packaged and live catalogue data conceptually aligned while preserving the offline catalogue invariant.

Live catalogue queries are provider-level only in V1. Top-level global discovery functions such as `rr.stations()` and `rr.products()` remain packaged/offline aggregations.

## 6. Catalogue Result Shape

All catalogue calls return one result shape:

```python
CatalogResult(
    data=...,
    provenance=CatalogProvenance(...),
    issues=[...],
)
```

`data` is the requested catalogue table. Public and internal harness tables use Polars as the canonical dataframe engine. Pandas export is a convenience, not the internal contract.

`provenance` records where the catalogue came from:

- for packaged catalogues: provider ID, RivRetrieve version, catalogue version, artifact ID/path, artifact hash, generated timestamp when known;
- for live catalogues: provider ID, retrieval timestamp, endpoints/calls made, query parameters, provider response version when available.

`issues` records structured diagnostics such as unsupported live metadata, partial live responses, validation warnings, or stale/ambiguous source information.

Public catalogue methods return `CatalogResult` directly. They do not hide provenance or issues behind a bare table return.

## 7. Catalogue Record Model

Catalogue records use a small common schema plus provider-owned metadata.

The common schema exists for cross-provider discovery and request validation. It must stay small. Provider-specific metadata must not be forced into hundreds of sparse common columns.

Provider-specific metadata is preserved in a `metadata` field.

Decision:

- Common fields are RivRetrieve's normalized view.
- `metadata` preserves the provider/source record as faithfully as practical.
- `metadata` includes original values even when they were normalized into common columns.
- Generic harness code treats `metadata` as opaque.
- Provider metadata is represented by provider-owned Pydantic models internally and as plain dictionaries at public table boundaries.

Provider metadata models are separate by catalogue kind:

```python
class ChFoenStationMetadata(BaseModel): ...
class ChFoenProductMetadata(BaseModel): ...
class ChFoenStationProductMetadata(BaseModel): ...
```

These models should allow extra fields so source metadata is not lost while stable fields can still be validated and documented. Generic harness code treats public `metadata` dictionary values as opaque.

Packaged catalogue artifacts use Parquet as the on-disk format. Inside Parquet, the `metadata` column holds JSON-encoded strings in a `pl.Utf8` column, not nested struct types. This preserves round-trip fidelity through Parquet readers that do not support arbitrary Python objects and lets generic harness code remain schema-agnostic. Encoding and decoding happen at the catalogue I/O boundary; in-memory `metadata` values are still plain Python dictionaries as described above.

### Station Catalogue

Common station fields:

```text
provider_id
station_id
name
latitude
longitude
country
elevation_m
drainage_area_km2
start_date
end_date
metadata
```

The unique station key in global tables is `(provider_id, station_id)`.

Physical gauges may appear in multiple provider catalogues. V1 lists those records separately. Cross-provider station crosswalks or deduplication are out of scope.

### Product Catalogue

A product is the thing a user asks RivRetrieve to retrieve from a station. It is more specific than a variable. `discharge` is a variable; `discharge_daily_mean` is a product.

Common product fields:

```text
provider_id
product_id
observed_property
frequency
statistic
period_type
period_anchor
unit
native_id
derived
derivation_method
metadata
```

`statistic` describes the product that exists in the catalogue. It is not an instruction for RivRetrieve to compute that statistic.

`native_id` records the provider parameter, variable, measure, or time-series identifier when useful.

Canonical product IDs come from [docs/product_dictionary.md](docs/product_dictionary.md). Providers may use canonical IDs only when their native product semantics match closely enough. If they do not match, the provider may expose a provider-specific product ID and explain it in product metadata.

### Station-Product Catalogue

Station-product availability is explicit.

Common station-product fields:

```text
provider_id
station_id
product_id
availability
availability_reason
start_date
end_date
last_catalogue_check
metadata
```

Allowed availability values:

```text
available
unavailable
unknown
```

Providers should return known available records. They may return explicit unavailable records when the source provides that information. If availability cannot be determined, providers return `unknown` records with `availability_reason`.

Providers are not expected to materialize every possible unavailable station-product pair.

## 8. Product Dictionary

The product dictionary is a separate living document: [docs/product_dictionary.md](docs/product_dictionary.md).

The dictionary defines canonical product IDs using structured fields:

```text
product_id
observed_property
frequency
statistic
period_type
period_anchor
unit
derived
derivation_method
description
notes
```

Rules:

- Product IDs are opaque labels.
- Code must not parse product IDs.
- Providers use canonical IDs only when native semantics match closely enough.
- Provider-native product identifiers stay in `native_id` and provider metadata.
- Provider ports may propose dictionary additions when real products do not fit.
- V1 does not include RivRetrieve-derived products. Product filters select catalogue products; they are not computation requests.

The dictionary is intentionally separate from this architecture because it will evolve more frequently.

## 9. Provider Module Contract

Each provider lives in its own Python subpackage:

```text
src/rivretrieve/providers/usgs_nwis/
    __init__.py
    catalogue/
        provider.json
        products.parquet
        stations.parquet
        station_products.parquet
    generate_catalogue.py
    metadata.py
```

Provider runtime modules expose a flat function-based contract. There are no public provider classes and no inheritance hierarchy at the provider implementation boundary.

The provider may use private classes internally, but the harness sees functions:

```python
def info() -> ProviderInfo: ...

def products(
    *,
    source: CatalogSource = "packaged",
    observed_property: str | None = None,
    frequency: str | None = None,
    statistic: str | None = None,
    on_issue: OnIssue = "warn",
) -> CatalogResult[ProductCatalog]: ...

def stations(
    *,
    source: CatalogSource = "packaged",
    on_issue: OnIssue = "warn",
) -> CatalogResult[StationCatalog]: ...

def station_products(
    stations: Sequence[str] | None = None,
    *,
    source: CatalogSource = "packaged",
    on_issue: OnIssue = "warn",
) -> CatalogResult[StationProductCatalog]: ...

def row_annotation_schema() -> list[AnnotationSchema]: ...
def series_annotation_schema() -> list[AnnotationSchema]: ...
def observations(request: ObservationRequest, *, on_issue: OnIssue = "warn") -> ObservationResult: ...
```

The public provider handle adapts user-friendly keyword arguments into typed internal requests. Provider modules receive normalized objects, not loose public input.

The public provider handle is typed by a `typing.Protocol` that exposes the same public catalogue and observation behavior. `source` and `on_issue` are part of the public catalogue method contract.

Provider info is offline in V1. `rr.provider_info()` and `provider.info()` report installed provider metadata and declared capabilities from packaged artifacts/code; they do not call provider APIs. The provider info record carries identifying fields (`provider_id`, a human-readable `name`, and `catalogue_version` for the packaged snapshot in use) and declared capabilities (the three catalogue live-support flags `live_stations`, `live_products`, `live_station_products`, plus a descriptive `bulk_observations` capability). Capability flags help planning and UI behavior, but runtime calls still report failures or unsupported operations through structured issues.

## 10. Maintainer Catalogue Generation

`generate_catalogue.py` is maintainer-only code.

It may:

- call provider APIs,
- scrape source pages,
- download files,
- use credentials,
- perform slow provider-specific work,
- normalize units for common schema fields,
- preserve provider-native records in metadata.

It must not be imported during normal package use.

Generated artifacts must satisfy runtime catalogue schemas before release. Provider catalogues should normally be regenerated when preparing a release, with documented exceptions when a release intentionally does not refresh catalogues.

## 11. Observation Request

The internal request object is normalized by the public provider handle.

Core fields:

```text
provider_id
stations
products
start
end
```

`stations` and `products` are normalized sequences.

`start` and `end` are typed temporal values. They are required in V1.

The request shape is intentionally small: station IDs, product IDs, time range, and policy options. Product filters are catalogue queries; they are not instructions for RivRetrieve to compute statistics during retrieval.

The public API always accepts a single station/product ID or a sequence of IDs. RivRetrieve owns decomposition, batching, safe concurrency, retries, and aggregation where needed so users can rely on one ergonomic bulk request. Exact execution strategy is internal and provider-aware. V1 does not expose a public backend-policy abstraction.

## 12. Observation Result

The canonical observation table is long-form:

```text
time
station_id
product_id
value
```

Provider-scoped results do not need `provider_id` in every row because the provider is known from the handle/result. Any combined cross-provider observation table must include `provider_id`.

Observation result shape:

```python
ObservationResult(
    data=ObservationTable,
    row_annotations=AnnotationTable,
    series_annotations=AnnotationTable,
    provenance=ObservationProvenance,
    issues=list[Issue],
    raw=RawPayload | None,
)
```

`data` is normalized long-form observation data.

`row_annotations` are provider-native metadata attached to individual observations, such as quality flags. They are long-form:

```text
time
station_id
product_id
annotation
value
```

`series_annotations` are metadata attached to a station-product series for a request:

```text
station_id
product_id
annotation
value
```

Examples include native unit actually returned, returned time range, resolved timezone, native time-series ID, or provider endpoint when it applies to the series. Station attributes remain in the station catalogue.

`provenance` is the receipt for the retrieval event: request parameters, retrieval timestamps, RivRetrieve version, catalogue version, and provider calls made.

`issues` are structured warnings or anomalies.

`raw` preserves original provider payloads when practical. It may be `None`, may differ by provider, and is not the cross-provider interface. Complete auditability must come from `data`, annotations, provenance, and issues rather than from `raw`.

Observation methods return `ObservationResult` directly. Pandas and wide-form exports are convenience methods, not the primary result shape. The minimum export contract is:

- `result.data` is the canonical Polars long table.
- `result.to_polars()` returns the canonical long table.
- `result.to_pandas()` returns the canonical long table as pandas.

Wide-form export is expected later, but its exact index and column semantics are left to implementation after the canonical result model exists.

## 13. Annotation Schemas

Providers declare annotation schemas up front:

```python
def row_annotation_schema() -> list[AnnotationSchema]: ...
def series_annotation_schema() -> list[AnnotationSchema]: ...
```

Annotation schema fields:

```text
annotation_id
description
value_type
allowed_values
source_field
```

Observation results may only use annotation names declared by the provider schema. The harness validates annotation names in tests or debug validation.

Quality annotations remain provider-native. RivRetrieve does not harmonize quality-code semantics across agencies in V1.

## 14. Provenance

Provenance is common retrieval/build bookkeeping. It is separate from provider scientific metadata and annotations.

Catalogue provenance records how a catalogue result was obtained:

- packaged artifact identity, version, and integrity information when available for packaged catalogue calls,
- retrieval timestamp and endpoint/call details for live catalogue calls.

Observation provenance records how an observation result was obtained:

- provider ID,
- request parameters,
- requested/retrieved timestamps,
- RivRetrieve version,
- catalogue version,
- provider calls made,
- endpoint/query/status metadata where available.

Secrets must not be stored in provenance.

Keep provenance sufficient for audit and debugging without over-specifying nested provenance structures before provider evidence requires them. Per-series or per-row interpretation facts belong in `series_annotations` or `row_annotations`.

## 15. Issues and Error Policy

Catalogue and observation results share one structured `Issue` type.

Issue severities:

```text
info
warning
error
```

Recoverable provider/data problems return partial results with issues by default.

The common policy knob is:

```text
on_issue="warn"    return result, emit Python warnings for warning/error issues
on_issue="raise"   raise on warning/error issues
on_issue="ignore"  return result without warning, but keep issues
```

Informational issues do not raise by default.

Fatal contract failures raise immediately regardless of `on_issue`, including unknown provider IDs, invalid catalogue source values, corrupt packaged catalogue artifacts, and provider implementation schema violations.

`on_issue` is the harness-level policy. Missing data is represented as structured issues rather than requiring a separate `on_missing` policy.

## 16. Time and Units

Product time semantics are explicit in product metadata:

```text
frequency:      irregular | 5min | 10min | 15min | 30min | hourly | daily | monthly | annual | provider_defined | unknown
statistic:      instantaneous | mean | sum | min | max | provider_defined | unknown
period_type:    instant | interval
period_anchor:  instant | start | end | midpoint | provider_defined | unknown
```

The observation table has one `time` column, not `time_start` and `time_end`. Interval semantics must be read from product and response metadata.

RivRetrieve preserves provider-native timestamps by default. It should only shift or reinterpret timestamps when the provider-specific convention is documented and the conversion is recorded.

Timezone facts belong in series annotations. If RivRetrieve infers, changes, or finds a mismatch in timezone interpretation, the result should also include a structured issue.

Units are standardized where fields are part of the common schema. Native units actually returned during a request belong in response metadata, especially when conversion occurred.

## 17. Multi-API Providers and Stitching

Some providers expose different APIs for recent/realtime and historical data. The public API remains one observation call.

For V1:

- users do not choose provider backends through the common API,
- providers split/fetch/stitch internally,
- provenance records every source/API call,
- row annotations record per-row source, quality, or alternative-value facts when relevant,
- issues record gaps, overlaps, conflicting values, failed source calls, or ambiguous transitions.

If overlapping source APIs return conflicting values for the same timestamp, the provider must not discard the conflict silently. The canonical `data.value` contains the provider's declared preferred value for that product/source situation, alternatives are preserved in row annotations, and a structured warning issue is emitted.

The harness does not define a shared backend-policy type in V1. If repeated provider ports show that backend policy needs to become a harness concept, update this architecture from those pain points.

## 18. Reference Provider and Feedback Loop

The first reference provider is `ch_foen`.

`ch_foen` is a full provider port used to validate the harness, document pain points, and provide a working example. It is not a universal template for other providers.

Port pain points are captured in [docs/provider_ports/ch_foen.md](docs/provider_ports/ch_foen.md). If a pain point exposes a harness design issue, the porter may update this architecture document directly.

Implement the harness and one full `ch_foen` port first. Capture the port evidence, update this architecture for shared harness implications, and then proceed with broader provider ports. Each provider port should maintain a lightweight notes file at `docs/provider_ports/<provider_id>.md`, even when the port is straightforward.

## 19. Deferred Design Questions

These questions are intentionally deferred and should not be silently decided by implementation agents:

- What wide-form pandas export helpers are needed beyond the minimum long-form `to_pandas()` contract?
- When, if ever, should RivRetrieve-owned derived products be introduced?
- When, if ever, should the canonical product vocabulary expand beyond river-gauge variables?

Provider ports may add evidence to these questions. Architecture changes should be made explicitly.
