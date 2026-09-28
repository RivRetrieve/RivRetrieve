# Czechia: CHMI

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `cz_chmi` |
| Country | Czechia |
| Published by | Český hydrometeorologický ústav (ČHMÚ), the Czech Hydrometeorological Institute (CHMI) |
| Read from | CHMI open data, historical hydrology files (`opendata.chmi.cz`) |
| Quantities | Daily mean discharge, stage and water temperature; hourly mean discharge and stage |
| Stations in the catalogue | 831. Availability depends on quantity and period |
| Credentials | None |
| Licence stated by CHMI | Creative Commons Attribution 4.0 (CC BY 4.0) |
| Agency documentation | [CHMI open data, hydrology](https://opendata.chmi.cz/hydrology/), [dataset descriptions](https://opendata.chmi.cz/hydrology/read_me/) |

RivRetrieve reads CHMI's historical daily and hourly files. Retrieve one week of
published daily mean discharge at station `0-203-1-180100`, VD České Údolí on the
Radbuza:

```python
import rivretrieve as rr

selection = rr.find(
    provider="cz_chmi",
    station="0-203-1-180100",
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
2020-01-01T00:00:00.000000,+00:00,1.7,m3/s
2020-01-02T00:00:00.000000,+00:00,1.54,m3/s
2020-01-03T00:00:00.000000,+00:00,1.5,m3/s
7
()
```

The request returned seven daily means in m³/s, one for each date from January 1
to 7. The preview shows the first three. The empty tuple `()` means that retrieval
reported no issues; it does not establish the quality of the values. RivRetrieve
reads the means CHMI publishes rather than calculating them from more frequent
observations.

`cache="bypass"` requests CHMI rather than a local cache. This output was checked
live on 2026-09-28. Published values can change, so a later retrieval need not
reproduce it exactly. See [Usage](../usage.md) for general selection and result
handling.

## Who measures, and who publishes

CHMI [establishes and operates state monitoring networks](https://www.chmi.cz/o-chmu)
for the atmosphere and hydrosphere and processes their measurements. It publishes
data from the national hydrometeorological database through its
[open-data service](https://www.chmi.cz/o-chmu/produkty-a-sluzby/data-a-vyhodnoceni).
This institutional role does not identify the operator of every station in the
published catalogue.

The historical hydrology service publishes one file per station and calendar
year for each group of quantities. Station identifiers are CHMI's WIGOS
identifiers, for example `0-203-1-180100`.

## What you can retrieve

| Quantity filter | CHMI code | Published statistic | Source unit | Returned unit |
|---|---|---|---|---|
| `discharge` | QD | Daily mean | m³/s | m³/s |
| `stage` | HD | Daily mean | cm | m |
| `temperature` | TD | Daily mean | °C | °C |
| `discharge` | QH | Hourly mean | m³/s | m³/s |
| `stage` | HH | Hourly mean | cm | m |

Select `frequency="daily"` or `frequency="hourly"`, with `statistic="mean"`.
CHMI's [dataset description](https://opendata.chmi.cz/hydrology/read_me/Popis_datovych_sad_historical.pdf)
defines these as mean daily values (*průměrné denní hodnoty*) and mean hourly
values (*průměrné hodinové hodnoty*). RivRetrieve converts stage from centimetres
to metres. Discharge and water temperature need no unit conversion. Stage is
water level; RivRetrieve has not established its vertical reference or datum.

The catalogue lists all five series at each station because the station metadata
does not state which of these quantities are available. A station being listed
does not guarantee data for every quantity or requested period.

## How far back, and how recent

Availability depends on the annual files CHMI has published for a station and on
the series within those files. RivRetrieve reads only the `historical` service,
so requests cannot provide observations more recent than its published records.
There is no fixed latest year imposed by RivRetrieve.

CHMI also publishes current observations in its `recent` and `now` folders and
other historical datasets. RivRetrieve does not read those through this provider.
The quantities in the table above describe what is available through RivRetrieve,
not the full range of CHMI publications.

## Time and data status

CHMI's historical observation timestamps carry a UTC `Z` suffix. RivRetrieve
returns their wall-clock labels in `time`, paired with `time_zone="+00:00"`.
Daily values have midnight labels. The boundaries of the averaging day are
unknown, so do not assume a daily mean covers midnight to midnight UTC. Hourly
values are published means, but whether their labels mark the start or end of
the averaging hour is also unknown.

The historical records read here carry timestamps and values without
observation-level quality or approval flags. Being in the historical service
does not by itself establish a value's validation status. RivRetrieve makes no
quality judgement of its own.

A published null remains a row with `value=null`. A date without a published
observation supplies no row. A failed request remains an issue alongside any
successful records. Check [issues](../usage.md#issues) before interpreting an
empty result.

## Terms and citation

CHMI's [open-data page](https://www.chmi.cz/o-chmu/produkty-a-sluzby/data-a-vyhodnoceni)
states that its open data can be used free of charge under Creative Commons
[BY 4.0](https://creativecommons.org/licenses/by/4.0/). Retrieval requires no
personal credentials.

Its [disclaimer and conditions of use](https://www.chmi.cz/vylou%C4%8Den%C3%AD-odpov%C4%9Bdnosti)
state:

> Produkty Českého hydrometeorologického ústavu dostupné na těchto webových stránkách podléhají
> licenci Creative Commons 4.0 CC-BY. Dílo smíte sdílet a upravovat za podmínky uvedení původu
> (zdroje ČHMÚ).

In English, unofficially: CHMI's products available on these websites are licensed
under Creative Commons 4.0 CC BY; you may share and adapt the work on condition
that you credit the origin (the source, ČHMÚ).

No formatted data citation was identified in these terms. Credit ČHMÚ and retain
the station, quantity, requested period and access date to make the retrieved
record traceable. This is practical guidance, not a CHMI citation template.

## Sources

Publisher pages checked on 2026-09-28:

- [About CHMI](https://www.chmi.cz/o-chmu): institutional responsibilities.
- [Data and evaluation](https://www.chmi.cz/o-chmu/produkty-a-sluzby/data-a-vyhodnoceni): the national database, open-data access and licence.
- [CHMI open data, hydrology](https://opendata.chmi.cz/hydrology/): historical and current publication routes.
- [Historical dataset description](https://opendata.chmi.cz/hydrology/read_me/Popis_datovych_sad_historical.pdf): annual files and published statistics.
- [Historical code description](https://opendata.chmi.cz/hydrology/read_me/Popis_kodu_historical.pdf): WIGOS identifiers.
- [Series dictionary](https://opendata.chmi.cz/hydrology/historical/metadata/meta2.json): quantity codes, statistics and source units.
- [Disclaimer and conditions of use](https://www.chmi.cz/vylou%C4%8Den%C3%AD-odpov%C4%9Bdnosti): attribution.

The station count describes the packaged catalogue. The example was retrieved
live on 2026-09-28. The [verification record](../verification/czech-provider/README.md)
retains commands, source checks, exact output and limitations.
