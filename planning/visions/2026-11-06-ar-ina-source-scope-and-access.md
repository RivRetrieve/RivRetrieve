# Argentina INA Alerta5 source, scope and access

Complete [Effort #713](https://github.com/RivRetrieve/RivRetrieve/issues/713) with an evidence-backed source, scope, and access handoff for the Argentine hydrological provider (`ar_ina`). This Effort covers primary-source consolidation, scope definition, and bounded access verification rather than provider implementation. Verified completion of this vision and the companion research record completes #713.

The port belongs to [Program #348](https://github.com/RivRetrieve/RivRetrieve/issues/348). Follow [provider-port step 1](../../docs/maintenance/provider-ports.md) and the [evidence process](../../docs/maintenance/evidence.md). Keep all `ar_ina` implementation pull requests targeted at the dedicated `port/ar-ina` branch until the complete port is verified and ready for [final review #720](https://github.com/RivRetrieve/RivRetrieve/issues/720).

## Settled scope

Publish `ar_ina` using direct, unauthenticated [`LiveStages`](../../src/rivretrieve/_internal/providers/registration.py) retrieval (`required_credentials=()`) from the **Alerta5 (`a5`)** hydrological database and REST API (`https://alerta.ina.gob.ar/a5`), operated by Argentina's **Instituto Nacional del Agua (`INA`)**, *Subgerencia de Sistemas de Información y Alerta Hidrológico* (`SIyAH`), and documented in INA's live OpenAPI 3.1 specification (`https://alerta.ina.gob.ar/a5/yaml/apidocs_v3_1.yml`). INA aggregates gauge records across national, binational, provincial, and municipal networks, including *Red Hidrológica Nacional - SSRH* (`sat2` and `alturas_bdhi`), *Prefectura Naval Argentina* (`alturas_prefe`), *INA Delta y AMBA* (`ina_delta`), *Comisión Técnica Mixta de Salto Grande* (`estaciones_salto_grande`), *Nucleoeléctrica Argentina* (`na-sa`), *Quilmes* (`quilmes`), *INTA Delta* (`inta_delta`), and *Comisión Administradora del Río Uruguay* (`CARU`, `alturas_varios`). No bulk national archive download is published, so on-demand `LiveStages` backed by the shared local observation store is the appropriate access mode.

Earlier third-party adapters (legacy PR #90 and `hydrodownloadR`'s `adapter_AR_INA.R`) queried only `var_id=40` (daily mean discharge, 82 observed stations) through `csvless` responses that stripped series identifiers. Primary-source checks on 2026-11-06 across all 95 variables in `obs/variables` established that INA Alerta5 publishes 13 distinct observed river discharge and stage series types across 829 river stations, while storing hydrological model simulations and forecasts in the same `series` table distinguished by procedure identifier (`procedimiento.id`).

Include all 13 observed river discharge and stage series types published with direct gauge measurement (`procedimiento.id = 1`, *medición directa*) or stage-discharge rating-curve derivation (`procedimiento.id = 2`, *Curva de gasto*):

1. **River discharge (`discharge`, native `m^3/s` under `unit_id=10`, returned `m3/s`):**
   - `var_id=40` (`Qmd`, *Caudal medio diario*): daily mean discharge (`proc_id=1`, 82 river stations).
   - `var_id=4` (`Q`, *Caudal*): instantaneous or sub-daily rating-curve discharge (`proc_id=2`, 32 river stations).
   - `var_id=48` (`Qmm`, *caudal medio mensual*): monthly mean discharge (`proc_id=1`, 36 river stations).
   - `var_id=51` (`Qmmin`, *Caudal mínimo mensual*): monthly minimum discharge (`proc_id=1`, 28 river stations).
   - `var_id=52` (`Qmmax`, *Caudal máximo mensual*): monthly maximum discharge (`proc_id=1`, 28 river stations).
2. **River stage (`stage`, native `m` under `unit_id=11`, returned `m`, measured relative to local gauge zero `cero_ign`):**
   - `var_id=39` (`Hmd`, *Altura hidrométrica media diaria*): daily mean stage (`proc_id=1`, 756 river stations).
   - `var_id=2` (`H`, *Altura hidrométrica*): instantaneous or native-cadence stage (`proc_id=1`, 808 river stations).
   - `var_id=101` (`Hm4h`, *Altura hidrométrica 4-horaria*): 4-hourly stage (`proc_id=1`, 391 river stations).
   - `var_id=85` (`H1h`, *Altura hidrométrica horaria*): hourly stage (`proc_id=1`, 3 river stations).
   - `var_id=67` (`Hms`, *Altura hidrométrica media semanal*): weekly mean stage (`proc_id=1`, 32 river stations).
   - `var_id=33` (`Hmm`, *Altura hidrométrica media mensual*): monthly mean stage (`proc_id=1`, 249 river stations).
   - `var_id=49` (`Hmmin`, *Altura hidrométrica mínima mensual*): monthly minimum stage (`proc_id=1`, 83 river stations).
   - `var_id=50` (`Hmmax`, *Altura hidrométrica máxima mensual*): monthly maximum stage (`proc_id=1`, 83 river stations).

Keep each published `var_id` as a distinct source series without calculating aggregates across resolutions or merging series. Across all 13 in-scope `var_id`s, restricting to `procedimiento.id` in `{1, 2}` yields at most one non-empty observed series (`date_range.timestart != null`) per `(station, var_id)` pair.

### Documented exclusions and portal boundaries

- **Water temperature (`temperature`):** Although `obs/variables` defines `var_id=73` (`TAgua`, *Temperatura del agua*, `ºC`) in its CUAHSI Observations Data Model dictionary, `obs/puntual/series?var_id=73` registers only two placeholder rows (`29391` at `Bell Ville` and `29379` at `Aguapey - Caa Caraí`), both with `has_obs: false`, `timestart: null`, and empty observation responses (`[]`). All other temperature variables in `alerta5` measure air, dewpoint, wet-bulb, or soil temperature. As a result, `ar_ina` exposes no water-temperature products.
- **Model simulations, forecasts, climatologies, and synthetic analyses:** Exclude `procedimiento.id` `3` (*Interpolado*), `4` (*Simulado*, hydrological model runs), `5` (*Estimado*, indirect estimates), `6` (*Análisis*, such as composite outflow series `42277` at virtual node `8090` `"Descarga al Río de la Plata"`), `7` (*Climatología*), `8` (*Traza*, forecast traces), and `9` (*Derivado*).
- **Virtual model stations:** Exclude stations flagged `real: false` or `tipo: "V"` (150 synthetic model nodes, delta-front boundary points in `puntos_FDelta`, and virtual basin nodes in `estaciones_virtuales` and `estaciones_virtuales_public`). Retain physical river gauges whose `real` attribute is `true` or `null`.
- **Coastal and outer-estuary tide gauges:** Exclude the two mareographic tide-gauge networks published in `alerta5`: `estaciones_shn` (*Mareógrafos SHN* operated by *Servicio de Hidrografía Naval*, such as *Mar del Plata*, *Santa Teresita*, and *Puerto Belgrano* on *Mar Argentino*) and `estaciones_pvnymm` (*Estaciones mareográficas - PVNyMM*, 36 outer-estuary and coastal navigation tide gauges). Document their availability in the private research record and user documentation in case coastal tide-gauge coverage is revisited later.
- **Shared-border and `pais=null` river gauges:** Include all physical river and inner freshwater *Río de la Plata* gauges accessible through INA's API after the virtual and tide-gauge exclusions above (829 stations in the 2026-11-06 check). This includes shared *Río Uruguay* border gauge `1699` (`Nueva Palmira`, operated by binational commission `CARU` with `pais: "URUGUAY"`) and the four Greater Buenos Aires urban stream gauges in `ina_delta` (`6949` `Finky`, `6950` `LP_Libano`, `6951` `SF_Montevideo`, and `6952` `SD_Olmos`) whose `pais` field is `null` in upstream metadata. Do not filter stations by requiring `pais == "Argentina"`.
- **Field calibration gaugings and non-river variables:** Exclude sparse manual discharge gaugings (`var_id=29` `Aforos:Caudal` and `var_id=19` `par Altura/Caudal`), groundwater phreatic depth (`var_id=96` `Altura freatimétrica`), snow depth (`var_id=37`), simulated astronomical/meteorological tide (`var_id=35`, `var_id=36`), and categorical flow classes (`var_id=104`).
- **Sibling federal SSRH SNIH portal ([RivRetrieve#729](https://github.com/RivRetrieve/RivRetrieve/issues/729)):** Argentina's *Subsecretaría de Recursos Hídricos* (`SSRH`) operates a separate federal portal, *Sistema Nacional de Información Hídrica* (`SNIH`, `https://snih.hidricosargentina.gob.ar/`), serving 344 daily-mean discharge stations and 251 water-temperature stations across all Argentine hydrographic regions. Track `ar_snih` as a separate candidate provider in [#729](https://github.com/RivRetrieve/RivRetrieve/issues/729) rather than mixing two distinct institutional publications inside `ar_ina`.

## Access architecture and request conditions

All public discovery and observation routes respond anonymously over HTTPS `GET` without cookies, tokens, or session state (administrative model and write routes in `apidocs_v3_1.yml` declare `cookieAuth` or `bearerAuth`, whereas `/a5/obs/*` and `/a5/getObservaciones` are public):

- **Catalogue and dictionary routes:**
  - `GET https://alerta.ina.gob.ar/a5/obs/puntual/estaciones?format=json`: returns all 4,695 punctual stations in a single WGS84 GeoJSON-geometry JSON array (`id`, `nombre`, `id_externo`, `geom`, `tabla`, `provincia`, `pais`, `rio`, `has_obs`, `tipo`, `automatica`, `propietario`, `localidad`, `real`, `cero_ign`, `altitud`, `red`).
  - `GET https://alerta.ina.gob.ar/a5/obs/puntual/series?format=json&var_id={var_id}`: returns every punctual series for `var_id`, including `id` (`series_id`), nested `estacion`, `var` (with CUAHSI ODM `timeSupport`), `procedimiento`, `unidades`, `fuente`, and `date_range` (`timestart`, `timeend`, `count`, `data_availability`). Prefer `format=json` over `format=geojson` because `format=geojson` omits `pais` and `real` from station properties.
  - `GET https://alerta.ina.gob.ar/a5/obs/variables?format=json`, `/a5/obs/unidades?format=json`, `/a5/obs/procedimientos?format=json`, and `/a5/obs/puntual/fuentes?format=json`: canonical variable, unit, procedure, and network dictionaries.
  - `GET https://alerta.ina.gob.ar/a5/obs/puntual/estaciones/{estacion_id}?format=json&get_drainage_basin=true`: per-station detail endpoint returning optional `drainage_basin` polygon geometry and `area` (to be audited across all in-scope gauges during [Effort #714](https://github.com/RivRetrieve/RivRetrieve/issues/714)).
- **Observation retrieval route:**
  - `GET https://alerta.ina.gob.ar/a5/obs/puntual/series/{series_id}/observaciones?timestart={start}&timeend={end}` (or equivalent JSON `/a5/getObservaciones?tipo=puntual&series_id={series_id}&timestart={start}&timeend={end}`): returns JSON observation objects (`id`, `tipo`, `series_id`, `timestart`, `timeend`, `valor`, `unit_id`, `timeupdate`).
  - Prefer structured JSON over `format=csvless&no_id=true` because JSON preserves `series_id` on every returned observation row for response-identity verification, while `csvless&no_id=true` strips `series_id`.
  - Both `timestart` and `timeend` are required query parameters (`HTTP 400` when `timeend` is omitted), and `timeend` is exclusive (`timestart=2024-01-01&timeend=2024-01-10` returns 9 daily intervals covering `2024-01-01` through `2024-01-09`).
- **Rate discipline:** Enforce polite client concurrency and rate limits (`<= 2` requests per second) across runtime retrieval and offline catalogue verification.

## Terms and attribution

Official INA pages (`https://www.ina.gob.ar/` and `https://www.ina.gob.ar/alerta`), governed by Argentina's national portal terms (`https://www.argentina.gob.ar/terminos-y-condiciones`), license public contents under **Creative Commons Attribution 4.0 International (`CC BY 4.0`, `https://creativecommons.org/licenses/by/4.0/deed.es`)** unless otherwise stated, requiring attribution to the publishing institution:

> Fuente: Instituto Nacional del Agua (INA), Sistema de Información y Alerta Hidrológico (SIyAH), `https://alerta.ina.gob.ar/a5` (CC BY 4.0), con datos de las redes hidrométricas aportantes.

Per-station network ownership (`propietario` and `red.nombre`, such as *Red Hidrológica Nacional - SSRH*, *Prefectura Naval Argentina*, and *CARU*) is published in `estaciones` metadata and will be preserved in station metadata review during [Effort #714](https://github.com/RivRetrieve/RivRetrieve/issues/714).

## Private research record and downstream handoff

Maintain the continuing Argentina INA research record in the private `verification-evidence` repository (`research/ar-ina-source-access.md`) and retain unmodified HTTP response originals with SHA-256 receipts in collection `ar_ina-access-2026-11-06-v1`. Keep raw source payloads and receipts out of public repositories, issues, and pull requests.

This scope and access baseline hands off concrete responsibilities to the remaining Efforts on `port/ar-ina`:

- **[Catalogue #714](https://github.com/RivRetrieve/RivRetrieve/issues/714):** Reconcile `obs/puntual/estaciones` with the 13 in-scope `obs/puntual/series` inventories (`proc_id in {1, 2}`, `date_range.timestart != null`); apply and test the virtual-station (`real: false`, `tipo: "V"`) and tide-gauge (`estaciones_shn`, `estaciones_pvnymm`) exclusions while preserving shared-border (`1699`, `country="UY"`) and `pais=null` Argentine gauges (`country="AR"` where geographically verified or `unknown` per catalogue policy); audit coordinate reference (`WGS84`), `altitud`, `cero_ign` gauge-zero datum vs ground elevation, and `get_drainage_basin=true` catchment areas; bind deterministic `(station_id, product) -> series_id` lookup coordinates; and complete metadata disclosure review under `CC BY 4.0`.
- **[Series meaning #715](https://github.com/RivRetrieve/RivRetrieve/issues/715):** Establish `SourceIdentity` and `PhysicalFacts` for all 13 in-scope river series; verify interval semantics (`timestart` vs `timeend` on daily `03:00:00.000Z` to `03:00:00.000Z` `UTC-03:00` intervals, 4-hourly, hourly, weekly, and 1st-of-month `03:00:00.000Z` intervals versus `timestart == timeend` instantaneous rows on `var_id=2` and `var_id=4`); check whether monthly `min`/`max` (`var_id=49..52`) aggregate daily means or instantaneous readings; verify `cero_ign` (`gauge_zero`) vertical reference on stage; and check missing-value (`valor: null`, `skip_nulls`) and quality/status fields.
- **[Retrieval #716](https://github.com/RivRetrieve/RivRetrieve/issues/716):** Establish window translation for INA's required and exclusive `timeend` parameter without shifting engine-supplied bounds silently; verify response row limits, pagination, or long-history multi-decade behavior (`43,000+` rows); validate `series_id` identity on returned JSON rows; and separate `EMPTY` (`[]` within valid window), `NO_MATCH`, and HTTP/transport `FAILED` outcomes.
- **[Integration #717](https://github.com/RivRetrieve/RivRetrieve/issues/717), [verification #718](https://github.com/RivRetrieve/RivRetrieve/issues/718), and [user documentation #719](https://github.com/RivRetrieve/RivRetrieve/issues/719):** Wire `ar_ina` into `LiveStages`, verify against retained evidence (including a bounded hydrograph comparison against CAMELS-AR / CAMELS-CL or documented regional benchmark availability in Step 6), and author `docs/providers/ar_ina.md` covering `CC BY 4.0` attribution, gauge-zero stage, excluded tide-gauge and simulation series, and the relationship to `ar_snih` (#729).

## Completion

Verify `ar_ina-access-2026-11-06-v1` with `archive validate`, an independent `archive fetch` byte-equivalence check, and the private archive checks before closing #713. Post a concise, disclosure-safe summary on #348 and #713 once both the private research PR and this vision PR merge. Keep #348 and Efforts #714 through #720 open, and leave final review (#720) unassigned until Efforts #713 through #719 are complete.
