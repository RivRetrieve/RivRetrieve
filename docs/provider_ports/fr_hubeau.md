# fr_hubeau Provider Port Notes

These notes capture evidence and context from porting France / Hubeau. They are not user documentation and not an architecture contract.

## Source Endpoints

| Endpoint | Role | Credentials |
| --- | --- | --- |
| `https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations` | Maintainer-only: station catalogue generation (paginated). | None — public API. |
| `https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab` | Runtime: observation retrieval (paginated with `next` link). | None — public API. |

## Catalogue Mapping

| Legacy / source field | Canonical target | Provider metadata | Decision |
| --- | --- | --- | --- |
| `code_station` | `station_id` | `native_id` | Direct — matches Hubeau obs_elab `code_entite`. |
| `libelle_station` | `name` | `name` | Provider station label. |
| `longitude_station`, `latitude_station` | `longitude`, `latitude` | `latitude`, `longitude` | WGS84 decimal degrees — used directly. Stations without valid coordinates are filtered out. |
| `altitude_ref_alti_station` | `elevation_m` | `elevation_m` | In meters — used directly. Null when not provided. |
| `surface_bv_reel_station` | `drainage_area_km2` | `drainage_area_km2` | In km² — used directly. Null when not provided. |
| `libelle_cours_eau` | None (no common column) | `river_name` | Preserved as metadata. |
| `libelle_commune`, `libelle_departement` | None | `commune`, `departement` | Preserved as metadata for administrative reference. |
| `en_service`, `date_ouverture_station` | None | `in_service`, `opening_date` | Preserved as metadata. |

## Product Mapping

| Legacy variable | Hubeau grandeur | Native unit | Canonical product | Conversion |
| --- | --- | --- | --- | --- |
| `constants.DISCHARGE_DAILY_MEAN` | `QmnJ` (débit moyen journalier) | l/s | `discharge_daily_mean` | ÷ 1000 → m³/s |
| `constants.STAGE_DAILY_MAX` | `HIXnJ` (hauteur instantanée maximale journalière) | mm | `stage_daily_max` | ÷ 1000 → m |

Both products are V1 canonical. No fr_hubeau-specific product IDs needed.

## Timezone / Timestamp Convention

**Key decision:** Hubeau `obs_elab` returns `date_obs_elab` as date-only strings (`YYYY-MM-DD`). No time-of-day component.

- Interpretation: UTC midnight (`YYYY-MM-DDT00:00:00Z`).
- Series annotation `date_only_timestamp_flag = "true"` always set.
- Series annotation `timezone_source = "date_only_utc_midnight"`.
- Warning issue `date_only_timestamp` emitted per parser call when date-only rows are encountered.

France operates on CET (UTC+1) / CEST (UTC+2). For daily elaborated observations, the date represents a French calendar day but the underlying timezone is not tracked in the response. The UTC midnight interpretation is consistent and follows the same pattern as Lithuania (lt_lhmt). A user wanting French-civil-day alignment should use the date component, not the full timestamp.

## Pagination

Hubeau `obs_elab` uses cursor-based pagination:
- Initial request to base URL with query parameters.
- Response includes `"next"` field with full URL for the next page (or `null`).
- Subsequent requests use the full `next` URL with no additional parameters.
- HTTP 206 (Partial Content) is returned for paginated results — this is not an error; `requests.raise_for_status()` does not raise for 2xx codes.

The observation client makes one HTTP call at a time; the retrieval layer loops until `next_url is None`.

The station catalogue generator uses the same `next` URL pattern.

## Quirks and Pain Points

| Issue | Resolution |
| --- | --- |
| HTTP 206 on paginated results | Not an error — 206 is a valid 2xx response; `raise_for_status()` does not raise. Pagination followed via `parsed.next_url`. |
| Large paginated response | Station `A021005050` (Rhine at Basel) returns 18848 obs_elab records total when fetching a long range — pagination essential. |
| Date-only timestamps | Hubeau `date_obs_elab` is date-only for daily obs_elab products. Interpreted as UTC midnight; `date_only_timestamp` warning emitted. |
| Unit conversion | `QmnJ` in l/s (÷1000 → m³/s); `HIXnJ` in mm (÷1000 → m). Same factor for both but different semantics documented in product metadata. |
| No per-variable station availability | `referentiel/stations` does not expose which grandeurs each station reports. All station-product pairs materialised as `availability=unknown`. |
| Station coordinates | Stations without `latitude_station` or `longitude_station` are filtered out during catalogue generation. |
| Overseas stations | Hubeau includes stations in DOM-TOM (French overseas: Guadeloupe, Martinique, etc.) — these are included in the catalogue under `country="France"`. |

## Station Count (2026-06-03)

6420 stations with valid coordinates from Hubeau `referentiel/stations?in_use=true`. Minimum live-station guard set at 500 in `generate_catalogue.py`.

## Schema Divergence from Legacy

Legacy `FranceFetcher.get_data()` returns a wide-form pandas DataFrame indexed by date, one column per variable. The new provider returns long-form `ObservationResult` with canonical columns `time`, `station_id`, `product_id`, `value`, plus row and series annotations and structured provenance.
