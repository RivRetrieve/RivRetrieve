# Argentina: INA (Alerta5)

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `ar_ina` |
| Country | Argentina (plus one binational Río Uruguay border gauge in Uruguay) |
| Published by | Instituto Nacional del Agua (INA), Subgerencia de Sistemas de Información y Alerta Hidrológico (SIyAH), with federated national, binational, provincial and municipal networks |
| Read from | Official INA Alerta5 REST API (`alerta.ina.gob.ar/a5`) |
| Quantities | Discharge, stage |
| Stations in the catalogue | 829 river gauges. Availability depends on station, quantity, series and period |
| Station metadata | Station name and water-body name. See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | None |
| Licence stated by Argentina.gob.ar | Creative Commons Attribution 4.0 International (`Creative Commons Atribución 4.0 Internacional`, CC BY 4.0); source attribution required |
| Agency documentation | [INA Alerta Hidrológico](https://www.ina.gob.ar/alerta), [Alerta5 portal](https://alerta.ina.gob.ar/a5/secciones/mapa/puntual), [Alerta5 OpenAPI specification](https://alerta.ina.gob.ar/a5/yaml/apidocs_v3_1.yml), [Punctual series guide](https://alerta.ina.gob.ar/a5/contents/metadata_series_puntuales.html) |

Retrieve four days of daily mean discharge at station `8`, Andresito on the
Iguazú River:

```python
import rivretrieve as rr

selection = rr.find(
    provider="ar_ina",
    station="8",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)

result = rr.fetch(selection, start="2024-01-01", end="2024-01-04", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print([(issue.severity, issue.code) for issue in result.issues])
```

Output:

```text
time,time_zone,value,unit
2024-01-01T03:00:00.000000,+00:00,839.95,m3/s
2024-01-02T03:00:00.000000,+00:00,898.63,m3/s
2024-01-03T03:00:00.000000,+00:00,2051.27,m3/s
4
[('info', 'provenance.citation_not_established')]
```

The request returned four published daily means in m³/s. The preview shows the
first three days. Each Argentine calendar day since March 2009 begins at local
midnight in `UTC-03:00`, so 1 January's daily mean is labelled
`2024-01-01T03:00:00.000000` with `time_zone="+00:00"`; see
[Time and data status](#time-and-data-status) for historical Daylight Saving
Time periods.

The informational issue `provenance.citation_not_established` means the packaged
provider catalogue has no fixed verbatim citation string configured. It does not
mean retrieval failed or that attribution is optional; follow the attribution
requirements in [Terms and citation](#terms-and-citation).

`cache="bypass"`, the default for live `rr.fetch` calls, requests Alerta5
directly without reading or writing a local cache. Passing `cache="reuse"`
stores retrieved observations locally so later requests for already-covered
dates reuse the local store. This output was checked live on 2026-11-09. Source
records can be updated or revised over time. See [Usage](../usage.md) for
selection options and working with returned data.

## Who measures, and who publishes

Argentina's National Water Institute (*Instituto Nacional del Agua*, INA),
through its Hydrological Information and Warning Systems Sub-directorate
(*Subgerencia de Sistemas de Información y Alerta Hidrológico*, SIyAH),
publishes national and *Cuenca del Plata* river observations through the
[Alerta5](https://alerta.ina.gob.ar/a5/secciones/mapa/puntual) service. Alerta5
aggregates gauge measurements collected by several operating networks, so
appearance on Alerta5 does not mean that INA operates every station itself. The
829 river gauges in RivRetrieve's packaged catalogue belong to nine source
networks:

| Source network in Alerta5 | Stations |
|---|---:|
| Red Hidrológica Nacional, telemetric network (`sat2`, SSRH) | 479 |
| Red Hidrológica Nacional, historical database (`alturas_bdhi`, SSRH) | 235 |
| Prefectura Naval Argentina staff gauges (`alturas_prefe`) | 88 |
| INA Delta and Greater Buenos Aires network (`ina_delta`) | 16 |
| Salto Grande binational dam hydrometeorological network (`estaciones_salto_grande`) | 4 |
| Nucleoeléctrica Argentina (`na-sa`) | 3 |
| Municipality of Quilmes (`quilmes`) | 2 |
| INTA Delta (`inta_delta`) | 1 |
| Comisión Administradora del Río Uruguay (`alturas_varios`, station `1699` Nueva Palmira) | 1 |

No API key or account is required. RivRetrieve searches the packaged station and
series catalogue offline; `rr.fetch` then requests JSON observations over HTTPS
from Alerta5. Station identifiers are integer Alerta5 station IDs kept as
strings, such as `"8"` or `"1967"`. When the same physical river location has
entries in more than one contributing network (for example a telemetric `sat2`
entry alongside a historical `alturas_bdhi` entry), Alerta5 assigns each network
entry its own station ID, and RivRetrieve keeps them separate.

The packaged `ar_ina` catalogue covers physical river and inland-delta gauges
with observed discharge or stage records:

- `828` gauges carry `EPSG:4326` coordinates, and `1` river gauge (`"96"`,
  Colorado on the Bermejo River) is retained with `null` latitude and longitude
  because Alerta5 publishes its stage series without station coordinates.
- Inland Paraná Delta and freshwater inner *Río de la Plata* gauges (such as
  Tigre, San Fernando, Buenos Aires, and La Plata in `alturas_prefe`, and urban
  Greater Buenos Aires stream gauges in `ina_delta`) and the shared *Río
  Uruguay* border gauge `1699` (Nueva Palmira, Uruguay, operated by CARU) are
  included.
- Virtual hydrological-model nodes, model simulations, forecasts, climatologies,
  and interpolated or derived analysis series stored in Alerta5 alongside gauge
  measurements are excluded; RivRetrieve admits only direct measurement
  (*medición directa*) and rating-curve (*curva de gasto*) observational
  procedures.
- Maritime and outer-estuary coastal tide-gauge networks (*Servicio de
  Hidrografía Naval* `estaciones_shn` and *PVNyMM* `estaciones_pvnymm`), sparse
  manual field discharge gaugings (*aforos*), and groundwater phreatic wells are
  excluded.
- Surface-water temperature has only two empty placeholder entries in Alerta5
  with no observations, so `ar_ina` exposes discharge and stage only.

Argentina's *Subsecretaría de Recursos Hídricos* (SSRH) also operates a separate
federal hydrological portal ([SNIH](https://snih.hidricosargentina.gob.ar/))
with additional historical discharge, stage, and water-temperature records; a
separate provider for SNIH is tracked in
[#729](https://github.com/RivRetrieve/RivRetrieve/issues/729).

## What you can retrieve

Alerta5 publishes five observational river discharge series types and eight
observational river stage series types:

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | `Qmd` (*Caudal medio diario*; per-series ID in `variant`) | Daily | Mean | m^3/s | m³/s |
| `discharge` | `Q` (*Caudal*; per-series ID in `variant`) | Unknown | Instantaneous | m^3/s | m³/s |
| `discharge` | `Qmm` (*Caudal medio mensual*; per-series ID in `variant`) | Monthly | Mean | m^3/s | m³/s |
| `discharge` | `Qmmin` (*Caudal mínimo mensual*; per-series ID in `variant`) | Monthly | Minimum | m^3/s | m³/s |
| `discharge` | `Qmmax` (*Caudal máximo mensual*; per-series ID in `variant`) | Monthly | Maximum | m^3/s | m³/s |
| `stage` | `Hmd` (*Altura hidrométrica media diaria*; per-series ID in `variant`) | Daily | Mean | m | m |
| `stage` | `H` (*Altura hidrométrica*; per-series ID in `variant`) | Unknown | Instantaneous | m | m |
| `stage` | `H1h` (*Altura hidrométrica horaria*; per-series ID in `variant`) | Hourly | Unknown | m | m |
| `stage` | `Hm4h` (*Altura hidrométrica 4-horaria*; per-series ID in `variant`) | Unknown | Unknown | m | m |
| `stage` | `Hms` (*Altura hidrométrica media semanal*; per-series ID in `variant`) | Unknown | Mean | m | m |
| `stage` | `Hmm` (*Altura hidrométrica media mensual*; per-series ID in `variant`) | Monthly | Mean | m | m |
| `stage` | `Hmmin` (*Altura hidrométrica mínima mensual*; per-series ID in `variant`) | Monthly | Minimum | m | m |
| `stage` | `Hmmax` (*Altura hidrométrica máxima mensual*; per-series ID in `variant`) | Monthly | Maximum | m | m |

Discharge in `m^3/s` and stage in `m` require no numerical scaling; RivRetrieve
normalises the discharge unit label to `m3/s` while keeping `"m^3/s"` in
`source_unit`. It does not calculate daily or monthly aggregates from sub-daily
readings or merge separate series.

Availability varies substantially across stations. In the packaged catalogue
snapshot (`2,611` witnessed station-series pairs across `829` gauges),
instantaneous stage (`H`) is listed at `808` stations and daily mean stage
(`Hmd`) at `756`, whereas daily mean discharge (`Qmd`) is listed at `82`
stations, instantaneous rating-curve discharge (`Q`) at `32`, 4-hourly stage
(`Hm4h`) at `391`, hourly stage (`H1h`) at `3`, and weekly mean stage (`Hms`) at
`32`. A station being listed in the catalogue does not guarantee observations
for every quantity or requested period.

Each published Alerta5 time series has its own numeric Alerta5 series ID, which
RivRetrieve exposes as `variant` (for example `variant="26605"` for daily mean
discharge at station `"8"`). Unlike providers with named processing levels,
these numeric IDs belong to individual station series rather than forming a
provider-wide menu. Within the packaged river catalogue, each station has at
most one observational series per row in the table above.

Several stage series have `Unknown` in `Frequency` or `Statistic`:

- **Hourly (`H1h`) and 4-hourly (`Hm4h`) stage:** Alerta5 declares `1`-hour and
  `4`-hour time steps with a `Continuous` data type rather than `Average`.
  Comparing overlapping observations shows that these series place a single
  stage reading onto each 1-hour or 4-hour slot rather than averaging readings
  across the slot. RivRetrieve sets `frequency="hourly"` on `H1h`, leaves
  `frequency` unknown on `Hm4h` (4-hourly is not a named filter in
  RivRetrieve's frequency vocabulary), and leaves `statistic` unknown on both so
  mean and instantaneous filters do not select them by mistake.
- **Weekly mean stage (`Hms`):** Summarises 7-day Monday-to-Monday intervals
  with `statistic="mean"`. Because RivRetrieve's frequency filter vocabulary has
  `daily` and `monthly` rather than `weekly`, `frequency` remains unknown.
- **Instantaneous discharge (`Q`) and stage (`H`):** Match
  `statistic="instantaneous"` without a `frequency` filter because telemetry and
  staff-gauge reporting intervals vary across stations and periods (from
  10- or 15-minute automatic transmissions to daily or sub-daily manual
  readings).
- **Monthly minimum and maximum series (`Qmmin`, `Qmmax`, `Hmmin`, `Hmmax`):**
  Report the minimum or maximum of the station's underlying observations within
  each calendar month, stamped at the start of the month.

Inspect all candidate series and station metadata at a gauge offline before
fetching, and use `rr.pick(..., variant=...)` (or `frequency="hourly"` for
`H1h`) when targeting a series whose frequency or statistic is unknown:

```python
station_52 = rr.find(provider="ar_ina", station="52", quantity="stage")
candidates = rr.series(station_52)
metadata = rr.metadata(station_52)

hourly_stage = rr.pick(station_52, variant="31605")
```

## Stage references and station metadata

River stage (*altura hidrométrica*) in Alerta5 is measured in metres relative to
each station's local staff-gauge zero (*cero de escala*). RivRetrieve sets
`vertical_reference="gauge_zero"` and leaves `vertical_datum` unknown on all
stage series. Water levels below local gauge zero are physically valid during
low-water periods and remain negative (for example `-0.27 m` in monthly minimum
stage at station `8`, Andresito). Do not compare raw stage values across
different gauges as elevations above sea level.

Station metadata from `rr.metadata(selection)` exposes two native fields from
Alerta5:

- `nombre` as `station_name` (populated for all `829` river gauges), and
- `rio` in `water_body_name_value` (populated for `353` gauges and `null` at the
  remaining `476` gauges where Alerta5 leaves `rio` empty).

Both `drainage_area_*` and `elevation_*` columns are `null` (`state="no_metadata"`
in `rr.metadata(selection, view="source")`):

- Alerta5's station inventory does not publish catchment areas, and its optional
  basin-polygon endpoint covers fewer than 3% of river gauges while mixing total
  drainage basins with incremental model subcatchments and zero placeholders.
- An optional `cero_ign` attribute in Alerta5 (`73` river gauges) records the
  height of the local staff-gauge zero relative to Argentina's *Instituto
  Geográfico Nacional* (IGN) datum rather than ground elevation, while a sparse
  `altitud` attribute (`10` river gauges) states neither a unit nor a vertical
  datum. Neither field is exposed as station ground elevation.

## Time and data status

Alerta5 returns all observation timestamps in UTC (`...Z`). RivRetrieve
preserves those UTC timestamps with `time_zone="+00:00"` (`time_zone="UTC"` in
`rr.series(...)`), and `rr.to_utc(result)` returns them unchanged.

Pay attention to local civil midnight when aligning daily, weekly, or monthly
aggregates with calendar dates:

- **March 2009 to present (`UTC-03:00`):** Argentina has observed fixed
  `UTC-03:00` without Daylight Saving Time since March 2009. Daily, weekly, and
  monthly intervals begin at `00:00` local time, which appears as `03:00:00` UTC
  (for example `2024-01-01T03:00:00.000000` for 1 January 2024).
- **Pre-2009 Daylight Saving Time transitions (`UTC-02:00` in summer):** During
  historical Argentine summer-time periods (such as October 2008 to March 2009),
  local midnight fell at `02:00:00` UTC (`UTC-02:00`). In Alerta5's database,
  the spring transition day spans 23 hours (`03:00:00` UTC to the next day's
  `02:00:00` UTC), summer days begin at `02:00:00` UTC, and the autumn
  transition day spans 25 hours (`02:00:00` UTC to `03:00:00` UTC). Because the
  UTC offset of local midnight shifts across historical DST years, RivRetrieve
  leaves `day_definition` unknown rather than claiming a fixed UTC offset across
  all decades.

On daily, weekly, monthly, hourly, and 4-hourly series, `time` marks the start
of the interval (`timestamp_anchor="start"`). On instantaneous discharge (`Q`)
and stage (`H`), `time` marks the measurement instant
(`timestamp_anchor="measurement_time"`), including exact sub-minute telemetry
timestamps (such as `:10` seconds) where recorded by automatic loggers.

Alerta5 serves operational real-time telemetry and historical gauge archives
through the same API without per-observation quality-assurance flags; series
metadata codes (`H`, `C`, `RT`, `NRT`) describe operational feed latency rather
than data validation grades, and RivRetrieve makes no quality judgement of its
own.

Keep missing-data cases distinct when inspecting results:

- Missing dates or sub-daily gaps in Alerta5 generally produce no observation
  rows rather than `null` placeholders. RivRetrieve requests stored database
  observations only (suppressing Alerta5's synthetic regular-grid boundary
  nulls) and does not fill missing time steps.
- Where Alerta5 stores an explicit database record whose value is `null`,
  RivRetrieve omits that gap marker and records an informational
  `source.gap_marker` issue in `result.issues`.
- Long retrieval windows are split automatically into bounded requests (at most
  365 days per request for sub-daily and slotted stage or instantaneous
  discharge, and at most 3,650 days per request for daily and weekly series) and
  assembled without boundary duplicates. Check [issues](../usage.md#issues)
  whenever a request returns fewer rows than expected.

## Terms and citation

INA's [Alerta Hidrológico portal](https://www.ina.gob.ar/alerta) is published on
Argentina's national [`argentina.gob.ar`](https://www.argentina.gob.ar/)
platform, whose [terms and
conditions](https://www.argentina.gob.ar/terminos-y-condiciones) license public
content under [Creative Commons Attribution 4.0 International (CC BY
4.0)](https://creativecommons.org/licenses/by/4.0/deed.es) (*Creative Commons
Atribución 4.0 Internacional*) unless otherwise stated. Reuse requires
attribution to the source.

Both `rr.describe("ar_ina")` and `result.provenance` expose
`license="Creative Commons Atribución 4.0 Internacional"`, while `citation` is
omitted from `rr.describe("ar_ina")` and `None` on `result.provenance`
(because `argentina.gob.ar` states general CC BY 4.0 attribution obligations
rather than prescribing a single verbatim citation string, which also produces
the informational `provenance.citation_not_established` issue during `rr.fetch`).
When publishing or redistributing retrieved data, credit the **Instituto
Nacional del Agua (INA), Subgerencia de Sistemas de Información y Alerta
Hidrológico (`https://alerta.ina.gob.ar/a5`)**, name the contributing monitoring
network where applicable (such as *Subsecretaría de Recursos Hídricos*,
*Prefectura Naval Argentina*, *CARU*, or *Salto Grande*), and record the station
ID, series variant ID, requested period, and retrieval date.

RivRetrieve paces live requests politely (at most two requests per second) and
reuses locally cached observations when `cache="reuse"` is passed.

## Sources

Publisher documents and API specifications checked on 2026-11-06 and verified
reachable on 2026-11-09:

- [INA: *Sistema de Información y Alerta Hidrológico* (`ina.gob.ar/alerta`)](https://www.ina.gob.ar/alerta): institutional overview of SIyAH hydrological monitoring and Cuenca del Plata forecasting.
- [INA Alerta5 punctual stations map (`alerta.ina.gob.ar/a5/secciones/mapa/puntual`)](https://alerta.ina.gob.ar/a5/secciones/mapa/puntual): interactive station map, `EPSG:4326` geometry, gauge-zero (*cero de escala*) descriptions, and series availability codes.
- [INA Alerta5 OpenAPI 3.1 specification (`apidocs_v3_1.yml`)](https://alerta.ina.gob.ar/a5/yaml/apidocs_v3_1.yml): REST endpoint schemas for `/obs/puntual/estaciones`, `/obs/puntual/series`, and `/obs/puntual/series/{series_id}/observaciones`.
- [INA Alerta5 punctual series metadata guide (`metadata_series_puntuales.html`)](https://alerta.ina.gob.ar/a5/contents/metadata_series_puntuales.html): structure of punctual stations, variables, units, and observational versus simulated procedures.
- [Argentina.gob.ar: *Términos y condiciones*](https://www.argentina.gob.ar/terminos-y-condiciones): *Creative Commons Atribución 4.0 Internacional* (CC BY 4.0) licensing and source-attribution requirements.

The station and series counts describe the packaged catalogue snapshot
(2026-11-06). The example observations were verified live on 2026-11-09. This
live example does not establish continuous coverage.
