# lt_lhmt Provider Port Notes

These notes capture evidence and decisions from porting the Lithuanian Hydrometeorological Service (Meteo.lt) provider. They are not user documentation. Provider-specific porting details stay here. See [Architecture](../architecture.md) for shared contracts.

## Source Endpoints

| Endpoint | Role | Credential status | Notes |
| --- | --- | --- | --- |
| `https://api.meteo.lt/v1/hydro-stations` | Maintainer-side catalogue input (station metadata). Runtime catalogue reads packaged artifacts only. | No token. | Returns a JSON array; each element has `code`, `name`, `waterBody`, `coordinates.latitude`, `coordinates.longitude`. |
| `https://api.meteo.lt/v1/hydro-stations/{station_id}/observations/historical/{YYYY-MM}` | Runtime observation retrieval per station per calendar month. | No token. | Returns `{"observations": [...]}` where each entry has `observationDateUtc`, `waterDischarge`, and `waterLevel`. Rate limit: 180 requests/minute per the legacy fetcher comment. HTTP 404 means no data for that station/month, not an error. |

## Catalogue Mapping

| Native field | Canonical target | Decision |
| --- | --- | --- |
| `code` | `provider_id`, `station_id` | Exact slug-style source identity. |
| `coordinates` latitude and longitude | `latitude`, `longitude` | Direct numeric coordinates. |
| Publisher API documentation | `crs` | Documented constant `EPSG:4326`. |
| `name`, `waterBody`, and other fields | Native only | Preserved in source vocabulary and not promoted into identity-and-geometry columns. |

Observation parsing remains direct for `waterDischarge` in m³/s and `waterLevel` in cm. The shared
engine converts stage from cm to canonical metres.

## Product Dictionary

Two canonical products, no provider-specific product IDs.

| API field | `product_id` | Native unit | Canonical unit | Conversion |
| --- | --- | --- | --- | --- |
| `waterDischarge` | `discharge_daily_mean` | m³/s | m³/s | None |
| `waterLevel` | `stage_daily_mean` | cm | m | divide by 100 |

Both products have `frequency=daily`, `statistic=mean`, `period_type=interval`, `period_anchor=provider_defined`. The API documentation does not define whether the daily observation is a start-of-day, end-of-day, or midnight-centered mean; `provider_defined` is the correct anchor.

No V1 vocabulary expansion needed. The legacy Lithuania fetcher exposed exactly `DISCHARGE_DAILY_MEAN` and `STAGE_DAILY_MEAN`, both mapping directly to canonical products.

## Time and Timezone

The official API documentation defines `observationDateUtc` as an observation date in UTC. The parser
preserves its date label as a naive midnight wall clock and sets `time_zone="+00:00"`. The daily
interval anchor remains provider-defined because the documentation does not state whether the label
is the start or end of the represented day.

## Observation Retrieval Design

The shared engine decomposes the padded fetch window into `YYYY-MM` values. The provider fetcher sends
one exact monthly request per station-month through `HttpClient`. Because each response contains both
`waterDischarge` and `waterLevel`, requests for both products coalesce into one source call and one
publisher receipt. HTTP 404 and retry exhaustion become source issues. The provider performs no
clipping, unit conversion, retry loop, or result assembly.

## Native Catalogue Attestation

The complete `/v1/hydro-stations` response was retrieved at `2026-08-01T18:31:08Z` and verified
content-identical to `tests/test_data/lithuania_metadata_stations.json`. It contains 97 stations.
Sorting by `code` and serializing with sorted object keys, compact separators, default
`ensure_ascii=True`, and UTF-8 produces SHA-256
`02d16a6e872939b43ee7ae6d1c54e00b6b924f3d9a3f9a7553fc13680edc12d8` for both inputs.

Canonical artefacts are built only from committed `catalogue/native.parquet` plus origins. They contain
97 stations, two products, and 194 station-product rows with `availability=unknown` because the station
endpoint does not publish variable availability. The digest and pure build are checked by
`tests/test_lt_lhmt_generate_catalogue.py`.

## Pain Points

| Issue | Status | Action |
| --- | --- | --- |
| Date-only UTC labels | Documented source semantics. | Preserve midnight wall clock and `+00:00`; keep interval anchor provider-defined. |
| Stage unit is cm | Declared in provider config. | Shared conversion changes cm to m. |
| No per-variable station availability | Existing packaged Lithuania edges remain `unknown`. | Do not broaden catalogue claims. |
| Source request failures | 404 and retry exhaustion are recoverable source issues. | Generic retry policy remains in `HttpClient`. |
