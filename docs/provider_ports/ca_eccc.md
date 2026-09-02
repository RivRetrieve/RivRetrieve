# ca_eccc Provider Port Notes

## Source Endpoints

| Endpoint | Role | Auth | Notes |
|---|---|---|---|
| `https://api.weather.gc.ca/collections/hydrometric-stations/items` | Native catalogue refresh | None — public open data | OGC Features API; paginated with `limit=1000` and offsets until `numberMatched` is reached exactly. Coordinates are GeoJSON longitude, latitude. |
| `https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/Hydat_sqlite3_YYYYMMDD.zip` | Observation cache | None | Date-stamped HYDAT SQLite archive downloaded and cached by the observation client. |

## Catalogue and Observation Source Split

Catalogue refresh uses the ECCC OGC Features API because it exposes the complete station population in
a structured source vocabulary. Observation retrieval remains HYDAT-based: the observation client
downloads the national SQLite archive, caches it locally, and queries `DLY_FLOWS` and `DLY_LEVELS`.
The catalogue migration does not change that cache lifecycle, query path, issue vocabulary, or parser.

## Native Catalogue and Origins

The committed `native.parquet` contains all 8,057 features supplied by the orchestrator's attested
live fetch at `2026-08-02T01:09:10Z`. It has 17 source columns: feature `id`, all 13 property fields,
geometry type, and both coordinate scalars, plus the stamped UTC `retrieved_at`. Rows sort by feature
`id`. Source strings, integers, floats, and nulls are preserved without defaults or trimming.

The complete census found zero missing or duplicate `STATION_NUMBER` values, zero invalid coordinate
rows, and zero disagreements among `id`, `IDENTIFIER`, and `STATION_NUMBER`. Consequently all 8,057
native rows become canonical stations; any future offender produces named issues and aborts the build
instead of being filtered. `DRAINAGE_AREA_EFFECT` contains 1,661 populated source floats and 6,396
source nulls.

The nine-page FeatureCollection was retrieved from `2026-08-02T01:09:10Z` through
`2026-08-02T01:09:20Z`, assembled in attested page order, and canonicalized with sorted
object keys, compact separators, `ensure_ascii=False`, and UTF-8. Its SHA-256 is
`3613c17b3e1ad76e8490d6dcb659be251f2270e5568fb6ff1e05fe780037083d`. Native-table and sorted-id
digests are enforced by `catalogue/provenance.json` and `tests/test_ca_eccc_catalogue.py`.

| Source field | Canonical target | Notes |
|---|---|---|
| `properties.STATION_NUMBER` | `station_id` | Exact native station identity; no normalization. |
| `geometry.coordinates[1]` | `latitude` | GeoJSON lon, lat order — lat is index 1 |
| `geometry.coordinates[0]` | `longitude` | Source longitude, unchanged. |
| Collection metadata CRS84 declaration | `crs` | Documented as `EPSG:4326`; CRS84 establishes longitude/latitude source order while canonical columns name each axis separately. No transformation or reprojection. |

Every other source field remains readable in the native table. `VERTICAL_DATUM` is native-only and is
not treated as a horizontal CRS. Drainage areas, names, status, contributors, province/territory, and
real-time flags are not promoted into the identity-and-geometry canonical station shape.

## Products

Both products read daily values from the cached HYDAT SQLite archive.

| Product ID | OGC field | Symbol field | Unit | Notes |
|---|---|---|---|---|
| `discharge_daily_mean` | `FLOW` | `FLOW_SYMBOL` | m³/s | `DLY_FLOWS`; no conversion. |
| `stage_daily_mean` | `LEVEL` | `LEVEL_SYMBOL` | m | `DLY_LEVELS`; no conversion. |

## Timestamps

HYDAT publishes calendar dates without a source time-zone or day-definition declaration. Unlike the live adapters that use the established `date_only_timestamp` convention, the bulk store retains each date as a naive midnight wall-clock value with `time_zone = "unknown"`. RivRetrieve does not infer UTC or a Canadian zone.

## Quality Flags

`FLOW_SYMBOL1..31` and `LEVEL_SYMBOL1..31` remain exact native HYDAT cells in the compiled store and opt-in store-excerpt receipts. They are not interpreted, harmonised, or added to the five-column canonical result.

## Station-Product Availability

All rows are `availability = "unknown"`. The OGC stations endpoint does not expose per-variable availability (unlike NVE HydAPI's `seriesList`). Users requesting a station/product pair may encounter HTTP 404 or empty results when the station does not measure that variable.

## Live Catalogue

`live_stations = False` — the generator is a maintainer tool. Runtime catalogue paths read packaged Parquet artifacts.

The `--live` refresh operation fetches `hydrometric-stations/items` with `limit=1000`, requires each
page to agree on `numberMatched`, and stops only at exact accumulated equality. It rejects malformed,
missing, repeated, short intermediate, underflowing, and overflowing pages and repeated feature ids.
The usable-station floor is 8,055, calibrated to the prior successful catalogue. Canonical build is a
separate network-free operation over committed `native.parquet` plus origin declarations.

## Pagination

The attested station population required nine requests at offsets 0 through 8,000 and assembled 8,057
features. Tests exercise the same accumulation using a deliberately small page size and a faithful
three-feature FeatureCollection fixture. The fixture is not a flat HYDAT-style list.

## Windowing

HYDAT selects the inclusive range of years containing the requested endpoints. The parser then filters
the reconstructed daily rows to the exact requested dates.

## Station Count

8,057 stations from 8,057 attested OGC features retrieved on 2026-08-02. All have valid coordinates;
no source feature was filtered. The previous 8,055 count is retained only as the live-refresh floor.

## Surprises and Pain Points

| Issue | Detail |
|---|---|
| Coordinates in geometry, not properties | `LATITUDE`/`LONGITUDE` are not source properties. Native columns preserve coordinate indices 0 and 1; the canonical build aliases them only at its strict station inventory boundary. |
| CRS evidence | Collection metadata declares `http://www.opengis.net/def/crs/OGC/1.3/CRS84`; this documents source longitude/latitude order and WGS 84. |
| Source scalar fidelity | `REAL_TIME` and `RHBN` remain integers; drainage values remain floats or source nulls. No fixture compatibility coercions remain. |
| Observation cache | The national HYDAT SQLite archive is cached once and queried read-only per station-product pair. |
| No canonical elevation | The canonical station shape is identity and geometry; source station fields remain in `native.parquet`. |
| No per-variable availability | Cannot materialize `available`/`unavailable` station-product rows at catalogue-generation time. All rows are `unknown`. |
