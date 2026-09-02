# th_thaiwater Provider Port Notes

These notes capture evidence and handoff context from the `th_thaiwater` provider port. They are not user documentation and not an architecture contract; promote shared harness commitments to [ADRs](../adr/) only with concrete evidence.

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

The legacy `ThailandFetcher` drops timezone after localizing (`.dt.tz_localize(None)`), storing naive Bangkok-time datetimes. The new port instead converts to UTC as its provider-specific transform; shared time and zone representation is owned by [ADR 0006](../adr/0006-time-and-zone-are-two-columns.md) and [ADR 0007](../adr/0007-zone-values-are-iana-offset-or-unknown.md).

## Native Catalogue Attestation

The complete `waterlevel_load` response was retrieved at `2026-08-02T12:42:03Z` and contained 825
rows with 825 unique integer `station.id` values. Canonicalizing the parsed response with sorted keys,
compact separators, `ensure_ascii=False`, and UTF-8 produces SHA-256
`d42fdac929ddf87f348ed8cd9a6732768fb9775a47fff2bc54f4e0e74ee8bdee`. The four-row fixture is a
verbatim parser subset, not a native-table source. The native table preserves 61 lexicographically
ordered dotted source columns and widens only values needed for a lossless scalar dtype. The source
population has changed relative to the legacy catalogue: 87 new IDs are present and 16 legacy IDs are
absent, so the 825-row result is source churn rather than a missing filter. The committed native-frame
digest and semantic comparison are held by `catalogue/provenance.json`, origins, and generator tests.

The publisher coordinate-standard page was captured at `2026-08-02T13:51:44Z` as
`tests/test_data/th_thaiwater_coordinate_standard.html`. Its byte identity and SHA-256 are pinned by
the origin-evidence receipt; it documents coordinate semantics and contributes no native rows.

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

The packaged catalogue advertises the two source-published instantaneous products. It does not
advertise daily means; those were derived by the retired observation implementation.

| Native field | Canonical `product_id` | Unit |
| --- | --- | --- |
| `value` | `stage_instantaneous` | m |
| `discharge` | `discharge_instantaneous` | m³/s |

No unit conversion is required.

## Observation Retrieval

- **Windowing**: 365-day windows per `MAX_WINDOW_DAYS = 365`. Each station-product request is decomposed into (start_date, end_date) pairs.
- **Date filtering**: After parsing, records are filtered to the Bangkok-day range corresponding to the requested UTC start/end. This prevents off-by-one issues at window boundaries: the filter converts the requested UTC range to Bangkok calendar dates before clamping.
- **Daily aggregation**: Group by Bangkok calendar day (`dt.convert_time_zone("Asia/Bangkok").dt.truncate("1d")`), compute mean, then convert Bangkok midnight → UTC for storage.
- **Instantaneous deduplication**: `dedup.unique(subset=["time"], keep="last", maintain_order=True)` following the same intent as the legacy `drop_duplicates(keep="last")`.
- **HTTP 404**: Emits `http_not_found` warning issue (not fatal), matching the lt_lhmt / usgs_nwis / cz_chmi pattern.

## Station Count

825 stations at catalogue version `2026-08-02`, built offline from committed `native.parquet` plus the five station origins. Every native row is required to have `station_type == "tele_waterlevel"`, non-null latitude and longitude, and a unique String `station.id`; violations fail the build rather than being filtered, dropped, or deduplicated.

The packaged station-product carrier is currently empty. Availability lacks row-level acquisition
bindings, so the loader withholds all 1,650 candidate rows and records
`no_acquisition_record_established` for each.

## Shared Architecture Impact

None. The Bangkok→UTC conversion is provider-specific. The structured `timezone_local_to_utc` info-issue is provider-specific. Daily Bangkok-day aggregation is provider-specific. No shared harness gap discovered.

## Pain Points

| Issue | Status | Action |
| --- | --- | --- |
| Naive Bangkok timestamps | Documented; handled by zoneinfo conversion in parser. | Keep timezone annotation + issue; do not change. |
| Daily aggregation on Bangkok calendar days | Implemented in transform layer via `convert_time_zone("Asia/Bangkok").dt.truncate("1d")`. | Bangkok midnight UTC timestamps (e.g., 17:00Z) may look surprising to users; the series annotation `local_timezone = "Asia/Bangkok"` documents this. |
| No elevation or drainage area | `None` in both common columns; documented in metadata. | No action needed. |
| Multilingual station names | Preserved as flattened native columns in `native.parquet`. | Keep source language values unchanged. |
| Former station-type, null-coordinate, and duplicate-ID filters | Replaced by explicit fatal build contracts. | Never silently reject a native row during canonical generation. |
