# Thailand — ThaiWater

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `th_thaiwater` |
| Country | Thailand |
| Published by | Hydro-Informatics Institute (HII), through ThaiWater, the national water data warehouse |
| Station agencies | HII, Royal Irrigation Department, Electricity Generating Authority of Thailand, Friend in Need (of "Pa") Volunteers Foundation |
| Variables | Discharge, stage |
| Stations in the catalogue | 825 |
| Credentials | None |
| Terms | No data licence or citation request published |
| Agency documentation | [ThaiWater](https://www.thaiwater.net/), [ThaiWater data standards](https://standard.thaiwater.net/docs/) |

```python
import rivretrieve as rr

selection = rr.find(provider="th_thaiwater", product="stage_reported")
selection = rr.pick(selection, station="1")
result = rr.fetch(selection, start="2024-06-01", end="2024-06-03")
```

## Who measures, and who publishes

RivRetrieve reads ThaiWater's public API. ThaiWater, คลังข้อมูลน้ำแห่งชาติ (the national water data warehouse), is run by the Hydro-Informatics
Institute, a public organisation under Thailand's Ministry of Higher Education, Science, Research
and Innovation. It brings together water data from many agencies; its site states that 54 agencies
contribute data.

So ThaiWater publishes data from stations run by different agencies. ThaiWater attributes each
station to an agency, and the 825 stations in RivRetrieve's catalogue are attributed to:

| Agency | Stations |
|---|---:|
| Hydro-Informatics Institute | 329 |
| Royal Irrigation Department | 328 |
| Friend in Need (of "Pa") Volunteers Foundation | 95 |
| Electricity Generating Authority of Thailand | 73 |

## What you can retrieve

| Product | Unit | Stations with data |
|---|---|---:|
| `stage_reported` | m | 813 |
| `discharge_reported` | m³/s | 283 |

Most stations report stage; about a third also report discharge.

The products are named `_reported` because the source does not state whether each value is an
instantaneous reading or an average; the catalogue records frequency and statistic as `unknown`.
In practice the values arrive every 10 minutes: at station `1`, stage came back at 10-minute steps
for windows in 2012, 2018, 2024 and 2026.

"Stations with data" is what RivRetrieve found when it tested each station over a recent window
while building the catalogue; the catalogue records the window it tested.

The API answers at most 365 days per request, so RivRetrieve splits longer requests.

## Time

Values come back with `time_zone` `unknown`. The API gives times without stating a zone, and
RivRetrieve does not fill one in.

## Terms

ThaiWater publishes no licence and no citation request for its data. The site lists only cookie
and privacy policies, and its footer carries a copyright notice:

> Copyright © 2019 Hydro - Informatics Institute,All rights reserved.

Each station is attributed to one of the agencies listed above.

## Sources

| Page | Retrieved |
|---|---|
| [ThaiWater](https://www.thaiwater.net/) | 2026-09-19 |
| [ThaiWater data standards](https://standard.thaiwater.net/docs/) | 2026-09-19 |

Station counts and agencies come from the packaged catalogue. The 10-minute spacing was checked by
retrieval on 2026-09-19.
