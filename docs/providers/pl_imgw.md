# Poland — IMGW-PIB

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `pl_imgw` |
| Country | Poland |
| Published by | Instytut Meteorologii i Gospodarki Wodnej – Państwowy Instytut Badawczy (IMGW-PIB), the Institute of Meteorology and Water Management – National Research Institute |
| Variables | Discharge, stage, water temperature |
| Stations in the catalogue | 1,301 |
| Credentials | None |
| Access | Bulk: IMGW's yearly files are downloaded once, then read locally |
| Terms stated by IMGW-PIB | Free of charge with exceptions, including business use; attribution required |
| Agency documentation | [IMGW public data](https://danepubliczne.imgw.pl/), [Regulamin (regulations)](https://danepubliczne.imgw.pl/regulations) |

```python
import rivretrieve as rr

rr.download("pl_imgw")  # once: downloads and compiles IMGW's yearly files

selection = rr.find(provider="pl_imgw", product="discharge_daily_mean")
selection = rr.pick(selection, station="152140120")
result = rr.fetch(selection, start="2020-01-01", end="2020-12-31")
```

## Who measures, and who publishes

IMGW-PIB is Poland's national hydrological and meteorological service. It runs the national
measurement network and publishes its data on its public data portal,
[danepubliczne.imgw.pl](https://danepubliczne.imgw.pl/), as yearly files of daily values for all
stations at once. RivRetrieve reads those files.

## Downloading the archive first

Poland is a bulk provider. Because RivRetrieve does not redistribute any data and IMGW publishes whole years for every station in one file,
RivRetrieve downloads the files locally once and reads them from your disk:

```python
rr.download("pl_imgw")
```

The download happens only when you ask for it. Until then, retrieval returns an empty result and
an issue saying the store is missing; `rr.cache_status("pl_imgw")` tells you whether it is there. 

## What you can retrieve

| Product | IMGW column | Unit published | Unit delivered | Stations listed |
|---|---|---|---|---:|
| `discharge_daily_mean` | Flow [m^3/s] | m³/s | m³/s | 1,301 |
| `stage_daily_mean` | Water level [cm] | cm | m | 1,301 |
| `water_temperature_daily_mean` | Water temperature [deg. C] | °C | °C | 1,301 |

Availability is `unknown` for every station and product because IMGW does
not state which variables each station measures.

## Station coordinates

The coordinates in the catalogue come from the Global Runoff Data Centre (GRDC), which supplied
metadata for the same 1,301 stations, not from IMGW. The catalogue records the coordinate reference system as `unknown`, because
the source does not state one.

## Data status

IMGW's regulations note that some data may not have been verified:

> Część udostępnianych danych może stanowić dane niezweryfikowane, gdy IMGW-PIB dysponuje danymi
> jedynie w takiej postaci na chwilę ich udostępnienia.

In English, unofficially: some of the data made available may be unverified, where IMGW-PIB holds
the data only in that form at the time they are made available.

## Time

Values come back with `time_zone` `unknown`. IMGW's files give dates, not a time zone, and do not
state the clock that bounds each day.

## Terms and citation

IMGW-PIB's [regulations](https://danepubliczne.imgw.pl/regulations) make use free of charge,
subject to exceptions, and set a condition:

> Udostępnienie i korzystanie z danych następuje pod warunkiem wskazania źródła pochodzenia danych,
> poprzez umieszczenie przez korzystającego na wszelkiego rodzaju pracach lub produktach,
> opracowanych z użyciem danych IMGW-PIB informacji: „Źródłem pochodzenia danych jest Instytut
> Meteorologii i Gospodarki Wodnej – Państwowy Instytut Badawczy".

In English, unofficially: access and use are conditional on stating the source, by placing on any
work or product made with IMGW-PIB data the statement "The source of the data is the Institute of
Meteorology and Water Management – National Research Institute".

Where the data have been processed, the regulations ask for a second statement as well:

> „Dane Instytutu Meteorologii i Gospodarki Wodnej – Państwowego Instytutu Badawczego zostały
> przetworzone".

In English, unofficially: "The data of the Institute of Meteorology and Water Management – National
Research Institute have been processed". 

The regulations also state that free access does not cover use for business activity or for a set
of listed purposes, unless the data are high-value datasets:

> Nieodpłatnym dostępem nie są objęte przypadki udostępniania danych do celów, o których mowa w
> ust. 2, chyba że są to dane o wysokiej wartości.

They warn that missing attribution can lead to liability, including under Polish copyright law.
Read [the regulations](https://danepubliczne.imgw.pl/regulations) in full before commercial use.

## Sources

| Page | Retrieved |
|---|---|
| [IMGW public data portal](https://danepubliczne.imgw.pl/) | 2026-09-19 |
| [Regulamin Udostępniania Danych IMGW-PIB](https://danepubliczne.imgw.pl/regulations) | 2026-09-19 |

Station counts come from the packaged catalogue. The provenance of the station positions is
recorded in the provider's catalogue evidence.
