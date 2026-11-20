# Chile: Dirección General de Aguas (DGA)

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `cl_dga` |
| Country | Chile |
| Published by | Dirección General de Aguas (DGA), Ministerio de Obras Públicas (MOP) |
| Quantities | Historical daily discharge and monthly mean discharge |
| Stations in the catalogue | 784. Availability depends on period |
| Station metadata | Station name and elevation. See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | None |
| Access | Explicit national DGA archive download, then local retrieval |
| Terms | MOP non-commercial reproduction with clear citation; commercial use and adaptation require written permission; dataset-specific licence unestablished. See [Terms and citation](#terms-and-citation) |
| Agency documentation | [Visor de Mapas y Estadística Hidrométrica (`mapas2`)](https://mapas2.mop.gob.cl/), [Manual de usuario `mapas2` (PDF)](https://mapas2.mop.gob.cl/manual_usuario_mapas2.pdf) |

First prepare the national archive. This transfers and compiles both national
historical discharge files, not just the station used below. Allow time and
disk space for that operation; see [Downloading the archive](#downloading-the-archive).

```python
import rivretrieve as rr

rr.download("cl_dga")
```

Then retrieve one week of published daily discharge at station `01050002`, Río
Piga en Collacagua:

```python
selection = rr.find(
    provider="cl_dga",
    station="01050002",
    quantity="discharge",
    frequency="daily",
)

result = rr.fetch(
    selection, start="2024-01-01", end="2024-01-07", cache="bypass"
)

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(float_precision=3), end="")

print(result.data.height)
print([(issue.severity, issue.code) for issue in result.issues])
```

Output:

```text
time,time_zone,value,unit
2024-01-01T00:00:00.000000,unknown,0.303,m3/s
2024-01-02T00:00:00.000000,unknown,0.306,m3/s
2024-01-03T00:00:00.000000,unknown,0.311,m3/s
7
[('info', 'provenance.license_not_established'), ('info', 'provenance.citation_not_established')]
```

The request returned seven daily discharge values in m³/s for 1 to 7 January
2024, with both endpoint dates included. The preview shows the first three
values rounded to three decimal places. Keep leading zeros in station
identifiers such as `"01050002"`. RivRetrieve sets `time_zone="unknown"`
because the source archive gives calendar dates without a time zone or interval
definition.

No warning or error issues occurred. The two informational issues report that
RivRetrieve has not established an official open-data licence
(`result.provenance.license` is `None`) or an agency citation template
(`result.provenance.citation` is `None`) for `cl_dga`. They do not mean
retrieval failed or that attribution is optional; follow the MOP conditions in
[Terms and citation](#terms-and-citation).

For this bulk provider, `cache="bypass"` still reads the compiled local store.
This example was checked live against DGA's national archives on 2026-11-20. A
successful example at one station and week does not establish continuous
records at that gauge or national coverage. Run the snippets in order in the
same Python session, and see [Usage](../usage.md) for general selection and
result handling.

## Who measures, and who publishes

Chile's *Dirección General de Aguas* (DGA), within the *Ministerio de Obras
Públicas* (MOP), operates the national hydrometric network and publishes
historical streamflow statistics through its *Visor de Mapas y Estadística
Hidrométrica* portal ([`mapas2.mop.gob.cl`](https://mapas2.mop.gob.cl/)).

`cl_dga` reads two national historical ZIP archives published on `mapas2`:
daily discharge (`caudal_diario_historico.zip`) and monthly mean discharge
(`caudal_medio_mensual_historico.zip`). Historical discharge is the delivered
scope for this provider. Operational *Hidrolínea* telemetry, river stage, and
water temperature are excluded.

DGA does not publish an archive edition date, dataset version, or update
schedule on `mapas2`.

## Downloading the archive

`rr.download("cl_dga")` downloads both national historical discharge ZIP
archives over HTTPS with no credentials and compiles them into one local
observation store. RivRetrieve never starts this transfer during `rr.fetch`.
Without a compiled store, retrieval returns an empty result with a
`bulk.store_missing` warning and an instruction to run `download`.

In the verified snapshot checked on 2026-11-20, the two compressed ZIP files
totalled about 37.4 MB (about 35.8 MB daily and 1.6 MB monthly) and about
892 MB uncompressed. The compiled local store occupied about 47.7 MB, and fresh
download and compilation took under three minutes on the verification machine.
Size and duration vary with the snapshot, network, and computer. Streaming
extraction and sorting require working space beyond the compressed ZIP size.
RivRetrieve checks estimated free space before extracting and compiling.

Choose a cache location with `RIVRETRIEVE_CACHE_DIR` before preparing the
archive; see [cache configuration](../usage.md#cache-and-bulk-downloads). After
preparation, inspect the local copy without downloading it again:

```python
status = rr.cache_status("cl_dga")

print(status.presence.value)
print(status.source_vintage)
```

Output for the verified copy:

```text
present
None
```

`status.source_vintage` remains `None` because DGA does not publish a vintage
or edition date for these static archives. RivRetrieve does not substitute HTTP
headers, ZIP file timestamps, download dates, or the latest observation date
for an unestablished source vintage.

The same compiled copy serves later requests for other stations and periods.
Both `cache="bypass"` and `cache="reuse"` read it locally. `cache="refresh"` is
refused: run `rr.download("cl_dga")` explicitly to replace the local store with
a fresh download. Retrieval does not check for newer publisher files. A
successful download replaces the store atomically without carrying forward rows
absent from the newer snapshot, while a failed download or invalid archive
preserves any existing committed store.

## What you can retrieve

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | `Caudal_diario` in `caudal_diario_historico.txt` | Daily | Unknown | m³/s | m³/s |
| `discharge` | `Caudal_Medio_mensual` in `caudal_medio_mensual_historico.txt` | Monthly | Mean | m³/s | m³/s |

Both products publish discharge in cubic metres per second (`m3/s`) and need no
unit conversion. `Caudal_diario` has no established statistic in DGA's files or
manuals, so `statistic` remains unknown. As a consequence, filtering with
`statistic="mean"` selects only `discharge_monthly_mean` (`Caudal_Medio_mensual`).
To retrieve daily discharge, request `frequency="daily"` without `statistic="mean"`,
as shown in the example above. RivRetrieve reads DGA's published monthly means
directly; it does not calculate them from the daily series.

A station being listed in the catalogue does not guarantee data for every
requested period. In the verified snapshot, the packaged catalogue contains
784 stations, all backed by the same station set in both historical archives,
with records spanning from 1960 through September 2026 (`1960-01-01` to
`2026-09-30` daily, and `1960-01` to `2026-09` monthly). Station start and end
dates vary across the network, and neither archive contains records before
1960. Treat this station count and date span as observations from the verified
snapshot, rather than permanent availability promises.

Packaged station metadata exposes `NOMBRE ESTACION` as station name and positive
`ALTITUD` values in metres (`m`, vertical datum unknown) as elevation. Water-body
names and drainage areas are not published in these files, and horizontal
coordinate reference systems (`crs`) remain unknown. Placeholder `ALTITUD=0`
entries (present at 84 of the 784 stations in the verified snapshot) are
withheld as `source_null` rather than returned as `0 m`. See the
[station metadata guide](../station-metadata.md) and
[Fields by provider](../station-metadata.md#fields-by-provider) for shared
columns, source-view inspection, and metadata structure.

## Time and data status

Daily observations carry source dates at midnight (`YYYY-MM-DDT00:00:00.000000`)
with `time_zone="unknown"`. Read `time` and `time_zone` together. RivRetrieve has
not established the time zone or interval boundaries of the daily values. The
midnight label does not make them UTC or Chile local time, and `rr.to_utc`
refuses to convert them.

Monthly mean records publish only year (`Año`) and month (`Mes`) without a day
of month, clock time, or time zone. RivRetrieve selects every calendar month
overlapping `[start, end]`: for example, requesting `start="2024-02-10"` and
`end="2024-02-20"` returns February 2024, and requesting `start="2023-12-15"`
and `end="2024-01-10"` returns both December 2023 and January 2024. Each monthly
row is returned on `YYYY-MM-01T00:00:00.000000` with `time_zone="unknown"`. That
first-of-month timestamp is a table carrier used to store the row, not a source
timestamp or instant.

Daily files in the verified snapshot contain duplicate `(station_id, date)` rows:
2,442 duplicate date keys across 21 stations, almost all with conflicting
discharge values and no column that explains or ranks the duplicates. RivRetrieve
preserves every published row without deduplicating, dropping, or averaging
duplicates. Inspect retrieved daily series for duplicate dates before computing
summaries.

In the verified snapshot, every published monthly mean agreed closely with the
arithmetic mean of the corresponding daily rows for that station and month,
including months with missing days and single-day months (519 station-months
in that snapshot had only one daily row). Do not assume that a published monthly
mean represents a complete month of daily observations. This observation comes
from comparing the snapshot files; DGA does not publish a documented minimum-day
threshold or completeness rule for these monthly means.

Genuine `0.0 m³/s` measurements remain numeric `0.0` rows. Dates or months with
no source row supply no rows in `result.data`. A missing store or failed request
is reported separately through [issues](../usage.md#issues); an empty result
alone does not distinguish absent data from a missing store. Neither historical
file includes a quality or approval-status column, so `rr.annotations(result)`
is empty for `cl_dga` and RivRetrieve makes no quality judgements. Optional
`receipts=True` returns Parquet store excerpts (`store_excerpt`) retaining
raw source columns, not copies of the original ZIP archives; see
[receipts](../usage.md#receipts-optional).

## Terms and citation

MOP publishes portal terms of use at
[Condiciones de Uso](https://www.mop.gob.cl/condiciones-de-uso/), which state:

> Siempre que no sea para fines comerciales, el MOP autoriza la reproducción de
> los contenidos de este sitio, citando en forma clara su procedencia. Si se
> desea hacer dicha referencia en materiales promocionales u otros medios, se
> podrá hacer sólo con el permiso por escrito de parte del Ministerio de Obras
> Públicas, lo cual debe solicitarse en Contáctenos o a través de la Oficina de
> Información, Reclamos y Sugerencias (OIRS).

Unofficial English translation: provided it is not for commercial purposes, MOP
authorizes reproduction of the contents of this site, clearly citing its
source. If such reference is intended in promotional materials or other media,
it may only be made with written permission from the Ministerio de Obras
Públicas, requested through *Contáctenos* or the *Oficina de Información,
Reclamos y Sugerencias* (OIRS).

Check these conditions before redistributing, adapting, or using DGA data
commercially:

- **Non-commercial reproduction requires clear citation.** Always cite DGA and
  MOP and reference the source URL (`https://mapas2.mop.gob.cl/`) and MOP
  terms URL (`https://www.mop.gob.cl/condiciones-de-uso/`).
- **Commercial reuse, promotional materials, and adaptation.** MOP's published
  terms condition free reproduction on non-commercial use and require written
  permission for promotional materials or other media. A dataset-specific open
  licence permitting unrestricted commercial reuse or adaptation has not been
  established.
- **Software licence exclusion.** `result.provenance.license` is `None` (and
  `rr.describe("cl_dga")` omits a top-level `license` field) because no
  dataset-specific open licence is established; `license = None` is not
  unrestricted reuse. RivRetrieve's MIT licence covers RivRetrieve's software
  only, never DGA/MOP observation data or packaged catalogues and station
  metadata. Maintainer approval in RivRetrieve does not grant agency
  permission.

RivRetrieve also leaves `result.provenance.citation` as `None` (and
`rr.describe("cl_dga")` omits a top-level `citation` field) because no official
agency citation template is established, so every fetch includes
`provenance.license_not_established` and `provenance.citation_not_established`
as informational issues. The `station_metadata` record set in
`rr.describe("cl_dga")` carries the MOP terms and non-MIT notice for packaged
metadata. When citing retrieved data, credit DGA and MOP (*Estadística
Hidrométrica*, `https://mapas2.mop.gob.cl/`, terms at
`https://www.mop.gob.cl/condiciones-de-uso/`) and record the station
identifier, product, and download date for traceability.

## Sources

Publisher pages and documents checked for the `cl_dga` port and verified on
2026-11-18 through 2026-11-20:

- [Visor de Mapas y Estadística Hidrométrica (`mapas2.mop.gob.cl`)](https://mapas2.mop.gob.cl/): national historical daily (`caudal_diario_historico.zip`) and monthly mean (`caudal_medio_mensual_historico.zip`) discharge archives.
- [Manual de usuario `mapas2` (PDF)](https://mapas2.mop.gob.cl/manual_usuario_mapas2.pdf) and [Preguntas frecuentes DGA (PDF, August 2026)](https://dga.mop.gob.cl/uploads/sites/13/2026/08/preguntas-frecuentes-17-08-2026.pdf): portal scope and discharge terminology.
- [Condiciones de Uso, Ministerio de Obras Públicas (MOP)](https://www.mop.gob.cl/condiciones-de-uso/): non-commercial reproduction, clear source citation, and written-permission conditions.

The station count describes the packaged catalogue snapshot (2026-11-18). A
fresh national download and the example on this page were checked live on
2026-11-20. The example verifies one station, daily discharge, and one week,
not continuous history or national coverage. The
[private verification archive](https://github.com/RivRetrieve/verification-evidence#readme)
retains the commands, source checks, ten-basin CAMELS-CL comparison, and limits
of these checks.
