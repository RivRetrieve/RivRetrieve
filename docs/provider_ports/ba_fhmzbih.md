# ba_fhmzbih Provider Port Notes

Port of the legacy Python `BosniaHerzegovinaFetcher` (`thirdparty/RivRetrieve-Python` @ `codex-bosnia-and-herzegovina:rivretrieve/bosnia_herzegovina.py`) and reference for the equivalent R `adapter_BA_AVPS.R` (https://github.com/bafg-bund/hydrodownloadR). Provider ID `ba_fhmzbih` follows the `<country_code>_<agency>` convention for the Federal Hydrometeorological Institute of Bosnia and Herzegovina (FHMZBiH), which operates the `vodostaji.voda.ba` portal.

## Source Endpoints

| Endpoint | Role | Auth | Notes |
|---|---|---|---|
| `https://vodostaji.voda.ba/data/internet/layers/20/index.json` | Catalogue generation — station metadata snapshot | None | JSON array; one row per (station, parameter) timeseries — 60 unique stations as of 2026-06-08. Fields used: `metadata_station_no`, `metadata_station_name`, `metadata_river_name`, `metadata_catchment_name`, `metadata_station_latitude/longitude/elevation`, `metadata_CATCHMENT_SIZE`. |
| `https://vodostaji.voda.ba/data/internet/stations/{group}/{station_id}/{code}/{file}` | Observation retrieval — per-station-parameter Excel workbook | None | `group` is a numbered shard (1–10), `code` is `Q`/`H`/`WT`, `file` is `Q_1Y.xlsx`/`H_1Y.xlsx`/`Tvode_1Y.xlsx`. Always returns a rolling ~1-year window of hourly data (confirmed live: 8631 rows for station 4510/Q on 2026-06-08). |

Both endpoints were exercised live during this port (not just against fixtures): the metadata endpoint returned 60 stations and the workbook endpoint returned a real 124 KB xlsx for station 4510 — see "Live verification" below.

## Known Limitation: Rolling 1-Year Window Only

**The portal does not support arbitrary date-range queries.** Each `<code>_1Y.xlsx` workbook always contains a fixed rolling window of hourly observations (~8600 rows, ~1 year) ending at the most recent reading — there is no query parameter to request historical periods outside this window. This mirrors a constraint also present in `pl_imgw` and `ca_eccc` (data-coverage limits), but here it applies to *every* request, not just historical gaps.

Consequences for the port:
- `retrieve_observations()` fetches the workbook once per `(station_id, parameter_code)` — shared across the instantaneous and daily-mean variants of the same product — then filters/aggregates to the requested window.
- Requests whose window does not overlap the available data emit a recoverable `requested_range_beyond_window` warning issue (with `available_local_start`/`available_local_end` details) and return an empty series for that station/product.
- `bulk_observations` capability metadata documents this constraint explicitly so callers do not assume historical queries work.

## Station Group Discovery

The portal shards station workbooks across ten numbered "groups" (`/stations/{1..10}/...`); the group for a given station is **not** exposed in the metadata snapshot. `BaFhmzbihObservationClient.fetch_workbook()` probes groups 1–10 in order, returns the first 200 response with a non-empty body, and caches the discovered group per station-id for the lifetime of the client instance (live-verified: station 4510 resolves to group 4). A `station_group` series annotation records which group served each series, and `station_group_not_found` is emitted as a recoverable issue if every group probe 404s.

## Catalogue Mapping

| Source field | Canonical target | Notes |
|---|---|---|
| `metadata_station_no` | `station_id` | String station code, e.g. `"4510"` |
| `metadata_station_name` | `name` | Station name (e.g. "HS Kaloševići") |
| `metadata_river_name` | `metadata.river_name` | River name |
| `metadata_catchment_name` | `metadata.catchment_name` | Catchment/sub-basin name |
| `metadata_station_latitude`, `metadata_station_longitude` | `latitude`, `longitude` | Numeric strings parsed to float; stations without valid coordinates excluded |
| `metadata_station_elevation` | `elevation_m` | Often an empty string in the live snapshot — parsed to `None` when not numeric |
| `metadata_CATCHMENT_SIZE` | `drainage_area_km2` | String like `"123.4 km²"` — the `km²` suffix is stripped and the remainder parsed as a float |

## Products

All six V1 canonical products are mapped — three observed properties (`discharge`, `stage`, `water_temperature`) each with `instantaneous` and `daily_mean` variants. Each pair shares one workbook file.

| Product ID | Parameter code | Workbook file | Native unit | Canonical unit | Conversion |
|---|---|---|---|---|---|
| `discharge_instantaneous` / `discharge_daily_mean` | `Q` | `Q_1Y.xlsx` | m³/s | m³/s | none |
| `stage_instantaneous` / `stage_daily_mean` | `H` | `H_1Y.xlsx` | cm | m | ÷100 |
| `water_temperature_instantaneous` / `water_temperature_daily_mean` | `WT` | `Tvode_1Y.xlsx` | °C | °C | none |

`derived` is `False` and `derivation_method` is `None` for all six products in the packaged catalogue, matching the convention used by `br_ana`/`no_nve`/`pl_imgw` (the daily-mean variants are products in their own right, not flagged as harness-derived).

## Workbook Format

Each `*_1Y.xlsx` is a single-worksheet Excel file with eight descriptive header rows (station name, parameter, unit symbol, row count, a blank separator row, and a `#Timestamp`/`Value` column header), followed by one `(naive datetime, float)` row per hourly observation. The parser (`openpyxl`, `read_only=True, data_only=True`) skips the first eight rows and reads `(timestamp, value)` pairs, emitting a recoverable `invalid_row` warning for any row that fails to parse as `(datetime, float)`.

`openpyxl` (and its `et-xmlfile` dependency) was added to the project via `uv add openpyxl` — no prior dependency in this repository could read `.xlsx` files (plain `pandas`/`polars` cannot without an Excel engine, and `fastexcel` is also not a dependency).

## Timestamps and Timezone (Inferred — Europe/Sarajevo)

Workbook timestamps are **naive local time with no UTC offset** — the xlsx contains plain `datetime` cells, not ISO strings with an offset. The portal does not document the timezone anywhere in the workbook or the metadata snapshot.

The timezone was **inferred as `Europe/Sarajevo`** (CET/CEST, observing EU daylight-saving rules) from the live `layers/20/index.json` metadata feed, whose `L1_timestamp` field *does* carry an explicit offset for the same stations (e.g. `"2026-06-08T11:00:00.000+02:00"` — `+02:00` is CEST, consistent with Sarajevo in June). All offsets observed in a live snapshot were `+02:00`.

Because this is an inference rather than a documented fact, the port follows the user's instruction to surface it explicitly:

- An `info`-severity `timezone_local_to_utc` issue is emitted for every successful series, stating that timestamps were interpreted as `Europe/Sarajevo` and converted to UTC.
- Series annotations record `resolved_timezone = "UTC"`, `timezone_source = "local_to_utc_conversion"`, and `source_timezone = "Europe/Sarajevo"` so downstream consumers can see exactly what was assumed.
- Conversion uses `pl.col("time_local").dt.replace_time_zone("Europe/Sarajevo", ambiguous="earliest", non_existent="null").dt.convert_time_zone("UTC")`. DST spring-forward gap times become `null` and are dropped (verified live: `2025-03-30 02:30:00` localizes to `null`); `ambiguous="earliest"` resolves the autumn fall-back overlap deterministically.

## Daily-Mean Aggregation

`*_daily_mean` products are derived in `transform_series()` by grouping the localized hourly rows by **local** (`Europe/Sarajevo`) calendar day — not UTC day — averaging `raw_value`, then re-anchoring the result at local midnight before converting to UTC. This avoids the date-shift bug that the `no_nve` port found and fixed in the legacy `NorwayFetcher` (aggregating by UTC day shifts the reported date near midnight local time). The `aggregation` series annotation records `"local_calendar_day_mean"` vs `"instantaneous_hourly"` so the method is visible to callers.

## Unit Conversion

Stage values are published in centimetres and divided by `100.0` to produce the canonical metre unit; the original centimetre value is preserved in the `raw_value` row annotation (e.g. `82.2` cm → `0.822` m, live-verified against station 4510). Discharge (m³/s) and water temperature (°C) require no conversion.

## Station-Product Availability

All rows are `availability = "unknown"`. The metadata snapshot does not indicate which parameters a given station actually reports — in practice some stations' workbooks for a given parameter return zero data rows (e.g. station 4510's water-temperature workbook is empty both in the upstream test fixture and in the live response captured 2026-06-08). The retrieval path treats an empty-but-successfully-fetched workbook as `missing_data`, distinct from a `station_group_not_found` failure.

## Live Verification

Per the project convention of confirming downloads "really work" before declaring a port complete (and not repeating the `th_thaiwater` mistake where downloads were silently not happening), this port was exercised against the live portal during development:

- `generate_catalogue_from_live()` fetched `layers/20/index.json` and produced 60 stations, 6 products, and 360 station-product rows, all passing harness validation — these are the artifacts packaged in `catalogue/`.
- `BaFhmzbihObservationClient.fetch_workbook("4510", "Q", "Q_1Y.xlsx")` resolved to group `4`, returned HTTP 200 and 124,674 bytes, and parsed into 8,631 valid hourly rows spanning 2025-06-08 through 2026-06-07.
- A full `retrieve_observations()` call against live data for station 4510 (discharge, stage, water-temperature, May–June 2026) returned 1,666 rows, three `timezone_local_to_utc` info issues, one `missing_data` warning for the empty water-temperature workbook, and correctly UTC-converted/aggregated daily-mean values (e.g. `2026-04-29 22:00:00 UTC` anchors `2026-04-30` local midnight in CEST).

## Live Catalogue

`live_stations = False`, `live_products = False`, `live_station_products = False`. The generator is maintainer-only; runtime catalogue reads packaged Parquet artifacts. The live guard requires at least 30 stations (`MIN_LIVE_STATIONS`).

## Surprises and Pain Points

| Issue | Detail |
|---|---|
| No xlsx-reading dependency | The project had no Excel reader; `openpyxl` was added via `uv add openpyxl`. |
| Undocumented station→group mapping | The portal shards stations across ten numbered groups with no published lookup; the client must probe and cache. |
| No date-range query support | Every workbook always returns the same ~1-year rolling window — see "Known Limitation" above. This is a hard constraint of the source, not a parsing or pagination issue. |
| Inferred timezone | Workbook timestamps carry no offset; `Europe/Sarajevo` was inferred from a sibling feed's `L1_timestamp` field and is surfaced via an `info` issue plus series annotations rather than asserted as fact. |
| Empty per-parameter workbooks | A station can have a valid, reachable workbook for a parameter it does not actually measure (zero data rows after the 8-row header). Treated as `missing_data`, not a fetch failure. |
| `metadata_station_elevation` often blank | The live metadata snapshot frequently has `""` for elevation; parsed to `None` rather than `0.0`. |
| `metadata_CATCHMENT_SIZE` is a formatted string | e.g. `"123.4 km²"` — requires stripping the unit suffix before parsing as a float. |
