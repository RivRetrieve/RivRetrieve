# Canada — Environment and Climate Change Canada

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `ca_eccc` |
| Country | Canada |
| Published by | Water Survey of Canada, Environment and Climate Change Canada |
| Variables | Discharge, stage |
| Stations in the catalogue | 8,057 |
| Credentials | None |
| Access | Bulk: the national archive is downloaded once, then read locally |
| Licence | Open Government Licence – Canada |
| Agency documentation | [Water Office](https://wateroffice.ec.gc.ca/), [National water data archive: HYDAT](https://www.canada.ca/en/environment-climate-change/services/water-overview/quantity/monitoring/survey/data-products-services/national-archive-hydat.html) |

```python
import rivretrieve as rr

rr.download("ca_eccc")  # once: downloads and compiles the national archive

selection = rr.find(provider="ca_eccc", product="discharge_daily_mean")
selection = rr.pick(selection, station="05OG008")
result = rr.fetch(selection, start="2000-01-01", end="2000-12-31")
```

## Who measures, and who publishes

The Water Survey of Canada, part of Environment and Climate Change Canada, runs the national
hydrometric network with provincial, territorial and other partners, and publishes the results
through the [Water Office](https://wateroffice.ec.gc.ca/).

Canada publishes its record in two forms:

- **Near real-time readings**, through the Water Office and an ECCC programming interface. These
  are minutes to a couple of hours old.
- **HYDAT**, the national archive of reviewed data, republished from time to time as a dated
  edition. The edition available on 19 September 2026 was dated 17 July 2026.

RivRetrieve reads HYDAT. That means Canadian data arrive reviewed but not recent: the most recent
weeks or months are not in the archive yet. RivRetrieve does not read the near real-time service.

## Downloading the archive first

Canada is a bulk provider. Rather than answering station by station, the agency distributes its
whole archive as one SQLite database, so RivRetrieve downloads it once and then reads it from your
own disk:

```python
rr.download("ca_eccc")
```

That download is about 1 GB, it happens only when you ask for it, and RivRetrieve never starts it
on its own. Until it has run, retrieval returns an empty result and an issue saying the store is
missing. `rr.cache_status("ca_eccc")` tells you whether the archive is present.

Afterwards, retrieval is local and fast, and the same copy serves every station and year until you
download a newer vintage.

## What you can retrieve

| Product | HYDAT table and column | Unit | Stations |
|---|---|---|---:|
| `discharge_daily_mean` | `DLY_FLOWS.FLOW` | m³/s | 8,057 |
| `stage_daily_mean` | `DLY_LEVELS.LEVEL` | m | 8,057 |

Availability is `unknown` for every station and product in the catalogue, and the catalogue says
why: the station endpoint ECCC publishes does not state which variables a station actually holds.
Whether a given station has discharge or stage becomes clear once the archive is on your disk.

The catalogue carries no published record dates for Canada, so the span of each station's record
is known only from the archive itself.

## Data status

The Water Office's
[disclaimer](https://wateroffice.ec.gc.ca/disclaimer_info_e.html) distinguishes what the agency
treats as official:

> Official data Products are Water Level and Discharge. Any other available parameters are
> categorized as data Outputs and do not receive a standardized level of quality assurance.

and describes its near real-time readings as preliminary:

> The data are preliminary and have been transmitted automatically with limited verification and
> review for quality assurance. Subsequent quality assurance and verification procedures may
> result in differences between what is currently displayed and what will become the official
> record.

HYDAT, which RivRetrieve reads, is the reviewed archive rather than those near real-time readings.
Each daily value in it can carry a symbol, for example for ice conditions or an estimated value;
HYDAT defines them in its own `DATA_SYMBOLS` table. RivRetrieve keeps the symbols in the compiled
store, and returns the value itself.

## Time

Daily values come back with `time_zone` `unknown`. HYDAT records a calendar date for each daily
value and does not state the clock that bounds the day, so RivRetrieve does not fill one in.

## Terms and citation

The HYDAT archive is published under the
[Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada),
which states:

> The Information Provider grants you a worldwide, royalty-free, perpetual, non-exclusive licence
> to use the Information, including for commercial purposes, subject to the terms below.

and requires attribution:

> Acknowledge the source of the Information by including any attribution statement specified by
> the Information Provider(s) and, where possible, provide a link to this licence.

Where no specific statement is given, the licence prescribes the wording:

> Contains information licensed under the Open Government Licence – Canada.

The Water Office disclaimer adds its own conditions on redistribution:

> Information presented on this web site is considered public information and may be distributed
> or copied. No agency or individual can bundle the raw information and resell the raw
> information. However, agencies and individuals may add value to the data and charge for the
> value added options. An appropriate byline acknowledging Environment Canada is required.

## Sources

| Page | Retrieved |
|---|---|
| [Water Office](https://wateroffice.ec.gc.ca/) | 2026-09-19 |
| [Disclaimer for Hydrometric Information](https://wateroffice.ec.gc.ca/disclaimer_info_e.html) | 2026-09-19 |
| [Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada) | 2026-09-19 |
| [Open Government portal, HYDAT dataset records](https://open.canada.ca/data/en/dataset?q=HYDAT) | 2026-09-19 |

Station counts come from the packaged catalogue. The archive is downloaded from
`collaboration.cmc.ec.gc.ca`.
