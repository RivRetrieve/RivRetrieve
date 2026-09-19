# Bosnia and Herzegovina — AVP Sava

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `ba_fhmzbih` |
| Country | Bosnia and Herzegovina |
| Published by | Agencija za vodno područje rijeke Save (AVP Sava), the Sava River Watershed Agency |
| Read from | `vodostaji.voda.ba`, the agency's hydrological monitoring site |
| Variables | Discharge, stage, water temperature |
| Stations in the catalogue | 60 |
| Credentials | None |
| History available | About the last year only |
| Terms | No licence or citation request published; the site states its data are informational, not official |
| Agency documentation | [vodostaji.voda.ba](https://vodostaji.voda.ba/), [Impressum](https://vodostaji.voda.ba/data/html/impressum.html) |

```python
import rivretrieve as rr

selection = rr.find(provider="ba_fhmzbih", product="discharge_reported")
selection = rr.pick(selection, station="2310")
result = rr.fetch(selection, start="2026-09-01", end="2026-09-10")
```

## Who measures, and who publishes

The data come from AVP Sava, the agency responsible for the Sava river watershed, which publishes
the readings of its automatic hydrological monitoring system on
[vodostaji.voda.ba](https://vodostaji.voda.ba/). RivRetrieve reads the workbooks that site offers
for each station and parameter.

The provider identifier is `ba_fhmzbih`, but the publisher of the data RivRetrieve retrieves is
AVP Sava.

## Only the last year

The site publishes each station's data as a rolling one-year workbook. So through RivRetrieve you
get roughly the last twelve months.

If you need a longer record for Bosnia and Herzegovina, you should contact the agency directly.

## What you can retrieve

| Product | Source parameter | Unit published | Unit delivered | Stations with data |
|---|---|---|---|---:|
| `discharge_reported` | Proticaj | m³/s | m³/s | 60 |
| `stage_reported` | Vodostaj | cm | m | 60 |
| `water_temperature_reported` | Temperatura vode | °C | °C | 12 |

The products are named `_reported` because the source does not state whether each value is an
instantaneous reading or an average; the catalogue records frequency and statistic as `unknown`.
In practice the values arrive about once an hour, with occasional longer gaps.

"Stations with data" is what RivRetrieve found in each station's workbook when the catalogue was
built.

## Data status

The site's [Impressum](https://vodostaji.voda.ba/data/html/impressum.html) states:

> Svi podaci koji se prikazuju i koji se dobiju kao rezultat pretrage su informativnog karaktera i
> ne mogu služiti kao zvanični podaci.

In English, unofficially: all data displayed, and all data obtained as search results, are for
information only and cannot serve as official data.

## Time

Values come back with `time_zone` `unknown`. The workbooks give times without stating a zone, and
RivRetrieve does not fill one in.

## Terms

The site publishes no licence and no citation request. Its Impressum describes the data as
informational rather than official.

## Sources

| Page | Retrieved |
|---|---|
| [vodostaji.voda.ba](https://vodostaji.voda.ba/) | 2026-09-19 |
| [Impressum](https://vodostaji.voda.ba/data/html/impressum.html) | 2026-09-19 |

Station counts come from the packaged catalogue. The one-year depth was checked by retrieval on
2026-09-19.
