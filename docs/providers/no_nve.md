# Norway — NVE

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `no_nve` |
| Country | Norway |
| Published by | Norges vassdrags- og energidirektorat (NVE), the Norwegian Water Resources and Energy Directorate |
| Variables | Discharge, stage, water temperature |
| Stations in the catalogue | 3,804 |
| Credentials | Required: `NVE_API_KEY`, free and issued immediately |
| Licence stated by NVE | Norwegian Licence for Open Government Data (NLOD) |
| Agency documentation | [HydAPI documentation](https://hydapi.nve.no/UserDocumentation/) |

```python
import rivretrieve as rr

selection = rr.find(provider="no_nve", product="discharge_daily_mean")
selection = rr.pick(selection, station="2.605.0")
result = rr.fetch(selection, start="2024-01-01", end="2024-12-31")
```

## Who measures, and who publishes

NVE runs Norway's hydrological network and publishes the observations through HydAPI, its
programming interface for hydrological data. RivRetrieve reads HydAPI.

## Credentials

Norway needs a key, but getting one takes a minute and costs nothing. Fill in the form at
[hydapi.nve.no](https://hydapi.nve.no/Users) with an email address, and the key is issued on the
spot.

```bash
export NVE_API_KEY="your-key"
```

`rr.providers()` shows `ready` once it is set. Catalogue browsing works without it; only retrieval
needs it.

Note that NVE throttles requests per key and caps how many observations one request may return.
Large retrievals should be split rather than asked for at once.

## What you can retrieve

Norway is one of the most complete providers in RivRetrieve so far: three variables, each at three time steps,
with availability established station by station.

| Variable | Daily mean | Hourly mean | Instantaneous |
|---|---:|---:|---:|
| Discharge (m³/s) | 1,637 | 1,057 | 1,635 |
| Stage (m) | 2,845 | 1,584 | 2,850 |
| Water temperature (°C) | 1,212 | 792 | 1,235 |

The numbers are the stations offering each product, all of them marked `available`: NVE's series
list states which parameter and resolution each station serves, so the catalogue records it rather
than leaving it unknown.

NVE names a series by a parameter number and a time resolution in minutes: discharge is `1001`
and a day is `1440` minutes, so daily mean discharge is `1001:1440`. That is what the catalogue's
`native_id` column shows.

## Time

Values come back with `time_zone` `+00:00`. HydAPI timestamps are UTC, and RivRetrieve keeps
them as published, including for daily values. Norway is unusual in this: most providers state no
zone for daily data.

## Data status

Each observation from HydAPI carries a `quality` and a `correction` code, and the service lets a
caller filter on them. RivRetrieve returns the value and does not filter on, or interpret, either
code.

## Terms and citation

NVE's [documentation](https://hydapi.nve.no/UserDocumentation/) states:

> The data provided by the API is licensed under the Norwegian License for Open Government Data
> (NLOD) which is compatible with CC Navngivelse 3.0 Norge (CC BY 3.0).

and asks for credit:

> When using data from this service, if possible, please refer to this service as origin of data.

Each API response also carries the licence in its header, as `https://data.norge.no/nlod/en`.

## Sources

| Page | Retrieved |
|---|---|
| [HydAPI documentation](https://hydapi.nve.no/UserDocumentation/) | 2026-09-19 |
| [HydAPI key request](https://hydapi.nve.no/Users) | 2026-09-19 |
| [Norwegian Licence for Open Government Data](https://data.norge.no/nlod/en) | 2026-09-19 |

Station counts come from the packaged catalogue.
