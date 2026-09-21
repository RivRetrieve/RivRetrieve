# BAFU Official Data API — Observations for a Swiss Route

Status: research note. Nothing here is implemented. Probed live on 2026-09-21.

`ch_foen` reads BAFU hydrology through Existenz.ch (see [ch_foen.md](ch_foen.md)). BAFU now
publishes the same network itself, through a GraphQL API on its data platform. This note records
what that API returned, so a decision about the Swiss route can rest on observed facts.

The prompt was the `CH_BAFU` adapter in the R package hydrodownloadR
([adapter_CH_BAFU.R](https://github.com/bafg-bund/hydrodownloadR/blob/main/R/adapter_CH_BAFU.R)),
which reads `data_1day_mean` from this API.

## Endpoint

`POST https://data.bafu.admin.ch/api`, GraphQL, anonymous, `Content-Type: application/json`.
Documentation: [Hydrologische Beobachtungen](https://data.bafu.admin.ch/dataproduct-water-observations).

Query root: `water { observations { … } }`. Fields found by schema introspection:

| Field | Content |
|---|---|
| `stations` | Station metadata: `no`, `name`, `siteName`, `riverName`, `catchmentName`, `latitude`, `longitude`, `elevation`, `status` |
| `data_10min_mean`, `data_1hour_mean` | Sub-daily means |
| `data_1day_mean`, `data_1day_min`, `data_1day_max` | Daily statistics |
| `data_1month_mean`, `data_1month_min`, `data_1month_max` | Monthly statistics |
| `data_1year_mean`, `data_1year_min`, `data_1year_max` | Yearly statistics |
| `data_live` | Near-real-time feed |

Parameters, by `parameterName`: `Q` discharge, `W` stage, `WT` water temperature. Each data row
carries `timestamp` (UTC), `value`, `releaseState` and `station { no }`; the documentation's example
also requests `unitSymbol`.

The documentation states, for the aggregated fields:

- results come in no particular order;
- one query returns at most 10 000 rows, and a query over that limit is rejected rather than
  truncated, so long series are read in timestamp windows;
- the resolver requires a station filter or a timestamp filter;
- filter operators follow the Hasura convention (`_eq`, `_in`, `_gte`, `_lt`, …).

For `data_live` it states a 5–10 minute update, a 7-day window, no rows older than 12 hours, and
no embedded `station` object. The live resolver takes `stationNo`, not `station { no }`.

The same page offers the complete series as prepared monthly `.csv.gz` files, by year and
aggregation. Those were not probed.

hydrodownloadR's comments state a limit of 500 requests per rolling 5 minutes. That figure was not
found in BAFU's documentation during this probe.

## Stations

`stations(limit: 10000)` returned 1 341 stations. The packaged `ch_foen` catalogue has 246.
Station numbers look shared between the two (2018, 2016 and 2091 exist in both); a full
cross-walk was not made.

## Observed coverage

Daily means (`data_1day_mean`) were read in full, in 20-year windows, for three stations and all
three parameters. Each row's UTC timestamp was converted to a Swiss calendar date.

| Station | Parameter | Days | First → last date | Missing days | Null values |
|---|---|---:|---|---:|---:|
| 2018 | Q, W, WT | 20 716 each | 1970-01-02 → 2026-09-20 | 0 | 0 |
| 2016 | Q, W, WT | 20 716 each | 1970-01-02 → 2026-09-20 | 0 | 0 |
| 2091 | Q, W, WT | 20 716 each | 1970-01-02 → 2026-09-20 | 0 | 0 |

`releaseState` over the discharge series:

| Station | 3 | 2 | 1 | none |
|---|---:|---:|---:|---:|
| 2018 | 20 089 | 486 | 0 | 141 |
| 2016 | 20 089 | 510 | 1 | 116 |
| 2091 | 19 358 | 1 242 | 1 | 115 |

hydrodownloadR reads 1, 2 and 3 as provisional, validated and definitive. No BAFU definition of
the codes was located during this probe. The rows without a state are the most recent ones.

Water temperature at 2091 is 0.0 °C on each of the first five days of January 1970. Over
1970–1979 the 2091 series has 932 distinct values; the 2018 series has 1 121.

Sub-daily depth, station 2018, discharge: `data_10min_mean` returned a full day of 144 values on
1990-01-01, 2000-01-01, 2010-01-01 and 2020-01-01; `data_1hour_mean` returned 24 values on
1975-01-01 and 2000-01-01. Earlier sub-daily dates were not probed.

Only three stations were read in full. Start dates of the other 1 338 were not read.

## Before 1970

With a timestamp filter of `_lt: "1970-01-01T00:00:00Z"` and no station filter, `data_1month_mean`,
`data_1day_mean`, `data_1hour_mean` and `data_10min_mean` returned no rows. `data_1year_mean`
returned rows stamped `1969-12-31T23:00:00Z`, which is 1970-01-01 in Swiss time; with
`_lt: "1969-12-31T22:59:59Z"` it returned none.

So across all stations and aggregations the API serves nothing before 1970. Station 2091 (Rhine,
Basel) starts on the same date as the others. Whether BAFU publishes pre-1970 data through another
channel was not checked.

## Day labelling

Every daily row read for station 2018 in 1970 and in 2025 is stamped `23:00:00Z`, in winter and in
summer alike: midnight at a fixed UTC+1, with no daylight-saving shift. The first row,
`1970-01-01T23:00:00Z`, is 1970-01-02 00:00 at UTC+1. The API does not say whether that stamp opens
or closes the day it summarises. hydrodownloadR takes the stamp's date in Europe/Zurich as the
day's date; because the stamp is always 23:00Z, that gives the same date as UTC+1. The dates in
this note follow the same reading. A daily product would need it confirmed.

## Terms

The platform's [Lizenz & Quelle](https://data.bafu.admin.ch/lizenz-und-quelle) page places the
data under the opendata.swiss licence «Freie Nutzung. Quellenangabe ist Pflicht.»: commercial and
non-commercial use allowed, with attribution (author, title and link to the dataset) required. The
opendata.swiss terms of use apply.

For comparison, the 2019 BAFU conditions cited for `ch_foen` recommend attribution, and Existenz.ch
states public and non-commercial use.

## Differences from the current route

| | `ch_foen` today (Existenz.ch) | BAFU data API |
|---|---|---|
| Publisher | Third party, self-described as unofficial | BAFU |
| Anonymous history | 32 days (REST); older data needs an Influx credential that the engine does not load | Back to 1970 |
| Stations | 246 | 1 341 |
| Aggregation | Not stated; products are `_reported` with unknown statistic | Stated: 10-min, hourly, daily, monthly, yearly means; daily, monthly, yearly min and max |
| Quality field | None | `releaseState` |
| Terms | Non-commercial (Existenz.ch) | Free use, attribution required |

With the anonymous transport, `ch_foen` failed on 2026-09-21 for station 2018 in January of 2000,
2010, 2015, 2019, 2021 and 2024, each with
`FatalContractError: ch_foen REST payload must contain a payload object`. A window starting
2026-08-01 succeeded.

## Open points

- What the daily timestamp stands for: start or end of the Swiss day.
- BAFU's definition of the `releaseState` codes.
- Start dates across all 1 341 stations, and which parameters each serves.
- The request limit, from BAFU rather than hydrodownloadR.
- Whether pre-1970 data exists elsewhere at BAFU.
- Whether the prepared `.csv.gz` files are a better route for full-history fetches.
- Whether this replaces the Existenz route in `ch_foen` or becomes a separate provider.

## Sources

| Page | Retrieved |
|---|---|
| [BAFU — Hydrologische Beobachtungen](https://data.bafu.admin.ch/dataproduct-water-observations) | 2026-09-21 |
| [BAFU data platform — Lizenz & Quelle](https://data.bafu.admin.ch/lizenz-und-quelle) | 2026-09-21 |
| [hydrodownloadR `adapter_CH_BAFU.R`](https://github.com/bafg-bund/hydrodownloadR/blob/main/R/adapter_CH_BAFU.R) | 2026-09-21 |
| `POST https://data.bafu.admin.ch/api`, live queries | 2026-09-21 |
