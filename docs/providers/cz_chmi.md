# Czechia — CHMI

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `cz_chmi` |
| Country | Czechia |
| Published by | Český hydrometeorologický ústav (ČHMÚ), the Czech Hydrometeorological Institute (CHMI) |
| Read from | CHMI open data, historical hydrology files (`opendata.chmi.cz`) |
| Variables | Discharge, stage, water temperature |
| Stations in the catalogue | 831 |
| Credentials | None |
| Licence stated by CHMI | Creative Commons Attribution 4.0 (CC BY 4.0) |
| Agency documentation | [CHMI open data, hydrology](https://opendata.chmi.cz/hydrology/), [dataset descriptions](https://opendata.chmi.cz/hydrology/read_me/) |

```python
import rivretrieve as rr

selection = rr.find(provider="cz_chmi", product="discharge_daily_mean")
selection = rr.pick(selection, station="0-203-1-180100")
result = rr.fetch(selection, start="2020-01-01", end="2020-12-31")
```

## Who measures, and who publishes

CHMI runs the Czech national hydrological network and publishes its data as open data at
[opendata.chmi.cz](https://opendata.chmi.cz/hydrology/), as one file per station and calendar
year. RivRetrieve reads the historical daily and hourly files.

Station identifiers are CHMI's WIGOS identifiers, for example `0-203-1-180100`.

## What you can retrieve

| Product | CHMI code | Unit | Stations listed |
|---|---|---|---:|
| `discharge_daily_mean` | QD | m³/s | 831 |
| `stage_daily_mean` | HD | m | 831 |
| `water_temperature_daily_mean` | TD | °C | 831 |
| `discharge_hourly_mean` | QH | m³/s | 831 |
| `stage_hourly_mean` | HH | m | 831 |

CHMI's [dataset description](https://opendata.chmi.cz/hydrology/read_me/Popis_datovych_sad_historical.pdf)
defines the daily files as mean daily values (*průměrné denní hodnoty*) and the hourly files as
mean hourly values (*průměrné hodinové hodnoty*), which is where the `_mean` in the product names
comes from.

Availability is `unknown` for every station and product because CHMI's
metadata does not state which variables each station measures.

## How recent

CHMI publishes its hydrology in three folders, and RivRetrieve reads only the first:

| CHMI folder | Contents | Coverage on 19 September 2026 |
|---|---|---|
| `historical` | one file per station and calendar year | up to 2025; no 2026 file yet |
| `recent` | one file per station and day, stage and discharge every 10 minutes, UTC | 1 January 2026 to the previous day |
| `now` | the current day, every 10 minutes | the current day |

So through RivRetrieve, Czech data currently end on 31 December 2025. CHMI publishes the current
year in `recent` and `now`, which RivRetrieve does not read.

## Time

Values come back with `time_zone` `+00:00`, as the provider records CHMI's timestamps in UTC.

## Terms and citation

CHMI's [disclaimer and conditions of use](https://www.chmi.cz/vylou%C4%8Den%C3%AD-odpov%C4%9Bdnosti)
state:

> Produkty Českého hydrometeorologického ústavu dostupné na těchto webových stránkách podléhají
> licenci Creative Commons 4.0 CC-BY. Dílo smíte sdílet a upravovat za podmínky uvedení původu
> (zdroje ČHMÚ).

In English, unofficially: CHMI's products available on these websites are licensed under Creative
Commons 4.0 CC BY; you may share and adapt the work on condition that you credit the origin (the
source, ČHMÚ).

CHMI publishes no formatted citation for the data.

## Sources

| Page | Retrieved |
|---|---|
| [CHMI open data, hydrology](https://opendata.chmi.cz/hydrology/) | 2026-09-19 |
| [Popis datových sad, historical (dataset description)](https://opendata.chmi.cz/hydrology/read_me/Popis_datovych_sad_historical.pdf) | 2026-09-19 |
| [Vyloučení odpovědnosti a podmínky použití](https://www.chmi.cz/vylou%C4%8Den%C3%AD-odpov%C4%9Bdnosti) | 2026-09-19 |

Station counts come from the packaged catalogue.
