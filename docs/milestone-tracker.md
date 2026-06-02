# RivRetrieve Milestone Tracker

## 1. Port scope and non-goals

V1 ships the provider-based RivRetrieve redesign for river-gauge scalar time series: provider discovery, packaged/offline catalogue discovery, provider-level live catalogue queries where supported, normalized catalogue/result envelopes, one required-date observation request shape, structured issues/provenance/annotations, and one full reference provider port, `ch_foen` (architecture.md §1, §18). V1 does not ship provider API internals as shared abstractions, cross-provider station deduplication, quality-code harmonization, rating curves, cross sections, profiles, gridded data, catchment rainfall, precipitation, meteorological variables, or non-river products (architecture.md §1, §19). Explicit deferrals are wide-form pandas helpers beyond the minimum long-form export, RivRetrieve-derived products, and vocabulary expansion beyond river-gauge variables (architecture.md §19).

## 2. Cross-cutting invariants

- Keep the package installable/importable and `uv run pytest` green at every milestone boundary; no milestone may leave half-wired public imports or failing placeholder behavior (architecture.md §0).
- Do not add speculative shared abstractions; shared harness concepts require architecture authority or concrete provider-port evidence (architecture.md §0).
- Provider IDs are `snake_case`, identify source/agency where possible, and match provider package/module naming (architecture.md §2).
- Station IDs remain provider-native; global station keys are `(provider_id, station_id)` (architecture.md §2, §7).
- V1 public observation calls are keyword-only, accept one or many station/product IDs, and require `start` and `end` (architecture.md §3, §11).
- The top-level `rr.observations(...)` is only a wrapper around `rr.provider(...).observations(...)` and must not duplicate retrieval logic (architecture.md §3).
- Normal discovery is packaged/offline and must not call provider APIs; packaged catalogues are maintainer-owned release artifacts (architecture.md §4).
- `source="packaged" | "live"` is a provider-level catalogue choice only in V1; global discovery remains packaged/offline (architecture.md §5).
- All catalogue calls return `CatalogResult(data, provenance, issues)` once introduced; no bare public catalogue tables (architecture.md §6).
- Polars is the canonical dataframe engine for public and internal harness tables; pandas is export convenience only (architecture.md §6, §12).
- Common catalogue schemas stay small, declare nullability explicitly, and preserve provider-native metadata in opaque public `metadata` dictionaries (architecture.md §7).
- Product IDs are opaque labels; code must not parse IDs, and V1 product filters select catalogue products rather than compute products (architecture.md §8, §11).
- No public provider classes and no implementation inheritance hierarchy at the provider boundary; provider runtime modules expose the function-based contract (architecture.md §9).
- The public `ProviderHandle` Protocol, once exported, must expose the full public catalogue and observation behavior; it is not introduced as an empty public Protocol (architecture.md §9).
- `generate_catalogue.py` is maintainer-only and must not be imported during normal package use (architecture.md §10).
- Observation results use only `ObservationResult(data, row_annotations, series_annotations, provenance, issues, raw)` once introduced; no per-provider ad hoc returns (architecture.md §12).
- Observation data and annotation tables are long-form; provider-scoped observation rows do not require `provider_id` (architecture.md §12).
- Providers declare `row_annotation_schema()` and `series_annotation_schema()` before emitting annotation names (architecture.md §13).
- Provenance records retrieval/build bookkeeping and never secrets; scientific/provider metadata belongs in metadata or annotations (architecture.md §14).
- `Issue` is the shared diagnostic type; `on_issue` is the sole harness policy knob for recoverable issues (architecture.md §15).
- Fatal contract failures raise immediately regardless of `on_issue` (architecture.md §15).
- Time semantics and units are represented in product metadata, annotations, provenance, and issues rather than inferred from product IDs (architecture.md §16).
- Multi-API source splitting and stitching are provider-internal; provenance, annotations, and issues preserve calls, gaps, overlaps, preferred/fallback source choices, and conflicts (architecture.md §17).
- `ch_foen` is the first reference provider port and the only V1 provider port unless architecture changes explicitly authorize another (architecture.md §18).
- Do not silently resolve the deferred questions in architecture.md §19.

## 3. Milestone list

Chosen bound: 5 implementation milestones after this tracker. This deliberately exceeds the earlier 6-10-file and two-public-method soft targets in M1 and M2, because the 11-cut created two worse intermediate states: an empty public provider Protocol and a registered `ch_foen` provider with undefined observation behavior. The 5-cut follows the natural architecture seams: harness foundation, complete no-provider harness, `ch_foen` catalogue provider, `ch_foen` observations plus wrapper, then map and closeout.

### M1 — Harness foundation

- Goal: Establish the dependency and catalogue foundation for the redesign in one shippable commit. This includes shared identifiers, issue policy, catalogue result/provenance envelopes, packaged artifact schemas, registry machinery, and `rr.provider_info()` over an empty or stub registry. The provider handle machinery may exist internally, but the public `ProviderHandle` Protocol is not exported until M2 when it can expose the full catalogue and observation surface required by architecture.md §9.
- Architecture sections covered: §0, §2, §4, §6, §7, §8, §10, §14, §15.
- In scope:
  - Add runtime dependencies needed before later code consumes them: Polars, pandas for the minimum export contract, Pydantic for provider metadata/schema models, and `requests` for provider runtime/generator HTTP calls translated from the legacy Python fetchers.
  - Introduce `CatalogSource`, `OnIssue`, `Issue`, issue severities, provider/product ID aliases, and Polars table aliases.
  - Encode `on_issue="warn" | "raise" | "ignore"` behavior for structured issues.
  - Introduce `CatalogResult`, `CatalogProvenance`, common station/product/station-product/provider-info catalogue schemas, and `PackagedCatalogArtifact`.
  - Common schema validation declares nullable fields explicitly, including nullable `elevation_m` and `drainage_area_km2`.
  - Introduce provider registry internals, deterministic `rr.providers()`, `rr.provider(provider_id)` lookup, fatal unknown-provider errors, and public `rr.provider_info()` as `CatalogResult`.
  - Tests against an empty registry plus stub packaged catalogue artifacts, including corrupt-artifact failure and offline import behavior.
- Out of scope / explicitly deferred to which later milestone:
  - Public provider catalogue methods and the public `ProviderHandle` Protocol: M2.
  - Observation request/result contracts: M2.
  - Real `ch_foen` catalogue artifacts or runtime registration: M3.
  - Map rendering: M5.
- Public API surface introduced or changed:
  - `def providers() -> list[str]: ...`
  - `def provider(provider_id: str) -> object: ...`
  - `def provider_info() -> CatalogResult[ProviderInfoCatalog]: ...`
- Internal types/contracts introduced:
  - `CatalogSource`
  - `OnIssue`
  - `Issue`
  - `IssueSeverity`
  - `ProviderId`
  - `ProductId`
  - `CatalogResult`
  - `CatalogProvenance`
  - `StationCatalog`
  - `ProductCatalog`
  - `StationProductCatalog`
  - `ProviderInfoCatalog`
  - `PackagedCatalogArtifact`
  - `ProviderRegistry`
- Legacy Python analogues consulted:
  - `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/base.py`
  - `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/usa.py`
  - `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/uk_ea.py`
  - `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/uk_nrfa.py`
  - `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/canada.py`
  - Legacy analogue: `RiverDataFetcher`, `get_cached_metadata()`, cached metadata CSVs, variable constants, and country/source class registration patterns; no legacy analogue for `CatalogResult`, provenance, artifact validation, or `on_issue`.
- Exit criteria:
  - `rr.providers()` is deterministic and offline.
  - `rr.provider("missing")` raises a fatal unknown-provider error.
  - `rr.provider_info()` returns `CatalogResult(data, provenance, issues)`.
  - Stub packaged artifacts validate; corrupt packaged artifacts raise immediately regardless of `on_issue`.
  - Common schema tests prove `elevation_m` and `drainage_area_km2` are nullable.
  - Importing `rivretrieve` does not import any provider module or catalogue generator.
  - `uv run pytest` passes.
- Dependencies on earlier milestones:
  - None.
- Risk / known unknowns:
  - This milestone is heavier than the original soft bound, but it removes the empty public Protocol state and pins runtime dependencies before they are consumed.

### M2 — Discovery and observation contracts

- Goal: Complete the no-provider harness surface against stub providers. This milestone introduces all public catalogue methods, provider-level `source` handling, the full public `ProviderHandle` Protocol, normalized observation request/result contracts, annotation schemas, and long-form exports. After this commit, the harness is shippable without `ch_foen`.
- Architecture sections covered: §3, §4, §5, §6, §7, §8, §9, §11, §12, §13, §14, §15, §16, §17.
- In scope:
  - Public provider handle typed by a non-empty `typing.Protocol` exposing catalogue and observation methods.
  - Provider-handle `info()`, `products()`, `stations()`, `station_products()`, `row_annotation_schema()`, `series_annotation_schema()`, and `observations(...)`.
  - Global `rr.stations()`, `rr.products()`, and `rr.product_info()` over packaged catalogues.
  - Provider-level `source="packaged" | "live"` validation; global discovery remains packaged/offline.
  - Unsupported live catalogue calls return `CatalogResult` with warning issues.
  - Product filters for `observed_property`, `frequency`, and `statistic`.
  - `ObservationRequest`, `ObservationResult`, `ObservationProvenance`, `AnnotationSchema`, annotation tables, raw payload slot, and `to_polars()` / long-form `to_pandas()`.
  - Stub provider tests for single and bulk observation normalization, required `start`/`end`, annotation schema validation, and `on_issue`.
- Out of scope / explicitly deferred to which later milestone:
  - Real `ch_foen` catalogue artifacts and registration: M3.
  - Real observation retrieval: M4.
  - Top-level `rr.observations(...)`: M4.
  - `rr.map_stations()`: M5.
  - Wide-form pandas helpers: post-V1 deferral from §19.
- Public API surface introduced or changed:
  - `class ProviderHandle(Protocol): ...`
  - `def provider(provider_id: str) -> ProviderHandle: ...`
  - `def stations(...) -> CatalogResult[StationCatalog]: ...`
  - `def products(...) -> CatalogResult[ProductCatalog]: ...`
  - `def product_info(...) -> CatalogResult[ProductCatalog]: ...`
  - `def ProviderHandle.info() -> ProviderInfo: ...`
  - `def ProviderHandle.products(*, source: CatalogSource = "packaged", observed_property: str | None = None, frequency: str | None = None, statistic: str | None = None, on_issue: OnIssue = "warn") -> CatalogResult[ProductCatalog]: ...`
  - `def ProviderHandle.stations(*, source: CatalogSource = "packaged", on_issue: OnIssue = "warn") -> CatalogResult[StationCatalog]: ...`
  - `def ProviderHandle.station_products(stations: Sequence[str] | None = None, *, source: CatalogSource = "packaged", on_issue: OnIssue = "warn") -> CatalogResult[StationProductCatalog]: ...`
  - `def ProviderHandle.row_annotation_schema() -> list[AnnotationSchema]: ...`
  - `def ProviderHandle.series_annotation_schema() -> list[AnnotationSchema]: ...`
  - `def ProviderHandle.observations(*, stations: str | Sequence[str], products: str | Sequence[str], start: object, end: object, on_issue: OnIssue = "warn") -> ObservationResult: ...`
  - `def ObservationResult.to_polars() -> pl.DataFrame: ...`
  - `def ObservationResult.to_pandas() -> pandas.DataFrame: ...`
- Internal types/contracts introduced:
  - `ProviderInfo`
  - `ProviderHandle`
  - `ProviderModule`
  - `CatalogueReader`
  - `CatalogueValidator`
  - `LiveCatalogueUnsupportedIssue`
  - `ObservationRequest`
  - `ObservationResult`
  - `ObservationProvenance`
  - `AnnotationSchema`
  - `AnnotationTable`
  - `RawPayload`
- Legacy Python analogues consulted:
  - `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/base.py`
  - `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/usa.py`
  - `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/uk_ea.py`
  - `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/uk_nrfa.py`
  - `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/canada.py`
  - Legacy analogue: `get_available_variables()`, `get_cached_metadata()`, live `get_metadata()` in `uk_ea.py` and `uk_nrfa.py`, `get_data(gauge_id, variable, start_date, end_date)`, download/parse split, unit conversion, endpoint quality fields, pagination/limits, and local archive/database handling.
- Exit criteria:
  - Public `ProviderHandle` Protocol exposes the full catalogue and observation method set; there is no empty public Protocol phase.
  - Provider and global catalogue methods return `CatalogResult` with Polars data and do not call provider APIs for packaged source.
  - Invalid `source` raises as a fatal contract error.
  - Unsupported `source="live"` produces a warning issue under `on_issue="warn"`, raises under `"raise"`, and remains in `issues` under `"ignore"`.
  - A fake provider returns valid `ObservationResult` for one station/product and multiple stations/products through the same public method.
  - Missing `start` or `end` raises before provider execution.
  - Annotation names not declared by provider schemas fail validation in tests/debug validation.
  - `result.data`, `result.to_polars()`, and `result.to_pandas()` expose the same canonical long table.
  - `uv run pytest` passes.
- Dependencies on earlier milestones:
  - M1.
- Risk / known unknowns:
  - This milestone lands a broad public API surface in one commit; the tradeoff is that every public handle shape is coherent at the milestone boundary.

### M3 — `ch_foen` catalogue provider

- Goal: Translate the legacy Python `SwitzerlandFetcher` catalogue knowledge into the new provider catalogue model, generate packaged artifacts, and register `ch_foen` as the first real provider. This is translation-with-redesign: the unmerged Switzerland branch proves the Existenz.ch BAFU hydro locations endpoint and fixtures exist, while this commit reshapes them into provider metadata, product catalogues, station catalogues, station-product availability, and maintainer-only generation. Because observation retrieval lands in M4, `ch_foen.observations(...)` must be Protocol-conformant at this boundary by returning an `ObservationResult` with a structured not-yet-implemented issue and no data rows.
- Architecture sections covered: §0, §2, §3, §4, §5, §6, §7, §8, §9, §10, §15, §16, §18.
- In scope:
  - Translate `SwitzerlandFetcher.get_metadata()` and cached Switzerland site data into `ch_foen` catalogue generation.
  - Provider-specific Pydantic metadata models for station, product, and station-product metadata.
  - Maintainer-only `generate_catalogue.py` for `ch_foen`.
  - Commit packaged `provider.json`, `products.parquet`, `stations.parquet`, and `station_products.parquet` artifacts.
  - Runtime `ch_foen.info()`, `products()`, `stations()`, `station_products()`, `row_annotation_schema()`, and `series_annotation_schema()`.
  - `ch_foen.observations(...)` placeholder returning `ObservationResult` with `error` severity issue code `observations_not_yet_implemented`, empty canonical tables, provenance, and no raw payload.
  - Provider capabilities including live catalogue support flags and bulk observation capability description.
  - Commit and use the Switzerland metadata fixture from `origin/switzerland` as recorded catalogue-generator input.
  - Document `ch_foen` catalogue translation pain points, including null `elevation_m` and `drainage_area_km2`, in `docs/provider_ports/ch_foen.md`.
- Out of scope / explicitly deferred to which later milestone:
  - Real `ch_foen` observation retrieval: M4.
  - Top-level `rr.observations(...)`: M4.
  - `rr.map_stations()`: M5.
  - Product dictionary expansion beyond existing V1 observed properties: post-V1 unless architecture/product dictionary are explicitly changed.
  - Any second provider: post-V1 unless architecture changes.
- Public API surface introduced or changed:
  - No new signatures; `rr.providers()` now includes `"ch_foen"` and existing catalogue APIs return non-empty `ch_foen` data.
- Internal types/contracts introduced:
  - `ChFoenStationMetadata`
  - `ChFoenProductMetadata`
  - `ChFoenStationProductMetadata`
  - `ch_foen` provider module contract implementation.
- Legacy Python analogues consulted:
  - `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/base.py`
  - `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/usa.py`
  - `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/uk_ea.py`
  - `git show origin/switzerland:rivretrieve/switzerland.py`
  - `git show origin/switzerland:rivretrieve/cached_site_data/switzerland_sites.csv`
  - `git show origin/switzerland:tests/test_data/switzerland_metadata_locations.json`
- Exit criteria:
  - `rr.providers()` includes `"ch_foen"`.
  - `rr.provider("ch_foen").stations()` and `rr.stations()` return `CatalogResult` with Polars data and packaged provenance.
  - `source="live"` behavior matches declared capabilities and never mutates packaged artifacts.
  - `docs/provider_ports/ch_foen.md` records the translated source endpoints/artifacts from `SwitzerlandFetcher`, including `https://api.existenz.ch/apiv1/hydro/locations`.
  - `tests/test_data/switzerland_metadata_locations.json` from `origin/switzerland` is committed under the target repo and used as the recorded response for catalogue-generator tests.
  - Catalogue-generator tests match legacy fixture facts, including station count `246` and station `2016` named `Brugg`.
  - `ch_foen` catalogue artifacts validate against common schemas, including nullable elevation and drainage-area fields.
  - `rr.provider("ch_foen").observations(...)` returns `ObservationResult` with empty data and one `observations_not_yet_implemented` issue rather than raising `AttributeError` or `NotImplementedError`.
  - Normal package import does not import `generate_catalogue.py`.
  - `uv run pytest` passes without network.
- Dependencies on earlier milestones:
  - M1, M2.
- Risk / known unknowns:
  - The legacy Switzerland branch is unmerged community work, so executors must verify that translated catalogue semantics fit architecture.md rather than copying class behavior directly.

### M4 — `ch_foen` observations and top-level wrapper

- Goal: Replace the M3 placeholder with real `ch_foen` observation retrieval and add the top-level convenience wrapper. `ch_foen` retrieves one or many stations/products through the same provider-handle method, normalizes to long-form Polars data, records row/series annotations, preserves practical raw payloads, and captures provenance and issues. The wrapper proves `rr.observations(...)` delegates rather than reimplements provider lookup, validation, or retrieval.
- Architecture sections covered: §3, §9, §11, §12, §13, §14, §15, §16, §17, §18.
- In scope:
  - Real `ch_foen.observations(request, *, on_issue=...)`.
  - Single-station and bulk station/product normalization through the existing provider handle.
  - Provider-internal windowing, decomposition, batching, safe concurrency, retries, and stitching only to the extent needed for `ch_foen`.
  - Translate legacy Switzerland Flux query behavior, 366-day windows, parameter preference (`flow` preferred over `flow_ls`), `flow_ls` unit conversion, daily aggregation, and instant time filtering.
  - Row/series annotations and provenance for native field, preferred/fallback source choice, native unit, converted unit, endpoint/query metadata, returned time range, and timezone facts where available.
  - Structured issues for missing data, partial responses, gaps, overlaps, conflicts, unit conversion ambiguity, timezone ambiguity, and placeholder removal.
  - Commit and use the three Switzerland CSV fixtures from `origin/switzerland` as observation parser tests.
  - Public `rr.observations(...)` thin wrapper with delegation tests.
  - Update `docs/provider_ports/ch_foen.md` with observation retrieval pain points.
- Out of scope / explicitly deferred to which later milestone:
  - `rr.map_stations()`: M5.
  - Shared backend-policy abstraction: post-V1 unless port evidence forces an architecture update.
  - Wide-form pandas export helpers: post-V1 deferral from §19.
  - Quality-code harmonization across providers: post-V1.
  - Additional providers: post-V1 unless architecture changes.
- Public API surface introduced or changed:
  - `def observations(*, provider: str, stations: str | Sequence[str], products: str | Sequence[str], start: object, end: object, on_issue: OnIssue = "warn") -> ObservationResult: ...`
- Internal types/contracts introduced:
  - `ChFoenObservationClient`
  - `ChFoenRawPayload`
  - `ChFoenObservationIssueCodes`
- Legacy Python analogues consulted:
  - `git show origin/switzerland:rivretrieve/switzerland.py`
  - `git show origin/switzerland:tests/test_switzerland.py`
  - `git show origin/switzerland:examples/test_switzerland_fetcher.py`
  - `git show origin/switzerland:docs/fetchers/switzerland.rst`
  - `git show origin/switzerland:tests/test_data/switzerland_2016_temperature_20200101.csv`
  - `git show origin/switzerland:tests/test_data/switzerland_2206_discharge_20250101.csv`
  - `git show origin/switzerland:tests/test_data/switzerland_2282_stage_20250101.csv`
  - `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/usa.py` for parameter mapping and unit conversion contrast.
  - `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/uk_ea.py` for product/measure discovery, pagination, and quality fields.
- Exit criteria:
  - `rr.provider("ch_foen").observations(...)` returns real `ObservationResult` data for deterministic fixture-backed calls, not the M3 `observations_not_yet_implemented` issue.
  - The three legacy CSV fixtures are committed under the target repo's `tests/test_data/` and used to feed observation parse/retrieval tests.
  - Fixture-backed tests cover discharge fallback conversion for station `2206`, instant stage for station `2282`, and daily water temperature for station `2016`.
  - Where the new long-form schema diverges from the legacy wide-form pandas output, the divergence is documented in `docs/provider_ports/ch_foen.md`.
  - A bulk request uses the same public method and returns aggregated long-form data or structured issues for partial failure.
  - Provider call provenance lists source calls made without secrets.
  - Annotation schema tests cover emitted row and series annotation names.
  - A monkeypatch/spy test proves `rr.observations(...)` delegates to the provider handle.
  - Top-level calls require `provider`, `stations`, `products`, `start`, and `end`.
  - `uv run pytest` passes without depending on live network.
- Dependencies on earlier milestones:
  - M1, M2, M3.
- Risk / known unknowns:
  - The legacy branch embeds an Influx token; implementation must avoid storing secrets in provenance and should review whether the token belongs in code, config, or documented provider access handling.

### M5 — Map and V1 closeout

- Goal: Ship `rr.map_stations()` as a packaged-catalogue view and close V1 with architecture conformance evidence. The map is deliberately late because it depends on real packaged station data and should not drive catalogue design. This milestone also records final `ch_foen` feedback, discovery notes, and verification results.
- Architecture sections covered: §0 through §18; §19 deferrals are reaffirmed but not implemented.
- In scope:
  - Add/pin the map backend dependency selected by implementation, such as `leafmap`, or define explicit optional-dependency behavior with a clear fatal dependency error.
  - `rr.map_stations()` over packaged station catalogue data.
  - Same basic filters already supported by `rr.stations()` where implemented.
  - Tests that `map_stations()` reads packaged data rather than provider APIs.
  - Architecture conformance tests or checklist mapping architecture.md §0-§18 to behavior and §19 to explicit deferral.
  - `docs/provider_ports/ch_foen.md` final V1 pain-point updates.
  - `docs/discoveries.md` entries for discoveries that contradicted architecture.md.
  - README or user-facing docs only if needed to expose already-implemented V1 behavior.
  - Full local verification with `uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`, and `uv run pytest`.
- Out of scope / explicitly deferred to which later milestone:
  - Any new provider.
  - Any §19 deferred feature.
  - Plugin entry points, cross-provider crosswalks, derived products, live global map discovery, and map-specific metadata not present in catalogue data.
- Public API surface introduced or changed:
  - `def map_stations(...) -> object: ...`
- Internal types/contracts introduced:
  - `StationMap`
- Legacy Python analogues consulted:
  - No direct legacy analogue for mapping; this is a new discovery-view concept.
  - This milestone reviews evidence already collected from `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/` and `origin/switzerland`.
- Exit criteria:
  - `rr.map_stations()` renders or returns the selected map object using only packaged station data.
  - Missing optional map backend, if treated as optional by implementation, fails with a clear fatal dependency error rather than silently changing semantics.
  - A documented conformance checklist maps architecture.md §0-§18 to implemented behavior and §19 to explicit deferral.
  - `docs/provider_ports/ch_foen.md` contains final V1 feedback.
  - `docs/discoveries.md` exists if any architecture contradictions were found.
  - `uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`, and `uv run pytest` pass.
- Dependencies on earlier milestones:
  - M1, M2, M3, M4.
- Risk / known unknowns:
  - architecture.md commits `rr.map_stations()` to V1, but dependency policy for `leafmap` is not specified; this milestone must choose and document the packaging behavior without changing the architecture contract.

## 4. Sequencing rationale

The sequence keeps the workspace installable/importable and `uv run pytest` green at every boundary by landing coherent capability slices rather than thin contract fragments. M1 makes the package dependency-complete for the committed architecture and establishes catalogue artifacts/results. M2 completes the public no-provider harness and avoids an empty public `ProviderHandle` Protocol by introducing it only when the full catalogue and observation method surface exists. M3 registers `ch_foen` as a real catalogue provider while keeping observation behavior Protocol-conformant through an explicit `ObservationResult` issue. M4 replaces that placeholder with real fixture-backed retrieval and adds the top-level wrapper. M5 adds the map view and conformance closeout.

Building `ch_foen` before the harness types is tempting because the legacy Python `SwitzerlandFetcher` already provides concrete endpoint and fixture evidence, but it would force the first provider to invent result shapes, issue policy, provenance, catalogue schemas, and request normalization in the same commit. The chosen order gives `ch_foen` enough harness to be a real validation port, while still leaving a feedback loop: if the provider exposes shared design pain, the porter records it in `docs/provider_ports/ch_foen.md` and updates architecture.md explicitly rather than slipping new abstractions into provider code.

`generate_catalogue.py` is grouped with packaged `ch_foen` artifacts in M3 because the generator and artifacts should be reviewed together for the first provider. The top-level `rr.observations(...)` ships with real provider observations in M4 so tests can prove it delegates. Bulk machinery is folded minimally into M2 request normalization and M4 provider-aware execution because architecture.md §11 and provider-redesign §3 define single and bulk as the same method; more elaborate batching/retry/concurrency design remains internal and provider-aware, not a public milestone unless provider evidence forces it.

## 5. `ch_foen` positioning

Per architecture.md §18, `ch_foen` is the first reference provider and the only V1 provider port in this tracker. It is introduced in M3 as translation of the legacy Python `SwitzerlandFetcher` into maintainer catalogue generation, packaged catalogue artifacts, runtime registration, and Protocol-conformant not-yet-implemented observation behavior. It becomes a full observation provider in M4.

The minimum harness before a real provider can be ported is M1-M2: shared issue/policy primitives, provider registry internals, catalogue artifact/result contracts, public catalogue discovery APIs, full public provider Protocol, and observation request/result/annotation contracts. `ch_foen` unblocks M4 because the top-level observation wrapper needs a real delegate to prove it is thin, and M5 because station mapping and architecture closeout need concrete packaged station data and port evidence.

## 6. Open questions

- How many milestones? Recommendation: 5 implementation milestones after this tracker. Rationale: the 5-cut removes the empty-Protocol and half-wired-provider states from the 11-cut while preserving one-commit shippability at each boundary.
- Should packaged catalogue artifact schemas be frozen in their own milestone, or inside the first milestone that consumes them? Recommendation: freeze them in M1 before `ch_foen`. Rationale: architecture.md §4, §6, §7, and §10 make packaged catalogues foundational, and `ch_foen` should consume schemas rather than invent them.
- Where does the harness/types layer end and the first provider port begin? Recommendation: M1-M2 are harness, M3 begins `ch_foen`. A stub provider is used before `ch_foen` so contracts compile and tests prove behavior without mixing harness shape with Switzerland translation complexity.
- Does packaged-catalogue artifact generation get its own milestone? Recommendation: no for the first provider; combine `ch_foen` generation and packaged artifacts in M3. Rationale: architecture.md §10 says generation is maintainer-only, but the first provider's generator and artifacts should be reviewed together to validate the artifact contract.
- Does `rr.observations(...)` ship with `provider.observations(...)` or after? Recommendation: ship it in M4 with real `ch_foen` observations. Rationale: architecture.md §3 says it is only a wrapper, and M4 can prove delegation against a real provider.
- Does `rr.map_stations()` ship in V1? Recommendation: yes, but late in M5. Rationale: architecture.md §3 includes it in the public API and says it is a view over packaged station catalogues. It is less useful with one provider, but the architecture still commits to it.
- Where do `row_annotation_schema` and `series_annotation_schema` get introduced? Recommendation: introduce the contract in M2, `ch_foen` schemas in M3, and emitted annotation validation in M4. Rationale: architecture.md §13 makes schemas part of the provider contract, but provider-specific annotation IDs need source evidence.
- Does global discovery belong in one milestone or split? Recommendation: keep non-map global discovery in M2 and map discovery in M5. Rationale: `rr.stations()`, `rr.products()`, and `rr.product_info()` are pure packaged table aggregation, while `rr.map_stations()` brings a mapping dependency and should not drive catalogue schema decisions.
- Where does bulk/batching machinery go? Recommendation: fold minimum single/bulk normalization into M2 and `ch_foen` provider-aware execution into M4; do not create a public backend-policy milestone. Rationale: architecture.md §11 says single and bulk use one request shape and RivRetrieve owns decomposition, while §17 says backend strategy remains internal in V1.
- Contradiction between architecture.md and docs/design/provider-redesign.md: provider-redesign §8 uses `on_missing`, while architecture.md §15 replaces it with `on_issue` as the sole policy knob. Recommendation: follow architecture.md and note the discrepancy in implementation docs if it causes confusion.
- Is `provider_info()` returned as `CatalogResult` from the first registry milestone? Recommendation: yes, in M1. Rationale: architecture.md §6 says all catalogue calls return `CatalogResult`; there is no interim bare-table phase.
- Is `leafmap` a hard runtime dependency? Recommendation: leave the dependency decision to M5 implementation, but require `rr.map_stations()` to have clear behavior and not silently omit the feature. Rationale: architecture.md commits the API but does not define packaging strategy.
- Is `ch_foen` greenfield or translation? Recommendation: translation-with-redesign. The unmerged `origin/switzerland` branch provides `SwitzerlandFetcher`, tests, fixtures, cached site data, and docs; M3-M4 must translate that evidence into the provider boundary, `CatalogResult`, and `ObservationResult` rather than invent Swiss API knowledge from scratch or copy the old class shape.

## 7. Deferrals (post-V1)

- What wide-form pandas export helpers are needed beyond the minimum long-form `to_pandas()` contract? Hard rationale: architecture.md §19 explicitly defers the shape decision, and M2 only ships long-form `to_pandas()`.
- When, if ever, should RivRetrieve-owned derived products be introduced? Hard rationale: architecture.md §19 explicitly defers derived products; architecture.md §8 and §11 say V1 product filters select catalogue products, not computations.
- When, if ever, should the canonical product vocabulary expand beyond river-gauge variables? Hard rationale: architecture.md §19 explicitly defers vocabulary expansion; docs/product_dictionary.md limits V1 observed properties to `discharge`, `stage`, and `water_temperature`.
- End-user live catalogue refresh or mutation. Hard rationale: architecture.md §4 and §5 make packaged catalogues maintainer-owned and live catalogue queries non-mutating.
- Plugin entry points for third-party providers. Hard rationale: provider-redesign §9 lists plugin entry points as out of scope for V1, and architecture.md §18 says broader provider ports come after harness plus `ch_foen`.
- Cross-provider station crosswalks and deduplication. Hard rationale: architecture.md §7 says V1 lists physical gauges appearing in multiple catalogues separately.
- Cross-provider quality-code harmonization. Hard rationale: architecture.md §13 says quality annotations remain provider-native in V1.
- Public backend-policy abstraction for source selection, concurrency, retries, or stitching. Hard rationale: architecture.md §11 and §17 keep execution strategy internal and provider-aware in V1.
- Cross-provider combined observation tables beyond the rules already stated for including `provider_id`. Hard rationale: V1 scoped to `ch_foen`; `lt_lhmt` was added as a post-V1 port following the established provider contract.
- Map-specific metadata or live global mapping. Hard rationale: architecture.md §3 says `rr.map_stations()` is a view over the same packaged station catalogue.
- Product vocabulary additions for precipitation, catchment rainfall, meteorological variables, or other non-river products. Hard rationale: architecture.md §1 and docs/product_dictionary.md exclude them from V1 canonical scope.

## 9. `lt_lhmt` — Lithuania provider port (post-V1)

- **Source:** `https://github.com/kratzert/RivRetrieve-Python/blob/main/rivretrieve/lithuania.py` (legacy `LithuaniaFetcher`).
- **Provider ID:** `lt_lhmt`
- **Status:** Shipped. Registered alongside `ch_foen` in `_ensure_default_providers_registered()`. All 476 tests pass (34 lt_lhmt-specific).
- **Products ported:** `discharge_daily_mean` (waterDischarge, m³/s direct), `stage_daily_mean` (waterLevel, cm→m conversion).
- **Stations:** 97 (2026-05-31 fixture). Elevation and drainage area null (API does not provide them).
- **Key decisions:**
  - Date-only UTC timestamps (`YYYY-MM-DD`) interpreted as UTC midnight; `date_only_timestamp` structured warning issued per month; `date_only_timestamp_flag` series annotation always `"true"`.
  - Stage cm→m conversion in transform layer; raw cm value preserved in `raw_value` row annotation.
  - Monthly chunking instead of 366-day windows; HTTP 404 months emit `http_not_found` warning rather than raising.
  - No auth token; no fallback fields.
  - Rate-limit enforcement deferred post-V1.
- **Port notes:** `docs/provider_ports/lt_lhmt.md`.
- **Fixture:** `tests/test_data/lithuania_metadata_stations.json` (97 stations, 2026-05-31), `tests/test_data/lithuania_anyksciu_vms_2023_06.json` (June 2023 observations for station `anyksciu-vms`).
- **Architecture.md impact:** None. The date-only timestamp pattern is provider-specific. No shared harness gap discovered.

## 10. `usgs_nwis` — USA / USGS NWIS provider port (post-V1)

- **Source:** `https://github.com/kratzert/RivRetrieve-Python/blob/main/rivretrieve/usa.py` (legacy `USAFetcher` using `dataretrieval` package).
- **Provider ID:** `usgs_nwis`
- **Status:** Shipped. Registered alongside `ch_foen` and `lt_lhmt` in `_ensure_default_providers_registered()`. All 512 tests pass (36 usgs_nwis-specific).
- **Products ported:** `discharge_daily_mean` (DV 00060/00003, cfs→m3/s), `discharge_instantaneous` (IV 00060, cfs→m3/s), `stage_daily_mean` (DV 00065/00003, ft→m), `stage_daily_max` (DV 00065/00001, ft→m), `stage_daily_min` (DV 00065/00002, ft→m), `stage_instantaneous` (IV 00065, ft→m).
- **Stations:** 5 (2026-06-01 fixture; representative set). For production, regenerate from live USGS site service (8000+ stream gauges).
- **Key decisions:**
  - Direct USGS WaterServices REST API calls (no `dataretrieval` package). DV and IV endpoints selected per product.
  - Annual 365-day windows for retrieval.
  - Timestamps carry explicit ISO 8601 timezone offsets (e.g. `-06:00` for CST); parsed and converted to UTC. Series annotation `timezone_source = "provider_timestamp_offset"`.
  - No auth token; public USGS API.
  - Elevation converted ft→m; drainage area converted sq mi→km². Raw values preserved in station metadata.
  - Station-product availability materialized as `unknown` (NWIS site catalogue does not expose per-variable availability).
  - HTTP 404 per window emits `http_not_found` warning issue (not fatal), matching lt_lhmt pattern.
- **Port notes:** `docs/provider_ports/usgs_nwis.md`.
- **Fixtures:** `tests/test_data/usgs_nwis_metadata_sites.json` (5 stations, 2026-06-01), `tests/test_data/usgs_nwis_07374000_dv_00060_2023-01-01.json` (DV discharge Jan 2023 for station 07374000).
- **Architecture.md impact:** None. Timestamp offset conversion is provider-specific. Unit conversions (cfs, ft) are provider-specific. No shared harness gap discovered.

## 11. `cz_chmi` — Czech Republic / CHMI provider port (post-V1)

- **Source:** `https://github.com/kratzert/RivRetrieve-Python/blob/main/rivretrieve/czech.py` (legacy `CzechFetcher`).
- **Provider ID:** `cz_chmi`
- **Status:** Shipped. Registered alongside `ch_foen`, `lt_lhmt`, and `usgs_nwis` in `_ensure_default_providers_registered()`. All 544 tests pass (30 cz_chmi-specific).
- **Products ported:** `discharge_daily_mean` (QD, m³/s direct), `stage_daily_mean` (HD, cm→m), `water_temperature_daily_mean` (TD, °C direct), `discharge_instantaneous` (QH, m³/s direct), `stage_instantaneous` (HH, cm→m).
- **Stations:** 831 (2026-06-02 live catalogue from CHMI metadata endpoint).
- **Key decisions:**
  - Direct CHMI Open Data REST calls. Annual year-by-year windowing per the legacy fetcher pattern.
  - Timestamps carry a Z suffix (e.g., `2020-01-01T00:00:00Z`); parsed as UTC directly. Series annotation `timezone_source = "provider_timestamp_utc"`. No structured issue emitted (no inference).
  - Stage cm→m conversion in transform layer; raw cm value preserved in `raw_value` row annotation.
  - Three daily products (QD, HD, TD) all fetched from the daily DQ file per year. Two hourly products (QH, HH) from the hourly HQ file per year. One HTTP call per product per year (no file-level deduplication in V1).
  - Elevation always `None` (not in CHMI metadata).
  - Drainage area (`PLO_STA`) preserved in km² from the metadata; nullable when absent.
  - No auth token; public CHMI Open Data.
  - HTTP 404 per year emits `http_not_found` warning issue (not fatal), matching lt_lhmt/usgs_nwis pattern.
- **Port notes:** `docs/provider_ports/cz_chmi.md`.
- **Fixtures:** `tests/test_data/cz_chmi_metadata.json` (3 stations, fixture), `tests/test_data/cz_chmi_0-203-1-016000_daily_2020.json` (daily observations for station `0-203-1-016000`, year 2020, with QD/HD/TD entries).
- **Architecture.md impact:** None. UTC-explicit timestamps are provider-specific. Stage cm→m conversion is provider-specific. Annual windowing is provider-specific. No shared harness gap discovered.

## 8. Stopping conditions for milestone executors

- Do not silently re-open architecture.md §19 deferrals.
- Do not introduce a public provider class.
- Do not recreate the `RiverDataFetcher` base-class shape from `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/base.py` (`get_data`, `get_cached_metadata`, `get_available_variables`, shared abstract base) inside any provider package, public or private. Provider runtime modules expose the function-based contract in architecture.md §9; provider-internal classes are permitted only as bounded implementation details, never as a shared abstract base.
- Do not add abstractions on a "we'll need it later" basis; architecture.md §0 forbids speculative shared abstractions.
- Do not weaken the Polars-canonical contract.
- Discoveries that contradict architecture.md must be logged to `docs/discoveries.md` and surfaced; do not silently follow them.
- Do not add a second V1 provider unless architecture.md is explicitly changed.
- Do not broaden the V1 product vocabulary beyond `discharge`, `stage`, and `water_temperature`.
- Do not let `source="live"` mutate packaged catalogues or appear as a global discovery mode in V1.
- Do not replace `on_issue` with `on_missing` or add a second public issue policy knob.
- Do not import `generate_catalogue.py` during normal runtime package use.
- Do not leave a milestone with failing tests, broken imports, empty public Protocols, or public API signatures that contradict architecture.md.
