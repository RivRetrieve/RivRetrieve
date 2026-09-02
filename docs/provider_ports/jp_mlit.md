# jp_mlit Provider Port Notes

These notes capture evidence and context from porting the MLIT Water Information System (Japan) provider. They are not user documentation and not architecture contracts; promote only shared harness commitments to [ADRs](../adr/).

## Source

Legacy reference: `JapanFetcher` from `https://github.com/kratzert/RivRetrieve-Python/blob/main/rivretrieve/japan.py`.

## Source Endpoints

| Endpoint | Role | Credential | Notes |
| --- | --- | --- | --- |
| `http://www1.river.go.jp/cgi-bin/DspWaterData.exe` | Observation HTML scrape page | None (public) | Returns EUC-JP HTML with a `.dat` download link; params: KIND, ID, BGNDATE, ENDDATE, KAWABOU |
| `http://www1.river.go.jp/dat/dload/download/*.dat` | Actual data file | None (public) | Shift-JIS encoded; link extracted by regex from the HTML page |
| `http://www1.river.go.jp/cgi-bin/SiteInfoDetail.exe?ID={station_id}` | Native station-detail capture | None (public, historically) | EUC-JP HTML. The accepted 2026-08-02 campaign required HTTP 200 and the bytes for `世界測地系`; the endpoint later returned HTTP 403. |

## Catalogue Mapping

The committed native table is a semantic materialization of 1,023 accepted station-detail responses,
not of the legacy cached CSV or the three-row fixture. It preserves the fifteen source columns,
including distinct null, empty-string, and non-breaking-space states, and sorts by exact `観測所記号`.

| Native field | Canonical target | Decision |
| --- | --- | --- |
| `観測所記号` | `provider_id`, `station_id` | Exact source identity. |
| `世界測地系` latitude/longitude DMS | `latitude`, `longitude` | Deterministic DMS conversion; `日本測地系` is retained but never consumed. |
| Horizontal CRS | `crs` | `unknown`; the present source publishes no horizontal CRS token, and no datum or EPSG value is inferred. |
| Other source fields | Native only | Preserved in source vocabulary. |

The source DMS corrected three legacy packaged coordinates. The affected stations are `302011282228100`
(about 3.79 km), `302011282218050` (about 96 m), and `308011288805010` (about 40 m). Source coordinates
are authoritative.

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

## Native Capture Attestation

The request seed is the sorted 1,024-station legacy catalogue at `origin/main` commit `22ff07c`.
Requests ran from `2026-08-02T19:35:42Z` through `2026-08-02T19:50:44Z`. There were 1,023 accepted
published responses and one source-confirmed absence, station `307051287711040`. The accepted responses
carry 902 distinct whole-second retrieval instants from the capture manifest.

The complete manifest and all reverified response bindings canonicalize to SHA-256
`d935586b317cdf234760959c9e97788803bfda9cea2ff6551beaefaeb6e20d21`. The per-request URLs, bodies,
timestamps, acceptance result, rejected witness, derived identifier and timestamp digests, parser
witnesses, and native-frame digest are pinned by `origins.py`, `catalogue/provenance.json`, committed
test data, and `tests/test_jp_mlit_catalogue.py`.

The representative CRS evidence response for `301011281104010` was accepted at
`2026-08-02T19:35:42Z`. A later request on `2026-08-03T12:31:42Z` returned HTTP 403 with a 77-byte access-restriction body,
so the evidence is non-refetchable and no later success is claimed. Canonical artefacts must be built only from committed
`catalogue/native.parquet` plus origins.

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
