# th_thaiwater Provider Port Notes

These notes capture evidence and handoff context from the `th_thaiwater` provider port. They are not user documentation and not an architecture contract; promote shared harness commitments to [ADRs](../adr/) only with concrete evidence.

## Source Endpoints

| Endpoint | Role | Credential | Notes |
| --- | --- | --- | --- |
| `https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_load` | Maintainer-side native-table refresh input; returns all telemetered stations in one response. | None. Public ThaiWater Open API. | Canonical artefacts are built offline from committed `native.parquet` plus origins. |
| `https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_graph` | Runtime observation retrieval. Query params: `station_type=tele_waterlevel`, `station_id`, `start_date` (YYYY-MM-DD), `end_date` (YYYY-MM-DD). | None. | Returns a `data.graph_data` list with `datetime`, `value` (stage in m), and `discharge` (m³/s) fields per row. |

## Observation Time and Zone

The recorded `graph_data[].datetime` values use `YYYY-MM-DD HH:MM` with no UTC designator,
numeric offset, or timezone field. No captured official source establishes a zone. The parser therefore
preserves each value as a naive source wall clock and sets `time_zone="unknown"`. It does not infer
`Asia/Bangkok` from the country, station coordinates, or retired code. `to_utc` refuses these rows
atomically.

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

The packaged catalogue advertises two source-published reported-value products. Their temporal support is unknown. It does not
advertise daily means; those were derived by the retired observation implementation.

| Native field | Canonical `product_id` | Unit |
| --- | --- | --- |
| `value` | `stage_reported` | m |
| `discharge` | `discharge_reported` | m³/s |

No unit conversion is required.

## Observation Retrieval

- **Windowing**: the shared engine renders one inclusive date request for the requested source-label window. No publisher cap is claimed.
- **Request**: `station_type=tele_waterlevel`, `station_id`, `start_date`, and `end_date` are sent to
  `waterlevel_graph` through the shared `HttpClient` transport seam.
- **Coalescing**: one graph response publishes both `value` and `discharge`, so a station-window
  requested for both products produces one source call and one publisher receipt.
- **Parsing**: `value` and `discharge` are projected directly into source-labeled rows without claiming an instant or interval. Nulls
  remain null. `value_out` remains uninterpreted. There is no provider clipping, aggregation, unit
  conversion, retry loop, or result assembly.

## Station Count

825 stations at catalogue version `2026-08-02`, built offline from committed `native.parquet` plus the five station origins. Every native row is required to have `station_type == "tele_waterlevel"`, non-null latitude and longitude, and a unique String `station.id`; violations fail the build rather than being filtered, dropped, or deduplicated.

The packaged station-product carrier contains exactly the two edges established by the recorded
station `1373273` response: `stage_reported` and `discharge_reported`. Their published record
bounds remain null and `last_catalogue_check` is the recording date, `2026-09-02`. The other 1,648
candidate availability facts remain explicitly withheld and do not become catalogue rows.

## Shared Architecture Impact

The public selection path previously drove each selected station-product edge as a separate engine
request. That prevented a provider from coalescing fields published by one response. The public path
now groups the selected products for each station before it calls the engine; it does not invent a
station-product Cartesian product.

## Pain Points

| Issue | Status | Action |
| --- | --- | --- |
| Naive graph timestamps | Source zone is not established. | Preserve wall clock with `time_zone="unknown"`; never infer UTC or Bangkok. |
| Response publishes two products together | Expressed by one payload with two station-product pairs. | Keep one call and receipt per station-window. |
| No elevation or drainage area | Null in the canonical station columns. | Do not infer values. |
| Multilingual station names | Preserved in flattened native columns. | Keep source language values unchanged. |
