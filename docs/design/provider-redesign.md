# RivRetrieve redesign proposal

## 1. Motivation

The current Python package is built around one class per country. For example, there is a `USAFetcher`, a `CanadaFetcher`, and so on. This was a reasonable starting point, especially because the original R package had country-level functions. It is now becoming the wrong abstraction. The real boundary is not the country, it is the data source and its API. USGS NWIS, HYDAT, UK Environment Agency, NRFA, BAFU, and other sources all have their own identifiers, metadata conventions, units, availability rules, and response formats.

I propose redesigning RivRetrieve around **providers**. A provider is a named data source that RivRetrieve knows how to query. It has a catalogue of stations and products, and it has provider-specific runtime code for downloading observations. This keeps the provider-specific mess in one place, while giving users one consistent way to discover and request data.

The goal is not to pretend that all hydrological APIs are the same. They are not. The goal is to define clear boundaries: what RivRetrieve standardises, what stays provider-native, and where users can inspect the original source information when needed.

This proposal is forward-looking. It is not a migration guide and it is not a release plan. I am trying to define the shape of the redesigned package so collaborators can judge whether the data model and abstractions are right for hydrological workflows.

## 2. Core principles

The provider is the main boundary. Instead of asking users to instantiate a country class, I want users to ask for a provider by name:

```python
usgs = rr.provider("usgs_nwis")
```

That provider exposes stations, products, availability, and observations. Internally, each provider can do whatever it needs to do to talk to its source API. Externally, all providers implement the same small interface, which is the internal provider contract described in Section 5.

Catalogue metadata and response metadata are separate. I think of this as: **the catalogue is the contract, the response metadata is the receipt**. The catalogue says what RivRetrieve believes is available when the package is released: provider info, stations, products, and known station-product availability. The response metadata says what actually happened during one request: the URL used, the native unit returned, the retrieval timestamp, the returned time range, and any warnings or anomalies.

This distinction matters because catalogues can be stale or incomplete. A provider may change a station record after a RivRetrieve release. A request may return a native unit that differs from what was expected. In those cases, the response metadata should describe the actual result, and it should win for that specific request.

A **Product** is the thing a user asks RivRetrieve to retrieve from a station. It is more specific than a variable. For example, `discharge` is a variable, but `discharge_daily_mean` is a product. It says what is measured, how often it is represented, what statistic it contains, and what unit RivRetrieve returns.

Product IDs are intentionally treated as opaque labels. A product may be called `discharge_daily_mean`, and humans can read that name, but code should not split the string to infer its meaning. The structured `Product` metadata is the source of truth. That means programmatic logic should inspect fields such as `observed_property`, `frequency`, `statistic`, `period_anchor`, and `unit`, not parse the product ID.

This avoids a common failure mode. If product IDs become mini-grammars, then every exception creates parsing bugs. The ID is for users. The metadata is for code.

Canonical product IDs are used where a provider product fits the RivRetrieve vocabulary. For example, many providers can honestly expose a `discharge_daily_mean` product. But a shared canonical ID does not mean the measurement methods, QC procedures, rating-curve handling, or publication status are identical. It only means the product matches the shared schema fields. For cross-provider analysis, users should inspect provider documentation and the response metadata.

Provider IDs use `snake_case` everywhere. I do not want a public ID like `usgs-nwis` and an internal module called `usgs_nwis`. That adds unnecessary translation in notebooks, scripts, and configuration files. The public provider ID and Python package name should match.

V1 is scalar time series only. The current package retrieves scalar observations such as discharge, stage, water temperature, and some precipitation products over time. The proposed v1 data model keeps that general shape. Rating curves, profiles, cross sections, gridded data, and other structured products are out of scope for v1.

## 3. API surface

The main user workflow starts with provider discovery.

```python
import rivretrieve as rr
import pandas as pd

rr.providers()
rr.provider_info()
```

`rr.providers()` returns just the installed provider IDs. `rr.provider_info()` returns richer information for all installed providers, such as provider name, citation, catalogue version, station count, and available products. These values describe the catalogue snapshot installed with RivRetrieve. They are not a live query against the provider. A new user should be able to run `rr.provider_info()` and understand what data sources RivRetrieve currently includes.

A user then gets a provider handle.

```python
usgs = rr.provider("usgs_nwis")

usgs.products()
usgs.stations()
usgs.station_products()
usgs.info()
```

`usgs.products()` tells the user what products this provider exposes. `usgs.stations()` returns the station catalogue for this provider. `usgs.station_products()` describes which products are known to be available at which stations. `usgs.info()` returns provider-specific metadata for this one provider. If station-product availability is unknown, that uncertainty appears explicitly in the returned data rather than being hidden.

The object returned by `rr.provider()` should be typed against a public `typing.Protocol`. This gives static analysis tools and IDEs a stable interface for autocomplete and type checking, while still allowing provider implementations to stay function-based internally.

Observation retrieval accepts one or many stations and one or many products.

```python
result = usgs.observations(
    stations="07374000",
    products="discharge_daily_mean",
    start=pd.Timestamp("2020-01-01"),
    end=pd.Timestamp("2020-12-31"),
)
```

The same method also supports bulk requests.

```python
result = usgs.observations(
    stations=["07374000", "02471078"],
    products=["discharge_daily_mean", "stage_instantaneous"],
    start=pd.Timestamp("2020-01-01"),
    end=pd.Timestamp("2020-12-31"),
    on_missing="warn",
)
```

The parameter names are plural because the method accepts either a single string or a list. Internally, RivRetrieve normalises both forms to lists. This gives a simple single-station workflow without creating a separate bulk API.

The `stations` argument uses the station IDs from the selected provider. The provider namespace is already established by `usgs.observations(...)`, or by the `provider` argument in the top-level wrapper, so users should not need to prepend RivRetrieve's provider ID to station IDs they already know from the source.

The public `observations()` API should be keyword-only. It accepts timestamp-like inputs for `start` and `end`, including ISO date strings as a convenience, but it normalises them at the API boundary. The internal `ObservationRequest` passed to providers should contain typed temporal values such as `pd.Timestamp`, and duration or resolution fields should use typed objects such as `pd.Timedelta`.

Observation requests require explicit `start` and `end` dates in v1. RivRetrieve should not silently fall back to provider defaults, because those defaults vary and can produce unexpectedly large requests.

Products can also be discovered by structured product fields. These fields are filters over the provider catalogue. They do not mean that RivRetrieve computes the statistic during the request.

```python
products = usgs.products(
    observed_property="discharge",
    frequency="daily",
    statistic="mean",
)

result = usgs.observations(
    stations="07374000",
    products=products["id"],
    start=pd.Timestamp("2020-01-01"),
    end=pd.Timestamp("2020-12-31"),
)
```

Retrieval should have one request shape: station IDs, product IDs, time range, and policy options. Product IDs remain opaque labels. Users and code should inspect catalogue metadata for product semantics rather than parsing product ID strings.

There is also a top-level convenience function.

```python
result = rr.observations(
    provider="usgs_nwis",
    stations="07374000",
    products="discharge_daily_mean",
    start=pd.Timestamp("2020-01-01"),
    end=pd.Timestamp("2020-12-31"),
)
```

This is only a thin wrapper around:

```python
rr.provider("usgs_nwis").observations(...)
```

I want this convenience because one-line scripts are common, but I do not want duplicate logic.

Global discovery functions work across providers.

```python
rr.stations()
rr.products()
rr.product_info()
rr.map_stations()
```

By "global" I mean that these functions combine the packaged catalogues from all providers. An unfiltered global call such as `rr.stations()` returns the common station table for every provider included in RivRetrieve. `rr.product_info()` should return product metadata with the provider included, because the same product ID may appear for more than one provider. Later, optional filters can make this easier to use:

```python
rr.stations(providers=["usgs_nwis", "bafu"])
rr.stations(country="CH")
rr.stations(bbox=(5.9, 45.8, 10.5, 47.9))
```

The unfiltered calls are the baseline because they make discovery possible without knowing provider-specific details in advance. `rr.map_stations()` should render the same offline station catalogue as an interactive map, probably using `leafmap`. It is a discovery tool, not a separate metadata source. For v1, the map should support the same basic filters as `rr.stations()`: providers, country, and bounding box.

## 4. Data model

The canonical observation table is long-form:

```text
time | station_id | product_id | value
```

Long-form means there is one row per observation. If a station has both discharge and stage at the same timestamp, those are two rows with different `product_id` values. This is different from wide-form data, where each product gets its own column, for example `time | discharge_daily_mean | stage_instantaneous`.

I propose long-form internally because it handles multiple products and multiple stations cleanly. It also works when products have different timestamps, such as daily discharge and irregular instantaneous stage. Wide-form is often convenient for pandas users, so export methods can provide it, but the internal model should be long-form.

Observation results from a provider handle are scoped to one provider, so `station_id` is unambiguous within that result. Any table that combines observations or annotations across providers should include `provider_id` and use `(provider_id, station_id)` as the station key.

The core product metadata is:

```text
id
observed_property
frequency
statistic
period_type
period_anchor
unit
native_id
derived
derivation_method
```

For example:

```python
Product(
    id="discharge_daily_mean",
    observed_property="discharge",
    frequency="daily",
    statistic="mean",
    period_type="interval",
    period_anchor="provider_defined",
    unit="m3/s",
    native_id="00060:dv:mean",
    derived=False,
    derivation_method=None,
)
```

Here, `id` is the user-facing product label. `native_id` records the provider-specific identifier or parameter code. The other fields define the actual semantics RivRetrieve relies on. `statistic` describes the product that exists in the catalogue. It is not an instruction for RivRetrieve to compute that statistic.

An instantaneous product might look like this:

```python
Product(
    id="stage_instantaneous",
    observed_property="stage",
    frequency="irregular",
    statistic="instantaneous",
    period_type="instant",
    period_anchor="instant",
    unit="m",
    native_id="00065:iv",
    derived=False,
    derivation_method=None,
)
```

The station catalogue also has two levels. The global station table contains only fields that can reasonably be shared across providers:

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
```

This is the common-core schema. It is intentionally small. `station_id` is the station identifier used by the provider. It does not need to be globally unique by itself. The unique key for global tables is `(provider_id, station_id)`. If RivRetrieve later needs a deterministic single-column join key, it can derive one internally, but users should not need to type a RivRetrieve-prefixed station ID.

Provider-specific fields, such as USGS HUC codes or source-specific station status fields, should remain out of the common schema by default. A provider-level call can expose those fields explicitly:

```python
usgs.stations(include_native=True)
```

Some physical gauges will appear in multiple provider catalogues. The global table should list those records separately because they are records from different providers. Cross-provider deduplication is a separate problem and should not be silently guessed in v1.

Station-product availability also needs an explicit schema:

```text
provider_id
station_id
product_id
availability
availability_reason
start_date
end_date
last_catalogue_check
```

The allowed availability values are:

```text
available
unavailable
unknown
```

Providers should return known available records. They may return explicit unavailable records when the source provides that information. If a provider cannot determine availability, it should return unknown records with an `availability_reason`. Providers are not expected to materialise every possible unavailable station-product pair.

An observation result contains the data and the receipt for the request:

```text
result.data
result.row_annotations
result.series_annotations
result.issues
result.raw
```

`result.data` is the canonical long observation table. `row_annotations` are provider-native metadata attached to individual observations, such as quality flags. They are also stored in long form:

```text
time | station_id | product_id | annotation | value
```

Examples might be `bom.quality_code`, `bom.interpolation_type`, or `usgs.qualifier`. These remain provider-native in v1. I do not propose a shared quality-code model across agencies. Providers should document row annotations in an annotation schema.

`series_annotations` are metadata attached to a station-product series for this specific request:

```text
station_id | product_id | annotation | value
```

Examples include source URL, native unit actually returned, retrieval timestamp, provider endpoint, and actual returned time range. There is no `time` column here because these annotations describe the whole station-product series returned by the request, not individual observations. These are not station attributes. Station attributes belong in the station catalogue.

Series annotations should also be documented in an annotation schema. Annotation tables use one `value` column. The schema says what type of value to expect.

```text
annotation_id
description
value_type
allowed_values
source_field
```

`issues` are structured warnings or anomalies from the request. `raw` is the original provider payload or dataframe when it is practical to preserve it, for example when the payload is small enough and serialisable enough to keep without making the result object unwieldy. `raw` may be `None`, may differ by provider, and should not be used as the cross-provider data interface.

## 5. Provider contract

This section describes the internal contract that provider implementations must satisfy. It is not the same as the public `usgs.observations(stations=..., products=...)` API shown above. The public provider handle collects those keyword arguments, validates them, turns them into an `ObservationRequest`, and then calls the provider's internal `observations(request)` function.

Each provider lives in its own Python subpackage, meaning a directory with an `__init__.py` file. The runtime code, packaged catalogue artefacts, and catalogue generation script are co-located.

```text
src/rivretrieve/providers/usgs_nwis/
    __init__.py
    catalogue/
        provider.json
        products.parquet
        stations.parquet
        station_products.parquet
    generate_catalogue.py
```

The runtime module implements a small function-based contract. There are no provider classes and no inheritance hierarchy. I prefer this because each provider implementation stays flat and readable. A maintainer can open one provider module and see what it does without also needing to understand a base class or inherited behaviour.

```python
def info() -> ProviderInfo: ...
def products(
    *,
    observed_property: str | None = None,
    frequency: str | None = None,
    statistic: str | None = None,
) -> ProductCatalog: ...
def stations() -> StationCatalog: ...
def station_products(stations: Sequence[str] | None = None) -> list[StationProduct]: ...
def row_annotation_schema() -> list[AnnotationSchema]: ...
def series_annotation_schema() -> list[AnnotationSchema]: ...
def observations(request: ObservationRequest) -> ProviderObservationResult: ...
```

Most of these return types are names for the data structures described earlier. `ProviderInfo` is the provider-level metadata. `ProductCatalog` and `StationCatalog` are tables of products and stations. `StationProduct` records station-product availability. `ObservationRequest` is the normalised internal request, and `ProviderObservationResult` is the provider's canonical long-form data plus annotations, issues, and raw payload.

`AnnotationSchema` describes provider-native annotations that may appear in results. For example, a provider can declare that it may return `usgs.qualifier` as a row annotation, or `native_unit` as a series annotation. Exposing schemas lets users and tests know what annotations a provider may produce without having to make a data request first.

The catalogue functions read packaged files. They do not call provider APIs. This is important because metadata browsing should work offline, without credentials, network access, rate limits, or mocked HTTP calls in tests.

`station_products()` is required for every provider. If a provider does not publish station-product availability, the function still returns records, but with `availability="unknown"` and a reason. This keeps the interface uniform and makes uncertainty explicit in the data.

`generate_catalogue.py` is maintainer-only code. It can call APIs, scrape files, read PDFs, or do slow provider-specific work. It is not imported during normal RivRetrieve use. Provider catalogues should normally be regenerated when preparing a release, with documented exceptions when a release intentionally does not refresh catalogues.

## 6. Discovery and metadata

The two-tier metadata model drives much of this design.

The catalogue tier is shipped with the library. This means that when a user installs RivRetrieve, they also install the known provider list, product catalogues, station catalogues, and any available station-product manifests. A call like `rr.stations()` reads packaged files. It does not ask every provider API for its latest station list.

The response tier is created only when a user requests observations. It records what happened for that request. This is where dynamic facts belong: the exact endpoint used, the response timestamp, the native unit returned, the time range actually received, and any provider-side warning signs.

I propose this split because live catalogue discovery is fragile. It would make simple browsing depend on network access and provider uptime. It would also make tests slower and less reliable. The downside is that catalogue metadata can lag behind provider reality. If a new station is added by an agency, it will not appear in RivRetrieve until a new catalogue artefact is generated and shipped in a release. I think that is acceptable for v1, as long as it is documented clearly.

End-user live catalogue refresh is out of scope for v1. Catalogue refresh should be a release-time maintainer workflow, not something that happens during normal discovery.

For v1, I propose packaging catalogue artefacts inside the wheel. If the catalogues become too large, a later design can move them to downloadable release assets with checksum verification and local caching.

## 7. Time and units

Product time semantics are explicit in metadata. V1 uses these fields:

```text
frequency:      irregular | 5min | 10min | 15min | 30min | hourly | daily | monthly | annual | provider_defined | unknown
statistic:      instantaneous | mean | sum | min | max | provider_defined | unknown
period_type:    instant | interval | unknown
period_anchor:  instant | start | end | midpoint | provider_defined | unknown
```

`period_type="unknown"` records that source temporal support is unestablished. It corresponds to `UnknownTemporalSupport` in the shared observation engine and prevents a provider from guessing instant or interval support.

The statistic is interpreted over the frequency interval. For example, `frequency="daily"` and `statistic="mean"` means a daily mean. `frequency="monthly"` and `statistic="sum"` means a monthly sum. In v1, statistics other than `instantaneous` should not normally be combined with `frequency="irregular"`, because the interval is not defined.

The observation table has one `time` column, not separate `time_start` and `time_end` columns. This is a simplification. It keeps the data easy to use in pandas, but it means interval semantics must be read from product and response metadata.

RivRetrieve should preserve provider-native timestamps by default. It should only shift or reinterpret timestamps when the provider-specific convention is documented and the conversion is recorded in metadata. This is especially important for interval products such as daily and monthly values, where the timestamp may represent the start of the period, the end of the period, or a provider-specific convention.

Timestamps should be timezone-aware when possible. If a provider gives UTC, RivRetrieve should keep UTC. If a provider gives local time and the station has coordinates, RivRetrieve can resolve an IANA timezone from latitude and longitude using a timezone lookup library. A bare value like `local` is not enough because it does not say which local timezone is meant. If the timezone cannot be resolved, the result should carry a `timezone="unknown"` series annotation.

Timezone facts belong in series annotations. If RivRetrieve infers, changes, or finds a mismatch in timezone interpretation, the result should also include a structured issue so users see it.

```text
timezone_original
timezone_resolved
timezone_source
timezone_mismatch
```

Daily and monthly local-calendar products have unavoidable calendar caveats. Around daylight saving transitions, a local daily period may be 23 or 25 hours. Monthly periods vary in length. Reconstructing exact intervals from `time + frequency` is therefore approximate for these products.

Units should be standardised during catalogue generation where fields are part of the common schema. For example, the global station catalogue should use `elevation_m` and `drainage_area_km2` regardless of provider-native units. This prevents silent mistakes when users combine providers. Native units actually returned during a request belong in response metadata, especially when conversion occurred.

## 8. Missing data and error policy

Hydrological records are ragged. Stations start and stop. Products are added late. Providers may expose a station but not the requested product. Some providers do not publish station-product availability at all.

For that reason, I propose `on_missing="warn"` as the default. A request should return partial data when possible, emit warnings, and record structured issues on the result.

```python
result = rr.observations(
    provider="usgs_nwis",
    stations=["07374000", "missing_station"],
    products="discharge_daily_mean",
    start=pd.Timestamp("2020-01-01"),
    end=pd.Timestamp("2020-12-31"),
    on_missing="warn",
)

result.issues
```

The policy should still be configurable:

```text
on_missing="warn"    return partial data, warnings.warn(...), populate result.issues
on_missing="raise"   fail if any requested station-product is missing
on_missing="ignore"  return partial data, populate result.issues, do not warn
```

Warnings should use Python's standard `warnings.warn(...)` machinery, not `print()` or logging. Even `ignore` should not discard diagnostics. It should only suppress warnings.

An issue is structured so users can filter or summarise it programmatically.

```python
Issue(
    severity="warning",
    code="missing_data",
    provider_id="usgs_nwis",
    station_id="07374000",
    product_id="stage_instantaneous",
    message="No data returned for the requested interval.",
)
```

This avoids silent partial failure while still matching the reality of hydrological data retrieval.

## 9. Out of scope for v1

V1 is intentionally limited. These are out of scope:

- non-scalar products such as rating curves, vertical profiles, cross sections, and gridded data
- live catalogue refresh by end users
- plugin entry points for third-party providers
- cross-provider station crosswalks and deduplication
- cross-provider harmonisation of quality-code semantics
- a CLI-specific naming scheme

Quality annotations remain provider-native in v1. For example, `bom.quality_code` and `usgs.qualifier` should not be forced into one shared quality model. Harmonising quality semantics across agencies is a real research and data governance problem, not a prerequisite for this redesign.

## 10. Open questions

This proposal now contains several concrete decisions, but a few important questions still need agreement before implementation starts.

First, should RivRetrieve provide derived products? A common example is daily mean discharge computed from higher-frequency data when the provider does not publish a daily mean product. This is useful, but it is not a small decision. It needs clear rules for timezone handling, period anchoring, missing-data thresholds, and provenance metadata. Until this is settled, product filters should be understood as selecting catalogue products, not asking RivRetrieve to compute new products.

Second, which observed properties belong in RivRetrieve v1? Discharge, stage, and water temperature are clearly river-gauge products. Catchment precipitation is already implemented for UK NRFA, and rainfall appears in some provider metadata such as UK Environment Agency, but including precipitation may broaden RivRetrieve beyond river observations. The project needs a scope decision before committing to the v1 `observed_property` vocabulary.

Third, the canonical product vocabulary needs to be written as an explicit table before providers adopt canonical IDs. That table should define each canonical ID in terms of observed property, frequency, statistic, period anchor, unit, and whether the product is provider-native or derived. Providers should only use a canonical ID when they match that definition closely enough.

Finally, the pandas export shape needs more thought. Internally, `data`, `row_annotations`, and `series_annotations` should be long-form. For pandas users, the default may need to be wider, especially for simple single-product requests. I want the export to feel familiar without compromising the internal model.
