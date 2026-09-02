# br_ana Provider Port Notes

These notes capture endpoint facts, catalogue mapping decisions, and pain points from porting Brazil's ANA Hidroweb provider. Pain that is `br_ana`-specific stays here; shared harness gaps would be promoted to [ADRs](../adr/).

## Source Endpoints

| Endpoint | Role | Credential status |
| --- | --- | --- |
| `https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/OAUth/v1` | Bearer token authentication. Credentials via `Identificador` and `Senha` request headers. Returns `{"status":"OK","items":{"tokenautenticacao":"<token>","sucesso":true}}` on success, `{"status":"UNAUTHORIZED","items":null}` on failure. Token TTL 60 min per ANA documentation; conservatively cached for 55 min (3300 s). | `ANA_IDENTIFICADOR` + `ANA_SENHA` env vars required. |
| `https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroInventarioEstacoes/v1` | Station metadata per-state. Called with `?Unidade%20Federativa=<STATE>` for each of the 27 Brazilian states + DF. Response is either a bare JSON array or `{"status":"OK","items":[...]}`. | Bearer token required. |
| `https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroSerieVazao/v1` | Daily discharge time series (`discharge_daily_mean`). Legacy/"convencional" (manual-collection) columnar series — no quality flags, no temperature. | Bearer token required. |
| `https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroSerieCotas/v1` | Daily stage time series (`stage_daily_mean`). Same legacy/"convencional" family as above. | Bearer token required. |
| `https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroinfoanaSerieTelemetricaAdotada/v1` | Telemetric (QC-"adopted") sub-daily series — `discharge_instantaneous` (`Vazao_Adotada`) and `stage_instantaneous` (`Cota_Adotada`), each with a companion `*_Status` quality flag. Native cadence is the station's own telemetry interval (commonly ~15 min); requests are capped at 30 days (`Range Intervalo de busca`, max `DIAS_30`, anchored by `Data de Busca`). | Bearer token required. |
| `https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroinfoanaSerieTelemetricaDetalhada/v1` | Telemetric "detailed" series — superset of `Adotada` that also returns raw sensor fields. Used exclusively for `water_temperature_instantaneous` (`Temperatura_Agua` + `Temperatura_Agua_Status`; `Adotada` does not carry temperature). Same 30-day windowing constraint. | Bearer token required. |

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
| `Tipo_Estacao_Desc_Liquida`, `Tipo_Estacao_Escala`, `Tipo_Estacao_Qual_Agua` | (filter only — not preserved as a column) | Stations are kept only if **at least one** of these three flags is truthy (discharge / stage-level / water-quality measurement capability). Stations with none set are typically pure rain-gauge ("pluviométrica") stations, which are out of scope for `discharge_daily_mean`/`stage_daily_mean`. Flags are parsed tolerantly (`_to_bool`): booleans, 0/1, or Portuguese "Sim"/"Não" strings. Cross-checked against the R `hydrodownloadR` adapter, which surfaces these same three fields as `has_discharge`/`has_level`/`has_quality` (but does not filter on them — RivRetrieve filters at catalogue-build time instead, since our station catalogue is scoped to river discharge/stage products only). |
| `Altitude` | `elevation_m` | Direct (meters). Present for most stations. |
| `Area_Drenagem` | `drainage_area_km2` | Direct (km²). Present for most stations. |
| `Bacia_Nome` | `metadata.basin_name` | No common schema column for basin/river name; preserved in metadata. |
| `Rio_Nome` | `metadata.river_name` | Same rationale as `basin_name` — no common schema column; preserved in metadata. |
| `Data_Periodo_Telemetrica_Inicio`, `Data_Periodo_Telemetrica_Fim` | `start_date`, `end_date` | Parsed via `_to_date` (handles both bare `yyyy-MM-dd` and `yyyy-MM-ddTHH:MM:SS` forms; takes the first 10 chars). The telemetric operating period is the broadest "this station has reported data" signal available in the inventory; other `Tipo_Estacao_*`-specific sub-periods exist (e.g. `Data_Periodo_Desc_Liquida_*`, `Data_Periodo_Escala_*`) but telemetric is used as the umbrella record-range proxy. `Fim` is commonly `null` for currently-operating stations — mapped to `end_date = None`. |
| Country | `country = "Brazil"` | Constant. |

Station-product availability: materialized as `availability="unknown"` for all station × product pairs because the inventory endpoint does not expose per-variable data availability.

## Product Mapping

| Product | Native endpoint | Native unit | Canonical unit | Conversion |
| --- | --- | --- | --- | --- |
| `discharge_daily_mean` | `HidroSerieVazao/v1` | m³/s | m³/s | None (factor 1.0) |
| `stage_daily_mean` | `HidroSerieCotas/v1` | cm | m | ÷100 |
| `discharge_instantaneous` | `HidroinfoanaSerieTelemetricaAdotada/v1` (`Vazao_Adotada`) | m³/s | m³/s | None (factor 1.0) |
| `stage_instantaneous` | `HidroinfoanaSerieTelemetricaAdotada/v1` (`Cota_Adotada`) | cm | m | ÷100 |
| `water_temperature_instantaneous` | `HidroinfoanaSerieTelemetricaDetalhada/v1` (`Temperatura_Agua`) | °C | °C | None (factor 1.0) |

Stage raw value (cm) is always preserved in the `raw_value` row annotation (both daily and instantaneous variants).

`Temperatura_Interna` (logger/internal temperature, also present in the `Detalhada` payload) has no canonical home and no QC flag — it is intentionally **not** mapped to any product.

## Quality Flags (Telemetric Products Only)

The official manual (`manual-hidrowebservice_publica.pdf`) documents a `<Field>_Status` companion field for every telemetric measurement, with semantics **"0 = ok, 1 = suspeito, 2 = ruim"**. This pattern exists **only on the telemetric (`Adotada`/`Detalhada`) endpoints** — the legacy daily columnar series (`HidroSerieVazao`/`HidroSerieCotas`, i.e. `discharge_daily_mean`/`stage_daily_mean`) carry no status fields in either the manual's sample responses or our fixtures, so no quality-flag annotation is emitted for those two products.

For the three telemetric products, the raw numeric code is mapped to a canonical string and captured as a `quality_flag` **row annotation**, following the same pattern as `usgs_nwis`'s `qualifier` and `ca_eccc`'s `quality_flag`:

| Native code (`*_Status`) | Canonical `quality_flag` value |
| --- | --- |
| `"0"` | `ok` |
| `"1"` | `suspect` |
| `"2"` | `poor` |
| anything else / present-but-unrecognised | `unknown` |
| absent (`null`/missing) | *(no annotation emitted)* |

See `TELEMETRIC_QUALITY_FLAG_MAP` in `parser.py`.

## Telemetric Endpoint Facts (Live OpenAPI Spec)

Confirmed live via `https://www.ana.gov.br/hidrowebservice/api-docs`:

- Both `Adotada` and `Detalhada` v1 endpoints require `Código da Estação`, `Tipo Filtro Data` (`DATA_LEITURA`/`DATA_ULTIMA_ATUALIZACAO`), and `Range Intervalo de busca`; `Data de Busca (yyyy-MM-dd)` is optional.
- `Range Intervalo de busca` is an enum of **query-window sizes** — `MINUTO_5`...`HORA_24`, `DIAS_2`, `DIAS_7`, `DIAS_14`, `DIAS_21`, `DIAS_30` — **not** an output-resampling instruction. The endpoint summary states results are **"limitado a 30 dias por requisição"**; the actual reported cadence is whatever the station's telemetry logger reports natively (commonly ~15 minutes per the manual's sample payloads).
- `v2` variants of both endpoints exist, accepting up to 10 comma-separated station codes via `Codigos_Estacoes` — not used here (the v1 single-station form matches the established per-station retrieval loop and keeps the implementation symmetric with the daily-series clients).

**Open question requiring live verification** (see `/tmp/ana_telemetric_diag.py`): the exact relationship between `Data de Busca` and `Range Intervalo de busca` — i.e. whether the resolved window extends backward from, forward from, or is centered on the anchor date. `_split_30day_windows` currently anchors each ≤30-day chunk at its **end** date (the most common "give me the last N days" convention for such APIs); `_filter_local_date_range` then clips the merged result to the originally requested range regardless, so an incorrect anchor assumption would manifest as **gaps** (missing days at chunk boundaries) rather than wrong values — recoverable once the true semantics are confirmed and the anchor strategy adjusted.

## Timezone (Telemetric Products)

Unlike the daily columnar series (date-only, UTC-midnight), telemetric `Data_Hora_Medicao` timestamps carry genuine time-of-day information (e.g. `"2024-06-01 00:15:00.0"`) but the API documents no explicit timezone. They are interpreted as **Brasília Standard Time (UTC-3, no DST since 2019)** — ANA's documented operating timezone — and converted to UTC.

Per-fetch: a `naive_local_timestamp` `info`-severity issue is emitted (distinct from `date_only_timestamp`, since real time-of-day is present).
Per-series: `timezone_source = "naive_local_brt_minus_3"`, `date_only_timestamp_flag = "false"`.

## Response Format: Monthly Columnar Structure

The observation APIs return one JSON object per calendar month per station. Each object contains:
- `Data_Hora_Dado`: string like `"2020-01-01T00:00:00"` (year and month encoded in first 7 chars)
- `Vazao_01`..`Vazao_31` (discharge) or `Cota_01`..`Cota_31` (stage): string-encoded floats or `null`

Day values are reconstructed by iterating `1..31` and catching `ValueError` for invalid dates (e.g. Feb 30, Apr 31). The top-level response is either:
- A bare JSON array: `[{month1}, {month2}, ...]`
- A wrapper object: `{"status": "OK", "items": [{month1}, ...]}`

Both formats are handled in `parse_br_ana_json`.

## Timezone

The ANA API provides no explicit timezone for daily values. The source code constructs naive `datetime(year, month, day)` objects. This port interprets all timestamps as UTC midnight (`T00:00:00Z`) following the same pattern as `lt_lhmt`, `fr_hubeau`.

True local timezone is undocumented. Brazil uses multiple timezones (UTC-5 to UTC-2); the ANA agency operates in Brasília Standard Time (UTC-3). However, since the data is daily and the API provides no explicit timezone, UTC midnight is the safest and most consistent interpretation.

Per-fetch: a `date_only_timestamp` `warning`-severity issue is emitted.
Per-series: `timezone_source = "date_only_utc_midnight"`, `date_only_timestamp_flag = "true"` series annotations are always set.

## Windowing

Two distinct windowing strategies, selected per-product by `is_telemetric_product`:

- **Daily columnar products** (`discharge_daily_mean`, `stage_daily_mean`): annual chunks (year-by-year), matching the legacy `BrazilFetcher._download_data` pattern. `_split_annual_windows` decomposes `[start, end]` into `[(YYYY-01-01, YYYY-12-31), ...]` aligned to calendar years, clipped to the request range.
- **Telemetric/instantaneous products** (`discharge_instantaneous`, `stage_instantaneous`, `water_temperature_instantaneous`): ≤30-day chunks, matching the ANA API's documented per-request limit (`Range Intervalo de busca`, max `DIAS_30`). `_split_30day_windows` decomposes `[start, end]` into 30-day pieces; each is requested with `Range Intervalo de busca = DIAS_30` and `Data de Busca` anchored at the chunk's end date. `_filter_local_date_range` then clips the merged, parsed result back to the originally-requested range (on local calendar dates, prior to UTC conversion) — see "Open question" above regarding anchor-date semantics.

HTTP 404 per window emits `http_not_found` warning issue (not fatal), matching the established pattern from `lt_lhmt`, `usgs_nwis`, `cz_chmi`, `th_thaiwater`, `fr_hubeau`.

## Packaged Catalogue Status

`br_ana` is withheld from certified catalogue generation pending the credentialed native acquisition
owned by [issue 90](https://github.com/RivRetrieve/RivRetrieve/issues/90). The packaged catalogue keeps
provider metadata but emits empty product, station, and station-product tables with structured
`no_acquisition_record_established` provenance. The metadata fixture remains parser test data and must
not generate packaged values. See [`../catalogue-provenance.md`](../catalogue-provenance.md) for the
maintenance command and certification boundary.

A future credentialed response may refresh and attest a committed native table. It must not directly
generate canonical artefacts. Credentials remain restricted to request headers and must never enter
fixtures, logs, provenance, or repository files.

## Shared Architecture Impact

None. Authentication, date-only UTC midnight timestamps, naive-local-to-UTC conversion, dual windowing strategies (annual vs. ≤30-day), and manual URL encoding are all provider-specific. The `quality_flag` row-annotation pattern reuses the established convention from `usgs_nwis` (`qualifier`) and `ca_eccc` (`quality_flag`) — no new shared harness concept introduced. No shared harness gap discovered.

The authentication pattern (credentials via env vars, token cached in client, missing credentials → structured issue) is `br_ana`-specific for now. If future authenticated providers are added, the token management pattern here could serve as a reference, but it should not be promoted to shared harness until there is concrete evidence of reuse need.
