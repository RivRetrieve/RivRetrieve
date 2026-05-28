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

## Annotation

Row and series annotation schemas are empty in M3 by design: `ch_foen` is catalogue-only and its observation path is a non-raising placeholder. The empty schemas are explicit module behavior and are covered by `tests/test_ch_foen_module.py:43` and `tests/test_ch_foen_module.py:47`, with implementation at `src/rivretrieve/_internal/providers/ch_foen/module.py:68` and `src/rivretrieve/_internal/providers/ch_foen/module.py:72`.

M4 owns real observation annotations. Any row or series annotation emitted by the M4 observation implementation must be declared because the M2 provider handle always validates annotation names after provider execution.

## Issues

| Issue | Status | M4 or maintenance action | Citation |
| --- | --- | --- | --- |
| Token handling | Upstream `cd9b030` classifies the legacy literal token as public by restoring it intentionally; M3 target carries no token because it is catalogue-only. | At M4 start, confirm upstream's public-token classification still holds, then choose embedding mechanics (`literal`, configuration override, or both). This is not framed as "decide secret vs public." | `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/execution.md:81`, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:40, thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:200 |
| Maintainer-only generator | `generate_catalogue.py` may read the live locations endpoint only when a maintainer invokes it; runtime package import and catalogue methods use packaged artifacts. | Keep generator out of package import and re-run it only when catalogue artifacts or provider-info capabilities change. | `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:23`, `tests/test_offline_import.py:7`, `tests/test_ch_foen_registration.py:55` |
| Offline import invariant | `import rivretrieve` must not import provider runtime modules or generators. | Preserve lazy default registration and keep any M4 observation code behind provider lookup/call paths. | `tests/test_offline_import.py:7`, `tests/test_ch_foen_registration.py:55`, `docs/discoveries.md:128` |
| Observation placeholder | `observations()` returns empty data/annotations plus an `observations_not_yet_implemented` issue. | Replace with real observation retrieval and remove placeholder-only expectations in M4. | `src/rivretrieve/_internal/providers/ch_foen/module.py:76`, `tests/test_ch_foen_module.py:51` |
| D6 path shadowing | Provider packages under `rivretrieve.providers` can shadow public callables. | Keep provider code under `rivretrieve._internal.providers`. | `docs/discoveries.md:128` |
| D7 Pydantic extras and `ty` | `extra="allow"` constructor kwargs are not visible to `ty`. | If M4 uses Pydantic extras, assert them through `model_validate({...})`, not constructor kwargs. | `docs/discoveries.md:144` |
| D8 catalogue encoding round-trip | Generator code must serialize JSON metadata before typed-frame construction. | Apply the same generator-side serialization/provenance audit to observation artifacts or metadata-like result fields. | `docs/discoveries.md:172` |
| D9 `Mapping` narrowing under `ty` | `isinstance(x, Mapping)` over JSON-loaded data erases useful types. | Use concrete `dict` / `list` checks in M4 parser code unless abstract polymorphism is required. | `docs/discoveries.md:158` |
| Capability flags | M3 provider info honestly reports all live catalogue flags `False` and `bulk_observations="false"`. | M4 must revisit `bulk_observations` when observations land; if any provider-info capability changes, regenerate and commit packaged `provider.json`. The three `live_*` catalogue flags should stay `False` unless M4 adds live catalogue calls. | `src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json:1`, `tests/test_ch_foen_capabilities.py:9` |
