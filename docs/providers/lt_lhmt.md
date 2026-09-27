# Lithuania: LHMT

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `lt_lhmt` |
| Country | Lithuania |
| Published by | Lietuvos hidrometeorologijos tarnyba (LHMT), the Lithuanian Hydrometeorological Service under the Ministry of Environment |
| Read from | Meteo.lt API (`api.meteo.lt`) |
| Quantities | Daily mean discharge and stage |
| Stations in the catalogue | 97. Availability depends on quantity and period |
| Credentials | None |
| Licence stated by LHMT | Creative Commons Attribution-ShareAlike 4.0 (CC BY-SA 4.0), unless stated otherwise |
| Agency documentation | [Meteo.lt API](https://api.meteo.lt/) |

Retrieve one week of published daily mean discharge at station `nemajunu-vms`,
Nemajūnai on the Nemunas:

```python
import rivretrieve as rr

selection = rr.find(
    provider="lt_lhmt",
    station="nemajunu-vms",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)

result = rr.fetch(selection, start="2020-01-01", end="2020-01-07", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print(result.issues)
```

Output:

```text
time,time_zone,value,unit
2020-01-01T00:00:00.000000,+00:00,192.0,m3/s
2020-01-02T00:00:00.000000,+00:00,189.0,m3/s
2020-01-03T00:00:00.000000,+00:00,203.0,m3/s
7
()
```

The request returned seven daily means in m³/s, one for each date from January 1
to 7, and no retrieval issues (the empty tuple `()`). The preview shows the first
three. RivRetrieve reads the means LHMT publishes; it does not calculate them from
more frequent observations. An empty issue tuple does not establish the quality of
the values.

`cache="bypass"` requests the Meteo.lt API rather than a local cache. This output
was checked on 2026-09-27. Run the examples in order in the same Python session.
See [Usage](../usage.md) for general selection and result handling.

## Who measures, and who publishes

LHMT both measures and publishes these data. Its
[hydrology page](https://www.meteo.lt/klimatas/hidrologija/) describes Lithuania's
hydrological observations as carried out by a network of water measuring stations
(vandens matavimo stotis, abbreviated VMS) covering the whole country: currently
101 stations measuring water level, water temperature, air temperature,
precipitation and discharge.

The Meteo.lt API publishes data measured at LHMT's hydrological and meteorological
stations. RivRetrieve reads the API's historical hydrological observations. The
API's hydrological station list, which the packaged catalogue follows, contained
97 stations on 2026-09-27. The API does not explain the difference from the 101
stations in the network description.

Station identifiers are the API's own codes, which are words rather than numbers,
for example `nemajunu-vms`.

## What you can retrieve

| Quantity filter | API field | Published statistic | Source unit | Returned unit |
|---|---|---|---|---|
| `discharge` | `waterDischarge` | Daily mean | m³/s | m³/s |
| `stage` | `waterLevel` | Daily mean | cm | m |

The API documents both fields as daily means ("Vidurkis per parą"). RivRetrieve
converts stage from centimetres to metres; discharge needs no conversion. Stage is
water level; RivRetrieve has not established its vertical reference or datum.

```python
stage = rr.find(
    provider="lt_lhmt",
    station="nemajunu-vms",
    quantity="stage",
    frequency="daily",
    statistic="mean",
)

stage_result = rr.fetch(stage, start="2020-01-01", end="2020-01-07", cache="bypass")

preview = stage_result.data.select("time", "value", "source_unit", "unit").head(3)
print(preview.write_csv(), end="")
```

Output:

```text
time,value,source_unit,unit
2020-01-01T00:00:00.000000,0.45,cm,m
2020-01-02T00:00:00.000000,0.45,cm,m
2020-01-03T00:00:00.000000,0.51,cm,m
```

The API published 45, 45 and 51 cm for these dates; `source_unit` keeps the
published unit, and `value` is in metres.

The catalogue lists both quantities at every station, because the station list does
not say which quantities each station publishes. A station being listed does not
guarantee data for every quantity or requested period. Some stations publish stage
with discharge left empty; RivRetrieve returns those days as rows with `value=null`.
On 2026-09-27, five coastal and lagoon stations, such as `juodkrantes-vms`,
reported no historical observations at all.

## How far back, and how recent

The API documentation states:

> Istoriniai hidrologinių stebėjimų duomenys teikiami nuo 2000 metų.

> Duomenys už praėjusius metus pradedami teikti nuo einamųjų metų vidurio.

In English, unofficially: historical hydrological observations are provided from
2000; data for the previous year start to be provided from the middle of the
current year.

Records start later than 2000 at many stations. On 2026-09-27, no station's
historical record extended beyond December 31, 2024. Values from January 2025
were therefore still unpublished about 20 months later. Treat the stated timing
as the API's description, not a guarantee.

A request for a period that has not been published returns no rows and a
`source.http_not_found` warning, which reports that the API had no data for that
month. It is not a network failure. Check [issues](../usage.md#issues) before
interpreting an empty result.

The API also has a separate *measured* feed that RivRetrieve does not read. It
holds stage and water temperature for the last 30 days, with UTC timestamps, and
no discharge. The historical feed that RivRetrieve reads has no water temperature.

## Time and data status

The API labels each daily mean with a date that it describes as UTC
(`observationDateUtc`). RivRetrieve returns that date at midnight in `time`,
paired with `time_zone="+00:00"`. The API does not say when the averaging day
starts and ends, so RivRetrieve leaves the day definition unknown. Do not assume
the mean covers midnight to midnight UTC.

The historical feed carries no quality or approval flags. LHMT provides the data
as they are, without warranty of their quality or fitness for a particular
purpose. RivRetrieve makes no quality judgement of its own.

A published null remains a row with `value=null`. A date without a published
observation supplies no row. A failed request remains an issue, reported alongside
any successful records.

## Rate limits

The API limits each IP address:

> Užklausų kiekis iš vieno IP adreso ribojamas iki 180 užklausų per minutę. Prašome negeneruoti
> daugiau kaip 20.000 užklausų per vieną parą iš vieno IP adreso, nes viršijus nurodytą limitą
> Jūsų IP adresas gali būti užblokuotas be įspėjimo.

In English, unofficially: requests are limited to 180 per minute per IP address;
please do not generate more than 20,000 requests a day from one IP address, as
exceeding the limit may block the address without warning.

RivRetrieve sends one request per station, quantity and calendar month. It also
requests the neighbouring month when the selected period starts on the first or
second day of a month, or ends on one of its last two days. If that extra month is
unpublished, the request is not reported as an issue. Twenty years of both quantities at one station take
about 480 requests, so many stations add up quickly.

## Terms and citation

LHMT's data-use conditions, on the [API page](https://api.meteo.lt/), state that
the data are publicly available and free for public use, distribution and further
processing, on conditions including:

> 1) duomenys, jeigu nenustatyta kitaip, teikiami pagal Creative Commons Attribution-ShareAlike
> 4.0 (CC BY-SA 4.0) tarptautinę duomenų naudojimo licenciją, būtina susipažinti su licencijos
> sąlygomis;

> 5) publikuojant, pakartotinai atkartojant ar kitaip naudojant duomenis, būtina nurodyti, kad
> duomenų šaltinis yra Tarnyba.

In English, unofficially: unless stated otherwise, the data are provided under the
CC BY-SA 4.0 international licence, whose conditions users must read; and when
publishing, reproducing or otherwise using the data, LHMT must be stated as the
source.

The conditions add that access may be withdrawn if the source is not stated, and
that the data may be used only for lawful and defined purposes. The
[CC BY-SA 4.0 licence](https://creativecommons.org/licenses/by-sa/4.0/) also
requires adaptations to be shared under the same licence.

LHMT gives no formatted citation. Name LHMT and the Meteo.lt API as the source, and
retain the station, quantity, requested period and access date to make the
retrieved record traceable. This is practical guidance, not an LHMT citation
template.

## Sources

Publisher pages checked on 2026-09-27:

- [Meteo.lt API documentation and data-use conditions](https://api.meteo.lt/): fields, units, daily means, UTC labels, historical coverage, publication timing, the measured feed, rate limits and terms.
- [LHMT hydrology](https://www.meteo.lt/klimatas/hidrologija/): the national water measuring station network.
- [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/): the licence's share-alike condition.

The station count describes the packaged catalogue. The examples were retrieved
live on 2026-09-27. The [verification record](../verification/lithuania-provider/README.md)
retains commands, source checks, exact output and the limits of these checks.
