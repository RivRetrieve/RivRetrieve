# ca_eccc Provider Port Notes

## Source Endpoints

| Endpoint | Role | Auth | Notes |
|---|---|---|---|
| `https://api.weather.gc.ca/collections/hydrometric-stations/items` | Catalogue generation + station metadata | None — public open data | OGC Features API; paginated with `limit`/`offset`. Coordinates in GeoJSON `geometry.coordinates` (lon, lat), **not** in `properties`. |
| `https://api.weather.gc.ca/collections/hydrometric-daily-mean/items` | Observation retrieval | None | Filter by `STATION_NUMBER` and `datetime=YYYY-MM-DD/YYYY-MM-DD`. Returns GeoJSON FeatureCollection with `DISCHARGE`, `LEVEL`, `DISCHARGE_SYMBOL`, `LEVEL_SYMBOL` in each feature's `properties`. |

## Decision: OGC API vs HYDAT SQLite

The legacy `CanadaFetcher` (Python) and `adapter_CA_ECCC.R` both download the full HYDAT SQLite database (~1 GB zip) on first use. That approach:
- Is too heavy for a Python package runtime download
- Requires a web scrape to find the latest date-stamped URL
- Doesn't fit the REST/JSON pattern used by every other RivRetrieve provider

The ECCC OGC Features API at `api.weather.gc.ca` exposes the same data via standard REST. No authentication required. This port uses the OGC API for both catalogue generation and observation retrieval.

### ⚠ Known limitation: OGC API has incomplete historical coverage

The OGC `hydrometric-daily-mean` collection does **not** contain the full HYDAT archive. Many stations have gaps covering decades of historical data that exist in HYDAT but are not present in the OGC endpoint.

**Confirmed example — station `08GA031` (Capilano River at Canyon, BC):**

| Period | OGC API | HYDAT |
|---|---|---|
| 1929–1956 | ✅ Available | ✅ Available |
| 1957–2022 | ❌ Not in OGC | ✅ Available |
| 2023–present | ✅ Available | ✅ Available |

The legacy Python test `test_canada.py` uses `08GA031` with `start=2010-01-01` and passes because it queries HYDAT directly. The same request via `ca_eccc` returns empty because 2010 data is simply not in the OGC collection.

**Practical impact:** `ca_eccc` is suitable for:
- Recent/current operational data (typically last few years)
- Stations that happen to have their full record in the OGC collection
- Catalogue discovery (station list, metadata)

`ca_eccc` is **not** suitable as a drop-in replacement for HYDAT when full historical archives are needed. Users requiring complete historical records should use the HYDAT SQLite approach directly.

**Mitigation considered but not implemented:** A hybrid approach (OGC for recent + HYDAT for historical) was considered. Rejected for V1 because it reintroduces the HYDAT download problem. This is a known limitation documented here for future consideration.

## Catalogue Mapping

| Source field | Canonical target | Notes |
|---|---|---|
| `properties.STATION_NUMBER` | `station_id` | Native ID; e.g. `02GA010` |
| `properties.STATION_NAME` | `name` | |
| `geometry.coordinates[1]` | `latitude` | GeoJSON lon, lat order — lat is index 1 |
| `geometry.coordinates[0]` | `longitude` | |
| `properties.DRAINAGE_AREA_GROSS` | `drainage_area_km2` | Nullable; ECCC provides gross drainage area |
| `properties.PROV_TERR_STATE_LOC` | `metadata.province` | Province/territory code, e.g. `ON`, `BC` |
| `properties.STATUS_EN` | `metadata.hyd_status` | Live API: `"Active"` / `"Discontinued"`. Fixture may have `HYD_STATUS`: `"A"` / `"D"` — generator handles both. |
| `properties.REAL_TIME` | `metadata.real_time` | Live API returns int (0/1); fixture uses `"Y"`/`"N"`. Generator coerces to string. |
| (not in API) | `elevation_m` | Always null — ECCC OGC stations endpoint does not provide elevation |

## Products

Both products use the `hydrometric-daily-mean` OGC collection. One API call per (station, window) returns **both** DISCHARGE and LEVEL — the retrieval layer caches the raw response so requesting both products for the same station/window makes only one HTTP call.

| Product ID | OGC field | Symbol field | Unit | Notes |
|---|---|---|---|---|
| `discharge_daily_mean` | `DISCHARGE` | `DISCHARGE_SYMBOL` | m³/s | No conversion. |
| `stage_daily_mean` | `LEVEL` | `LEVEL_SYMBOL` | m | No conversion. |

## Timestamps

`DATE` field is date-only (`YYYY-MM-DD`). Follows the established `date_only_timestamp` pattern (same as `lt_lhmt`, `fr_hubeau`, `br_ana`, `jp_mlit` daily):
- Interpreted as UTC midnight `T00:00:00Z`
- `warning`-severity `date_only_timestamp` issue emitted per parser call
- Series annotation: `timezone_source = "date_only_utc_midnight"`, `date_only_timestamp_flag = "true"`

ECCC does not document the true period anchor (calendar day in what timezone — likely Eastern or local station time). UTC midnight is a safe convention consistent with all other daily-only providers.

## Quality Flags

`DISCHARGE_SYMBOL` and `LEVEL_SYMBOL` carry ECCC quality codes:
- `""` (empty) — no flag
- `"A"` — Estimated
- `"B"` — Ice conditions
- `"D"` — Dry (no flow)
- `"E"` — Estimated (ice affected)
- `"R"` — Revised

Preserved as `quality_flag` row annotation. Not harmonized across providers (V1 policy).

## Station-Product Availability

All rows are `availability = "unknown"`. The OGC stations endpoint does not expose per-variable availability (unlike NVE HydAPI's `seriesList`). Users requesting a station/product pair may encounter HTTP 404 or empty results when the station does not measure that variable.

## Live Catalogue

`live_stations = False` — the generator is a maintainer tool. Runtime catalogue paths read packaged Parquet artifacts.

The `--live` flag in `generate_catalogue.py` fetches `hydrometric-stations/items` paginated (limit=10000) until `numberReturned < limit`.

## Pagination

Both the stations endpoint and the daily-mean observation endpoint use OGC standard `limit`/`offset` pagination. The observation client follows pages until `numberReturned < page_size`. The fixture-backed test uses a small single-page response (3 features).

## Windowing

Annual windows: `YYYY-01-01/YYYY-12-31`. Inclusive on both ends per the OGC `datetime` interval parameter.

## Station Count

8055 stations from live OGC catalogue (2026-06-04). All have valid coordinates (stations without geometry are excluded by the generator's lat/lon guard).

## Surprises and Pain Points

| Issue | Detail |
|---|---|
| Coordinates in geometry, not properties | `LATITUDE`/`LONGITUDE` are **not** in `properties`. Must extract from `feature["geometry"]["coordinates"]` (GeoJSON lon/lat order). The fixture uses plain property dicts with `LATITUDE`/`LONGITUDE` for simplicity; the generator handles both formats. |
| Status field name difference | Live API uses `STATUS_EN` (`"Active"/"Discontinued"`); fixture/HYDAT-style uses `HYD_STATUS` (`"A"/"D"`). Generator checks `STATUS_EN` first, falls back to `HYD_STATUS`. |
| `REAL_TIME` is int in live API | Live returns `0`/`1`; fixture uses `"Y"`/`"N"`. Generator coerces to string. |
| Response cache deduplication | Both products (discharge, stage) are in the same OGC response. The retrieval layer uses a `dict` keyed by `(station_id, begin_date, end_date)` to avoid fetching the same page twice when both products are requested. This is documented in provenance `decomposition` field. |
| No elevation | ECCC OGC stations API does not expose elevation (masl). Always `None`. |
| No per-variable availability | Cannot materialize `available`/`unavailable` station-product rows at catalogue-generation time. All rows are `unknown`. |
