# th_thaiwater Provider Port Notes

These notes capture evidence and handoff context from the `th_thaiwater` provider port. They are not user documentation and not an architecture contract; promote shared harness commitments to [architecture.md](../../architecture.md) only with concrete evidence.

## Source Endpoints

| Endpoint | Role | Credential | Notes |
| --- | --- | --- | --- |
| `https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_load` | Maintainer-side native-table refresh input; returns all telemetered stations in one response. | None. Public ThaiWater Open API. | Canonical artefacts are built offline from committed `native.parquet` plus origins. |
| `https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_graph` | Runtime observation retrieval. Query params: `station_type=tele_waterlevel`, `station_id`, `start_date` (YYYY-MM-DD), `end_date` (YYYY-MM-DD). | None. | Returns a `data.graph_data` list with `datetime`, `value` (stage in m), and `discharge` (m³/s) fields per row. |

## Timezone — Critical Quirk

ThaiWater timestamps in `graph_data[].datetime` are **naive local Bangkok time** (format `"YYYY-MM-DD HH:MM:SS"`, no timezone suffix). They are NOT UTC.

Port decision: parse with `datetime.strptime`, localize to `Asia/Bangkok` (`ZoneInfo("Asia/Bangkok")`), convert to UTC before storing. This means:

- Instantaneous products: Bangkok time → UTC (offset -7h). Example: `"2023-06-01 01:00:00"` Bangkok → `2023-05-31T18:00:00Z`.
- Daily products: group by Bangkok calendar date (after `dt.convert_time_zone("Asia/Bangkok").dt.truncate("1d")`), compute mean, store UTC of Bangkok midnight (= previous day 17:00Z).

This conversion is **known and documented** (not inferred), but per the timezone policy in the prompt, a structured `info`-severity issue (`timezone_local_to_utc`) is emitted per station-product series to record the conversion explicitly. Series annotations carry `timezone_source = "local_to_utc_conversion"` and `local_timezone = "Asia/Bangkok"`.

The legacy `ThailandFetcher` drops timezone after localizing (`.dt.tz_localize(None)`), storing naive Bangkok-time datetimes. The new port instead converts to UTC, which is the required behaviour per architecture.md §16 and the deliverable prompt.

## Catalogue Mapping

| Legacy / source field | Canonical target | Provider metadata | Decision |
| --- | --- | --- | --- |
| `station.id` | `provider_id`, `station_id` | Native only | Exact identity copy of the committed String value; `station.tele_station_oldcode` is not identity. |
| `station.tele_station_name.*` | No canonical column | Native only | Multilingual source values remain readable in `native.parquet`. |
| `station.tele_station_lat`, `station.tele_station_long` | `latitude`, `longitude` | Native only | Exact decimal values, cast only to canonical schema dtypes. Null values fail the build. |
| `river_name`, `geocode.*`, `basin.*`, `agency.*` | No canonical columns | Native only | Source vocabulary remains readable in `native.parquet`; RivRetrieve does not adjudicate these labels. |
| `station.tele_station_oldcode` | No canonical column | Native only | Preserved source station code; never substituted for `station.id`. |
| CRS | `crs = "unknown"` | Origin evidence | ThaiWater's captured coordinate-standard page specifies ISO 6709 formatting but no datum, CRS, EPSG code, or projection. |
| `station_type` | Build contract | Native only | Every native row must equal `tele_waterlevel`; any other value fails loudly. |

## Product Dictionary

All four ported products map to canonical V1 product IDs. No `th_thaiwater`-specific IDs were needed.

| Legacy variable | Native field | Aggregate | Canonical `product_id` |
| --- | --- | --- | --- |
| `STAGE_DAILY_MEAN` | `value` | True (Bangkok-day mean) | `stage_daily_mean` |
| `STAGE_INSTANT` | `value` | False (deduplicate by time) | `stage_instantaneous` |
| `DISCHARGE_DAILY_MEAN` | `discharge` | True (Bangkok-day mean) | `discharge_daily_mean` |
| `DISCHARGE_INSTANT` | `discharge` | False (deduplicate by time) | `discharge_instantaneous` |

Both `value` (stage, m) and `discharge` (m³/s) are natively already in SI units. No unit conversion required.

## Observation Retrieval

- **Windowing**: 365-day windows per `MAX_WINDOW_DAYS = 365`. Each station-product request is decomposed into (start_date, end_date) pairs.
- **Date filtering**: After parsing, records are filtered to the Bangkok-day range corresponding to the requested UTC start/end. This prevents off-by-one issues at window boundaries: the filter converts the requested UTC range to Bangkok calendar dates before clamping.
- **Daily aggregation**: Group by Bangkok calendar day (`dt.convert_time_zone("Asia/Bangkok").dt.truncate("1d")`), compute mean, then convert Bangkok midnight → UTC for storage.
- **Instantaneous deduplication**: `dedup.unique(subset=["time"], keep="last", maintain_order=True)` following the same intent as the legacy `drop_duplicates(keep="last")`.
- **HTTP 404**: Emits `http_not_found` warning issue (not fatal), matching the lt_lhmt / usgs_nwis / cz_chmi pattern.

## Station Count

825 stations at catalogue version `2026-08-02`, built offline from committed `native.parquet` plus the five station origins. Every native row is required to have `station_type == "tele_waterlevel"`, non-null latitude and longitude, and a unique String `station.id`; violations fail the build rather than being filtered, dropped, or deduplicated.

## Architecture.md Impact

None. The Bangkok→UTC conversion is provider-specific. The structured `timezone_local_to_utc` info-issue is provider-specific. Daily Bangkok-day aggregation is provider-specific. No shared harness gap discovered.

## Pain Points

| Issue | Status | Action |
| --- | --- | --- |
| Naive Bangkok timestamps | Documented; handled by zoneinfo conversion in parser. | Keep timezone annotation + issue; do not change. |
| Daily aggregation on Bangkok calendar days | Implemented in transform layer via `convert_time_zone("Asia/Bangkok").dt.truncate("1d")`. | Bangkok midnight UTC timestamps (e.g., 17:00Z) may look surprising to users; the series annotation `local_timezone = "Asia/Bangkok"` documents this. |
| No elevation or drainage area | `None` in both common columns; documented in metadata. | No action needed. |
| Multilingual station names | Preserved as flattened native columns in `native.parquet`. | Keep source language values unchanged. |
| Former station-type, null-coordinate, and duplicate-ID filters | Replaced by explicit fatal build contracts. | Never silently reject a native row during canonical generation. |
