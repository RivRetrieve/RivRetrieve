# br_ana Provider Port Notes

These notes capture endpoint facts, catalogue mapping decisions, and pain points from porting Brazil's ANA Hidroweb provider. Pain that is `br_ana`-specific stays here; shared harness gaps would be promoted to [architecture.md](../../architecture.md).

## Source Endpoints

| Endpoint | Role | Credential status |
| --- | --- | --- |
| `https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/OAUth/v1` | Bearer token authentication. Credentials via `Identificador` and `Senha` request headers. Returns `{"status":"OK","items":{"tokenautenticacao":"<token>","sucesso":true}}` on success, `{"status":"UNAUTHORIZED","items":null}` on failure. Token TTL 60 min per ANA documentation; conservatively cached for 55 min (3300 s). | `ANA_IDENTIFICADOR` + `ANA_SENHA` env vars required. |
| `https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroInventarioEstacoes/v1` | Station metadata per-state. Called with `?Unidade%20Federativa=<STATE>` for each of the 27 Brazilian states + DF. Response is either a bare JSON array or `{"status":"OK","items":[...]}`. | Bearer token required. |
| `https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroSerieVazao/v1` | Daily discharge time series (`discharge_daily_mean`). | Bearer token required. |
| `https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroSerieCotas/v1` | Daily stage time series (`stage_daily_mean`). | Bearer token required. |

## URL Encoding Pain Point

The ANA observation endpoints use **Portuguese parameter names with special characters** (accented letters, spaces, parentheses). The source encodes these manually:

```
Código da Estação     → C%C3%B3digo%20da%20Esta%C3%A7%C3%A3o
Tipo Filtro Data      → Tipo%20Filtro%20Data
Data Inicial (yyyy-MM-dd) → Data%20Inicial%20(yyyy-MM-dd)
Data Final (yyyy-MM-dd)   → Data%20Final%20(yyyy-MM-dd)
```

These pre-encoded names are embedded in the URL string directly. Using `requests.get(params=dict)` would double-encode them (e.g. `%` → `%25`). The `BrAnaObservationClient` constructs the full URL as a string and passes `params=None` to the requests transport.

## Authentication Model (Novel for RivRetrieve)

`br_ana` is the first authenticated provider in this codebase.

**Design decisions:**
- Credentials are read from `ANA_IDENTIFICADOR` / `ANA_SENHA` env vars (or passed to `BrAnaObservationClient` directly).
- Token is fetched lazily on the first observation request and cached until near-expiry.
- If no credentials are present, `retrieve_observations()` immediately returns an empty `ObservationResult` with one `auth_missing` warning issue (no per-station loops).
- If credentials are present but the token request fails, an `auth_failed` issue is emitted per-window.
- Credentials are **never written to provenance, raw metadata, or any log**. The `BrAnaObservationClient` only passes credentials in HTTP request headers.
- The observable impact for offline tests: pass a `transport` callable to `BrAnaObservationClient` that returns a fake token response for `AUTH_URL` and fixture data for data URLs.
- `generate_catalogue.py` uses `urllib.request` directly (no `requests`) so no token caching is needed during maintainer catalogue generation.

## Catalogue Mapping

| Source field | Canonical target | Decision |
| --- | --- | --- |
| `codigoestacao` | `station_id` | String coercion. |
| `Estacao_Nome` | `name` | Direct. |
| `Latitude`, `Longitude` | `latitude`, `longitude` | Direct. Stations without both are filtered out. |
| `Altitude` | `elevation_m` | Direct (meters). Present for most stations. |
| `Area_Drenagem` | `drainage_area_km2` | Direct (km²). Present for most stations. |
| `Bacia_Nome` | `metadata.basin_name` | No common schema column for basin/river name; preserved in metadata. |
| Country | `country = "Brazil"` | Constant. |

Station-product availability: materialized as `availability="unknown"` for all station × product pairs because the inventory endpoint does not expose per-variable data availability.

## Product Mapping

| Product | Native endpoint | Native unit | Canonical unit | Conversion |
| --- | --- | --- | --- | --- |
| `discharge_daily_mean` | `HidroSerieVazao/v1` | m³/s | m³/s | None (factor 1.0) |
| `stage_daily_mean` | `HidroSerieCotas/v1` | cm | m | ÷100 |

Stage raw value (cm) is always preserved in the `raw_value` row annotation.

## Response Format: Monthly Columnar Structure

The observation APIs return one JSON object per calendar month per station. Each object contains:
- `Data_Hora_Dado`: string like `"2020-01-01T00:00:00"` (year and month encoded in first 7 chars)
- `Vazao_01`..`Vazao_31` (discharge) or `Cota_01`..`Cota_31` (stage): string-encoded floats or `null`

Day values are reconstructed by iterating `1..31` and catching `ValueError` for invalid dates (e.g. Feb 30, Apr 31). The top-level response is either:
- A bare JSON array: `[{month1}, {month2}, ...]`
- A wrapper object: `{"status": "OK", "items": [{month1}, ...]}`

Both formats are handled in `parse_br_ana_json`.

## Timezone

The ANA API provides no explicit timezone for daily values. The source code constructs naive `datetime(year, month, day)` objects. This port interprets all timestamps as UTC midnight (`T00:00:00Z`) following the same pattern as `lt_lhmt`, `fr_hubeau`, and `jp_mlit` daily products.

True local timezone is undocumented. Brazil uses multiple timezones (UTC-5 to UTC-2); the ANA agency operates in Brasília Standard Time (UTC-3). However, since the data is daily and the API provides no explicit timezone, UTC midnight is the safest and most consistent interpretation.

Per-fetch: a `date_only_timestamp` `warning`-severity issue is emitted.
Per-series: `timezone_source = "date_only_utc_midnight"`, `date_only_timestamp_flag = "true"` series annotations are always set.

## Windowing

Annual chunks (year-by-year), matching the legacy `BrazilFetcher._download_data` pattern. `_split_annual_windows` decomposes `[start, end]` into `[(YYYY-01-01, YYYY-12-31), ...]` aligned to calendar years, clipped to the request range.

HTTP 404 per window emits `http_not_found` warning issue (not fatal), matching the established pattern from `lt_lhmt`, `usgs_nwis`, `cz_chmi`, `th_thaiwater`, `fr_hubeau`, `jp_mlit`.

## Live Catalogue Generation

The generator fetches station metadata for all 27 states + DF sequentially with 0.1 s sleep between state requests to be polite to the API. A minimum live station guard of 1000 stations is set (Brazil reportedly has ~4000+ telemetry gauges; conservative floor catches silent fetch failures).

Run with:
```bash
ANA_IDENTIFICADOR=<user> ANA_SENHA=<pass> \
  python src/rivretrieve/_internal/providers/br_ana/generate_catalogue.py \
  --live --out src/rivretrieve/_internal/providers/br_ana/catalogue/
```

## Architecture.md Impact

None. Authentication, date-only UTC midnight timestamps, annual windowing, and manual URL encoding are all provider-specific. No shared harness gap discovered.

The authentication pattern (credentials via env vars, token cached in client, missing credentials → structured issue) is `br_ana`-specific for now. If future authenticated providers are added, the token management pattern here could serve as a reference, but it should not be promoted to shared harness until there is concrete evidence of reuse need.
