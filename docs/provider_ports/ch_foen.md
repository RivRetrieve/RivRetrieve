# ch_foen Provider Port Notes

These notes capture evidence and hand-off context from the M3 `ch_foen` reference provider port. They are not user documentation and not a new architecture contract; promote only shared harness commitments to [architecture.md](../../architecture.md).

## Source Endpoints

| Endpoint or source | M3 role | Credential status | Citation |
| --- | --- | --- | --- |
| Existenz.ch `/apiv1/hydro/locations` | Maintainer-side catalogue input for station metadata and the packaged station-product universe. Runtime catalogue calls read packaged artifacts only. | No token. | `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:15`, `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:177`, `src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json:1`, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:37-38 |
| Legacy SwitzerlandFetcher metadata parser | Reference for station field normalization from the locations payload. | No token. | thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:127-173 |
| Existenz.ch Influx archive query API | M4 observation background only; M3 does not call it. | Upstream `origin/switzerland` HEAD `cd9b030` (`Restore public Switzerland token`) intentionally restores a literal `INFLUX_TOKEN`, classifying it as a public service credential. Target M3 carries no token because it is catalogue-only. | `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/execution.md:81`, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:39-40, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:199-203 |
| BAFU/Existenz documentation and terms | M4 observation background and provenance context. | None in M3. | thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:30-34, `src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json:1` |

## Catalogue Mapping

| Legacy/source field | Canonical target | Provider metadata | Decision | Citation |
| --- | --- | --- | --- | --- |
| Payload station key and `details.id` | `StationCatalog.station_id` | `station_key`, `native_id` | Use `details.id` normalized to string, falling back to station key. | `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:62`, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:151-157 |
| `details.name` | `StationCatalog.name` | `name` | Preserve provider station name. | `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:64`, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:157 |
| `details["water-body-name"]` / `details["water_body_name"]` | No common station column | `water_body_name` | Retain as metadata because the common station schema has no river/water-body column. | `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:65`, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:152-158 |
| `details.lat`, `details.lon` | `StationCatalog.latitude`, `StationCatalog.longitude` | `latitude`, `longitude` | Use numeric latitude and longitude as required common fields. | `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:69`, `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:70`, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:159-160 |
| Legacy `COUNTRY`, `SOURCE` constants | `StationCatalog.country`; provider-info `name` | `country`, `source` | Preserve `"Switzerland"` and FOEN/BAFU source naming rather than introducing unscoped ISO or agency normalization. | `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:71`, `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:176-177`, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:41-42, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:163-164 |
| Legacy altitude and area placeholders | `StationCatalog.elevation_m`, `StationCatalog.drainage_area_km2` | `elevation_m`, `drainage_area_km2` | Store `None` in M3 because the locations endpoint does not provide these values; the canonical columns are nullable. | `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:77`, `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:78`, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:161-162 |
| Top-level fixture fields (`source`, `apiurl`, `opendata`, `license`) | No dedicated common columns | `api_source`, `api_url`, `open_data_url`, `license_url`; provider-info metadata JSON | Preserve as JSON metadata in packaged artifacts. | `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:73-76`, `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:183`, `src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json:1` |
| Six legacy variables from `VARIABLE_MAP` | Canonical V1 `ProductCatalog.product_id` rows | `legacy_variable`, `native_id`, `parameters`, `preferred_parameter`, `fallback_parameter`, `aggregate_daily` | All six map to canonical products; no `ch_foen`-specific product IDs and no dropped legacy SwitzerlandFetcher variables. | `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:155-170`, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:44-80 |
| Locations catalogue station universe x product dictionary | `StationProductCatalog` rows | `native_parameters`, `availability_source`, `availability_note` | Materialize `246 * 6 = 1476` rows with `availability="unknown"` because the locations endpoint does not expose per-variable station availability. | `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:127-153`, `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/execution.md:61` |

## Product Dictionary

M3 introduced no `ch_foen`-specific product IDs and dropped no legacy SwitzerlandFetcher variables. The six-product mapping follows step 02 plan section 3.4 (`docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:155`).

| Legacy variable | Native fields | Canonical product_id | M3 classification | M4 note |
| --- | --- | --- | --- | --- |
| `constants.DISCHARGE_DAILY_MEAN` | `flow`, fallback `flow_ls`; daily aggregation true | `discharge_daily_mean` | Canonical V1 | Confirm daily aggregation semantics when observation retrieval is implemented. |
| `constants.DISCHARGE_INSTANT` | `flow`, fallback `flow_ls`; daily aggregation false | `discharge_instantaneous` | Canonical V1 | Preserve fallback handling in parser tests. |
| `constants.STAGE_DAILY_MEAN` | `height_abs`, fallback `height`; daily aggregation true | `stage_daily_mean` | Canonical V1 | Confirm period anchoring and aggregation semantics. |
| `constants.STAGE_INSTANT` | `height_abs`, fallback `height`; daily aggregation false | `stage_instantaneous` | Canonical V1 | Preserve fallback handling in parser tests. |
| `constants.WATER_TEMPERATURE_DAILY_MEAN` | `temperature`; no fallback; daily aggregation true | `water_temperature_daily_mean` | Canonical V1 | Confirm daily aggregation semantics. |
| `constants.WATER_TEMPERATURE_INSTANT` | `temperature`; no fallback; daily aggregation false | `water_temperature_instantaneous` | Canonical V1 | Use as the simplest observation parser case. |

Legacy evidence: thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:22-29 and thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:44-80.

## Observation Retrieval

M4 replaced the placeholder observation path with real `ch_foen` retrieval behind the provider handle and the package-root convenience wrapper. The public paths are now:

- `rr.provider("ch_foen").observations(...)`, the primary provider-handle call path.
- `rr.observations(provider="ch_foen", ...)`, a delegation-only wrapper added in M4 step 03.

The implementation preserves the legacy SwitzerlandFetcher mechanics that matter for V1:

| Behavior | M4 target behavior | Legacy evidence |
| --- | --- | --- |
| Product/native-field mapping | The six canonical products use `flow`, `flow_ls`, `height_abs`, `height`, and `temperature` according to the product dictionary above. | `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python` @ `cd9b030:rivretrieve/switzerland.py:22-29`, `:44-81` |
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
