# jp_mlit Provider Port Notes

These notes capture evidence and context from porting the MLIT Water Information System (Japan) provider. They are not user documentation and not architecture contracts; promote only shared harness commitments to [architecture.md](../../architecture.md).

## Source

Legacy reference: `JapanFetcher` from `https://github.com/kratzert/RivRetrieve-Python/blob/main/rivretrieve/japan.py`.

## Source Endpoints

| Endpoint | Role | Credential | Notes |
| --- | --- | --- | --- |
| `http://www1.river.go.jp/cgi-bin/DspWaterData.exe` | Observation HTML scrape page | None (public) | Returns EUC-JP HTML with a `.dat` download link; params: KIND, ID, BGNDATE, ENDDATE, KAWABOU |
| `http://www1.river.go.jp/dat/dload/download/*.dat` | Actual data file | None (public) | Shift-JIS encoded; link extracted by regex from the HTML page |
| `http://www1.river.go.jp/cgi-bin/SiteInfo.exe` | Station metadata | None (public) | Live station list not supported; legacy `JapanFetcher.get_metadata()` explicitly raises `NotImplementedError` |

## Catalogue Mapping

| Legacy/source field | Canonical target | Decision |
| --- | --- | --- |
| `gauge_id` (cached CSV) | `station_id` | Direct mapping |
| `latitude`, `longitude` | `latitude`, `longitude` | Direct mapping |
| No name field in CSV | `name` | Gauge ID used as name; no station name available in cached CSV |
| No elevation, drainage area | `elevation_m`, `drainage_area_km2` | Both `None`; cached CSV does not provide these fields |
| `"Japan"` constant | `country` | Hardcoded |

The cached `japan_sites.csv` provides only `gauge_id`, `latitude`, and `longitude` — far sparser than other providers. There is no programmatic live catalogue endpoint.

## Product Mapping

| Legacy variable | KIND | Frequency | MLIT website label | Canonical product_id | Provider-specific? |
| --- | --- | --- | --- | --- | --- |
| `STAGE_HOURLY_MEAN` | 2 | hourly | "Daily" (misleading) | `stage_hourly_mean` | **Yes** — no canonical hourly stage product |
| `STAGE_DAILY_MEAN` | 3 | daily | Daily | `stage_daily_mean` | No — canonical match |
| `DISCHARGE_HOURLY_MEAN` | 6 | hourly | "Daily" (misleading) | `discharge_hourly_mean` | **Yes** — no canonical hourly discharge product |
| `DISCHARGE_DAILY_MEAN` | 7 | daily | Daily | `discharge_daily_mean` | No — canonical match |

### Provider-specific products

`stage_hourly_mean` and `discharge_hourly_mean` use provider-specific product IDs because the canonical product dictionary has no hourly-frequency stage or discharge entry. `hourly` is a valid frequency token in the architecture vocabulary, so these IDs use the correct format. Adding canonical hourly products to the product dictionary is deferred to a future port that needs a V1 extension.

### MLIT KIND labelling quirk

The MLIT website labels KINDs 2 and 6 as "Daily" but they actually return **hourly** data. KINDs 3 and 7 return true daily data. This is documented in the legacy source comment and reproduced in the product metadata notes.

## Units

All MLIT values are already in SI units:
- Stage: metres (m)
- Discharge: cubic metres per second (m³/s)

No unit conversion is applied. The `raw_value` row annotation preserves the provider value (which equals the canonical value).

## Timestamps and Timezone

### Hourly products (KINDs 2 and 6)

- `.dat` file columns: `1時` (hour 1 = 00:00 local JST) through `24時` (hour 24 = 23:00 local JST)
- Legacy convention: `timedelta(hours=row["Hour"] - 1)` starting from midnight
- Port convention: construct a `datetime(year, month, day, hour-1, tzinfo=ZoneInfo("Asia/Tokyo"))` then convert to UTC with `.astimezone(UTC)`
- Series annotation: `timezone_source = "local_to_utc_conversion"`, `local_timezone = "Asia/Tokyo"`
- Issue emitted: `timezone_local_to_utc` at `info` severity per parser call (always, to document the conversion)

**UTC offset**: JST = UTC+9, so 2023-01-01 00:00 JST = 2022-12-31 15:00:00 UTC. Confirmed from live data.

### Daily products (KINDs 3 and 7)

- `.dat` file rows: one row per month (e.g., `1月`), columns for each day
- Timestamps are date-only representing a JST calendar day
- Convention: interpreted as UTC midnight (`T00:00:00Z`) — same pattern as `lt_lhmt` and `fr_hubeau` obs_elab
- Series annotation: `timezone_source = "date_only_utc_midnight"`, `date_only_timestamp_flag = "true"`
- Issue emitted: `date_only_timestamp` at `warning` severity per parser call

**Note**: The underlying daily data represents a JST calendar day. UTC midnight is technically 9 hours off from JST midnight, but for daily-resolution data the exact timestamp convention is documented rather than corrected (consistent with established provider pattern).

## .dat File Format — Discovered Quirks

These format details are not documented in the legacy code and were discovered by examining live downloads:

### Daily format (KINDs 3 and 7)

Real files look like:
```
日流量年表検索結果
水系名,天塩川
河川名,天塩川
観測所名,茂志利
観測所記号,301011281104010
#
# (comment lines)
#
,1日,,2日,,3日,...,31日,      ← header line (starts with ,)
2023年                         ← year marker line — BETWEEN header and data rows
1月,    4.47, ,    4.41, ,...  ← month data rows
...
12月,...
```

Key discoveries:
1. **Year marker after header**: `2023年` appears as a standalone line BETWEEN the column-header line and the data rows. The parser must filter it out before CSV parsing (filtering by `_YEAR_PATTERN`).
2. **Leading whitespace in values**: Values like `"    4.47"` have leading spaces. `polars` cannot cast `"    4.47"` to `Float64` directly — `.str.strip_chars()` is required before `.cast(pl.Float64, strict=False)`.
3. **Extra monthly-average columns**: The `.dat` file includes extra `月平均データ, 月平均フラグ` (monthly average) columns at the end, beyond the 31 day pairs. `truncate_ragged_lines=True` is required in `pl.read_csv` to ignore these.
4. **Flag column for missing values**: Some days have `$` or `-` flags (欠測 = missing, 未登録 = not registered). The float cast returns `None` for these, which the filter then removes. The `-9999.xx` sentinel is also filtered via `> -9999.0`.

### Hourly format (KINDs 2 and 6)

Real files:
```
# header
,1時,1時フラグ,2時,...,24時,24時フラグ
YYYY/MM/DD,    val, ,    val, ,...
```

Same leading-whitespace issue as daily. The hourly header has 24 value+flag pairs.

## HTML Scrape

The MLIT API does not return JSON or structured data directly. The endpoint `DspWaterData.exe` returns an EUC-JP HTML page. The page contains an `<a href="/dat/dload/download/...">` link to a Shift-JIS `.dat` file. The observation client:
1. Fetches the HTML page (EUC-JP decode)
2. Extracts the `.dat` link via regex: `r'href="(/dat/dload/download/[^"]+)"'`
3. Fetches the `.dat` file (Shift-JIS decode)
4. Returns the decoded content string

When no `.dat` link is found (station/window has no data), a `no_dat_link` warning issue is emitted.

No BeautifulSoup dependency was added. Regex is sufficient for finding the single `.dat` link pattern.

## Windowing

- **Hourly (KINDs 2, 6)**: Monthly windows. Begin date = `YYYYMM01`, end date = `YYYYMMdd` (last day of month). Request format uses `YYYYMMDD` (no separator).
- **Daily (KINDs 3, 7)**: Yearly windows. Begin date = `YYYY0101`, end date = `YYYY1231`.

## Live Catalogue

Not supported. `JapanFetcher.get_metadata()` in the legacy source explicitly raises `NotImplementedError`. The packaged catalogue is built from the cached `japan_sites.csv` (1030 rows, providing only `gauge_id`, `latitude`, `longitude`). `generate_catalogue_from_live()` raises `FatalContractError` to prevent accidental invocations.

## Station Catalogue

1029 stations with valid coordinates (1030 in the CSV; station count depends on deduplication of `gauge_id`). No elevation or drainage area available in the source. Station names are gauge IDs (`gauge_id` as name).

## Pain Points

| Issue | Status | Action |
| --- | --- | --- |
| Leading spaces in .dat numeric values | Fixed | `.str.strip_chars()` before `.cast(pl.Float64)` in both parsers |
| Year marker line in daily .dat data section | Fixed | Filter `_YEAR_PATTERN` from data lines before CSV parse |
| Extra monthly-average columns in daily .dat | Fixed | `truncate_ragged_lines=True` in `pl.read_csv` |
| EUC-JP HTML + Shift-JIS .dat two-request flow | Documented | Observation client handles both encodings |
| No BeautifulSoup needed | Documented | Regex is sufficient for the `.dat` link pattern |
| Provider-specific hourly product IDs | Documented | `stage_hourly_mean`, `discharge_hourly_mean` use provider-specific IDs; canonical hourly products deferred |
| JST→UTC for hourly, date-only UTC midnight for daily | Documented | Follows th_thaiwater JST→UTC pattern for hourly; follows lt_lhmt/fr_hubeau pattern for daily |
| No live catalogue endpoint | Documented | `generate_catalogue_from_live()` raises `FatalContractError`; fixture path accepts CSV or JSON |
