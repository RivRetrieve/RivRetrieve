# Australia: Bureau of Meteorology (BoM)

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `au_bom` |
| Country | Australia |
| Published by | Bureau of Meteorology (BoM), Water Data Online |
| Quantities | Discharge, stage, water temperature |
| Stations in the catalogue | 8,120 river-gauge stations, all with at least one selectable series |
| Station metadata | Station name only. See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | None |
| Licence stated by BoM | Creative Commons Attribution (see [Terms and citation](#terms-and-citation)) |
| Agency documentation | [Water Data Online](https://www.bom.gov.au/waterdata/) |

No credentials are required for catalogue browsing or retrieval. Retrieve
five days of published daily mean stage at station `410730`:

```python
import rivretrieve as rr

selection = rr.find(
    provider="au_bom",
    station="410730",
    quantity="stage",
    frequency="daily",
    statistic="mean",
)

result = rr.fetch(selection, start="2026-10-28", end="2026-11-01", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit")
print(preview.write_csv(float_precision=3), end="")

print(result.data.height)
for issue in result.issues:
    print(f"{issue.severity}: {issue.message}")
```

Output:

```text
time,time_zone,value,unit
2026-10-28T00:00:00.000000,+10:00,0.606,m
2026-10-29T00:00:00.000000,+10:00,0.597,m
2026-10-30T00:00:00.000000,+10:00,0.590,m
2026-10-31T00:00:00.000000,+10:00,0.588,m
2026-11-01T00:00:00.000000,+10:00,0.591,m
5
info: BoM reports quality code 140 (quality-E) for 410730 stage_daily_mean at 2026-10-27T00:00:00
info: BoM reports quality code 140 (quality-E) for 410730 stage_daily_mean at 2026-10-28T00:00:00
info: BoM reports quality code 140 (quality-E) for 410730 stage_daily_mean at 2026-10-29T00:00:00
info: BoM reports quality code 140 (quality-E) for 410730 stage_daily_mean at 2026-10-30T00:00:00
info: BoM reports quality code 140 (quality-E) for 410730 stage_daily_mean at 2026-10-31T00:00:00
info: BoM reports quality code 140 (quality-E) for 410730 stage_daily_mean at 2026-11-02T00:00:00
info: BoM reports quality code -1 (None) for 410730 stage_daily_mean at 2026-11-03T00:00:00
```

The request returned five daily means in metres, each labelled with BoM's
stated `+10:00` offset. This output was checked on 2026-11-04. See
[Usage](../usage.md) for general selection and result handling.

## Who measures, and who publishes

BoM operates Australia's national water-data service, Water Data Online,
which republishes discharge, stage and water temperature records collected
by BoM and by state and territory water agencies across the country.
RivRetrieve reads Water Data Online's public web service (KiWIS); it does
not identify, station by station, which agency originally collected a record.

## What you can retrieve

| Quantity filter | Frequency | Statistic | Stations with this series | Source unit | Returned unit |
|---|---|---|---:|---|---|
| `discharge` | Hourly | Mean | 5,712 | cumec | m3/s |
| `discharge` | Daily | Mean | 5,712 | cumec | m3/s |
| `discharge` | Daily | Max | 5,712 | cumec | m3/s |
| `discharge` | Daily | Min | 5,712 | cumec | m3/s |
| `discharge` | Monthly | Mean | 5,712 | cumec | m3/s |
| `discharge` | Yearly | Mean | 5,712 | cumec | m3/s |
| `stage` | Hourly | Mean | 6,698 | m | m |
| `stage` | Daily | Mean | 6,698 | m | m |
| `stage` | Daily | Max | 6,698 | m | m |
| `stage` | Daily | Min | 6,698 | m | m |
| `stage` | Monthly | Mean | 6,698 | m | m |
| `stage` | Yearly | Mean | 6,698 | m | m |
| `temperature` | Daily | Mean | 2,848 | °C | degC |
| `temperature` | Daily | Max | 2,848 | °C | degC |
| `temperature` | Daily | Min | 2,848 | °C | degC |
| `temperature` | Monthly | Mean | 2,848 | °C | degC |
| `temperature` | Yearly | Mean | 2,848 | °C | degC |

These units require no numerical scaling. Stage is water level; BoM does not
state a vertical datum for it, so RivRetrieve has not established one. Water
temperature has no hourly series; BoM publishes it at daily resolution and
coarser only. A station being listed for a quantity does not guarantee
observations for every period requested, and a successful short request does
not establish continuous historical coverage.

## Discharge has two daily means; selecting by quantity alone returns both

BoM publishes two different daily-mean discharge series for many stations:
one averaged over the calendar day, midnight to midnight
(`discharge_daily_mean_24hr`), and one averaged over the hydrological day,
9am to 9am (`discharge_daily_mean_09hr`), the convention used by the
independently published CAMELS-AUS streamflow dataset. These give different
values for the same date; neither is a less precise version of the other.

Nothing in RivRetrieve's physical selection filters (`quantity`, `frequency`,
`statistic`) distinguishes the two series, so a request without narrowing
retrieves both. BoM names this distinction itself, so RivRetrieve carries it
as a `variant` (`"24hr"` or `"09hr"`), the same mechanism used for
[an agency publishing more than one version](../usage.md#when-an-agency-publishes-more-than-one-version):

```python
import rivretrieve as rr

selection = rr.find(
    provider="au_bom",
    station="138020A",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)
print(sorted(rr.series(selection)["product_id"].to_list()))

hydrological_day = rr.pick(selection, variant="09hr")
result = rr.fetch(hydrological_day, start="2026-10-28", end="2026-11-01", cache="bypass")

print(result.data["product_id"].unique().to_list())
print(result.data.select("time", "value", "unit").write_csv(float_precision=3), end="")
```

Output:

```text
['discharge_daily_mean_09hr', 'discharge_daily_mean_24hr']
['discharge_daily_mean_09hr']
time,value,unit
2026-10-28T09:00:00.000000,162.815,m3/s
2026-10-29T09:00:00.000000,105.281,m3/s
2026-10-30T09:00:00.000000,68.452,m3/s
2026-10-31T09:00:00.000000,45.926,m3/s
2026-11-01T09:00:00.000000,34.559,m3/s
```

`result.data` already holds only the requested variant's rows; no filtering
by `product_id` afterward is needed. Unlike `br_ana`'s `bruto`/`consistido`
pair, `rr.series(selection)["variant"]` is not yet set at this point: BoM's
own series identity, like its `series_id` (see below), is confirmed only
once a response names a concrete source series, not from the offline
catalogue alone. Restricting by `variant` before fetching still resolves
correctly, as shown above, but raises `selection.unresolved_inventory` on the
way, since the catalogue cannot settle the restriction by itself. Restricting
an already-fetched result instead has no such warning, because the real
identities are known by then:

```python
full_result = rr.fetch(selection, start="2026-10-28", end="2026-11-01", cache="bypass")
narrowed = rr.pick(full_result, variant="09hr")
print(narrowed.data["product_id"].unique().to_list())
```

Output:

```text
['discharge_daily_mean_09hr']
```

On these same dates, the calendar-day mean (`variant="24hr"`) gives 103.069,
86.354, 52.289, 38.572 and 30.721 m3/s, a wide and genuine difference from
the hydrological-day mean above, not a rounding variation. Decide which one
you need before reading the values.

## Two source identities can share one product at one station

Separately from the `24hr`/`09hr` distinction above, BoM's own internal
catalogue sometimes carries two different source series identities
(`ts_id`) for what is otherwise the same quantity, frequency, statistic and
station, with no field in BoM's catalogue saying which one is current. At
station `138020A`, `discharge_daily_mean_24hr` is one such case. Continuing
the example above:

```python
calendar_day = rr.pick(selection, variant="24hr")
calendar_result = rr.fetch(calendar_day, start="2026-10-28", end="2026-11-01", cache="bypass")

catalogued = rr.series(calendar_result).filter(rr.series(calendar_result)["product_id"] == "discharge_daily_mean_24hr")
print(catalogued["series_id"].to_list())

print(calendar_result.data["series_id"].unique().to_list())
```

Output:

```text
['74d8ea8c938349f8fb941c40cea5a031637df8e30b6e432bba2d5871d263852f', 'ebf223503b5e04ccc59a003034e090aa476187965f1180d898a496e260f3b317']
['ebf223503b5e04ccc59a003034e090aa476187965f1180d898a496e260f3b317']
```

Two source identities are catalogued for this one product at this one
station, but only one of them returned rows for this period; the other
returned none. RivRetrieve keeps both as distinct `series_id` values rather
than guessing which one to discard, and both carry the same `variant`
(`"24hr"`): BoM names no distinction between the two, unlike the `24hr`/`09hr`
pair above. Check which one has rows rather than assuming either in advance;
the one that is empty today is not necessarily the one that will be empty for
a different period.

## Time and data status

BoM labels every returned timestamp with an explicit `+10:00` offset.
RivRetrieve returns that wall-clock value in `time`, paired with
`time_zone="+10:00"`: read both columns together, since the datetime column
itself is timezone-naive. BoM's service does not name a time zone (such as
AEST) for this offset, so RivRetrieve does not supply one.

BoM publishes a `Quality Code` and `Quality Code Name` per observation (for
example `quality-A`, `quality-E`). RivRetrieve does not filter observations
by this code or add a quality column to `result.data`. An informational
issue reports every row whose quality code is not `quality-A`, naming the
station, product, code and timestamp, as in the first example above. These
are BoM's own descriptions of the observation's processing status, not a
RivRetrieve quality judgement.

A published null remains a row with `value=null` rather than being dropped.
An absent observation supplies no row. A failed request remains an issue and
an identified outcome alongside independent successful records. Check
[issues](../usage.md#issues) before interpreting gaps or empty results.

BoM's service does not publish a numeric request-rate limit.

## Terms and citation

BoM's Water Data Online portal states:

> Unless otherwise noted, all material on this page is licensed under the Creative Commons Attribution Australia Licence

BoM's general copyright page separately gives this attribution wording where
a Creative Commons licence applies:

> Bureau of Meteorology, © Commonwealth of Australia. Licensed from the Commonwealth of Australia under a Creative Commons Attribution 4.0 International licence.

The two pages name different versions of a Creative Commons Attribution
licence (an Australian port versus the international 4.0 version) rather
than stating one consistent version for this service. `rr.providers()` and
the retrieved result's provenance record both of these statements; review
them yourself for your use before republishing BoM data.

## Sources

Publisher pages checked on 2026-11-04:

- [Water Data Online](https://www.bom.gov.au/waterdata/): the public web
  service (KiWIS) RivRetrieve reads.
- [BoM copyright page](https://www.bom.gov.au/other/copyright.shtml):
  general licence and attribution wording.

The station counts and series tables above describe the packaged catalogue.
The [private verification archive](https://github.com/RivRetrieve/verification-evidence#readme)
retains the commands, retained source responses and the limits of these
checks, including a cross-check of the `24hr`/`09hr` distinction against the
independently published CAMELS-AUS v2 streamflow dataset.
