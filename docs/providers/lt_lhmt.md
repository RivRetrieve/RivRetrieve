# Lithuania — LHMT

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `lt_lhmt` |
| Country | Lithuania |
| Published by | Lietuvos hidrometeorologijos tarnyba (LHMT), the Lithuanian Hydrometeorological Service |
| Read from | Meteo.lt API (`api.meteo.lt`) |
| Variables | Discharge, stage |
| Stations in the catalogue | 97 |
| Credentials | None |
| Licence stated by LHMT | Creative Commons Attribution-ShareAlike 4.0 (CC BY-SA 4.0), unless stated otherwise |
| Agency documentation | [Meteo.lt API](https://api.meteo.lt/) |

```python
import rivretrieve as rr

selection = rr.find(provider="lt_lhmt", product="discharge_daily_mean")
selection = rr.pick(selection, station="nemajunu-vms")
result = rr.fetch(selection, start="2020-01-01", end="2020-12-31")
```

## Who measures, and who publishes

LHMT, the Lithuanian Hydrometeorological Service under the Ministry of Environment, runs the
national hydrological network and publishes its data through the Meteo.lt API. RivRetrieve reads
the API's historical hydrological observations, one station and month at a time.

Station identifiers are the API's own codes, which are words rather than numbers, for example
`nemajunu-vms`.

## What you can retrieve

| Product | API field | Unit published | Unit delivered | Stations listed |
|---|---|---|---|---:|
| `discharge_daily_mean` | `waterDischarge` | m³/s | m³/s | 97 |
| `stage_daily_mean` | `waterLevel` | cm | m | 97 |

The API documents both as daily means ("Vidurkis per parą").

Availability is `unknown` for every station and product, since the
station list does not state which variables each station serves.

## How far back, and how recent

The API documentation states:

> Istoriniai hidrologinių stebėjimų duomenys teikiami nuo 2000 metų.

> Duomenys už praėjusius metus pradedami teikti nuo einamųjų metų vidurio.

In English, unofficially: historical hydrological observations are provided from 2000; data for
the previous year start being provided from the middle of the current year.

So the daily record runs from 2000, and last year's values appear during the current year.

The API also has a separate *measured* feed that RivRetrieve does not read: hourly readings of
stage and water temperature, with UTC timestamps, kept for the last 30 days only. It carries no
discharge, while the historical feed carries no water temperature.

## Time

Values come back with `time_zone` `+00:00`. The API states that its observation dates are in UTC,
and RivRetrieve keeps that, including for daily means.

## Rate limits

The API limits each IP address:

> Užklausų kiekis iš vieno IP adreso ribojamas iki 180 užklausų per minutę. Prašome negeneruoti
> daugiau kaip 20.000 užklausų per vieną parą iš vieno IP adreso, nes viršijus nurodytą limitą
> Jūsų IP adresas gali būti užblokuotas be įspėjimo.

In English, unofficially: requests are limited to 180 per minute per IP address; please do not
generate more than 20,000 requests a day from one IP address, as exceeding it may block the address
without warning. RivRetrieve requests one station-month per call, so a long record for many
stations adds up quickly.

## Terms and citation

LHMT's data-use conditions, on the [API page](https://api.meteo.lt/), state that the data are
publicly available and free for public use, distribution and further processing, on conditions
including:

> 1) duomenys, jeigu nenustatyta kitaip, teikiami pagal Creative Commons Attribution-ShareAlike
> 4.0 (CC BY-SA 4.0) tarptautinę duomenų naudojimo licenciją, būtina susipažinti su licencijos
> sąlygomis;

> 5) publikuojant, pakartotinai atkartojant ar kitaip naudojant duomenis, būtina nurodyti, kad
> duomenų šaltinis yra Tarnyba.

In English, unofficially: unless stated otherwise, the data are provided under the CC BY-SA 4.0
international licence, whose conditions users must read; and when publishing, reproducing or
otherwise using the data, the Service must be stated as the source.

The conditions add that access may be withdrawn if the source is not stated. LHMT publishes no
formatted citation.

## Sources

| Page | Retrieved |
|---|---|
| [Meteo.lt API documentation and data-use conditions](https://api.meteo.lt/) | 2026-09-19 |

Station counts come from the packaged catalogue.
