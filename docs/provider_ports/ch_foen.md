# ch_foen Provider Port Notes

These notes capture evidence and hand-off context from the `ch_foen` provider port. The current provider declaration is catalogue-only; observation sections below are historical implementation evidence, not a shipped capability. These notes are not an architecture contract; promote only shared commitments to [ADRs](../adr/).

## Source Endpoints

| Endpoint or source | M3 role | Credential status | Citation |
| --- | --- | --- | --- |
| Existenz.ch `/apiv1/hydro/locations` | Maintainer-side catalogue input for station metadata and the packaged station-product universe. Runtime catalogue calls read packaged artifacts only. | No token. | `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:15`, `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:177`, `src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json:1`, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:37-38 |
| Legacy SwitzerlandFetcher metadata parser | Reference for station field normalization from the locations payload. | No token. | thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:127-173 |
| Existenz.ch Influx archive query API | M4 observation background only; M3 does not call it. | Upstream `origin/switzerland` HEAD `cd9b030` (`Restore public Switzerland token`) intentionally restores a literal `INFLUX_TOKEN`, classifying it as a public service credential. Target M3 carries no token because it is catalogue-only. | `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/execution.md:81`, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:39-40, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:199-203 |
| BAFU/Existenz documentation and terms | M4 observation background and provenance context. | None in M3. | thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:30-34, `src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json:1` |

## Native Catalogue Attestation

The complete `/apiv1/hydro/locations` response was retrieved at `2026-08-02T00:14:31Z`, contained 246
stations under `payload`, and was verified byte-identical to
`tests/test_data/switzerland_metadata_locations.json`. Canonical JSON has SHA-256
`7471e85de4f4a6d1e0968a9fe35a962c98729a4bb3b244e0991818f3038ce24a`. The sole integer
`details.id`, for station `2071`, is normalized to String so the native Parquet column has one scalar
dtype. Canonical artefacts are built only from the committed native table plus origins.

The publisher documentation evidence URL is `https://api.existenz.ch/#hydro`; the fragment is not sent
to the server. The byte-identical capture `tests/test_data/ch_foen_api_docs.html` records a direct HTTP
200 response from `https://api.existenz.ch/` at `2026-08-03T12:31:42Z` with no redirect. Its raw-byte digest and source
binding are pinned by the origin-evidence receipt and catalogue tests.

## Catalogue Mapping

| Native field | Canonical target | Decision |
| --- | --- | --- |
| top-level `name` | `provider_id`, `station_id` | Exact source station identity; no fallback identity is synthesized. |
| `details.lat`, `details.lon` | `latitude`, `longitude` | Direct numeric coordinates with no transformation. |
| Horizontal CRS | `crs` | `unknown`; the publisher documentation does not state a horizontal CRS. |
| All other location fields | Native only | Preserved in source vocabulary, including names, water-body values, Swiss coordinates, and the normalized `details.id`. |

The packaged catalogue contains three source-published instantaneous products and 738 station-product
rows. Availability is `unknown` because the locations endpoint does not expose per-variable station
availability.

## Product Dictionary

The packaged catalogue advertises three canonical instantaneous products. It does not advertise daily
means because the source location catalogue publishes no daily aggregates and RivRetrieve does not
harmonise judgement by deriving them.

| Native field | Canonical product ID | Unit |
| --- | --- | --- |
| `flow`, fallback `flow_ls` | `discharge_instantaneous` | m³/s |
| `height_abs`, fallback `height` | `stage_instantaneous` | m |
| `temperature` | `water_temperature_instantaneous` | °C |

## Observation Retrieval

M4 replaced the placeholder observation path with real `ch_foen` retrieval behind the provider handle and the package-root convenience wrapper. The public paths are now:

- `rr.provider("ch_foen").observations(...)`, the primary provider-handle call path.
- `rr.observations(provider="ch_foen", ...)`, a delegation-only wrapper added in M4 step 03.

The implementation preserves the legacy SwitzerlandFetcher mechanics that matter for V1:

| Behavior | M4 target behavior | Legacy evidence |
| --- | --- | --- |
| Historical product/native-field mapping | The retired observation work covered daily and instantaneous variants using `flow`, `flow_ls`, `height_abs`, `height`, and `temperature`; only the three instantaneous products are packaged now. | `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python` @ `cd9b030:rivretrieve/switzerland.py:22-29`, `:44-81` |
| Windowing | Observation calls decompose request ranges into 366-day windows before querying. | `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python` @ `cd9b030:rivretrieve/switzerland.py:43`, `:97-110` |
| Query shape | Flux queries target `existenzApi`, measurement `hydro`, one station, the configured native fields, and an exclusive stop date. | `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python` @ `cd9b030:rivretrieve/switzerland.py:175-188` |
| Transport loop | The legacy fetcher posts each station/product/window query with CSV accept headers and token authorization. M4 keeps runtime calls transport-injectable for offline tests. | `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python` @ `cd9b030:rivretrieve/switzerland.py:190-218` |
| CSV parse shape | CSV rows become station, native parameter, timestamp, and value records. M4 keeps canonical result timestamps timezone-aware UTC rather than returning legacy naive pandas indexes. | `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python` @ `cd9b030:rivretrieve/switzerland.py:220-241` |
| Fallback and conversion | Preferred native fields win per timestamp; `flow_ls` is converted from L/s to m3/s when used as discharge fallback. | `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python` @ `cd9b030:rivretrieve/switzerland.py:251-269` |
| Daily and instant products | Daily products aggregate by day; instant products keep the date range as an inclusive day selection with exclusive next-day stop. | `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python` @ `cd9b030:rivretrieve/switzerland.py:290-297`, `:348-352` |

Fixture-backed M4 tests pin the translated behavior without live network: station `2016` daily temperature, station `2206` instantaneous discharge with `flow_ls` fallback and L/s -> m3/s conversion, and station `2282` instantaneous stage. The legacy example uses gauge `2016` with daily discharge and water temperature, while legacy docs only expose an automodule stub: `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python` @ `cd9b030:examples/test_switzerland_fetcher.py:9-20` and `cd9b030:docs/fetchers/switzerland.rst:1-5`.

## Annotation Schema

M4 declares and emits non-empty row and series annotation schemas for `ch_foen`. The old M3 note that annotation schemas were empty is no longer true.

Row annotations describe per-observation facts such as native field, raw/native value, conversion, overlap, conflict, and provenance of the row-level source field. Series annotations describe per-station/product facts such as returned time range, resolved timezone, native unit returned, fallback use, timezone mismatch flags, provider query fields, and data-window summaries. The provider handle continues to validate emitted annotation names against the declared schemas after provider execution.

## Issues

Observation retrieval uses the M2 two-channel contract: fatal contract/parser/schema problems raise fatal exceptions, while provider/data problems are recoverable `Issue` rows by default and honor `on_issue`. The wrapper does not catch, transform, or reroute either channel.

Recoverable observation issues include missing data, partial responses, failed source requests, gaps, overlap, fallback conflicts, timezone ambiguity, and unit-conversion ambiguity. `on_issue="warn"` emits runtime warnings for recoverable issues, `on_issue="raise"` raises `IssuePolicyError`, and `on_issue="ignore"` returns the issues without warning.

The old placeholder issue code `observations_not_yet_implemented` was removed in M4 because provider-handle observations now delegate to real retrieval.

## Token Handling

The Influx token is treated as a public service credential because upstream legacy commit `cd9b030` intentionally restored the literal. The target implementation keeps it isolated in the observation client path, sanitizes authorization data from provenance/raw metadata, and keeps package import plus catalogue reads offline.

`rr.map_stations()` in M5 must not depend on this token path. Station catalogue data is already packaged, and observation token/client setup is only reachable through observation retrieval.

## M5/V1 Map Closeout

`rr.map_stations(...)` shipped as a map view over packaged station catalogue rows. It consumes the existing station fields, including `provider_id`, `station_id`, `name`, `latitude`, `longitude`, and `country`, and applies optional provider, country, and bounding-box filters before rendering. It does not read product rows, station-product rows, observation results, live catalogue paths, or provider-native observation metadata.

The old M5 token concern is closed for V1: token handling remains observation-only. Map rendering does not resolve or sanitize the Influx token because it never enters the observation transport/client path.

## Schema Divergence from Legacy Wide-Form Output

Legacy `SwitzerlandFetcher.get_data(...)` returns one pandas time-indexed, wide-form dataframe per gauge/variable call and names the value column after the legacy variable. M4 returns the shared long-form `ObservationResult.data` shape with canonical `station_id`, `product_id`, UTC `time`, and `value`, plus row/series annotation tables and structured provenance.

This divergence is intentional. It keeps `ch_foen` inside the common RivRetrieve observation contract and leaves wide-form pandas export outside M4. M5 station mapping should consume station catalogues, not infer map semantics from legacy wide observation frames.

## Pain Points

| Issue | Status | M4 or maintenance action | Citation |
| --- | --- | --- | --- |
| Maintainer-only generator | `generate_catalogue.py` may read the live locations endpoint only when a maintainer invokes it; runtime package import and catalogue methods use packaged artifacts. | Keep generator out of package import and re-run it only when catalogue artifacts or provider-info capabilities change. | `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:23`, `tests/test_offline_import.py:7`, `tests/test_ch_foen_registration.py:55` |
| Offline import invariant | `import rivretrieve` must not import provider runtime modules or generators. | Preserve lazy default registration and keep any M4 observation code behind provider lookup/call paths. | `tests/test_offline_import.py:7`, `tests/test_ch_foen_registration.py:55`, `docs/discoveries.md:128` |
| Observation placeholder | Closed in M4. `observations_not_yet_implemented` is no longer an issue code and provider observations delegate to real retrieval. | Keep this closed; do not reintroduce placeholder behavior in wrapper or map work. | `tests/test_ch_foen_module.py:109`, `tests/test_ch_foen_module.py:140` |
| D6 path shadowing | Provider packages under `rivretrieve.providers` can shadow public callables. | Keep provider code under `rivretrieve._internal.providers`. | `docs/discoveries.md:128` |
| D7 Pydantic extras and `ty` | `extra="allow"` constructor kwargs are not visible to `ty`. | If M4 uses Pydantic extras, assert them through `model_validate({...})`, not constructor kwargs. | `docs/discoveries.md:144` |
| D8 catalogue encoding round-trip | Generator code must serialize JSON metadata before typed-frame construction. | Apply the same generator-side serialization/provenance audit to observation artifacts or metadata-like result fields. | `docs/discoveries.md:172` |
| D9 `Mapping` narrowing under `ty` | `isinstance(x, Mapping)` over JSON-loaded data erases useful types. | Use concrete `dict` / `list` checks in M4 parser code unless abstract polymorphism is required. | `docs/discoveries.md:158` |
| Capability flags | M4 updates `bulk_observations` to `true: 366-day window decomposition with stitched N x M station-product requests; partial failures reported as recoverable issues`. The three `live_*` catalogue flags remain `False`. | M5 conformance closeout should treat this as the new baseline and should not infer live catalogue support from it. | `src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json:1`, `tests/test_ch_foen_capabilities.py:9` |
