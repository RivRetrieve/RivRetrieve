# United States — USGS

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `usgs_nwis` |
| Country | United States |
| Published by | U.S. Geological Survey, through Water Data for the Nation |
| Variables | Discharge, stage |
| Stations in the catalogue | 26,200 |
| Credentials | None |
| Terms stated by the USGS | U.S. Public Domain |
| Agency documentation | [NWIS water services](https://waterservices.usgs.gov/docs/), [Water Data for the Nation help](https://help.waterdata.usgs.gov/) |

```python
import rivretrieve as rr

selection = rr.find(provider="usgs_nwis", product="discharge_daily_mean")
selection = rr.pick(selection, station="07374000")
result = rr.fetch(selection, start="2024-01-01", end="2024-12-31")
```

## Who measures, and who publishes

The U.S. Geological Survey operates the national streamgauge network and publishes its
measurements through the National Water Information System, the database behind
[Water Data for the Nation](https://waterdata.usgs.gov/). RivRetrieve reads the NWIS water
services at `waterservices.usgs.gov`.

Gauges are funded and run in cooperation with many federal, state, tribal and local partners, so
a station's record may serve several programmes at once. The USGS remains the publisher of the
data RivRetrieve retrieves.

## What you can retrieve

| Product | Parameter and statistic codes | Unit | Stations | Earliest published record |
|---|---|---|---:|---|
| `discharge_daily_mean` | `00060:00003` | m³/s | 24,447 | 1857-02-01 |
| `discharge_instantaneous` | `00060` | m³/s | 13,177 | 1950-10-01 |
| `stage_daily_mean` | `00065:00003` | m | 5,636 | 1897-04-05 |
| `stage_daily_max` | `00065:00001` | m | 1,664 | 1965-10-01 |
| `stage_daily_min` | `00065:00002` | m | 1,637 | 1965-10-01 |
| `stage_instantaneous` | `00065` | m | 11,400 | 1955-05-03 |

In USGS terms, `00060` is discharge and `00065` is gauge height; `00003`, `00001` and `00002` are
the mean, maximum and minimum daily statistics. The USGS publishes discharge in cubic feet per
second and gauge height in feet; RivRetrieve converts both.

This is the only provider whose catalogue carries published record start and end dates, so
`rr.as_frame(selection)` tells you the span each station reports before you request anything.

The USGS also publishes water temperature, as parameter `00010`, on the same service. RivRetrieve
does not retrieve it for this provider yet.

## Provisional data

Recent values are provisional. The USGS
[Provisional Data Statement](https://waterdata.usgs.gov/provisional-data-statement/) says:

> This information is preliminary or provisional and is subject to revision. It is being provided
> to meet the need for timely best science. The information has not received final approval by
> the U.S. Geological Survey (USGS) and is provided on the condition that neither the USGS nor
> the U.S. Government shall be held liable for any damages resulting from the authorized or
> unauthorized use of the information.

and adds:

> Subsequent review based on field inspections and measurements may result in substantial
> revisions to the data.

RivRetrieve passes values through as published and does not mark them as provisional or approved.

## Time

Instantaneous values carry an offset from the source, for example `-05:00`, and RivRetrieve keeps
that offset in the `time_zone` column. Daily values are published as dates without an offset, so
their `time_zone` is `unknown`: the USGS states the calendar date, not the clock that bounds the
day.

## Terms and citation

The USGS states, in its
[copyrights and credits policy](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits):

> USGS-authored or produced data and information are considered to be in the U.S. Public Domain.

Its [water data citation page](https://waterdata.usgs.gov/citation/) gives the form to use, with
the brackets to be filled in by you:

> Example of how to cite USGS Water Data for the Nation in general: U.S. Geological Survey,
> [2024], USGS Water Data for the Nation: U.S. Geological Survey National Water Information System
> database, accessed [April 8, 2024], at https://doi.org/10.5066/F7P55KJN.

The same page notes that these websites are updated daily, so the current date can serve as the
publication date.

## Sources

| Page | Retrieved |
|---|---|
| [USGS Water Data for the Nation](https://waterdata.usgs.gov/) | 2026-09-19 |
| [Instantaneous values service documentation](https://waterservices.usgs.gov/docs/instantaneous-values/instantaneous-values-details/) | 2026-09-19 |
| [Provisional Data Statement](https://waterdata.usgs.gov/provisional-data-statement/) | 2026-09-19 |
| [Copyrights and Credits](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits) | 2026-08-20 |
| [How should I cite USGS Water Data for the Nation data?](https://waterdata.usgs.gov/citation/) | 2026-08-20 |

Station counts and record dates come from the packaged catalogue.
