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
stated `+10:00` offset. RivRetrieve requests a slightly wider period from BoM
than the one selected, then clips the returned rows to the requested period,
so the informational issues above can name dates just outside `2026-10-28`
to `2026-11-01`. This output was checked on 2026-11-04. BoM can revise recent
observations as sensors are recalibrated, so later retrievals of this same
period may return different values. See [Usage](../usage.md) for general
selection and result handling.

## Who measures, and who publishes

BoM operates Australia's national water-data service, Water Data Online,
which republishes discharge, stage and water temperature records collected
by BoM and by state and territory water agencies across the country. BoM is
the single point of access; it does not state, station by station, which
original agency collected a given record. RivRetrieve reads Water Data
Online's public web service (KiWIS); it does not contact state or territory
agencies directly.

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
one averaged over the calendar day (midnight to midnight, `discharge_daily_mean_24hr`)
and one averaged over the hydrological day BoM's own Hydrologic Reference
Stations programme and the independently published CAMELS-AUS streamflow
archive use (9am to 9am, `discharge_daily_mean_09hr`). These are not two
measurements of the same thing at different precision. Checked directly
against CAMELS-AUS v2 for one station and date, the `09hr` series matched
the reference value exactly while the `24hr` series gave a genuinely
different number.

Nothing in RivRetrieve's physical selection filters (`quantity`, `frequency`,
`statistic`) distinguishes these two series: filtering for daily mean
discharge selects both. A request without `variant` or `series_id` narrowing
retrieves both, as the duplicate `series_id` in the following example shows:

```python
import rivretrieve as rr

selection = rr.find(
    provider="au_bom",
    station="138020A",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)

result = rr.fetch(selection, start="2026-10-28", end="2026-11-01", cache="bypass")

print(rr.series(result).select("product_id", "series_id").unique().sort("product_id").rows())
```

Output:

```text
[('discharge_daily_mean_09hr', '28cf929e58599d9c089123f9dc07669cc723c773b862887f2dfb192a990fa93b'),
 ('discharge_daily_mean_09hr', '42687f9b8676c61f454bd6998835adc89578bb54792a91d720cf408f32a29cdf'),
 ('discharge_daily_mean_24hr', '74d8ea8c938349f8fb941c40cea5a031637df8e30b6e432bba2d5871d263852f'),
 ('discharge_daily_mean_24hr', 'ebf223503b5e04ccc59a003034e090aa476187965f1180d898a496e260f3b317')]
```

Decide which daily mean you need before retrieving, and check `product_id`
on the returned rows rather than assuming a single series.

## Two source identities can share one product at one station

Separately from the `24hr`/`09hr` distinction above, BoM's own internal
catalogue sometimes carries two different source series identities
(`ts_id`) for what is otherwise the same quantity, frequency, statistic and
station, with no field in BoM's catalogue saying which one is current. The
four `series_id` values in the example above are not two pairs of
duplicates; at station `138020A`, each of `discharge_daily_mean_09hr` and
`discharge_daily_mean_24hr` separately has this situation. RivRetrieve keeps
both of a station's source identities as distinct `series_id` values rather
than guessing which one to discard. In practice, one of a pair typically
returns observations for a requested period and the other returns none;
check which one has rows rather than assuming either in advance.

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
independently published CAMELS-AUS v2 streamflow archive.
