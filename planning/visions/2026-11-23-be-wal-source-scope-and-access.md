# Belgium - Wallonia (`be_wal`) source, scope and access

Complete [Effort #972](https://github.com/RivRetrieve/RivRetrieve/issues/972) with an evidence-backed source-and-access handoff for the Belgian Wallonia hydrometric provider (`be_wal`). This Effort settles scope, publisher licensing, KiWIS route semantics, and bounded access verification ahead of implementation; publishing this vision alone does not implement the provider.

The port belongs to [RivRetrieve#350](https://github.com/RivRetrieve/RivRetrieve/issues/350) (tracked under [#870](https://github.com/RivRetrieve/RivRetrieve/issues/870)). Follow [provider-port step 1](../../docs/maintenance/provider-ports.md) and the [evidence process](../../docs/maintenance/evidence.md). Keep all provider port work on the dedicated `port/be-wal` branch until the full port is complete and approved in final review [#979](https://github.com/RivRetrieve/RivRetrieve/issues/979).

## Settled scope

Publish `be_wal` as a single unauthenticated `LiveStages` provider (`required_credentials=()`) covering **Service public de Wallonie (SPW) — Hydrométrie** across its public KISTERS **KiWIS `queryServices`** API (`https://hydrometrie.wallonie.be/services/KiWIS/KiWIS?service=kisters&type=queryServices&datasource=0&format=json`):

1. **Full 62-product native ladder across 5 parameter families (`0` collisions, `0` unit mismatches, `8,287` listed / `8,198` non-empty eligible pairs):**
   - **Standard discharge (`Q`, `stationparameter_name="Débit"`, `m³/s` -> `m3/s`, 13 products):** `05-Debit.Complet` (`discharge_complete`), `10/11/12-Debit.1h.{Moyen,Minimum,Maximum}` (`discharge_hourly_{mean,min,max}`), `20/21/22-Debit.Jour.*` (`discharge_daily_*`), `40/41/42-Debit.Mois.*` (`discharge_monthly_*`), and `50/51/52-Debit.An.*` (`discharge_yearly_*`), active at `267-278` non-empty (`277-283` listed) gauges.
   - **Ultrasonic discharge (`Q`, `stationparameter_name="Débit ultrason"`, `m³/s` -> `m3/s`, 13 products):** `05..52` (`discharge_ultrasonic_complete`, `discharge_ultrasonic_{hourly,daily,monthly,yearly}_{mean,min,max}`), active at `11` gauges.
   - **Gauge-zero stage (`H`, `stationparameter_name in {"Hauteur", "Hauteur sonde"}`, `m` -> `m`, `vertical_reference="gauge_zero"`, `vertical_datum=None`, 13 products):** `05..52-Hauteur.*` (`stage_complete`, `stage_{hourly,daily,monthly,yearly}_{mean,min,max}`), active at `313-314` (`314` listed) gauges. `ESurf_Hauteur` and live readings (`5922`) confirm `"Hauteur"` and `"Hauteur sonde"` share identical physical semantics with zero overlap per station.
   - **Elevation stage (`H`, `stationparameter_name in {"Hauteur", "Hauteur sonde"}`, `m` -> `m`, `vertical_reference="above_sea_level"`, `vertical_datum=None`, 13 products):** `05..52-Hauteur absolue.*` (`stage_absolute_*`), active at the `3` navigable river gauges `3270 PECQ`, `7102 LIEGE`, and `8001 NAMUR`.
   - **Water temperature (`T`, `stationparameter_name in {"Température Eau", "Temperature Eau"}`, `°C` -> `degC`, 10 products):** `05-Temperature.Complet`, `10/11/12`, `20/21/22`, and `40/41/42` (`water_temperature_*`), active at `38-41` (`41-43` listed) gauges (`50/51/52` annual series do not exist for water temperature).
2. **Timestamps, `interval_start` anchoring, quality codes, and pacing:**
   - Queries pass `timezone=UTC` (avoiding Brussels DST fold repetition on `02:00` and summer `01:00+02:00` daily label shift) and losslessly re-express instants in fixed CET `+01:00` (`UTC + 1 h`), matching `station_utcoffset="-60"` across all `338` eligible stations.
   - Per SPW's `Guide d'utilisation` V1.0 (p. 43) and empirical verification on `3643 HYON`, `2708`, `5922`, `7102`, and `L8220`, every cadence carries left-closed **`interval_start`** labels on CET grid boundaries (`10/11/12` hourly `:00+01:00`, `20/21/22` daily `00:00+01:00` = `23:00Z`, `40/41/42` monthly `YYYY-MM-01T00:00+01:00`, `50/51/52` annual `YYYY-01-01T00:00+01:00`).
   - Missing gaps use `[ts, null, -1, None]`; operational peak rows flagged `Quality Code=200 (Unknown)` (such as the July 2021 Vesdre flood at `6228`) are preserved alongside observation-level quality-code source annotations (schema settled in Step 3).
   - Shared `TRANSPORT_POLICY` (`minimum_interval_seconds=1.0`, honoring `LicServicesSPW.pdf` Art. 5 §1) without provider-local sleep hacks.

## Station cohort (`338` flowing-water gauges) and metadata

From the `502` rows returned by `getStationList` (`ca_sta`), include all **`338` geolocated physical flowing-watercourse gauges** (`TYPE_STATION in {"Limnimètre", "Debitmètre"}`, valid coordinates, `station_georefsystem="Lambert 72"`) publishing at least one in-scope series across `Q`, `H`, or water `T`:
- Comprises `327` `Limnimètre` and `11` `Debitmètre` stations across `SPW ARNE DCENN` (`193`) and `SPW MI DGH` (`145`), including `4` cross-border French gauges (`PAYS="France"` -> `country="FR"`: `8702`, `L7260`, `L7940`, `L7950`) and `13` `STA_PUBINT="no"` gauges verified to return `HTTP 200` data anonymously (`L8470`, `L8720`, etc.).
- Metadata (`STATION_METADATA_FIELDS`): exposes `station_name` (`station_name`, `338/338`), `water_body_name` (`river_name`, `338/338`), and `drainage_area` (`CATCHMENT_SIZE` in `km2`, `265/338`), leaving `elevation` as `no_metadata` (`station_elevation` is populated on only `2/338` river gauges).

## Explicit exclusions

- **`95` `Station météorologique`** and **`59` empty-type** basin/zone shells.
- **`1` turbine `Ouvrage` (`640C01 EUPEN CENTRALE`)** publishing `Qturbine` (`Débit turbiné`).
- **`5` standing-water reservoirs/lakes** (`5997`, `640601`, `656601`, `7836`, `9216`), while retaining navigable river gauges `3270 PECQ`, `7102 LIEGE`, and `8001 NAMUR`.
- **`1` `0`-series station (`630201`)**, **`1` coordinate-less staging shell (`9109 MARIEMBOURG AVAL`)** (all `H` & `10/20/40/50` `Q` return `0` rows), and **`2` specialized-parameter-only stations** (`7326 FLORIFFOUX` `Débit axe hydraulique` only; `7406 LANDELIES` `Débit virtuel` only, omitted from SPW portal group `ESurf_Debit`).
- Out-of-scope parameters on otherwise eligible gauges (`Température Air`, `Débit Etimeuse`, `Hauteur relative`).

## License and attribution

Published by **Service public de Wallonie (SPW) — Hydrométrie** (`https://hydrometrie.wallonie.be/mentions-legales.html`, `DataSPW-CGA.pdf` v1.2, `DataSPW-CGU.pdf` v1.1 Art. 3 §2a-b, `LicServicesSPW.pdf` v1.1). End-user read/download is free without credentials, while bulk redistribution and commercial diffusion require SPW authorization. Accordingly:
- `be_wal` provides **`LiveStages` on-demand retrieval only** (never mirroring observation archives), sets `ProviderInfoCatalog.license = None` (`provenance.license_not_established`), sets `ProviderInfoCatalog.citation = "Service public de Wallonie (SPW) — Hydrométrie"`, and sets **`STATION_METADATA_NOTICE`** excluding packaged metadata from RivRetrieve's MIT software licence and documenting SPW's attribution and reuse restrictions.

## Retained verification evidence

Step 1 witnesses are published in the private archive collection **`be_wal-access-2026-11-23-v1`** (`release_id: 455948013`, `manifest.sha256: b53a3bc289b909f8a17c3bf99e45b5ac460c9a89583936abf32129da2161087c`, `102` acquisitions / `204` members verified byte-identical after independent `archive fetch`) and summarized in `verification-evidence/research/be-wal-source-access.md` ([verification-evidence#129](https://github.com/RivRetrieve/verification-evidence/pull/129)).

## Downstream efforts

- [#973](https://github.com/RivRetrieve/RivRetrieve/issues/973) (**Step 2**): Complete `338 x 62` `StationProductCatalog` coverage evidence, Lambert 72 vs WGS84 CRS check, offline `origins.py` + `STATION_METADATA_NOTICE`, and `be_wal-catalogue-2026-11-23-v1`.
- [#974](https://github.com/RivRetrieve/RivRetrieve/issues/974) (**Step 3**): `PhysicalFacts` & series identity across all `62` products, `Hauteur absolue` datum investigation, and `be_wal` quality-code observation annotation schema (`Quality Code`, `Quality Code Name`, `-1` gap / `200 Unknown` semantics).
- [#975](https://github.com/RivRetrieve/RivRetrieve/issues/975) – [#978](https://github.com/RivRetrieve/RivRetrieve/issues/978) (**Steps 4–7**): KiWIS `checkValueLimit` / `capped-span` chunking & `-1h` UTC fetch boundary, `LiveStages` implementation, strict verification, and `docs/providers/be_wal.md` user documentation.
- [#979](https://github.com/RivRetrieve/RivRetrieve/issues/979) (**Step 8**): Final maintainer review into `main`.
