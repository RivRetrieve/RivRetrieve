# pl_imgw Provider Port Notes

## Source Endpoints

| Endpoint | Role | Auth | Notes |
|---|---|---|---|
| `https://danepubliczne.imgw.pl/api/data/hydro/?format=json` | Partial publisher coordinate corroboration | None | JSON array; 913 published stations at 2026-08-02, 32 with zero or absent coordinates. It does not reproduce the packaged population. |
| `https://danepubliczne.imgw.pl/datastore/getfiledown/Arch/Telemetria/Hydro/kody_stacji.csv` | Primary publisher coordinate corroboration | None | 887 UTF-8, semicolon-delimited stations with whole-arc-second DMS coordinates; covers 784 packaged stations. |
| `https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/lista_stacji_hydro.csv` | Independent complete identity roster | None | 1,301 CP1250, headerless, comma-delimited rows; its stripped identifier set exactly equals the recovered set and it contains no geometry. |
| `https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/{year}/codz_{year}.zip` | Observation retrieval — annual ZIP (2023+) | None | One file per year; ~1.5 MB compressed, ~20 MB uncompressed. Contains all stations for the year. |
| `https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/{year}/codz_{year}_{month:02d}.zip` | Observation retrieval — monthly ZIP (pre-2023) | None | 12 files per year; ~2 MB each. Same schema as annual ZIP. Annual ZIPs do not exist for 2022 and earlier. |

## Historical decision: Local Parquet cache

The legacy Python `PolandFetcher` (Zarr), R `adapter_PL_IMGW.R` (WIDE master RDS), and the retired RivRetrieve observation pipeline built a local all-time cache. The cache implementation remains under `_internal` as the second runtime HTTP carve-out for the future provider port owned by ticket #17.

The current `pl_imgw` provider is catalogue-only. `rr.provider("pl_imgw").observations(...)`, `row_annotation_schema()`, and `series_annotation_schema()` raise `ObservationsUnavailableError`. Its provider handle does not expose `cache_status()` or `refresh_cache()`. This is deliberate: without the retired retrieval reader, rebuilding every IMGW ZIP from 1951 would produce a Parquet cache that no supported call can query.

The retained private `ImgwCacheClient` implementation still contains `cache_path_override`, `ensure_cache()`, `cache_status()`, and `refresh_cache()` so ticket #17 can use or replace the implementation when PL IMGW is ported to the engine stage contract. These are internal implementation details, not supported provider-handle methods.

## Catalogue Mapping

| Source field | Canonical target | Notes |
|---|---|---|
| `gauge_id` | `station_id` | Exact nine-character recovered token, retained as String |
| `latitude`, `longitude` | `latitude`, `longitude` | Exact recovered floating-point geometry; no publisher-coordinate substitution |
| `gauge_name`, `river`, `area`, `gauge_altitude` | Native table only | Preserved in source vocabulary; `gauge_altitude` remains String because `ND` is published |

The 1,301-row recovered source is byte-identical to `kratzert/RivRetrieve-Python`'s
`rivretrieve/cached_site_data/poland_sites.csv` at commit
`f67f6d8507a55144bf235feb3f27f65648b90f83`. Its commit timestamp,
`2025-10-10T18:46:34Z`, is the native-table provenance lower bound. The complete live roster captured
at `2026-08-02T19:54:27Z` independently establishes exact identity-set agreement but contributes no
geometry, names, area, or altitude. Publisher coordinate captures from `2026-08-02T18:45:32Z` are
partial, whole-arc-second corroboration only.

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
| Recovered `poland_sites.csv` | 1,301 | 2025-10-10 provenance lower bound | Complete finer-precision packaged geometry |
| `lista_stacji_hydro.csv` | 1,301 | 2026-08-02 | Complete exact identifier cross-check; no coordinates |
| `kody_stacji.csv` | 887 | 2026-08-02 | Whole-arc-second DMS; covers 784 packaged stations |
| `/api/data/hydro/?format=json` | 913 | 2026-08-02 | 881 usable coordinates; covers 779 packaged stations |
| Packaged catalogue | 1,301 | recovered import | Recovered geometry; publisher-route union covers 784 and leaves 517 uncovered |

## Live Catalogue

`live_stations = False`. Runtime catalogue reads packaged artifacts. `provider.json`,
`products.parquet`, `stations.parquet`, and `station_products.parquet` are a network-free function of
committed `catalogue/native.parquet` plus `STATION_CATALOGUE_ORIGINS`. The maintainer generator's
canonical mode accepts only that native table; live JSON and fixtures cannot produce these artifacts.

## Surprises and Pain Points

| Issue | Detail |
|---|---|
| Two CSV format eras | 2023+ is UTF-8 BOM + semicolon; pre-2023 is CP1250 + comma + quoting. Parser tries UTF-8-sig first (BOM detection), then CP1250, then latin-1. |
| Publisher geometry is partial and coarser | `lista_stacji_hydro.csv` has 1,301 identities but no coordinates. `kody_stacji.csv` covers 784 packaged stations and the usable API subset covers 779, leaving 517 without publisher-published coordinates. The DMS route has zero exact recovered pairs, 779 within 1.5 arc-seconds on both axes, and five accepted disagreements; worst is `154180190` at approximately 0.0053675° on one axis. Recovered values remain authoritative. |
| ZIP contains all stations | Every download fetches data for all ~900+ stations. The parser filters by `station_ids` immediately after decoding, discarding unrequested station rows. Memory usage peaks at ~20 MB per ZIP before filtering. |
| Sentinel masking | Water level 9999, discharge 99999.999/999, temperature 99.9 → `None`. The parser rounds to 3 decimal places before sentinel comparison to avoid floating-point near-miss. |
| Leading spaces in pre-2023 station codes | Pre-2023 CP1250 CSV has quoted station codes like `" 149180020"`. The parser strips whitespace after CSV unquoting. |
| Annual ZIP cut-off | Only 2023 and 2024 have `codz_{YYYY}.zip`. Earlier years use 12 monthly ZIPs. The client selects strategy based on `year >= ANNUAL_ZIP_FROM_YEAR`. |
| Data lag | Latest available data is 2024. 2025/2026 directories return 404. |
