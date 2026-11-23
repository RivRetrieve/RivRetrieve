# Estonia (`ee_est`) source, scope and access

Complete [Effort #940](https://github.com/RivRetrieve/RivRetrieve/issues/940) with an evidence-backed source-and-access handoff for the Estonian hydrometric provider (`ee_est`). This Effort settles scope, publisher licensing, route semantics, and bounded access verification ahead of implementation; publishing this vision alone does not implement the provider.

The port belongs to [RivRetrieve#352](https://github.com/RivRetrieve/RivRetrieve/issues/352) (tracked under [#870](https://github.com/RivRetrieve/RivRetrieve/issues/870)). Follow [provider-port step 1](../../docs/maintenance/provider-ports.md) and the [evidence process](../../docs/maintenance/evidence.md). Keep all provider port work on the dedicated `port/ee-est` branch until the full port is complete and approved in final review [#947](https://github.com/RivRetrieve/RivRetrieve/issues/947).

## Settled scope

Publish `ee_est` as a single unauthenticated `LiveStages` provider covering Estonia's national hydrological agency, the **Estonian Environment Agency (`Keskkonnaagentuur`)**, across its two official hydrological observation APIs cleanly partitioned by cadence:

1. **Daily series via EstModel (`https://estmodel.envir.ee`, Swagger `1.0.0`):**
   - `GET /stations` (equivalent to `GET /stations?limit=500`, `125` stations) and `GET /countries/EE/stations?limit=500` (`120` stations excluding the `5` lake/reservoir stations).
   - `GET /stations/{stationCode}/measurements` with `parameter` in `("Q", "H", "T")`, `type` in `("MEAN", "MAXIMUM", "MINIMUM")`, and integer `start-year` / `end-year` query bounds (`dateFrom`/`dateTo` are ignored).
   - Exposes `9` daily products (`discharge_daily_{mean,max,min}` in `m3/s`, `stage_daily_{mean,max,min}` in `m` relative to gauge zero, and `water_temperature_daily_{mean,max,min}` in `degC`), with `59/60` inland river stations active per product (`SJA5432000` lacks `Q`, `SJB4433000` lacks `H`, `SJB4488000` lacks `T`).
   - Preserves EstModel `qualityFlag` (`UNCHECKED` on current-year operational rows prior to annual WISKI verification; OpenAPI enum `["BELOW_LOQ", "OUTLIER", "UNCHECKED"]`) as observation-level source annotation schema `ee_est.estmodel`.
   - Applies sequential polite request pacing (`>= 0.5-0.75 s`) and respects `Retry-After` (`429 Retry-After: 260` on rapid bursts under Cloudflare protection).
2. **Hourly series via Keskkonnaandmed PostgREST (`https://keskkonnaandmed.envir.ee`, OpenAPI `12.0.1`):**
   - Requires HTTP header `Accept-Profile: apijahiala` (singular; portal docs misprint `apijahialad` which returns `HTTP 406`).
   - `GET /f_hydroseire` from `2012-01-01T00:00:00Z` through operational updates (approx. 3-4 day lag; latest observed `2026-11-19T21:00:00Z`) across `9` hourly series (`Äravool {avg,max,min}` in `m3/s` at `55` river stations; `WL {avg,max,min}` in `cm` converted `* 0.01` to `m` and `WT {avg,max,min}` in `degC` at `56` river stations).
   - Queries and parses strictly on monotonic `timeline_ts_utc` (`+00:00`), never `timeline_ts_local` (which skips or repeats `03:00` at EET/EEST DST transitions), preserves JSON `"vaartus": null` directly without sentinel filtering, and shards requests into bounded `365`-day `capped-span` windows (`<= 8,784` rows per station-product chunk, below the `20,000`-row ceiling) without relying on `limit`/`offset` pagination.

## Station cohort (`60` inland flowing-water gauges) and metadata

Include only the **`60` inland flowing-water hydrological stations** in EstModel `type="HYDROLOGICAL"` whose `f_seirejaamad` waterbody type (`veekogu_tyyp_selg`) is in `("Jõgi", "Oja", "Peakraav")` (`58 Jõgi`, `1 Oja`, `1 Peakraav`; `54 SJA*`, `6 SJB*`). This exact `60`-station cohort matches EstModel `GET /countries/EE/stations?limit=500` `type="HYDROLOGICAL"` one-to-one.

Both APIs belong to `Keskkonnaagentuur`; each field derives from one authoritative agency column without third-party endpoints (`stations.geojson` is not used) or string-splitting fallbacks:
- `keskkonnaandmed.envir.ee/f_seirejaamad` (`kkr_kood=like.SJ*&seiretyyp=eq.HJ`): `station_id` (`kkr_kood`), deterministic token crosswalk to `f_hydroseire.jaam_kood` (`kood`, resolving `41066` under `HJ` to `SJA8056000` and parsing `"41022; 41960"` to `41022` on `SJA5524000`, giving `56` hourly-active + `4` EstModel-only gauges), `latitude` / `longitude` / `crs="EPSG:4326"` re-projected from `(kesk_x, kesk_y)` (`EPSG:3301`), `station_name` (`nimi`), and `water_body_name` (`veekogu_nimi`).
- `estmodel.envir.ee/stations?limit=500`: `drainage_area` (`area` in `km2`, `60/60`).
- `elevation`: withheld (`merepinnast` is `null` for all `60` stations in `f_seirejaamad`).

## Explicit exclusions

- **5 standing lake/reservoir stations** (`SJA3914000`, `SJA4875000`, `SJA5000000`, `SJA5411000`, `SJA8843000`).
- **15 coastal sea-level stations** (*rannikumerejaamad* at `-500 cm EH2000`, e.g. `26045`).
- **60 EstModel `HYDROCHEMICAL` stations** and non-EstModel `f_seirejaamad` `HJ` entries (`95` rows).
- **EstModel `type=VALIDATION`** manual check measurements, **EstModel `/estimates`** model outputs, **EstModel parameter `V`** (`m/s` velocity), and **KAIA SWAT** forecasts.

## License and attribution

Published by **Estonian Environment Agency (Keskkonnaagentuur)** under **`CC BY 4.0`** (`https://keskkonnaportaal.ee/et/avaandmed`, `https://keskkonnaportaal.ee/et/avaandmed/hudroloogilise-seire-andmestik`), with mandatory source attribution under *Keskkonnaseire seadus* § 13(4) (`https://keskkonnaagentuur.ee/asutus-uudised-ja-kontakt/organisatsioon/visuaalne-visiitkaart-viitamine`). No API authentication is required.

## Retained verification evidence

Step 1 witnesses are published in the private archive collection **`ee_est-access-2026-11-23-v1`** (`release_id: 455331430`, `manifest.sha256: caa44bf3e4dbd980d251ec6714ff1fa4aabf0b84f72ad3d2077fbc9bba4fbcd7`, `42` acquisitions / `84` members verified byte-identical after independent `archive fetch`) and summarized in `verification-evidence/research/ee-est-source-access.md`.

## Downstream efforts

- [#941](https://github.com/RivRetrieve/RivRetrieve/issues/941) (**Step 2**): Full `60 × 18` station-product availability evidence, offline catalogue + metadata projection + `origins.py`, `ee_est-catalogue-2026-11-23-v1`, and `verify.py --catalogue-inputs`.
- [#942](https://github.com/RivRetrieve/RivRetrieve/issues/942) (**Step 3**): Physical-meaning, BK77 -> EH2000 overlap, and `qualityFlag` witnesses (`ee_est-series-meaning-2026-11-23-v1`), finalized `18` `PhysicalFacts` mappings, and `ee_est.estmodel` observation annotation schema.
- [#943](https://github.com/RivRetrieve/RivRetrieve/issues/943) – [#946](https://github.com/RivRetrieve/RivRetrieve/issues/946) (**Steps 4–7**): `n-year-chunk` planning extension (`YearRange` for `start-year`/`end-year`), `LiveStages` implementation, strict verification, and user documentation.
- [#947](https://github.com/RivRetrieve/RivRetrieve/issues/947) (**Step 8**): Final maintainer review into `main`.
