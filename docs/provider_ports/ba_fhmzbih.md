# ba_fhmzbih Provider Port Notes

Port of the legacy Python `BosniaHerzegovinaFetcher` (`thirdparty/RivRetrieve-Python` @ `codex-bosnia-and-herzegovina:rivretrieve/bosnia_herzegovina.py`) and reference for the equivalent R `adapter_BA_AVPS.R` (https://github.com/bafg-bund/hydrodownloadR). Provider ID `ba_fhmzbih` follows the `<country_code>_<agency>` convention for the Federal Hydrometeorological Institute of Bosnia and Herzegovina (FHMZBiH), which operates the `vodostaji.voda.ba` portal.

## Source Endpoints

| Endpoint | Role | Auth | Notes |
|---|---|---|---|
| `https://vodostaji.voda.ba/data/internet/layers/20/index.json` | Native-table refresh — station metadata snapshot | None | JSON array containing stable `metadata_*` station fields and volatile `L1_*` timeseries fields. Refresh preserves the 18 stable source-named fields and omits the volatile group. |
| `https://vodostaji.voda.ba/data/internet/stations/{group}/{station_id}/{code}/{file}` | Observation retrieval — per-station-parameter Excel workbook | None | `group` is a numbered shard (1–10), `code` is `Q`/`H`/`WT`, `file` is `Q_1Y.xlsx`/`H_1Y.xlsx`/`Tvode_1Y.xlsx`. Always returns a rolling ~1-year window of hourly data (confirmed live: 8631 rows for station 4510/Q on 2026-06-08). |

Both endpoints were exercised live during this port (not just against fixtures): the metadata endpoint returned 60 stations and the workbook endpoint returned a real 124 KB xlsx for station 4510 — see "Live verification" below.

## Known Limitation: Rolling 1-Year Window Only

**The portal does not support arbitrary date-range queries.** Each `<code>_1Y.xlsx` workbook always contains a fixed rolling window of hourly observations (~8600 rows, ~1 year) ending at the most recent reading — there is no query parameter to request historical periods outside this window. This mirrors a constraint also present in `pl_imgw` and `ca_eccc` (data-coverage limits), but here it applies to *every* request, not just historical gaps.

Consequences for the port:
- The archived legacy retrieval path fetched the workbook once per `(station_id, parameter_code)` and then filtered or aggregated it. The shipped provider is catalogue-only, and its catalogue advertises only source-published instantaneous products.
- Requests whose window does not overlap the available data emit a recoverable `requested_range_beyond_window` warning issue (with `available_local_start`/`available_local_end` details) and return an empty series for that station/product.
- `bulk_observations` capability metadata documents this constraint explicitly so callers do not assume historical queries work.

## Station Group Discovery

The portal shards station workbooks across ten numbered "groups" (`/stations/{1..10}/...`); the group for a given station is **not** exposed in the metadata snapshot. `BaFhmzbihObservationClient.fetch_workbook()` probes groups 1–10 in order, returns the first 200 response with a non-empty body, and caches the discovered group per station-id for the lifetime of the client instance (live-verified: station 4510 resolves to group 4). A `station_group` series annotation records which group served each series, and `station_group_not_found` is emitted as a recoverable issue if every group probe 404s.

## Catalogue Mapping

The packaged catalogue is a pure, network-free projection of the committed
`catalogue/native.parquet` and `STATION_CATALOGUE_ORIGINS`. Canonical station identity and decimal
coordinates come directly from the declared native columns. The source-only names, river,
catchment, elevation, projected/local coordinates, and other source vocabulary remain readable in
the native table. The publisher's station document does not publish a horizontal CRS, so the
declared `NotPublished` origin emits canonical `crs = "unknown"` without inference.

| Source field | Canonical target | Notes |
|---|---|---|
| `metadata_station_no` | `station_id` | String station code, e.g. `"4510"` |
| `metadata_station_latitude`, `metadata_station_longitude` | `latitude`, `longitude` | Decimal-degree strings strictly coerced to `Float64`; no transformation or reprojection |
| all other `metadata_*` fields | native only | Preserved exactly in source vocabulary and not promoted to canonical station columns |

## Products

The packaged catalogue advertises exactly three source-published hourly instantaneous products, one for each observed property. It does not advertise computed daily means.

| Product ID | Parameter code | Workbook file | Native unit | Canonical unit | Conversion |
|---|---|---|---|---|---|
| `discharge_instantaneous` | `Q` | `Q_1Y.xlsx` | m³/s | m³/s | none |
| `stage_instantaneous` | `H` | `H_1Y.xlsx` | cm | m | ÷100 |
| `water_temperature_instantaneous` | `WT` | `Tvode_1Y.xlsx` | °C | °C | none |

`discharge_daily_mean`, `stage_daily_mean`, and `water_temperature_daily_mean` are deliberately absent. The source publishes hourly workbook values; RivRetrieve does not aggregate them into catalogue products.

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

## Withdrawn Daily-Mean Aggregation

The inert legacy reference records how the pre-engine implementation computed local-calendar-day means from hourly rows. That code remains historical evidence only: it is excluded from the shipped package and test collection, and none of those computed products is advertised in the packaged catalogue. Do not restore the aggregation path.

## Unit Conversion

Stage values are published in centimetres and divided by `100.0` to produce the canonical metre unit; the original centimetre value is preserved in the `raw_value` row annotation (e.g. `82.2` cm → `0.822` m, live-verified against station 4510). Discharge (m³/s) and water temperature (°C) require no conversion.

## Station-Product Availability

All rows are `availability = "unknown"`. The metadata snapshot does not indicate which parameters a given station actually reports — in practice some stations' workbooks for a given parameter return zero data rows (e.g. station 4510's water-temperature workbook is empty both in the upstream test fixture and in the live response captured 2026-06-08). The retrieval path treats an empty-but-successfully-fetched workbook as `missing_data`, distinct from a `station_group_not_found` failure.

## Live Verification

Per the project convention of confirming downloads "really work" before declaring a port complete (and not repeating the `th_thaiwater` mistake where downloads were silently not happening), this port was exercised against the live portal during development:

- The attested `layers/20/index.json` response produced the committed 60-row native table. Packaged canonical artifacts are subsequently rebuilt only from that table and the origin declarations.
- `BaFhmzbihObservationClient.fetch_workbook("4510", "Q", "Q_1Y.xlsx")` resolved to group `4`, returned HTTP 200 and 124,674 bytes, and parsed into 8,631 valid hourly rows spanning 2025-06-08 through 2026-06-07.
- A historical live-verification run of the archived legacy retrieval path returned 1,666 rows for station 4510 (discharge, stage, water temperature, May–June 2026). This remains source-behavior evidence and does not make its computed daily means shipped catalogue products.

## Live Catalogue

`live_stations = False`, `live_products = False`, `live_station_products = False`. The generator is maintainer-only; runtime catalogue reads packaged Parquet artifacts. Canonical generation accepts only a committed native table and output directory. During native-table maintenance, `MIN_LIVE_STATIONS = 30` is enforced after parsing in the issue-returning live-refresh path; a smaller live payload returns `refresh_below_minimum` and writes nothing.

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
