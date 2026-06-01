# usgs_nwis Provider Port Notes

These notes capture evidence and decisions from porting the USGS National Water Information System (NWIS) USA provider. See [architecture.md](../../architecture.md) for shared harness contracts. Provider-specific pain stays here; only shared harness gaps should be promoted to architecture.md.

## Source Endpoints

| Endpoint | Role | Credential status |
| --- | --- | --- |
| `https://waterservices.usgs.gov/nwis/dv/?format=json&sites={site}&startDT={start}&endDT={end}&parameterCd={param}&statCd={stat}` | Daily values retrieval (DV) for discharge_daily_mean, stage_daily_mean, stage_daily_max, stage_daily_min | No token. Public endpoint. |
| `https://waterservices.usgs.gov/nwis/iv/?format=json&sites={site}&startDT={start}&endDT={end}&parameterCd={param}` | Instantaneous values retrieval (IV) for discharge_instantaneous, stage_instantaneous | No token. Public endpoint. |
| `https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&siteOutput=expanded&seriesCatalogOutput=true` | Maintainer-side catalogue generation: fetch stream gauge site metadata in RDB format | No token. |

Legacy source consulted: `https://github.com/kratzert/RivRetrieve-Python/blob/main/rivretrieve/usa.py` (uses `dataretrieval` package, which wraps the same NWIS endpoints).

## Catalogue Mapping

| Legacy/source field | Canonical target | Provider metadata | Decision |
| --- | --- | --- | --- |
| `site_no` | `StationCatalog.station_id` | `native_site_no` | USGS site number, left-padded with zeros as returned. |
| `station_nm` | `StationCatalog.name` | `name` | Preserve provider station name. |
| `dec_lat_va`, `dec_long_va` | `StationCatalog.latitude`, `longitude` | same | Direct numeric fields from RDB response. |
| `alt_va` (feet) | `StationCatalog.elevation_m` | `alt_va_ft` | Converted ft → m (× 0.3048). Raw ft value preserved in metadata. |
| `drain_area_va` (sq mi) | `StationCatalog.drainage_area_km2` | `drain_area_sq_mi` | Converted sq mi → km² (× 2.58999). Raw sq mi preserved in metadata. |
| `state_cd` | No common column | `state_cd` | Kept as 2-digit FIPS code in metadata. |
| `huc_cd` | No common column | `huc_cd` | HUC watershed code preserved as metadata. |
| `tz_cd` | No common column | `tz_cd` | Station timezone code (e.g. "CST6CDT") preserved as metadata. Used for documentation only; UTC conversion happens via timestamp offset. |
| `begin_date`, `end_date` | `StationCatalog.start_date`, `end_date` | same | Parsed from ISO date strings when present. |
| Station × product universe | `StationProductCatalog` rows | `availability_source`, `availability_note` | All `5 × 6 = 30` rows materialized as `availability=unknown`; NWIS site catalogue does not expose per-variable availability. |

## Product Dictionary

All six products map to canonical V1 product IDs. No USGS-specific product IDs were needed.

| Product ID | USGS endpoint | Param code | Stat code | Native unit | Canonical unit | Conversion |
| --- | --- | --- | --- | --- | --- | --- |
| `discharge_daily_mean` | DV | 00060 | 00003 | ft3/s | m3/s | × 0.0283168466 |
| `discharge_instantaneous` | IV | 00060 | (none) | ft3/s | m3/s | × 0.0283168466 |
| `stage_daily_mean` | DV | 00065 | 00003 | ft | m | × 0.3048 |
| `stage_daily_max` | DV | 00065 | 00001 | ft | m | × 0.3048 |
| `stage_daily_min` | DV | 00065 | 00002 | ft | m | × 0.3048 |
| `stage_instantaneous` | IV | 00065 | (none) | ft | m | × 0.3048 |

Legacy source used `constants.STAGE_DAILY_MAX` and `constants.STAGE_DAILY_MIN` via `dataretrieval`, which maps to statistic codes 00001 and 00002 respectively.

## Timezone and Timestamp Handling

**Critical fact:** USGS NWIS timestamps carry an explicit ISO 8601 timezone offset in every response value (e.g., `2023-01-01T00:00:00.000-06:00` for CST). For DV (daily) data, timestamps represent midnight local time; for IV data, they represent the actual measurement time. Both are parsed and converted to UTC in the `time` column.

Conversion approach:
1. Strip sub-second precision (`.000`) from the timestamp string.
2. Normalize trailing `Z` to `+00:00`.
3. Parse with Python `datetime.fromisoformat()` (handles `+HH:MM` offsets on Python 3.7+).
4. Convert to UTC with `.astimezone(UTC)`.
5. Store as `pl.Datetime("us", "UTC")`.

Series annotation `resolved_timezone` is always `"UTC"`. Series annotation `timezone_source` is `"provider_timestamp_offset"` because the conversion does not require inference — the offset is explicit in the response.

**Divergence from legacy behavior:** The legacy `USAFetcher._parse_data()` did `pd.to_datetime(df.index.dt.date)`, which stripped timezone and time-of-day entirely and produced a timezone-naive date index at midnight. The new implementation preserves the full UTC timestamp, so a DV observation for `2023-01-01` at a CST station becomes `2023-01-01T06:00:00Z`, not `2023-01-01T00:00:00Z`. This is the correct behavior per architecture.md §16.

## Observation Retrieval

The DV and IV endpoints are selected per product at retrieval time. A single `observations(request)` call may mix DV and IV products across the same station list; each station×product pair is dispatched to the correct endpoint.

Windowing: 365-day annual windows per station×product pair (similar to ch_foen's 366-day windows). Window boundaries are date strings (`YYYY-MM-DD`) passed as `startDT`/`endDT`.

No authentication required. USGS WaterServices is a fully public API.

HTTP 404 responses (station or parameter not found for the window) are treated as `http_not_found` warning issues, not fatal errors, matching the lt_lhmt pattern for 404 month requests.

## Row and Series Annotations

Row annotations capture `native_field` (parameter code), `native_unit`, `converted_unit`, `raw_value` (pre-conversion cfs or ft), and `qualifier` (USGS quality codes: A=Approved, P=Provisional, e=estimated, etc.).

Series annotations capture `resolved_timezone`, `timezone_source`, time range, `endpoint_type` ("dv" or "iv"), `param_code`, `stat_code`, `provider_endpoints`, and `requested_windows`.

## Unit Conversion Factors

- cfs → m3/s: 0.0283168466 (exact legacy value from `USAFetcher._parse_data()`)
- ft → m: 0.3048 (exact)
- sq mi → km²: 2.58999 (for drainage area in catalogue generation)

## Pain Points

| Issue | Status | Notes |
| --- | --- | --- |
| No `dataretrieval` dependency | Resolved | New implementation calls USGS WaterServices REST API directly with `requests`, matching the pattern of other providers. `dataretrieval` is not a project dependency and was not added. |
| Legacy strips timezone | Documented | Legacy `_parse_data()` used `.dt.date` which discards timezone and time-of-day. New implementation preserves full UTC-converted timestamps. Test `test_parser_timestamps_converted_from_cst` pins this behavior. |
| Large station catalogue | Post-V1 concern | The fixture shipped with the package contains 5 representative stations. For production use, the maintainer should run `generate_catalogue.py --live --out ...` to regenerate from the full NWIS site catalogue (8000+ stream gauges). |
| RDB parse for live catalogue | Resolved in generator | The USGS site service returns RDB (tab-delimited with comment lines). The generator parses RDB internally; the fixture format is pre-parsed JSON (list of dicts), consistent with other providers. |
| No per-variable availability | Documented | NWIS site catalogue does not expose which parameters are available per site. All station-product pairs are materialized as `availability=unknown`. |
| USGS API rate limits | Not enforced | USGS WaterServices has no documented hard rate limit for individual queries. Rate limit enforcement deferred post-V1. |
