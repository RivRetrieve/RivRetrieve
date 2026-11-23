# Ireland (`ie_opw`) source, scope and access

Complete [Effort #980](https://github.com/RivRetrieve/RivRetrieve/issues/980) with an evidence-backed source-and-access handoff for Ireland's Office of Public Works (`ie_opw`). This Effort settles scope, publisher licensing, route semantics, and bounded access verification ahead of implementation; publishing this vision alone does not implement the provider.

The port belongs to [RivRetrieve#354](https://github.com/RivRetrieve/RivRetrieve/issues/354) (tracked under [#870](https://github.com/RivRetrieve/RivRetrieve/issues/870)). Follow [provider-port step 1](../../docs/maintenance/provider-ports.md) and the [evidence process](../../docs/maintenance/evidence.md). Keep all provider port work on the dedicated `port/ie-opw` branch until the full port is complete and approved in final review [#987](https://github.com/RivRetrieve/RivRetrieve/issues/987).

## Settled scope

Publish `ie_opw` as a single unauthenticated `LiveStages` provider (`WindowGranularity("none")`) covering the **Office of Public Works (OPW)** Hydro-Data service (`https://waterlevel.ie/hydro-data/data/internet/`):

1. **Catalogue & GeoJSON CRS feeds (`stations.json`, `layers/{10,20,30}/index.json`, `geojson/`):**
   - `stations/stations.json` (`571` stations total, uniform `site_no="0"`), layers `10` (`waterlevel`), `20` (`watertemperature`), and `30` (`flow`), plus `https://waterlevel.ie/geojson/` certifying `EPSG:4326`.
2. **12 Observation Products (`Q`, `S`, `TWater` x `{daily_{mean,min,max}, instantaneous}` via `year.json` and `*_complete.zip`):**
   - **Discharge (`Q`, `cumec` mapped to `m3/s` via `SourceUnitCodeDefinition`):** `discharge_daily_{mean,min,max}` (`Q/year.json`, `WEB.Day.{Mean,Min,Max}`) and `discharge_instantaneous` (`Q/Discharge_complete.zip`, `#ts_shortname;WEB.Cmd.Runoff`).
   - **Stage (`S`, `m`, `vertical_reference="above_sea_level"`, `vertical_datum=None`):** `stage_daily_{mean,min,max}` (`S/year.json`, `WEB.Day.{Mean,Min,Max}`) and `stage_instantaneous` (`S/Waterlevel_complete.zip`, `#ts_shortname;WEB.Cmd.P-Continuous.Absolute`).
   - **Water temperature (`TWater`, `°C` -> `degC`):** `water_temperature_daily_{mean,min,max}` (`TWater/year.json`, `WEB.Day.{Mean,Min,Max}-Water-Temp`) and `water_temperature_instantaneous` (`TWater/WaterTemperature_complete.zip`, `#ts_shortname;WEB.Cmd.P-Water-Temp`, including `14124` whose ZIP uses `WEB.Cmd.P-Water-Temp` despite Layer `20` labelling it `Cmd.P-Water-Temp`).
   - Select `year.json` entries strictly by `ts_shortname` (never array index), treat every timestamp as UTC (`+00:00`, closed UTC bounds), preserve missing `-1`/`255` rows (`null` in JSON; empty `;;-1` in CSV), and expose `Quality Code` (`Int64`) plus `Aggregation Accuracy %` (`Float64` on `S/year.json`) as observation-level source annotations without filtering `qc=254` provisional rows.
   - Document the stilling-well/uncalibrated water temperature caveat and Ordnance Datum migration caveat (`Malin Head OSGM15` vs `Poolbeg` / `Malin Head`).

## Station cohort (`00001..41000` flowing watercourses only) and metadata

- Retain only OPW flowing-watercourse river/stream stations within OPW's `00001..41000` republication window (`386` Step 1 preliminary stations, subject to Step 2 exhaustive verification across every kept station and product).
- Explicitly retain the `5` EPA-registered OPW gauges (`09045`, `10047..10050`, documenting the `ie_epa` `#875` mirror) and river-outflow / town-named river gauges (`30061` Wolfe Tone Br, `26075` Cuppanagh, `35071` Lareen, `03055` Glaslough, `34018` Turlough, `10048` Cherry Wood, `30017` Carrownagower).
- Metadata from `stations.json`: `station_id` (`station_no`), `latitude`/`longitude`/`crs="EPSG:4326"`, `station_name`, `water_body_name` (`WTO_OBJECT`, blank `""` -> `source_null`), `drainage_area` (`CATCHMENT_SIZE` inline `km²`, blank `""` -> `source_null`), and `elevation` withheld (`no_metadata`).

## Explicit exclusions & future `TODO`

- **`76` stations `> 41000`** (`80101..83801` Rain Gauges in Layer `40`), excluded by OPW's republication policy.
- **`109` non-river gauges within `00001..41000`:** `29` `Tidal`/`SEA` gauges (`28 Tidal` + `06062`), `40` stage-only estuarine/tidally-pulsed gauges (`16` `* ESTY`/`* ESTUARY` + `24` semidiurnal tidal stage-only including zero-`Q` `12002`, `24053`, `27066`), `30` standing lake/lough/lagoon stations (excluding `26075` & `35071` outflows), `4` reservoir/headrace/turlough sites (`16073, 19094, 19095, 29002`), and `6` canal-lock/bog/landfill drains (`09110, 14056, 25058, 26374, 27092, 30034`). Full counts and layer availability are documented in `verification-evidence/research/ie-opw-source-access.md`.
- **Auxiliary / legacy feeds excluded:** `Q/gaugings.json`, `annual_statistics.json` (AMAX), `alarmlevel.json`, `calibration*.json`, `/data/month/*_0001.csv` & `*_OD.csv`, and rolling `week.json` / `*_48h.csv` / `Discharge_day.zip`.
- **Future optimization `TODO`:** Add lightweight incremental recent-window refreshes from `{param}/month.json` when serving short recent windows/cache updates instead of always re-fetching multi-megabyte `*_complete.zip` files.

## License, polite pacing, and attribution

Published by **Office of Public Works (OPW)** under **`CC BY 4.0`** (`https://waterlevel.ie/page/api/`, `https://data.gov.ie/`, mandatory attribution *"Contains Irish Public Sector Information licensed under a Creative Commons Attribution 4.0 International (CC BY 4.0) licence (source http://waterlevel.ie - provided by the Office of Public Works.)"*). Enforces `<= 1 req/s` client pacing; no external email is sent to OPW (document OPW's courtesy note only in user docs).

## Retained verification evidence

Step 1 witnesses are published in the private archive collection **`ie_opw-access-2026-11-23-v1`** (`release_id: 455955585`, `manifest.sha256: 101557a01ce45c3320aba0a41bfdf30412dc6590ac44c34c71c74a2b7e834cb9`, `60` acquisitions / `120` members verified byte-identical after independent `archive fetch`) and summarized in `verification-evidence/research/ie-opw-source-access.md`.

## Downstream efforts

- [#981](https://github.com/RivRetrieve/RivRetrieve/issues/981) (**Step 2**): Exhaustive river-cohort station/product census, offline catalogue + metadata + `origins.py`, `ie_opw-catalogue-2026-11-23-v1`, and `verify.py --catalogue-inputs`.
- [#982](https://github.com/RivRetrieve/RivRetrieve/issues/982) (**Step 3**): Physical-meaning, UTC day-boundary, `cumec -> m3/s`, `Quality Code` / `Aggregation Accuracy %` annotation witnesses (`ie_opw-series-meaning-2026-11-23-v1`), finalized `12` `PhysicalFacts` mappings.
- [#983](https://github.com/RivRetrieve/RivRetrieve/issues/983) – [#986](https://github.com/RivRetrieve/RivRetrieve/issues/986) (**Steps 4–7**): `LiveStages` retrieval, integration, empirical verification, and user docs.
- [#987](https://github.com/RivRetrieve/RivRetrieve/issues/987) (**Step 8**): Final maintainer review into `main`.
