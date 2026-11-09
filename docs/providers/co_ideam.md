# Colombia: IDEAM

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `co_ideam` |
| Country | Colombia |
| Published by | Instituto de Hidrología, Meteorología y Estudios Ambientales (IDEAM) |
| Read from | IDEAM Open Data historical S3 archive (`datos.ideam.gov.co`) |
| Quantities | Discharge, stage |
| Stations in the catalogue | 1,372 river gauges. Availability depends on station, quantity, series and period |
| Station metadata | Station name, water-body name and elevation. See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | None |
| Licence stated by IDEAM | Creative Commons Attribution-ShareAlike 4.0 (CC BY-SA 4.0); source attribution required |
| Agency documentation | [IDEAM Open Data portal](https://datos.ideam.gov.co/), [IDEAM Hydrometeorology](https://www.ideam.gov.co/), [Datos Abiertos Colombia](https://www.datos.gov.co/) |

Retrieve one week of daily mean discharge at station `0011017010`, Aguasal on
the Andágueda river in Chocó:

```python
import rivretrieve as rr

selection = rr.find(
    provider="co_ideam",
    station="0011017010",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)

result = rr.fetch(selection, start="2010-01-01", end="2010-01-07", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print(result.issues)
```

Output:

```text
time,time_zone,value,unit
2010-01-01T00:00:00.000000,unknown,128.7,m3/s
2010-01-02T00:00:00.000000,unknown,126.3,m3/s
2010-01-03T00:00:00.000000,unknown,162.8,m3/s
7
()
```

The request returned seven published daily means in m³/s from IDEAM's `Q_MEDIA_D`
historical CSV file. The preview shows the first three days. `time_zone` is
`unknown` because the exported CSV files carry no UTC offset and reflect a
1992-1993 national clock change; see [Time and data status](#time-and-data-status).
The empty tuple `()` means this retrieval reported no transport or structural
issues. Attribution and ShareAlike conditions apply when reusing the data; see
[Terms and citation](#terms-and-citation).

`cache="bypass"`, the default for live `rr.fetch` calls, requests IDEAM's S3
archive directly without reading or writing a local cache. Passing
`cache="reuse"` stores the downloaded series locally so later historical queries
within the cached span reuse the local store without downloading the multi-decade
CSV file again. This output was checked live on 2026-11-09. Published values can
change when IDEAM revises provisional rating curves. See [Usage](../usage.md)
for selection options and result handling.

## Who measures, and who publishes

Colombia's Instituto de Hidrología, Meteorología y Estudios Ambientales (IDEAM),
a public scientific institute affiliated with the Ministry of Environment and
Sustainable Development (*Ministerio de Ambiente y Desarrollo Sostenible*),
operates the national hydrometeorological monitoring network and publishes
historical surface-water series from its AQUARIUS Time-Series database to its
Open Data S3 portal (`datos.ideam.gov.co`). Some stations in the national
registry are operated by regional environmental authorities (*Corporaciones
Autónomas Regionales*) or hydropower and water utilities and shared through
IDEAM's national catalogue.

No API key or account is required. RivRetrieve searches the packaged station and
series catalogue offline; `rr.fetch` then downloads the corresponding per-station
CSV files over HTTPS. Station identifiers are ten-digit zero-padded IDEAM codes,
kept as strings such as `"0011017010"`. Include the two leading zeros when
selecting by station code, even though station display names often show the
eight-digit form in brackets (for example `AGUASAL [11017010]`).

The packaged `co_ideam` catalogue retains `1,372` flowing-watercourse gauges
that publish at least one river discharge or stage file in IDEAM's S3 historical
archive:

- **Excluded non-river and inactive entries:** Socrata station-registry rows
  with no S3 discharge or stage files, meteorological-only stations, and
  standing-water stage gauges on reservoirs (*Embalse*) and lagoons (*Laguna*)
  without discharge series are excluded. Gauges classified under a hydrological
  station category that publish river discharge or stream-named stage records
  are retained.
- **Separation from legacy `HIS_*` Socrata tables:** Colombia's national open
  data portal (`datos.gov.co`) also hosts older tabular datasets named
  `HIS_CAUDAL_D`, `HIS_NIVEL_D`, and similar `HIS_*` views. Those legacy tables
  stop around 2019 to 2022 and are superseded by IDEAM's daily-regenerated S3
  historical CSV archive (`s3-estacionesideam`), which carries both the earlier
  multi-decade history and current operational years. RivRetrieve reads only the
  S3 historical CSV archive and does not query or merge the legacy `HIS_*`
  tables.

## What you can retrieve

IDEAM publishes up to twenty hydrological CSV series per river gauge: ten for
discharge (*caudal*) and ten for water level (*nivel*):

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | `CAUDAL_H` | Unknown | Unknown | m³/s | m³/s |
| `discharge` | `Q_MEDIA_D` | Daily | Mean | m³/s | m³/s |
| `discharge` | `Q_MX_D` | Daily | Maximum | m³/s | m³/s |
| `discharge` | `Q_MN_D` | Daily | Minimum | m³/s | m³/s |
| `discharge` | `Q_MEDIA_M` | Monthly | Mean | m³/s | m³/s |
| `discharge` | `Q_MX_M` | Monthly | Maximum | m³/s | m³/s |
| `discharge` | `Q_MN_M` | Monthly | Minimum | m³/s | m³/s |
| `discharge` | `Q_MEDIA_A` | Yearly | Mean | m³/s | m³/s |
| `discharge` | `Q_MX_A` | Yearly | Maximum | m³/s | m³/s |
| `discharge` | `Q_MN_A` | Yearly | Minimum | m³/s | m³/s |
| `stage` | `NIVEL_H` | Unknown | Unknown | cm | m |
| `stage` | `NV_MEDIA_D` | Daily | Mean | cm | m |
| `stage` | `NV_MX_D` | Daily | Maximum | cm | m |
| `stage` | `NV_MN_D` | Daily | Minimum | cm | m |
| `stage` | `NV_MEDIA_M` | Monthly | Mean | cm | m |
| `stage` | `NV_MX_M` | Monthly | Maximum | cm | m |
| `stage` | `NV_MN_M` | Monthly | Minimum | cm | m |
| `stage` | `NV_MEDIA_A` | Yearly | Mean | cm | m |
| `stage` | `NV_MX_A` | Yearly | Maximum | cm | m |
| `stage` | `NV_MN_A` | Yearly | Minimum | cm | m |

A station may publish only a subset of these twenty files, and a listed series
need not cover the requested period. RivRetrieve reads the aggregated daily,
monthly, and yearly series directly as IDEAM publishes them; it does not compute
daily, monthly, or yearly summaries from sub-daily readings.

IDEAM's `variables.csv` dictionary labels `CAUDAL_H` and `NIVEL_H` as *Horario*
(hourly) with no statistic code. In practice, those two labels combine hourly
telemetry at automatic gauges with twice-daily (`06:00` and `18:00`) manual
staff-gauge readings at conventional gauges, and individual stations switch
cadence when upgraded from conventional observation to telemetry. Because one
series label spans both observation schedules without declaring whether readings
are instantaneous or interval averages, RivRetrieve leaves both `frequency` and
`statistic` unknown (`None`) on `CAUDAL_H` and `NIVEL_H`.

Filtering by `frequency` (`"daily"`, `"monthly"`, or `"yearly"`) and `statistic`
(`"mean"`, `"max"`, or `"min"`) selects the corresponding derived series directly.
To inspect all available series at a gauge offline or select `CAUDAL_H` or
`NIVEL_H` explicitly, inspect `rr.series(...)` and pick by `series_id`:

```python
import polars as pl

all_discharge = rr.find(provider="co_ideam", station="0011017010", quantity="discharge")
candidates = rr.series(all_discharge)
metadata = rr.metadata(all_discharge)

caudal_h_id = candidates.filter(pl.col("published_id") == "CAUDAL_H")["series_id"].item()
subdaily = rr.pick(all_discharge, series_id=caudal_h_id)
```

At automatic telemetric gauges, IDEAM derives daily maxima (`Q_MX_D`, `NV_MX_D`)
and minima (`Q_MN_D`, `NV_MN_D`) from intra-hour sensor extremes, which can
exceed the highest top-of-hour reading in `CAUDAL_H` or `NIVEL_H` on the same
date. Because sub-daily averaging and extreme-value conventions vary between
conventional and automatic equipment and are not stated per row in the exported
CSV files, `temporal_support` remains unknown across all twenty series.

## Stage references, coordinates, and metadata

River stage (*nivel*) is published in centimetres (`cm`) relative to the local
staff-gauge zero (*cero del limnímetro* or *cota cero* in IDEAM's hydrometric
manuals). RivRetrieve multiplies `cm` values by `0.01` to return metres (`m`),
preserves `"cm"` in `source_unit` (with `"m3/s"` on discharge), and sets
`vertical_reference="gauge_zero"` on all ten stage series. Genuine zero flows
(`0.0 m3/s`), zero stages (`0.0 m`), and negative stages below local gauge zero
are preserved without clamping.

IDEAM's open-data CSV exports and station registry do not publish local
gauge-zero elevations relative to sea level or dated histories of staff-gauge
relocations. As a result, `vertical_datum` is unknown on all stage series. Do
not add a station's general elevation (`Altitud`) to `gauge_zero` stage readings
to estimate water-surface elevation above sea level.

Station metadata (`rr.metadata(selection)`) exposes three fields from IDEAM's
station catalogue (`catalogo.csv`):

- `Nombre` as `station_name`
- `Corriente` as `water_body_name`
- `Altitud` as `elevation` (published as numeric text without an explicit unit
  or vertical datum in `catalogo.csv`, so `elevation_unit` and `elevation_datum`
  remain `null` in the packaged metadata)

IDEAM's station catalogue does not publish catchment drainage areas, so
`drainage_area_*` columns are `null`. Horizontal coordinates (`Latitud` and
`Longitud`) are decimal degrees in Colombia, but because neither `catalogo.csv`
nor its Socrata schema specifies whether coordinates refer to `MAGNA-SIRGAS`
(`EPSG:4686`), `WGS 84` (`EPSG:4326`), or unprojected legacy *Observatorio de
Bogotá* surveys, `crs` is `"unknown"`.

## Record currency and local caching

IDEAM regenerates active S3 CSV files daily from AQUARIUS. Active telemetric
gauges commonly extend to within one to three days of the current date, whereas
conventional or decommissioned gauges end earlier. Each S3 request downloads the
complete historical CSV file for one `(station, series)` pair (ranging from
single-row `85`-byte files up to roughly `35 MB` on multi-decade hourly series).

When `cache="reuse"` is passed to `rr.fetch`:

- RivRetrieve caches the series over its observed `[first_observation,
  last_observation]` span. Subsequent queries whose requested window falls inside
  that span are served offline from the local store with zero network requests.
- Requesting dates after `last_observation` (or before `first_observation`)
  triggers a fresh download of the S3 CSV file and updates any revised
  provisional values across the overlapping period. Because pre-record and
  post-record sub-spans are not marked complete in the local store, queries for
  future or newly published days are never blocked by stale empty-window cache
  entries.
- If you want to pick up in-place recalculations of provisional values inside an
  already cached date span without extending the query end date, pass
  `cache="refresh"`.

When a requested S3 CSV object returns `HTTP 404` (`NoSuchKey`), RivRetrieve
reports a `source.http_not_found` warning in `result.issues`, leaves sibling
stations and series unaffected, and retains any previously cached observations in
the local store rather than erasing them during transient S3 export rebuilds.

## Time and data status

Every S3 CSV row carries an unqualified wall-clock timestamp `fechaObservacion`
formatted as `YYYY-MM-DD HH:MM:SS` with no UTC offset. Outside 1992 and 1993,
Colombia uses standard civil time `UTC-05:00` year-round. Between May 1992 and
February 1993, Colombia observed one hour of daylight saving time (*Hora
Gaviria*, `UTC-04:00` under Decreto 591 de 1992). IDEAM's AQUARIUS exporter
formatted stored timestamps in historical local civil time without offsets:

- During May 1992 through early February 1993, daily, monthly, and yearly rows
  carry `01:00:00` instead of `00:00:00`, and conventional `06:00`/`18:00`
  readings shift to `07:00`/`19:00`.
- When clocks fell back on `1993-02-06 23:00:00`, hourly series (`CAUDAL_H`,
  `NIVEL_H`) can contain two distinct consecutive measurements stamped with the
  identical wall-clock string `1993-02-06 23:00:00`.

Because an offset-free timestamp cannot disambiguate the folded
`1993-02-06 23:00:00` hour and IDEAM's open documentation does not state the
exact hydrological day boundary across historical conventional and automatic
eras, RivRetrieve sets `time_zone="unknown"` and leaves `day_definition`,
`timestamp_anchor`, and `label_time` unknown across all twenty series.
`rr.to_utc()` refuses `unknown` time zones rather than guessing an offset on
ambiguous wall-clock timestamps, and duplicate `1993-02-06 23:00:00` rows are
preserved in source order.

Date and timestamp clipping follows each series's time resolution:

- **Daily series (`*_D`):** Clipped by calendar date (`YYYY-MM-DD`), so
  `1992-08-01 01:00:00` is matched as calendar date `1992-08-01` alongside
  ordinary `00:00:00` daily rows.
- **Sub-daily (`CAUDAL_H`, `NIVEL_H`), monthly (`*_M`), and yearly (`*_A`)
  series:** Clipped by exact source timestamp. Monthly series are stamped on the
  first day of the month (`YYYY-MM-01 00:00:00`, or `01:00:00` during
  1992-1993), and yearly series are stamped on January 1 (`YYYY-01-01 00:00:00`,
  or `1993-01-01 01:00:00`); include those first-of-period dates in `[start, end]`
  when requesting monthly or yearly summaries.

Each S3 CSV row includes a third column, `nivelAprobacion`, carrying IDEAM's
AQUARIUS approval status:

- `Preliminar`: provisional operational data (AQUARIUS approval level `900`),
  subject to rating-curve and quality-control revision.
- `En revisión`: data currently under hydrographic review (level `1100`).
- `Definitivo`: validated archival data (level `1200`).
- `""` (empty string): legacy ungraded rows in some older series.

Separate AQUARIUS `Grade` markers in IDEAM's open exports remain unpopulated
(`50 - INDEFINIDO`). Following RivRetrieve's library-wide convention, `rr.fetch`
returns observations across all `nivelAprobacion` states without filtering or
modifying values; the original source CSVs retain those per-row approval labels
if future flag support or direct source inspection is needed. Missing dates and
hours are simply absent from IDEAM's CSV files rather than written as placeholder
rows.

## Terms and citation

IDEAM's Socrata open-data metadata cards for the hydrological station catalogue
and the twenty historical discharge and stage series declare the
[Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA
4.0)](https://creativecommons.org/licenses/by-sa/4.0/) licence (`CC_40_BY_SA`)
with mandatory attribution to IDEAM:

> Instituto de Hidrología, Meteorología y Estudios Ambientales - IDEAM, Bogotá D.C.

Under CC BY-SA 4.0, you may copy, redistribute, and adapt the data for any
purpose, including commercial use, provided that you credit IDEAM, link to the
licence, indicate if changes were made, and distribute any adapted material
under the same CC BY-SA 4.0 licence (ShareAlike). Both `rr.describe("co_ideam")`
and `result.provenance` expose
`license="Creative Commons Attribution | Share Alike 4.0 International"` and
`citation="Instituto de Hidrología, Meteorología y Estudios Ambientales - IDEAM, Bogotá D.C."`.
For scientific reproducibility, also record the ten-digit station code, published
series code (such as `Q_MEDIA_D`), requested period, and retrieval date.

RivRetrieve paces requests to `datos.ideam.gov.co` at a maximum of one request
per second. Use `cache="reuse"` when running repeated analyses across many
stations or multi-decade records.

## Sources

Publisher portals, metadata cards, and manuals checked on 2026-11-06 through
2026-11-09:

- [IDEAM Open Data portal (`datos.ideam.gov.co`)](https://datos.ideam.gov.co/)
  and the `s3-estacionesideam` historical CSV archive
  (`observaciones/historicos/csv/` and `aire/emisiones/` metadata tables
  `catalogo.csv` and `variables.csv`): station registry, twenty hydrological
  series codes, units, and `nivelAprobacion` status labels.
- [Datos Abiertos Colombia (`datos.gov.co`)](https://www.datos.gov.co/): Socrata
  station catalogue (`n6vw-vkfe`) and series metadata cards declaring CC BY-SA
  4.0 (`CC_40_BY_SA`) licensing and IDEAM attribution, as well as legacy `HIS_*`
  dataset scope.
- IDEAM hydrometric manuals *Operación de estaciones hidrológicas*
  (`GCI-VH-MO001`, v03) and *Medición de niveles* (`GCI-VH-M028`, v03): local
  staff-gauge zero (*cero del limnímetro* / *cota cero*) definitions,
  conventional `06:00` and `18:00` observation schedules, and Colombian standard
  time (`UTC-5`).
- [Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA
  4.0)](https://creativecommons.org/licenses/by-sa/4.0/): attribution and
  share-alike licence conditions.

The station count (`1,372`) describes the packaged catalogue snapshot
(2026-11-06). The practical example was checked live on 2026-11-09. A successful
example retrieval does not guarantee continuous coverage across other dates,
quantities, or stations. The
[private verification archive](https://github.com/RivRetrieve/verification-evidence#readme)
retains the captured inputs, external CAMELS-COL comparison, and exact commands.
