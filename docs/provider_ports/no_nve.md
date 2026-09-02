# no_nve Provider Port Notes

These notes capture evidence and context from the `no_nve` port of the NVE HydAPI provider. They are not user documentation and not a new architecture contract; promote only shared harness commitments to [ADRs](../adr/).

## Source

Legacy source: `https://github.com/kratzert/RivRetrieve-Python/blob/main/rivretrieve/norway.py` (`NorwayFetcher`).

## Endpoints

| Endpoint | Role | Credential | Notes |
| --- | --- | --- | --- |
| `https://hydapi.nve.no/api/v1/Stations?Active={0\|1}` | Maintainer catalogue generation (active + inactive stations). | `NVE_API_KEY` HTTP header `X-API-Key`. | Called twice (active=1, active=0) to get both active and inactive stations. Response has `stationId`, `stationName`, `latitude`, `longitude`, `masl`, `drainageBasinArea`, `riverName`, `active`, `seriesList`. |
| `https://hydapi.nve.no/api/v1/Observations` | Runtime observation retrieval. | Same `NVE_API_KEY`. | Query params: `StationId`, `Parameter`, `ResolutionTime`, `ReferenceTime` (ISO 8601 interval `start/end`). |

## Authentication

NVE HydAPI requires an API key in the `X-API-Key` HTTP header. The key is read from the `NVE_API_KEY` environment variable. If absent, `retrieve_observations()` returns empty data with an `auth_missing` warning issue (same pattern as `br_ana`). No token caching is needed — the key itself is static per session.

The key is **never** written to provenance or raw metadata.

To obtain an API key: https://hydapi.nve.no/UserDocumentation/#termsofuse

## Product Catalogue Mapping

NVE exposes three parameters and three resolutions, giving 9 product combinations. All canonical V1 products match; hourly products use provider-specific IDs since no canonical hourly products exist in the V1 dictionary.

| NVE Parameter | ResolutionTime (min) | Product ID | Canonical? | V1 dictionary | Notes |
| --- | --- | --- | --- | --- | --- |
| 1000 (water level) | 1440 | `stage_daily_mean` | Yes | Yes | |
| 1000 | 60 | `stage_hourly_mean` | No — provider-specific | No hourly stage in V1 | Same pattern as `jp_mlit`. |
| 1000 | 0 | `stage_instantaneous` | Yes | Yes | |
| 1001 (discharge) | 1440 | `discharge_daily_mean` | Yes | Yes | |
| 1001 | 60 | `discharge_hourly_mean` | No — provider-specific | No hourly discharge in V1 | Same pattern as `jp_mlit`. |
| 1001 | 0 | `discharge_instantaneous` | Yes | Yes | |
| 1003 (water temperature) | 1440 | `water_temperature_daily_mean` | Yes | Yes | |
| 1003 | 60 | `water_temperature_hourly_mean` | No — provider-specific | No hourly water_temperature in V1 | |
| 1003 | 0 | `water_temperature_instantaneous` | Yes | Yes | |

`native_id` in the product catalogue is `"{parameter_id}:{resolution_time}"`, e.g. `"1001:1440"`.

## Station-Product Availability (NVE seriesList)

NVE is unique among ported providers in that the `/Stations` response contains a `seriesList` field for each station, listing available parameter+resolution pairs. This allows the catalogue generator to materialise accurate `available` / `unavailable` rows rather than `unknown` for all.

- Stations with a non-empty `seriesList`: `available` for each matched `(parameter_id, resolution_time)` pair; `unavailable` for the rest.
- Stations with an empty `seriesList` (`[]`): all products marked `unavailable`.
- Stations with no `seriesList` key at all: all products marked `unknown`.

## Timestamp Handling

NVE API timestamps include an explicit ISO 8601 timezone offset (e.g. `+01:00` for CET, `+02:00` for CEST in summer).

| Resolution | Handling | Series annotation `timezone_source` | Issue emitted |
| --- | --- | --- | --- |
| Daily (1440) | Date portion extracted from ISO string before offset conversion → UTC midnight `YYYY-MM-DD T00:00:00Z`. This preserves the Norwegian calendar day regardless of UTC offset. | `date_only_utc_midnight` | `date_only_timestamp` (warning) |
| Hourly (60) / Instantaneous (0) | Full ISO 8601 string with offset parsed by `datetime.fromisoformat()`; converted to UTC with `.astimezone(UTC)`. | `provider_timestamp_offset` | `timezone_local_to_utc` (info) |

**Daily date extraction rationale**: `2023-01-01T00:00:00+01:00` represents the start of the Norwegian calendar day `2023-01-01`. Converting to UTC first yields `2022-12-31T23:00:00Z`, which would place the daily value on `2022-12-31` — the wrong date. Extracting `2023-01-01` from the string before any timezone arithmetic correctly gives `2023-01-01T00:00:00Z`.

The legacy `NorwayFetcher` used `pd.to_datetime(..., utc=True).dt.date` which incorrectly assigned the UTC date (one day earlier in winter). The port fixes this by using the local calendar date directly.

## Units

NVE provides all values in standard units with no conversion required:
- Stage: metres (m)
- Discharge: m³/s
- Water temperature: °C

## Windowing

- Daily (resTime=1440): yearly windows, `YYYY-01-01/YYYY-12-31` ISO date intervals.
- Hourly (resTime=60): monthly windows, `YYYY-MM-01/YYYY-MM-DD`.
- Instantaneous (resTime=0): monthly windows (same as hourly, since NVE allows arbitrary date ranges but monthly chunks avoid excessively large requests).

## Packaged Catalogue Status

`no_nve` is withheld from certified catalogue generation pending the credentialed native acquisition
owned by [issue 90](https://github.com/RivRetrieve/RivRetrieve/issues/90). The packaged catalogue keeps
provider metadata but emits empty product, station, and station-product tables with structured
`no_acquisition_record_established` provenance. `tests/test_data/no_nve_metadata.json` is a three-row
parser fixture only and must not generate packaged values. See
[`../catalogue-provenance.md`](../catalogue-provenance.md) for the maintenance command and certification
boundary.

A future authenticated `/Stations` response may refresh and attest a committed native table. It must
not directly generate canonical artefacts, and the API key must not be recorded.

## Pain Points

| Issue | Resolution |
| --- | --- |
| `str, Enum` vs `StrEnum` | Issue codes must use `StrEnum` (not `str, Enum`) so that `str(code)` returns the value string, not the `ClassName.MEMBER` repr. Caught by test. See D7 in discoveries.md for related Pydantic extras issue. |
| Daily timezone: UTC-first vs date-extraction | The legacy `NorwayFetcher` converted timestamps to UTC then stripped to date, which gives the wrong Norwegian calendar day in winter (CET = UTC+1). Fixed by extracting the date string before offset conversion. Documented in this file. |
| `live_stations=True` vs harness routing | Initially set `live_stations=True` since NVE has a live `/Stations` endpoint. The harness raises `LiveCatalogueRoutingNotImplementedError` when this flag is set but no runtime live routing exists. Reverted to `live_stations=False` — the `generate_catalogue_from_live()` function is a maintainer tool, not a runtime catalogue path. Architecture `§5` note: declaring capability and routing capability are separate. |
| Auth_missing early exit | If no `NVE_API_KEY`, `retrieve_observations` returns early before `resolve_product_policy` is called. Unsupported-product test must use a client with fake credentials to exercise that path. |

## Architecture Impact

None. The `StrEnum` pattern, date extraction before UTC conversion, `seriesList` availability inference, and `auth_missing` early return are all provider-specific. No shared harness gap discovered.
