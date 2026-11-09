# Peru: SENAMHI

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `pe_senamhi` |
| Country | Peru |
| Published by | Servicio Nacional de Meteorología e Hidrología del Perú (SENAMHI), an agency attached to the Ministry of the Environment (MINAM) |
| Read from | Observatorio Nacional del Tiempo, Agua y Clima del Perú (`servicios.senamhi.gob.pe/api`) |
| Quantities | Discharge and stage |
| Stations in the catalogue | 270 with selectable series (771 station identities retained). Availability depends on quantity and period |
| Station metadata | Station name, water-body name and elevation. See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | None required |
| Terms stated by SENAMHI | User sole responsibility notice; see [Terms and citation](#terms-and-citation) |
| Agency documentation | [Observatorio SENAMHI](https://observatorio.senamhi.gob.pe/) |

Retrieve published daily discharge at station `212600`, Huayabamba on the Río Huayabamba:

```python
import rivretrieve as rr

selection = rr.find(
    provider="pe_senamhi",
    station="212600",
    quantity="discharge",
    frequency="daily",
)
selection = rr.pick(selection, variant="current")

result = rr.fetch(selection, start="2024-01-01", end="2024-01-07", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print([(issue.severity, issue.code) for issue in result.issues])
```

Output:

```text
time,time_zone,value,unit
2024-01-01T00:00:00.000000,unknown,1333.9661,m3/s
2024-01-02T00:00:00.000000,unknown,1184.2294,m3/s
2024-01-03T00:00:00.000000,unknown,1306.6894,m3/s
7
[('info', 'provenance.license_not_established'), ('info', 'provenance.citation_not_established')]
```

The request returned seven daily discharge values in m³/s for 1 to 7 January 2024.
Both endpoint dates are included. The preview shows the first three values.
The series requested is SENAMHI's published `current` field. RivRetrieve reads
the daily values SENAMHI publishes; it does not calculate them from more frequent
observations. RivRetrieve has not established whether `current` represents a daily
mean, nor when its observation day begins and ends. RivRetrieve preserves these physical
unknowns and returns `time_zone="unknown"`. Do not assume the daily values
represent midnight to midnight UTC or local time.

The two informational issues report that RivRetrieve has not established an
official open licence or citation template for SENAMHI. They are not retrieval
failures; see [Terms and citation](#terms-and-citation).

`cache="bypass"` requests the SENAMHI API directly rather than a local cache.
This output was checked on 2026-11-01. Published values can change, so a later
retrieval need not reproduce this output exactly.
See [Usage](../usage.md) for general selection and result handling.

## Who measures, and who publishes

SENAMHI operates Peru's national hydrological observing network across the Pacific,
Amazon, and Lake Titicaca drainage basins. It measures river stage and discharge and
publishes them through the Observatorio Nacional del Tiempo, Agua y Clima del Perú.
RivRetrieve reads the Observatorio's public backend API at `servicios.senamhi.gob.pe/api`.

The network includes conventional hydrological stations (categories HLM and HLG),
where observers record water levels at scheduled hours, and automatic telemetry
stations (categories EHA and EHMA), which transmit hourly sensor readings.

Of the 771 station identities retained in RivRetrieve's packaged catalogue from
SENAMHI's station registry, 270 are hydrological stations with supported series
in this snapshot.

Station identifiers are SENAMHI's station codes, such as `212600` or `47251282`.

## What you can retrieve

RivRetrieve provides river discharge and stage across two SENAMHI subsystems:
the PHISIS hydrological monitoring service and the surface observational station
archive.

### PHISIS hydrological monitoring

PHISIS publishes discharge and water level under the `/api/hydrology/*` routes:

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | `current` | Daily | Unknown | m³/s | m³/s |
| `discharge` | `minimum` | Daily | Unknown | m³/s | m³/s |
| `discharge` | `maximum` | Daily | Unknown | m³/s | m³/s |
| `discharge` | `value` | Hourly | Unknown | m³/s | m³/s |
| `stage` | `current` | Daily | Unknown | m, m.s.n.m | m |
| `stage` | `minimum` | Daily | Unknown | m, m.s.n.m | m |
| `stage` | `maximum` | Daily | Unknown | m, m.s.n.m | m |
| `stage` | `value` | Hourly | Unknown | m, m.s.n.m | m |

These field names are SENAMHI's published PHISIS values, returned in `published_id`.
Stage has two separate series per field: one in metres and one above sea level in
`m.s.n.m` (see [Units and vertical reference](#units-and-vertical-reference)). Narrow
to one field with `rr.pick(selection, variant=...)` using the value shown above, or
select an individual series directly with `series_id` from `rr.series(selection)`.

Each daily PHISIS response contains three separate published fields: `current`,
`minimum`, and `maximum`. RivRetrieve preserves each field as a distinct series.
PHISIS distinguishes daily date coordinates from hourly timestamp coordinates.
These establish `frequency="daily"` and `frequency="hourly"`, independently of
statistic. RivRetrieve has not established whether `current` or hourly `value`
is a mean or an instantaneous reading, or which period and population the daily
`minimum` and `maximum` summarize. Their statistics remain unknown.

Daily queries select whole published dates, including when the request bounds
contain clock times. This treats dates as source coordinates; it does not establish
the observation day's boundaries, temporal support or time zone. A daily frequency
filter matches the daily series, but a mean statistic filter does not.

Selecting `quantity="discharge"` or `quantity="stage"` without specifying a `series_id`
selects every supported series for that quantity at the station. Use `rr.series(selection)`
to inspect the available series IDs, or select an individual series directly with
`series_id`.

### Station archive readings

The station archive publishes water levels in metres (`m`) under `/api/station/stations/*`:

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `stage` | `NIVEL_DEL_RIO_06H` | Unknown | Unknown | m | m |
| `stage` | `NIVEL_DEL_RIO_10H` | Unknown | Unknown | m | m |
| `stage` | `NIVEL_DEL_RIO_14H` | Unknown | Unknown | m | m |
| `stage` | `NIVEL_DEL_RIO_18H` | Unknown | Unknown | m | m |
| `stage` | `NIVEL_DEL_RIO_PROMEDIO` | Unknown | Unknown | m | m |
| `stage` | `N_NIVELAGUA` | Unknown | Unknown | m | m |
| `stage` | `N_NIVELMEDIO` | Unknown | Unknown | m | m |
| `stage` | `N_NIV_INST_00` | Unknown | Unknown | m | m |
| `stage` | `N_NIV_INST_10` | Unknown | Unknown | m | m |

These field names are SENAMHI's published monthly station-archive JSON keys, also
returned in `published_id`. Narrow to one field with `rr.pick(selection, variant=...)`
using the value shown above, or select an individual series directly with `series_id`
from `rr.series(selection)`.

These nine fields remain distinct products in RivRetrieve. Frequency and statistic
remain unestablished because the available evidence does not define their meanings
across the supported fields and historical records. This is a gap in the evidence,
not an explicit statement by SENAMHI that the meanings are unspecified.

The `06H`, `10H`, `14H` and `18H` labels name clock hours, not sampling intervals.
The hydrometry manual describes scheduled readings and an arithmetic average, but
their applicability to `NIVEL_DEL_RIO_PROMEDIO` and individual archive records is
not established. The `N_NIV*` suffixes do not establish clock times or averaging
methods. Monthly request partitions do not establish observation frequency.

### Units and vertical reference

Discharge is published in m³/s and requires no conversion. Stage is published in
metres (`m`) or metres above sea level (`m.s.n.m`). Both return values in metres (`m`).

When the source unit is `m.s.n.m`, RivRetrieve marks `vertical_reference="above_sea_level"`.
SENAMHI does not name a geodetic vertical datum, so `vertical_datum` remains null.
For relative stage in metres, `vertical_reference` is null.

## How far back, and how recent

Record periods vary by station. PHISIS provides recent monitoring and historical
series. Daily PHISIS requests are partitioned by hydrological year (starting
1 September), while hourly requests use a two-day backward span. Station archive
requests query individual calendar months.

A station being listed does not guarantee data for every quantity or period.
When SENAMHI has no observations for a requested interval, RivRetrieve returns
no rows. Published null values remain rows with `value=null`. Absent dates supply
no rows. Failed source responses remain issues reported alongside any successful
records.

SENAMHI records occasionally contain negative values or future-dated timestamps;
RivRetrieve returns these values as published.

## Time and data status

SENAMHI timestamps and date labels carry no explicit time zone offset. RivRetrieve
sets `time_zone="unknown"`. Do not assume timestamps are UTC or Peru local time
(UTC-5).

PHISIS DAILY `current` is not established as a daily mean, and its averaging day
definition is unknown.

PHISIS automatic-station views on the Observatorio display the notice *"Esta
información corresponde a datos crudos registrados por la estación automática"*
("This information corresponds to raw data recorded by the automatic station").
This applies to PHISIS automatic-station series; it does not generalize to the
conventional station-archive series above.

SENAMHI provides data without warranty of fitness for a particular purpose.
RivRetrieve makes no quality judgements of its own.

## Rate limits

SENAMHI requests must respect an access limit of at most one request per second.
RivRetrieve's transport applies appropriate pacing. Avoid running concurrent
unthrottled retrievals against SENAMHI endpoints.

Direct connections to `servicios.senamhi.gob.pe` from some cloud or datacenter IP
ranges can time out even when the same requests succeed from residential or
institutional networks. If a retrieval times out on a cloud virtual machine or a
CI runner, this network boundary is a likely cause, not a problem with the request.

## Terms and citation

SENAMHI's service terms state:

> Información recopilada y trabajada por el Servicio Nacional de Meteorología e
> Hidrología del Perú. El uso que se le da a esta información es de mi (nuestra)
> entera responsabilidad.

In English, unofficially: information compiled and processed by SENAMHI; the use
made of this information is the user's sole responsibility.

SENAMHI does not declare a standardized open licence code or citation template.
RivRetrieve flags these conditions with informational issues
(`provenance.license_not_established` and `provenance.citation_not_established`).
When using these data, cite SENAMHI as the source and retain station identifiers,
quantities, and retrieval dates for traceability.

## Sources

Publisher pages checked on 2026-11-01:

- [Observatorio SENAMHI](https://observatorio.senamhi.gob.pe/): station network and portal.
- [SENAMHI API](https://servicios.senamhi.gob.pe/api): endpoints for hydrology and station readings.
- [Manual de Hidrometría](https://www.senamhi.gob.pe/load/file/00701SENA-924.pdf) (SENAMHI, 2018), page 16: describes conventional readings at 06, 10, 14 and 18 hours and their arithmetic average as an estimate of daily level, without binding that procedure to every published field or historical record.
- [CAMELS-PE](https://doi.org/10.5281/zenodo.21195425): an independent catchment-runoff benchmark dataset for Peru, used as background context during verification.

The station count describes the packaged catalogue. The example was verified on
2026-11-01. The [private verification archive](https://github.com/RivRetrieve/verification-evidence#readme)
retains commands, source checks, exact output and the limits of these checks.
