# Poland: IMGW-PIB

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `pl_imgw` |
| Country | Poland |
| Published by | Instytut Meteorologii i Gospodarki Wodnej – Państwowy Instytut Badawczy (IMGW-PIB), the Institute of Meteorology and Water Management – National Research Institute |
| Quantities | Daily discharge, stage and water temperature |
| Stations in the catalogue | 1,301. Availability depends on quantity and period |
| Credentials | None |
| Access | Explicit download of IMGW-PIB's national daily archive, then local retrieval |
| Terms | IMGW-PIB's data regulations: conditional free use, an agreement for business and other listed uses, and prescribed attribution; see [Terms and citation](#terms-and-citation) |
| Agency documentation | [IMGW-PIB public data](https://danepubliczne.imgw.pl/), [Regulamin (data regulations)](https://danepubliczne.imgw.pl/regulations), [daily hydrological data](https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/) |

First prepare the national archive. This downloads IMGW-PIB's daily files for every
station and every published year, then compiles them into a local store. Allow time
and disk space for that operation; see [Downloading the archive](#downloading-the-archive).

```python
import rivretrieve as rr

rr.download("pl_imgw")
```

Then retrieve one week of daily discharge on the Odra at Gozdowice, station `152140020`:

```python
selection = rr.find(provider="pl_imgw", station="152140020", quantity="discharge")

result = rr.fetch(selection, start="2024-01-01", end="2024-01-07")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print([(issue.severity, issue.code) for issue in result.issues])
```

Output:

```text
time,time_zone,value,unit
2024-01-01T00:00:00.000000,unknown,999.0,m3/s
2024-01-02T00:00:00.000000,unknown,1010.0,m3/s
2024-01-03T00:00:00.000000,unknown,1020.0,m3/s
7
[('info', 'provenance.license_not_established'), ('info', 'provenance.citation_not_established')]
```

The request returned seven daily values in m³/s, one for each date. Both endpoint
dates are included. The dates carry `time_zone="unknown"`; see
[Time and data status](#time-and-data-status). The value `999.0` on January 1 is a
published discharge, not a missing-data code.

The two informational issues say that RivRetrieve does not record a single licence
or citation for this provider. They are not retrieval problems, and they do not mean
that IMGW-PIB sets no conditions; see [Terms and citation](#terms-and-citation).

Retrieval reads the local store and makes no request to IMGW-PIB. This output was
checked on 2026-09-27 using the archive IMGW-PIB published on that date, whose latest
year ends on October 31, 2025. IMGW-PIB revises and withdraws historical values, so a
later download may return different values. Run the snippets in order in the same
Python session. See [Usage](../usage.md) for general selection and result handling.

## Who measures, and who publishes

IMGW-PIB runs the hydrological measurement and observation network of Poland's
state hydrological and meteorological service (państwowa służba
hydrologiczno-meteorologiczna, PSHM). Its 2025 hydrological yearbook reports 952
hydrological stations operating in that year. IMGW-PIB processes their measurements
and observations and stores them in its Central Historical Database (Centralna Baza
Danych Historycznych).

IMGW-PIB publishes daily hydrological data on its public data portal,
[danepubliczne.imgw.pl](https://danepubliczne.imgw.pl/), as archive files covering
every station at once. The files are organised by hydrological year, which runs from
November to October. RivRetrieve reads these daily files (`codz`). It does not read
IMGW-PIB's current operational data or its yearbooks.

According to IMGW-PIB's regulations, the data are owned by the State Treasury
(Skarb Państwa) and IMGW-PIB manages and makes them available.

## Downloading the archive

`rr.download("pl_imgw")` explicitly downloads and compiles the complete daily archive.
It first reads IMGW-PIB's directory listing of daily data, then downloads every daily
file listed from hydrological year 1951 to the latest year IMGW-PIB has published.
RivRetrieve never starts this transfer during `fetch`. Without a compiled store,
retrieval returns an empty result with a `bulk.store_missing` warning and an
instruction to run `download`.

On 2026-09-27 IMGW-PIB listed one file per month up to hydrological year 2022 and one
file per year from 2023 to 2025, so the download consisted of 867 files totalling
about 122 MB. The compiled store occupied about 223 MB. The whole operation took about
85 minutes on the verification machine: about 18 minutes to transfer the files and the
rest to compile and check the store. During compilation the cache location briefly
held at least 9 GB of working files. Size and duration vary with the archive, the
network and the computer. RivRetrieve refuses to start unless 6 GB are free at the
cache location, but that check does not cover the working space: allow at least 9 GB.

IMGW-PIB's notice in the daily-data folder (`UWAGA.txt`) says that the single annual
files are a temporary arrangement and that it will regenerate them in the earlier
form. RivRetrieve accepts either form for a year. It stops, rather than choosing, if
a year is listed in both forms or if the listed years leave a gap.

A failed download leaves any existing store unchanged. RivRetrieve retries an
interrupted file transfer up to three attempts in total. If a file still fails, the
download stops and removes the files it has downloaded.

Choose a cache location with `RIVRETRIEVE_CACHE_DIR` before preparing the archive;
see [cache configuration](../usage.md#cache-and-bulk-downloads).

IMGW-PIB adds each hydrological year some months after it ends. Its change list
(`lista_zmian_hydro.txt`) records hydrological year 2025 as added on 2026-08-31.
The archive downloaded on 2026-09-27 therefore ends on October 31, 2025, rather
than containing recent days. This archive end date does not establish the latest
observation at each station.

The same compiled copy serves later requests for other stations and periods. Both
`cache="bypass"` and `cache="reuse"` read it locally. `cache="refresh"` is refused:
run `rr.download("pl_imgw")` again to replace the store with the files IMGW-PIB
publishes at that time. Retrieval does not check for newer files.

## What you can retrieve

IMGW-PIB's field description (`CODZ_publiczne_format.txt`) names each field:

| Quantity filter | Frequency | Statistic | IMGW-PIB field | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | Daily | Unknown | `COPRZP`: Przepływ [m^3/s] (discharge) | m³/s | m³/s |
| `stage` | Daily | Unknown | `COSTAN`: Stan wody [cm] (water level) | cm | m |
| `temperature` | Daily | Unknown | `COPTMP`: Temperatura wody [st. C] (water temperature) | °C | °C |

RivRetrieve converts stage from centimetres to metres. Stage is water level, not
water depth or an elevation above sea level. RivRetrieve has not established its
vertical reference.

Each value is a daily value, and `frequency="daily"` matches all three quantities.
IMGW-PIB does not state one statistic for the whole archive. Its 2025 yearbook
describes daily water levels and discharges at automatic stations as means of
10-minute values, but uses the 06:00 UTC reading at stations where only an observer
measures, and daily water temperatures from 06:00 UTC measurements. The yearbook
covers selected stations in 2025, and RivRetrieve has not established which method
applies to each station and year in the archive. The statistic therefore remains
unknown, and `statistic="mean"` does not match these series.

Every catalogue station lists all three quantities. IMGW-PIB does not state which
quantities each station measures, so availability is unknown for every station and
quantity. A station being listed does not guarantee data for any quantity or
requested period. Far fewer stations measure water temperature than water level: for
2025, the yearbook reports daily water levels from 916 stations in IMGW-PIB's
database, discharges from 714 and water temperatures from 93.

IMGW-PIB uses empty fields and the codes below to indicate missing observations.
Its field description says that since 2024 missing observations are always empty
(`NULL`). RivRetrieve follows these explicit source definitions: it returns a
missing value rather than treating a missing-data code as a measurement. It does
not decide that an unusual measurement is missing or unreliable.

A source record with a missing observation remains a row with a missing value.
A date with no source record returns no row. Request and local-store failures are
reported separately as [issues](../usage.md#issues).

| Quantity | Code | Meaning stated by IMGW-PIB |
|---|---|---|
| Stage | `9999` | Brak danych w bazie (no data in the database) |
| Discharge | `99999.999` | Przepływ w tym dniu nie był opracowywany (discharge was not computed for that day) |
| Water temperature | `99.9` | Brak danych w bazie (no data in the database), for example because temperature is not measured at the station |

These are unofficial English translations. Other values, including `999`, are returned
as published.

## Station coordinates

IMGW-PIB's station list contains the 1,301 station identifiers, names and rivers, but
no coordinates. The station coordinates used by RivRetrieve were supplied by the
Global Runoff Data Centre (GRDC).
The coordinate reference system is recorded as `unknown` because it has not been
established. [Maps](../usage.md#maps) display such positions as if they used
EPSG:4326, which does not establish their reference system.

## Time and data status

The daily files give dates, not times or a time zone. RivRetrieve returns each date at
midnight with `time_zone="unknown"`. Read `time` and `time_zone` together. The
midnight label does not make the values UTC or Polish local time, and it does not
establish the interval a daily value represents. `rr.to_utc` refuses these rows.

IMGW-PIB's regulations warn that some data may be unverified:

> Część udostępnianych danych może stanowić dane niezweryfikowane, gdy IMGW-PIB
> dysponuje danymi jedynie w takiej postaci na chwilę ich udostępnienia.

Unofficial translation: Some of the data made available may be unverified data, where
IMGW-PIB holds the data only in that form at the time they are made available.

The daily files contain no quality flag, and RivRetrieve does not add a quality
judgement. A returned value does not establish that IMGW-PIB has verified it.

IMGW-PIB revises published files. Its change list (`lista_zmian_hydro.txt`) records
corrected values, and in 2026 it withdrew uncertain 1997 discharges and water levels
at several stations. The yearbook states that IMGW-PIB updates archived discharges when
the stage-discharge relationship at a gauge changes. A later download of the same
period may therefore contain different values.

## Terms and citation

IMGW-PIB's [Regulamin Udostępniania Danych](https://danepubliczne.imgw.pl/regulations)
(data regulations) set the conditions for using its data. IMGW-PIB publishes them in
Polish, and the English view of its portal shows the same Polish text. The
translations below are unofficial. Read the full
regulations before use, particularly for commercial, professional or planning work.
RivRetrieve does not decide which conditions apply to a particular use.

The regulations state that, subject to exceptions in generally applicable law and in
the regulations themselves, use of the data is free of charge („korzystanie z danych
jest nieodpłatne”). They allow free use for private purposes, and for any purpose
where the data are high-value datasets:

> Korzystający może używać nieodpłatnie udostępnionych danych do celów prywatnych,
> a w przypadku danych o wysokiej wartości w każdym celu.

Unofficial translation: The user may use data made available free of charge for
private purposes and, in the case of high-value data, for any purpose.

They define a private purpose as private, non-profit use, including master's and
doctoral theses. High-value data are defined by reference to EU Implementing
Regulation 2023/138. RivRetrieve has not established whether these daily archives are
high-value data.

Free access does not cover business activity or the other purposes listed in § 3 of
the regulations, unless the data are high-value data. Those uses require an agreement
with IMGW-PIB that sets the costs the user bears. The listed purposes include
hydrological and meteorological support for maritime and inland shipping, fisheries
and agriculture, and studies of hydrological and morphological elements of surface
waters for water-management planning. Separately, public authorities, water owners and managers,
universities, research institutes and certain other scientific bodies have free access
for their statutory tasks, research or teaching, as § 4 describes.

Use is conditional on stating the source on any work or product made with IMGW-PIB
data:

> Udostępnienie i korzystanie z danych następuje pod warunkiem wskazania źródła
> pochodzenia danych, poprzez umieszczenie przez korzystającego na wszelkiego rodzaju
> pracach lub produktach, opracowanych z użyciem danych IMGW-PIB informacji:
> „Źródłem pochodzenia danych jest Instytut Meteorologii i Gospodarki Wodnej –
> Państwowy Instytut Badawczy”.

Unofficial translation: Access to and use of the data are conditional on indicating
the source of the data, by the user placing on works or products of any kind prepared
using IMGW-PIB data the statement: "The source of the data is the Institute of
Meteorology and Water Management – National Research Institute".

Where the user has processed the data, the regulations require a second statement:

> „Dane Instytutu Meteorologii i Gospodarki Wodnej – Państwowego Instytutu
> Badawczego zostały przetworzone”.

Unofficial translation: "The data of the Institute of Meteorology and Water
Management – National Research Institute have been processed".

The prescribed statements are the Polish texts. RivRetrieve's output already differs
from the published files: stage is converted to metres, and the records are returned
as rows rather than as IMGW-PIB's files. The regulations do not define processing, and
RivRetrieve does not decide whether a particular use counts as processed data.

The regulations state that omitting these statements can lead to liability, including
criminal liability. They also describe using data made available free of charge for
the purposes listed in § 3 as fraud within the meaning of Article 286 of the Polish
Criminal Code. IMGW-PIB accepts no liability for damage arising from use of the data,
which is at the user's own risk.

Identify the station, quantity, requested period and download date of the archive
alongside the prescribed statements to make the retrieved record traceable. This is
practical guidance, not an IMGW-PIB citation template.

## Sources

| Source | Checked |
|---|---|
| [Regulamin Udostępniania Danych IMGW-PIB](https://danepubliczne.imgw.pl/regulations): owner and manager of the data, conditions of use, attribution, unverified data | 2026-09-27 |
| [Daily hydrological data](https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/): [field description](https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/CODZ_publiczne_format.txt), [notice](https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/UWAGA.txt), archive files | 2026-09-27 |
| [Station list](https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/lista_stacji_hydro.csv) and [change list](https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/lista_zmian_hydro.txt) | 2026-09-27 |
| [Rocznik Hydrologiczny 2025](https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/Roczniki/Rocznik%20hydrologiczny/Rocznik%20Hydrologiczny%202025.pdf) (hydrological yearbook), pp. 5 and 7–9: network, database and daily-value methods | 2026-09-27 |
| [IMGW-PIB: O Instytucie](https://imgw.pl/strona-glowna/o-instytucie/) (about the institute) | 2026-09-25 |

The station count describes the packaged catalogue. A fresh national download and the
examples on this page were run on 2026-09-27. They verify one station, three quantities
and one week, not continuous history or national coverage. The
[verification record](../verification/poland-provider/index.md) retains the commands,
source checks, exact output and the limits of these checks.
