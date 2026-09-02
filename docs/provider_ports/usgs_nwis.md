# usgs_nwis Provider Port Notes

These notes capture evidence and decisions from porting the USGS National Water Information System (NWIS) USA provider. See [ADRs](../adr/) for shared harness contracts. Provider-specific pain stays here; only shared architecture decisions should be promoted to an ADR.

## Source Endpoints

| Endpoint | Role | Credential status |
| --- | --- | --- |
| `https://waterservices.usgs.gov/nwis/dv/?format=json&sites={site}&startDT={start}&endDT={end}&parameterCd={param}&statCd={stat}` | Daily values retrieval (DV) for discharge_daily_mean, stage_daily_mean, stage_daily_max, stage_daily_min | No token. Public endpoint. |
| `https://waterservices.usgs.gov/nwis/iv/?format=json&sites={site}&startDT={start}&endDT={end}&parameterCd={param}` | Instantaneous values retrieval (IV) for discharge_instantaneous, stage_instantaneous | No token. Public endpoint. |
| `https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd={code}&seriesCatalogOutput=true` | Native-table refresh pass for source series and period-of-record rows | No token. |
| `https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd={code}&siteOutput=expanded` | Native-table refresh pass for expanded station fields | No token. |

Legacy source consulted: `https://github.com/kratzert/RivRetrieve-Python/blob/main/rivretrieve/usa.py` (uses `dataretrieval` package, which wraps the same NWIS endpoints).

## Native Catalogue Attestation

The native capture covers the ordered 51-code scope of the 50 states plus DC. It used separate series
and expanded requests because USGS does not allow `seriesCatalogOutput=true` and
`siteOutput=expanded` together. The accepted 102 responses contain 26,258 stations in each pass and
2,036,546 series rows with no cross-pass orphans. The supplied 55-code manifest also contains GU, MP,
PR, and VI, which are deliberately outside the accepted scope. Those files account for 275 stations;
the full supplied census has 26,533 stations in each pass and 2,055,307 series rows.

The complete supplied manifest has SHA-256
`d29ee34feaef0dda458c369ed5448e96b7e8b7064176a5f94360881b6cbdf34a`; its exact 102 consumed lines
have SHA-256 `e197d3d5eb6f971e631693d7d6e2b26d1c7b7031850d62ed11f5891011dbc6bc`. All entries were
verified against the manifest. The requests share campaign instant `2026-08-02T01:14:11Z`.
Canonicalization retains all 42 expanded fields as strings, aligns twelve series-only list columns,
preserves duplicate complete series rows, and sorts stations by exact `site_no`. The native-frame and
sorted-identifier digests are enforced by `catalogue/provenance.json`, origins, and
`tests/test_usgs_nwis_generate_catalogue.py`.

## Catalogue Mapping

| Native field | Canonical target | Decision |
| --- | --- | --- |
| `site_no` | `provider_id`, `station_id` origins | USGS site number is retained exactly and aligns every canonical row to the native table. |
| `dec_lat_va`, `dec_long_va` | `latitude`, `longitude` | Direct string-to-`Float64` coercion only; no spatial transformation or rounding. |
| `dec_coord_datum_cd` | `crs` | Closed mapping: NAD27→EPSG:4267, NAD83→EPSG:4269, OLDHI→EPSG:4135, WGS72→EPSG:4322, WGS84→EPSG:4326; all other tokens emit `unknown`. |
| `data_type_cd`, `parm_cd`, `stat_cd` lists | station-product availability | Exact returned-series keys use `dv` for daily products and `uv` with empty `stat_cd` for instantaneous products. |
| `begin_date`, `end_date` lists | station-product coverage | A unique or agreeing pair is propagated. Blank or conflicting pairs stay null with an explicit source-based reason. |
| Other expanded and series fields | Native table only | All 55 native columns remain in source vocabulary; no judgement-bearing station facts are promoted. |

## Product Dictionary

All six products map to canonical V1 product IDs. No USGS-specific product IDs were needed.

| Product ID | Request endpoint | Returned series key | Native unit | Canonical unit | Conversion |
| --- | --- | --- | --- | --- | --- |
| `discharge_daily_mean` | DV | `dv:00060:00003` | ft3/s | m3/s | × 0.0283168466 |
| `discharge_instantaneous` | IV | `uv:00060:` | ft3/s | m3/s | × 0.0283168466 |
| `stage_daily_mean` | DV | `dv:00065:00003` | ft | m | × 0.3048 |
| `stage_daily_max` | DV | `dv:00065:00001` | ft | m | × 0.3048 |
| `stage_daily_min` | DV | `dv:00065:00002` | ft | m | × 0.3048 |
| `stage_instantaneous` | IV | `uv:00065:` | ft | m | × 0.3048 |

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

**Divergence from legacy behavior:** The legacy `USAFetcher._parse_data()` did `pd.to_datetime(df.index.dt.date)`, which stripped timezone and time-of-day entirely and produced a timezone-naive date index at midnight. The new implementation preserves the full UTC timestamp, so a DV observation for `2023-01-01` at a CST station becomes `2023-01-01T06:00:00Z`, not `2023-01-01T00:00:00Z`. This is the ported behavior; shared time and zone representation is owned by [ADR 0006](../adr/0006-time-and-zone-are-two-columns.md) and [ADR 0007](../adr/0007-zone-values-are-iana-offset-or-unknown.md).

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
| National catalogue | Resolved | The committed native table contains 26,258 stations and 2,036,546 aligned source-series rows from the attested 51-code scope. |
| Two mutually exclusive site-service views | Resolved | Refresh performs separate strict RDB series and expanded passes, checks cross-pass equality, and joins on exact `site_no`. |
| Reproducible canonical build | Resolved | Canonical artifacts are built offline only with `--native catalogue/native.parquet --out catalogue/`; live and supplied-RDB modes refresh the native table only. |
| Per-variable availability | Resolved | Exact source-series matching emits `available` or `unavailable`; zero national matches fail the build and no station-product remains `unknown`. |
| USGS API rate limits | Not enforced | USGS WaterServices has no documented hard rate limit for individual queries. Rate limit enforcement deferred post-V1. |
