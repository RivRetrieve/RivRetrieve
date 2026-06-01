# lt_lhmt Provider Port Notes

These notes capture evidence and decisions from porting the Lithuanian Hydrometeorological Service (Meteo.lt) provider. They are not user documentation. Provider-specific pain stays here; shared harness changes require a concrete architecture.md update.

## Source Endpoints

| Endpoint | Role | Credential status | Notes |
| --- | --- | --- | --- |
| `https://api.meteo.lt/v1/hydro-stations` | Maintainer-side catalogue input (station metadata). Runtime catalogue reads packaged artifacts only. | No token. | Returns a JSON array; each element has `code`, `name`, `waterBody`, `coordinates.latitude`, `coordinates.longitude`. |
| `https://api.meteo.lt/v1/hydro-stations/{station_id}/observations/historical/{YYYY-MM}` | Runtime observation retrieval per station per calendar month. | No token. | Returns `{"observations": [...]}` where each entry has `observationDateUtc`, `waterDischarge`, and `waterLevel`. Rate limit: 180 requests/minute per the legacy fetcher comment. HTTP 404 means no data for that station/month, not an error. |

## Catalogue Mapping

| Source field | Canonical target | Provider metadata | Decision |
| --- | --- | --- | --- |
| `code` | `station_id` | `native_code` | Slug-style string identifiers (e.g. `anyksciu-vms`). Already unique. |
| `name` | `name` | `name` | Station name, preserved verbatim including Unicode (Lithuanian diacritics). |
| `waterBody` | No common column | `water_body` | River/water-body name; no canonical common-schema column for this. Preserved as provider metadata. |
| `coordinates.latitude` | `latitude` | `latitude` | Numeric, direct. |
| `coordinates.longitude` | `longitude` | `longitude` | Numeric, direct. |
| — | `elevation_m` | `elevation_m` | Not provided by the API. Stored as `None`; canonical column is nullable. |
| — | `drainage_area_km2` | `drainage_area_km2` | Not provided by the API. Stored as `None`; canonical column is nullable. |
| `waterDischarge` | `discharge_daily_mean` → `value` | `native_field`, `native_unit` | Direct: already in m³/s, no conversion needed. |
| `waterLevel` | `stage_daily_mean` → `value` | `native_field`, `native_unit`, `unit_conversion` | **Unit conversion required: cm → m (divide by 100).** This is the main numeric pain point. |

## Product Dictionary

Two canonical products, no provider-specific product IDs.

| API field | `product_id` | Native unit | Canonical unit | Conversion |
| --- | --- | --- | --- | --- |
| `waterDischarge` | `discharge_daily_mean` | m³/s | m³/s | None |
| `waterLevel` | `stage_daily_mean` | cm | m | divide by 100 |

Both products have `frequency=daily`, `statistic=mean`, `period_type=interval`, `period_anchor=provider_defined`. The API documentation does not define whether the daily observation is a start-of-day, end-of-day, or midnight-centered mean; `provider_defined` is the correct anchor.

No V1 vocabulary expansion needed. The legacy Lithuania fetcher exposed exactly `DISCHARGE_DAILY_MEAN` and `STAGE_DAILY_MEAN`, both mapping directly to canonical products.

## Time and Timezone

**Key finding:** Meteo.lt `observationDateUtc` values are **date-only strings** (`YYYY-MM-DD`), not datetimes. There is no time-of-day component. The field name includes `Utc`, which is the only explicit timezone signal.

**Decision:** Interpret date-only strings as UTC midnight (`T00:00:00Z`). The UTC claim is the provider's own declaration via the field name `observationDateUtc` — that is sufficient authority. The parser appends `T00:00:00Z` before calling `str.to_datetime(time_zone="UTC")`.

**Structured issue emitted:** `date_only_timestamp` — warning-severity issue per parsed month whenever date-only strings are encountered. Also recorded as a `date_only_timestamp_flag=true` series annotation.

**Series annotation `resolved_timezone` is always `"UTC"** for lt_lhmt. No timezone ambiguity because the source field name asserts UTC explicitly.

This is a provider-specific fact and does not update architecture.md §16. The architecture already requires timezone facts in series annotations and structured issues for inferred or ambiguous timestamps.

## Observation Retrieval Design

### Monthly chunking instead of 366-day windows

The legacy fetcher decomposed date ranges into calendar-month chunks (`pd.date_range(start, end, freq="MS")`). This matches the API URL shape (`/historical/{YYYY-MM}`). The lt_lhmt port uses the same monthly decomposition.

### 404 handling

HTTP 404 on a month URL means that station/month has no data. The legacy fetcher silently skipped 404s (`if r.status_code == 404: continue`). The lt_lhmt port issues a structured `http_not_found` warning per 404 month rather than silently skipping — this satisfies the on_issue contract without raising by default.

### No auth token

No `Authorization` header, no embedded credential, no environment variable for credentials. This simplifies the client considerably compared to ch_foen.

### Rate limiting

The legacy fetcher enforced a rolling 180-requests/minute limit with a deque. The lt_lhmt runtime port does not implement active rate-limit enforcement in V1. The rate limit is documented in `provider.json` metadata for maintainer awareness. If rate limiting is needed in production, it belongs in a future transport middleware layer, not hardcoded in the provider.

### No fallback fields

Unlike ch_foen (which has `flow` / `flow_ls` fallback, `height_abs` / `height` fallback), Meteo.lt has exactly one field per product. The transform layer has no preferred/fallback selection logic.

## Catalogue Generation

The generator reads a JSON array fixture (or live endpoint) and materializes:
- 97 stations (as of 2026-05-31 fixture)
- 2 products
- 97 × 2 = 194 station-product rows with `availability=unknown`

Station-product availability is `unknown` because the Meteo.lt hydro-stations catalogue does not indicate which stations have which variables. The actual availability must be probed by attempting observation requests.

## Pain Points

| Issue | Status | Action |
| --- | --- | --- |
| Date-only timestamps | Active; mitigated with UTC-midnight interpretation + structured issue. | Keep `date_only_timestamp` issue code; document in series annotations. |
| Stage unit is cm, not m | Active; convert on ingest with `divide_by_100`. Raw value preserved in `raw_value` row annotation. | No further action needed. |
| No per-variable station availability | Active; all station-product pairs materialized as `availability=unknown`. | Future: probe live API to determine real availability. |
| 404 months emit issues | Active; structured `http_not_found` warning per 404 month. | Documented. |
| No rate-limit enforcement in runtime | Active (V1 deferral). | Document rate limit in provider metadata; add transport middleware in V2 if needed. |
| elevation_m and drainage_area_km2 always null | Active (API limitation). | Same as ch_foen; canonical columns are nullable. |
