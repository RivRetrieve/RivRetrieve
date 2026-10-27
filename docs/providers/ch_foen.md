# Switzerland: FOEN

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `ch_foen` |
| Country | Switzerland |
| Published by | Federal Office for the Environment (FOEN / BAFU) and partner measurement networks |
| Read from | Official BAFU GraphQL API |
| Quantities | Discharge, stage, water temperature |
| Stations in the catalogue | 1,341. Availability depends on station, quantity, product and period |
| Station metadata | Station name, water-body name, drainage area and elevation. See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | None |
| Terms | Commercial and non-commercial use permitted; source attribution required |
| Agency documentation | [Water observations](https://data.bafu.admin.ch/en/dataproduct-water-observations) |

Retrieve published daily mean discharge at station `2018`, selecting the archive
variant `TagMittel`:

```python
import rivretrieve as rr

selection = rr.find(
    provider="ch_foen", station="2018", quantity="discharge",
    frequency="daily", statistic="mean",
)
daily = rr.pick(selection, variant="TagMittel")
result = rr.fetch(daily, start="2024-01-01", end="2024-01-07", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(float_precision=3), end="")

print(result.data.height)
print([(issue.severity, issue.code) for issue in result.issues])
```

Output:

```text
time,time_zone,value,unit
2023-12-31T23:00:00.000000,+00:00,113.624,m3/s
2024-01-01T23:00:00.000000,+00:00,107.088,m3/s
2024-01-02T23:00:00.000000,+00:00,114.261,m3/s
7
[('info', 'provenance.citation_not_established')]
```

The request returned seven daily means in m³/s. The preview shows the first three,
rounded to three decimal places. Each day begins at midnight in fixed UTC+1, so
1 January's mean is labelled 31 December at 23:00 UTC. Bare dates select the whole
first and last aggregate day. RivRetrieve preserves these UTC labels rather than
moving them to midnight UTC or applying summer time.

The informational issue `provenance.citation_not_established` means the packaged
provider catalogue has no configured citation. It does not mean retrieval failed
or that attribution is optional. Use the attribution in [Terms](#terms).
`cache="bypass"` requests the source rather than a local cache. Values can change;
a later retrieval need not reproduce this output exactly.
See [Usage](../usage.md) for selection options and working with returned data.

## Who measures, and who publishes

The Federal Office for the Environment runs Switzerland's national hydrological
monitoring network. BAFU is its German abbreviation, from Bundesamt für Umwelt;
FOEN is its English abbreviation. The official data platform brings together BAFU
and partner measurement networks. Its publisher name does not mean that BAFU
independently measured every observation.

No API key or account is required to retrieve observations. RivRetrieve searches
the station and product catalogue included with the package without contacting
BAFU. Fetching observations then requests data from the official API.

## What you can retrieve

The archive supplies the following published products for discharge (`discharge`),
water level (`stage`) and water temperature (`temperature`), where available:

| Frequency filter | Statistic filter | Product |
|---|---|---|
| `10min` | `mean` | Ten-minute mean |
| `hourly` | `mean` | Hourly mean |
| `daily` | `mean`, `min`, `max` | Daily mean, minimum or maximum |
| `monthly` | `mean`, `min`, `max` | Monthly mean, minimum or maximum |
| `yearly` | `mean`, `min`, `max` | Yearly mean, minimum or maximum |

The API also supplies recent raw readings separately from the archive products
above. RivRetrieve has not established the exact period represented by each
recent reading or its statistic, such as a mean. Its timestamp marks measurement
end, but the averaging duration remains unknown; do not treat the reading as an
instantaneous measurement. A daily-mean selection therefore excludes these
recent readings and selects only products known to represent daily means.

Minimum and maximum products describe extrema of short-term measurements, not
extrema of daily means. The underlying measurement duration and the occurrence
time of an extreme remain unknown. RivRetrieve retrieves published products;
it does not calculate additional products or splice recent readings into aggregates.
The public product page's abbreviated list omits some supported monthly and yearly
extrema. Availability still varies by station and quantity.

| Quantity filter | Source units | Returned unit |
|---|---|---|
| `discharge` | m³/s or l/s | m³/s (`m3/s`) |
| `stage` | m or cm, with source reference labels where published | m (`m`) |
| `temperature` | °C | °C (`degC`) |

RivRetrieve converts litres per second to cubic metres per second and centimetres
to metres. For archive data, RivRetrieve reads the unit supplied with the API
response. For recent readings, it uses the unit shown for that parameter on the
official station page. The original unit remains visible in `source_unit`; do
not assume archive and recent units are identical.
An above-sea-level label establishes that reference but not a named observation
datum. The LN02 datum attached to station altitude does not establish the datum
of water-level observations.

## Series selection

The archive gives each series a name in its `tsName` field, which RivRetrieve
returns as `variant`. These names distinguish source series; they do not select
a quality level. For example, station `2602` has concurrent `TagMittel` and
`TagMittel_01` series. RivRetrieve preserves both rather than choosing the
better-looking record. The recent feed has no archive `tsName`.

Inspect the candidates and station metadata before choosing a series:

```python
candidates = rr.series(selection)
metadata = rr.metadata(selection)
```

`candidates` describes known series, including their units, frequency and
statistic; `metadata` describes the station. The first example explicitly selects
`TagMittel`. Without a specific variant, RivRetrieve may request data again to
look for other source series. Selecting a known variant allows it to reuse
cached observations for periods already fetched. See [Usage](../usage.md) for
cache policies.

## Recent and older values

The catalogue lists 1,341 stations, but it does not list every product available
at every station. A station being listed does not guarantee data for every
product or period. Conversely, a product missing from a station's catalogue
entry may still exist at the source. Station operating dates and the timestamps
of a few retrieved values do not establish how far the API record extends.

It remains unclear how far back recent readings can be requested. The API
documentation says seven days in one place and twelve hours in another, so
RivRetrieve cannot promise either period. A cache can preserve readings already
fetched, but it cannot recover readings that disappeared from the source before
they were fetched. We are in touch with BAFU and will update this information
as soon as these limits are clarified.

A returned row with a null value, an absent row and a failed request are different
outcomes. RivRetrieve preserves null values and does not fill gaps; inspect
`result.issues` for reported failures. A successful request demonstrates only
what was returned for that station, product and period, not continuous coverage.

The separate official [Hydrological Data Service for watercourses and lakes](https://www.bafu.admin.ch/en/hydrological-data-service-for-watercourses-and-lakes)
accepts historical data orders beyond this provider's demonstrated scope. It is
an additional service, not a RivRetrieve provider or retrieval fallback. Its
statement about 40 days online does not establish how far back recent readings
can be requested through the GraphQL API.

## Data status

The source uses `releaseState` for archive data and `releaseStatus` for recent data:

| Source status | Publisher meaning |
|---|---|
| null or `0` | Raw |
| `1` | Unreleased / prechecked |
| `2` | Released / checked |
| `3` | Released / definitive |

Published null remains null even though its documented meaning is raw. The source
word `ersetzt` remains unresolved: it does not tell us which values replaced
others or which record to prefer. RivRetrieve does not rank values or select
variants by status.

These status fields are available in the original API responses, but RivRetrieve
does not include them in its returned observation table or cached rows. There is
no quality column or filter for selecting observations by status. See
[Receipts](../usage.md#receipts-optional) for retaining source material; cached
excerpts do not reproduce the original status fields.

## Time

Returned `time` values use UTC, as indicated by `time_zone="+00:00"`. Read those
columns together: the datetime column itself does not carry a time zone.
Ordinary aggregate timestamps mark interval starts. Daily, monthly and yearly
periods begin at midnight in fixed UTC+1, including summer. For example, February
2024 spans 31 January at 23:00 UTC through 29 February at 23:00 UTC, with the end
excluded. Its label belongs to February despite its January UTC date.

Recent timestamps mark measurement end; their spacing does not establish an
averaging duration. For station `7008`'s unusual `MonatsMittel_Orbe_flex` series,
RivRetrieve has not established the period each value represents, its statistic,
or whether its timestamp marks the beginning or end of that period. Neither the
series name nor the API route establishes daily or monthly values. The series
is therefore excluded by filters requiring those known properties.

## Terms

The [API terms](https://data.bafu.admin.ch/en/lizenz-und-quelle) permit commercial
and non-commercial use and require attribution containing the author, dataset
title and dataset link. The linked [open-data terms](https://opendata.swiss/en/terms-of-use)
call this “Open use. Must provide the source”; do not relabel it as CC-BY.
The Hydrodaten FAQ's general citation recommendation does not override the API's
mandatory attribution.

Suggested attribution:

> Bundesamt für Umwelt BAFU, Hydrologische Beobachtungen, https://data.bafu.admin.ch/dataproduct-water-observations

This is a suggested composition of the required fields, not an official template
or quotation. An access date is useful but is not one of those three required fields.

The API provides [read-only access without authentication](https://data.bafu.admin.ch/api-aufbau).
Its [rate limit](https://data.bafu.admin.ch/rate-limits) is 500 requests per client
IP in a rolling five-minute window; excess requests are rejected with HTTP 403.
Do not assume that RivRetrieve will automatically wait or retry that response.
The API also documents [pagination and result limits](https://data.bafu.admin.ch/pagination).

## Sources

| Page | Checked |
|---|---|
| [BAFU: Water observations](https://data.bafu.admin.ch/en/dataproduct-water-observations) | 2026-10-27 |
| [BAFU: API terms and source attribution](https://data.bafu.admin.ch/en/lizenz-und-quelle) | 2026-10-27 |
| [opendata.swiss: Terms of use](https://opendata.swiss/en/terms-of-use) | 2026-10-27 |
| [BAFU: API structure](https://data.bafu.admin.ch/api-aufbau) | 2026-10-27 |
| [BAFU: Rate limits](https://data.bafu.admin.ch/rate-limits) | 2026-10-27 |
| [BAFU: Pagination](https://data.bafu.admin.ch/pagination) | 2026-10-27 |
| [Hydrodaten: Frequently asked questions](https://www.hydrodaten.admin.ch/en/questions) | 2026-10-27 |
| [BAFU: Hydrological Data Service](https://www.bafu.admin.ch/en/hydrological-data-service-for-watercourses-and-lakes) | 2026-10-27 |

The station count describes the packaged catalogue. The example observations were
retrieved on 2026-10-27. This live example does not establish continuous coverage.
