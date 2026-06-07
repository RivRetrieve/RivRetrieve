# pl_imgw Provider Port Notes

## Source Endpoints

| Endpoint | Role | Auth | Notes |
|---|---|---|---|
| `https://danepubliczne.imgw.pl/api/data/hydro` | Catalogue generation — station list with coordinates | None | JSON array; 913 stations (2026-06-04). Fields: `id_stacji`, `stacja`, `rzeka`, `wojewodztwo`, `lon`, `lat`. Real-time metadata; not historical. |
| `https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/lista_stacji_hydro.csv` | Alternative station list (no coordinates) | None | 1301 stations; CP1250; no lat/lon. Not used for catalogue — coordinates come from the JSON endpoint. |
| `https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/{year}/codz_{year}.zip` | Observation retrieval — annual ZIP (2023+) | None | One file per year; ~1.5 MB compressed, ~20 MB uncompressed. Contains all stations for the year. |
| `https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/{year}/codz_{year}_{month:02d}.zip` | Observation retrieval — monthly ZIP (pre-2023) | None | 12 files per year; ~2 MB each. Same schema as annual ZIP. Annual ZIPs do not exist for 2022 and earlier. |

## Decision: Local Parquet cache (mirrors ca_eccc HYDAT approach)

The legacy Python `PolandFetcher` (Zarr) and R `adapter_PL_IMGW.R` (WIDE master RDS) both build a local all-time cache. This port follows the same pattern as `ca_eccc` (which downloads HYDAT SQLite once and caches it): on first `observations()` call, all IMGW yearly ZIPs are downloaded (1951–current year), parsed, deduplicated, and written as a single Parquet file in the user's cache directory. Subsequent calls read from the Parquet file — no network required.

Parquet was chosen over Zarr (Python) or RDS (R) because it is RivRetrieve's native format (Polars) and requires no extra dependency.

`ImgwCacheClient` mirrors `HydatClient` exactly:
- `cache_path_override`: injectable test path (like `db_path_override` in ca_eccc)
- `ensure_cache()`: returns `(path, issues)`; builds on first use
- `cache_status()`: reports existence, age, size — no download triggered
- `refresh_cache()`: deletes and rebuilds the cache

The provider handle exposes `cache_status()` and `refresh_cache()` at the same level as ca_eccc.

## Catalogue Mapping

| Source field | Canonical target | Notes |
|---|---|---|
| `id_stacji` | `station_id` | Strip whitespace; 9-digit numeric string |
| `stacja` | `name` | Station name (Polish) |
| `rzeka` | `metadata.river` | River or water body name |
| `wojewodztwo` | `metadata.province` | Polish administrative province |
| `lon`, `lat` | `longitude`, `latitude` | Float from string; stations without valid coordinates excluded |
| (not in API) | `elevation_m` | Always null — IMGW `/api/data/hydro` does not provide elevation |
| (not in API) | `drainage_area_km2` | Always null — not in any IMGW endpoint used |

## Products

All three V1 canonical daily products are available. IMGW daily CSVs contain all three in a single file, so one ZIP download serves all products for the same station.

| Product ID | CSV column | Native unit | Canonical unit | Sentinel values replaced with null |
|---|---|---|---|---|
| `discharge_daily_mean` | `Flow [m^3/s]` (col 8) | m³/s | m³/s | 99999.999, 999 |
| `stage_daily_mean` | `Water level [cm]` (col 7) | cm | m (÷100) | 9999 |
| `water_temperature_daily_mean` | `Water temperature [deg. C]` (col 9) | °C | °C | 99.9 |

## CSV Format

IMGW daily CSVs are 10-column headerless files. Two format eras:

| Era | Encoding | Delimiter | Quoting | Example first cell |
|---|---|---|---|---|
| 2023+ (annual ZIP) | UTF-8 with BOM | `;` | None | `151140030` |
| pre-2023 (monthly ZIPs) | CP1250 | `,` | Quoted with `"` | `" 149180020"` (leading space inside quotes) |

Both eras share the same 10 columns:
1. Station code (`id_stacji`)
2. Station name
3. River
4. Hydrological year
5. Month indicator in hydrological year (1=Nov, 2=Dec, 3=Jan, …, 12=Oct)
6. Day
7. Water level [cm]
8. Flow [m³/s]
9. Water temperature [°C]
10. Calendar month (1–12)

The parser uses the calendar month (column 10) directly. Calendar year = hydrological year − 1 if calendar month ≥ 11 (November or December), else hydrological year.

## Timestamps

IMGW provides year/month/day integers only — no time, no timezone. Follows the established `date_only_timestamp` pattern (same as `lt_lhmt`, `fr_hubeau`, `br_ana`, `jp_mlit` daily, `ca_eccc`):

- Interpreted as UTC midnight `T00:00:00Z`
- `warning`-severity `date_only_timestamp` issue emitted per parser call
- Series annotation: `timezone_source = "date_only_utc_midnight"`, `date_only_timestamp_flag = "true"`
- Row annotation: `timezone_source`, `date_only_timestamp_flag` on every row

True local timezone is undocumented. Likely Central European Time (CET/CEST, UTC+1/+2), but IMGW does not state this.

## Hydrological Year Convention

IMGW organises data by hydrological year (November–October). Column 10 (`Calendar month`) contains the calendar month (1–12) directly, simplifying date reconstruction vs interpreting column 5 (hydrological month indicator). Calendar year = hydrological year − 1 for November (11) and December (12); equals hydrological year for January (1) through October (10).

## ZIP URL Structure

- **2023+**: `codz_{YYYY}.zip` — one ZIP per calendar year. First confirmed year: 2023.
- **pre-2023**: `codz_{YYYY}_{MM}.zip` — 12 ZIPs per year. 2022 and earlier years only have monthly ZIPs.
- The cut-off year (2023) is encoded as `ANNUAL_ZIP_FROM_YEAR = 2023` in `observation_client.py`. Update if IMGW publishes annual ZIPs for future years (confirmed by live URL check) or retroactively for earlier years.
- `zjaw_{YYYY}.zip` also appears in IMGW directories — this contains ice/phenomena events, not daily gauge data. Ignored.

## Station-Product Availability

All rows are `availability = "unknown"`. IMGW does not expose per-variable station availability in any endpoint. Stations may not measure all three variables; sentinel values in the CSV mark missing measurements per day.

## Station Counts

| Source | Count | Date | Notes |
|---|---|---|---|
| `/api/data/hydro` JSON | 913 | 2026-06-04 | Active stations with coordinates |
| `lista_stacji_hydro.csv` | 1301 | 2026-06-04 | Includes inactive; no coordinates |
| Packaged catalogue | 913 | 2026-06-04 | From JSON; stations without valid lat/lon excluded |

## Live Catalogue

`live_stations = False`. The generator is maintainer-only. Runtime catalogue reads packaged Parquet artifacts. The live guard is 500 stations minimum.

## Surprises and Pain Points

| Issue | Detail |
|---|---|
| Two CSV format eras | 2023+ is UTF-8 BOM + semicolon; pre-2023 is CP1250 + comma + quoting. Parser tries UTF-8-sig first (BOM detection), then CP1250, then latin-1. |
| Coordinates not in station list CSV | `lista_stacji_hydro.csv` has 1301 stations but no coordinates. Catalogue uses `/api/data/hydro` JSON (913 active stations with lat/lon). Historical-only stations are not in the catalogue. |
| ZIP contains all stations | Every download fetches data for all ~900+ stations. The parser filters by `station_ids` immediately after decoding, discarding unrequested station rows. Memory usage peaks at ~20 MB per ZIP before filtering. |
| Sentinel masking | Water level 9999, discharge 99999.999/999, temperature 99.9 → `None`. The parser rounds to 3 decimal places before sentinel comparison to avoid floating-point near-miss. |
| Leading spaces in pre-2023 station codes | Pre-2023 CP1250 CSV has quoted station codes like `" 149180020"`. The parser strips whitespace after CSV unquoting. |
| Annual ZIP cut-off | Only 2023 and 2024 have `codz_{YYYY}.zip`. Earlier years use 12 monthly ZIPs. The client selects strategy based on `year >= ANNUAL_ZIP_FROM_YEAR`. |
| Data lag | Latest available data is 2024. 2025/2026 directories return 404. |
