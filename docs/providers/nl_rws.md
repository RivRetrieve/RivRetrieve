# Netherlands: Rijkswaterstaat

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `nl_rws` |
| Country | Netherlands |
| Published by | Rijkswaterstaat (executive agency of the Dutch Ministry of Infrastructure and Water Management) |
| Read from | Rijkswaterstaat Waterwebservices DDAPI 2.0 (`ddapi20-waterwebservices.rijkswaterstaat.nl`) |
| Quantities | Discharge, stage and surface water temperature |
| Stations in the catalogue | 1,706. Availability depends on quantity and product |
| Station metadata | Station name (`Naam`). See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | None |
| Licence stated by Rijkswaterstaat | Public Domain Mark 1.0 / CC0 1.0 |
| Agency documentation | [Rijkswaterstaat Waterdata](https://rijkswaterstaatdata.nl/onze-data/waterdata/) |

RivRetrieve reads open surface-water observations from Rijkswaterstaat's
Waterwebservices DDAPI 2.0. Retrieve one week of daily mean discharge at
Lobith (`lobith.bovenrijn.tolkamer`) on the Rhine:

```python
import rivretrieve as rr

selection = rr.find(
    provider="nl_rws",
    station="lobith.bovenrijn.tolkamer",
    quantity="discharge",
    frequency="P1D",
    statistic="mean",
)

result = rr.fetch(selection, start="2020-03-01", end="2020-03-07", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print(result.issues)
```

Output:

```text
time,time_zone,value,unit
2020-03-01T00:00:00.000000,+01:00,4312.0,m3/s
2020-03-02T00:00:00.000000,+01:00,4487.0,m3/s
2020-03-03T00:00:00.000000,+01:00,4721.0,m3/s
7
()
```

The request returned seven daily mean discharge values in m³/s from March 1 to
7, 2020, with the first three shown in the preview. Every timestamp carries
`+01:00`, and the empty tuple `()` means retrieval reported no issues (it does
not establish the quality of the values).

`cache="bypass"` requests Rijkswaterstaat's service rather than a local cache.
This output was checked live on 2026-11-28. Published values can change, so a
later retrieval need not reproduce this output exactly. See
[Usage](../usage.md) for general selection and result handling.

## Who measures, and who publishes

Rijkswaterstaat manages the national water network of the Netherlands and
publishes surface-water measurements through Waterwebservices DDAPI 2.0.
RivRetrieve admits only measured surface-water observations
(`Compartiment = "OW"`, `ProcesType = "meting"`, `Groepering = ""`). Forecasts
(`verwachting`), astronomical tides (`astronomisch`), and tidal extremes
(`GETETBRKD2` and `GETETM2`) are excluded.

The packaged catalogue contains 1,706 stations in `EPSG:4258` with station
names from Rijkswaterstaat's `Naam` field. No credentials or API keys are
required. A station being listed does not guarantee data for every product or
requested period, and Rijkswaterstaat's catalogue endpoint does not publish
start or end dates per station.

## What you can retrieve

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | `Q` (`NVT`, `discharge_m3s_nvt`) / `WaardeBepalingsMethode` | Unknown | Unknown | m³/s | m³/s |
| `discharge` | `Q` (`GEM24H`, `discharge_m3s_gem24h`) / `WaardeBepalingsMethode` | Daily (`P1D`) | Mean | m³/s | m³/s |
| `discharge` | `Q` (`NVT`, `discharge_m3d_nvt`) / `WaardeBepalingsMethode` | Unknown | Unknown | m³/d | m³/s |
| `stage` | `WATHTE` (`NAP`, `NVT`, `stage_nap_nvt`) / `WaardeBepalingsMethode` | Unknown | Unknown | cm | m |
| `stage` | `WATHTE` (`NAP`, `GEM24H`, `stage_nap_gem24h`) / `WaardeBepalingsMethode` | Daily (`P1D`) | Mean | cm | m |
| `stage` | `WATHTE` (`PLAATSLR`, `NVT`, `stage_plaatslr_nvt`) / `WaardeBepalingsMethode` | Unknown | Unknown | cm | m |
| `stage` | `WATHTE` (`MSL`, `NVT`, `stage_msl_nvt`) / `WaardeBepalingsMethode` | Unknown | Unknown | cm | m |
| `stage` | `WATHTE` (`TAW`, `NVT`, `stage_taw_nvt`) / `WaardeBepalingsMethode` | Unknown | Unknown | cm | m |
| `temperature` | `T` (`NVT`, `water_temperature_nvt`) / `WaardeBepalingsMethode` | Unknown | Unknown | °C | °C |
| `temperature` | `T` (`GEM24H`, `water_temperature_gem24h`) / `WaardeBepalingsMethode` | Daily (`P1D`) | Mean | °C | °C |

RivRetrieve converts discharge published in cubic metres per day (`m3/d`) to
cubic metres per second (`m3/s`), and stage published in centimetres (`cm`) to
metres (`m`). Discharge in `m3/s` and water temperature in degrees Celsius
(`oC` in the API, returned as `degC`) require no numeric rescaling.

Stage products referenced to `NAP`, `MSL`, and `TAW` are elevations relative to
mean sea level (`vertical_reference="above_sea_level"`). Stage referenced to
`PLAATSLR` uses a local reference whose vertical-reference category is not
established in the catalogue.

## Parallel measurement methods (`variant`)

Rijkswaterstaat can publish more than one measurement method
(`WaardeBepalingsMethode`) for the same station and product. For example,
Lobith publishes discharge under both `other:F216` and `other:F230`. RivRetrieve
keeps each measurement method as its own series rather than merging them,
exposing the method code in `variant`. Inspect `variant` when selecting or
comparing series at a station so you do not combine parallel methods
unintentionally.

## `NVT` and `GEM24H` series, historical depth, and unestablished semantics

Rijkswaterstaat distinguishes unaggregated measurements (`NVT`) from 24-hour
daily means (`GEM24H`):

- **`GEM24H`** series are daily means (`frequency="P1D"`, `statistic="mean"`).
  At major gauges they can span historical decades, though the exact day anchor
  used to define each 24-hour mean is not established in the catalogue.
- **`NVT`** series carry unaggregated observations whose sampling interval and
  statistic are not established in the catalogue (`frequency="unknown"`,
  `statistic="unknown"`). At many gauges modern `NVT` records are high
  frequency (such as 10-minute intervals), while at some long-running gauges
  such as Lobith `NVT` also includes historical daily readings reaching back to
  1901.

Because `NVT` cadence and statistic, `GEM24H` day anchor, and `PLAATSLR`
vertical-reference category are not established by the service metadata,
RivRetrieve leaves those facts unknown rather than assuming them.

## Time zone

Waterwebservices DDAPI 2.0 reports observation timestamps with a fixed `+01:00`
offset throughout the year, including across European daylight-saving
transitions. There is no spring or autumn clock jump in returned timestamps.

## Quality annotations and missing values

Every observation can carry source metadata under the `nl_rws.observation`
annotation schema with two fields:

- `statuswaarde`: Rijkswaterstaat's validation status for the observation (for
  example `Ongecontroleerd`, `Gecontroleerd`, or `Definitief`).
- `kwaliteitswaardecode`: the Aquo quality code attached to the observation
  (for example `"00"` for normal, `"25"` for qualified, and `"99"` for
  missing).

Rijkswaterstaat encodes missing observations using
`Kwaliteitswaardecode = "99"` and/or a numeric sentinel (`9.99999e+37`, or
`.999999E+38` in alphanumeric fields). RivRetrieve converts these sentinel
observations to `null` in `value`. It neither drops the timestamp row nor
leaves `9.99999e+37` in numeric values, and it keeps the corresponding
`nl_rws.observation` annotation attached to that timestamp so you can
distinguish explicitly flagged missing observations from gaps where no row was
published.

## Terms of use and attribution

Rijkswaterstaat publishes Waterwebservices data under Public Domain Mark 1.0 /
CC0 1.0. Recommended attribution is `"Bron: Rijkswaterstaat – Waterwebservices"`.
See [Rijkswaterstaat Waterdata](https://rijkswaterstaatdata.nl/onze-data/waterdata/)
for current service terms.
