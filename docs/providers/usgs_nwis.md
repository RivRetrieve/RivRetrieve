# United States: USGS

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `usgs_nwis` |
| Country | United States, 50 states and District of Columbia |
| Published by | U.S. Geological Survey, through Water Data for the Nation |
| Quantities | Discharge and stage |
| Selectable stations | 26,201 in the packaged catalogue. Availability depends on quantity and period |
| Credentials | No personal credentials required for modest public requests; optional `USGS_API_KEY` |
| Terms stated by USGS | USGS-produced data are in the U.S. Public Domain |
| Agency documentation | [Water Data APIs](https://api.waterdata.usgs.gov/), [Water Data for the Nation](https://waterdata.usgs.gov/) |

Retrieve one week of published daily mean discharge at station `07374000`,
Mississippi River at Baton Rouge, Louisiana:

```python
import rivretrieve as rr

selection = rr.find(
    provider="usgs_nwis",
    station="07374000",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)

result = rr.fetch(
    selection, start="2024-01-01", end="2024-01-07", cache="bypass"
)

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(float_precision=3), end="")

print(result.data.height)
print(result.issues)
```

Output:

```text
time,time_zone,value,unit
2024-01-01T00:00:00.000000,unknown,4927.131,m3/s
2024-01-02T00:00:00.000000,unknown,5125.349,m3/s
2024-01-03T00:00:00.000000,unknown,5238.617,m3/s
7
()
```

The request returned seven daily means in m³/s and no retrieval issues. The
preview shows the first three, rounded to three decimal places. USGS calculates
these daily means. Its daily API labels each value with a date; RivRetrieve
displays that date at midnight. The returned `time_zone` is `unknown` because
RivRetrieve has not established the time convention used to define these daily
periods.

Both endpoint dates are included. `cache="bypass"` requests the source rather than
cached observations. Source values can change, so later requests need not reproduce
this output exactly. See [Usage](../usage.md) for general selection and result
handling. Run the examples below in the same session.

## Who measures, and who publishes

The U.S. Geological Survey primarily operates and maintains the
[national streamgaging network](https://www.usgs.gov/mission-areas/water-resources/science/usgs-national-streamgaging-network),
with funding shared with federal, state, local and Tribal partners. It publishes
measurements through [Water Data for the Nation](https://waterdata.usgs.gov/).
USGS remains the publisher of the data RivRetrieve retrieves.

RivRetrieve reads the daily and continuous collections of the
[Water Data API v1](https://api.waterdata.usgs.gov/ogcapi/v1/).

## What you can retrieve

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | Daily values | Daily | Mean | ft³/s | m³/s |
| `stage` | Daily values | Daily | Mean, maximum or minimum | ft | m |
| `discharge` | Continuous observations | Unknown | Instantaneous; Unknown for some series | ft³/s | m³/s |
| `stage` | Continuous observations | Unknown | Instantaneous; Unknown for some series | ft | m |

RivRetrieve converts cubic feet per second to cubic metres per second, and feet
to metres. Source values already in m³/s or m are also supported and retain those
units. Stage is USGS gage height; it must not be treated as elevation above sea
level without an established reference.

For daily values, use `frequency="daily"` and `statistic="mean"`, `"max"` or
`"min"` as applicable. For established instantaneous observations, use
`statistic="instantaneous"` without a frequency filter. Continuous publication
does not establish a fixed sampling frequency. Some continuous series have unknown statistic and do not match
that instantaneous filter. Water temperature is outside this provider's supported quantities.

A listed station does not guarantee data for every quantity or requested period.
The catalogue is a recorded snapshot, not a live census of operating gauges.

## Published time series

Each published USGS time series has its own USGS time-series ID. RivRetrieve
exposes it as `variant`, which can be passed to `rr.pick(..., variant=...)` before
retrieval. These IDs identify individual published time series. They are not a
provider-wide menu of processing categories or measurement methods.

Most stations have one matching series for a given quantity, frequency and
statistic. In the packaged catalogue, 575 of 26,201 selectable stations (about
2.2%) have multiple matching series for at least one such combination. For daily
mean discharge, this occurs at 134 of 24,495 stations (about 0.55%). These counts
do not establish overlapping observations or current availability. A populated
`variant` field alone does not mean that alternatives exist.

Station `02196000` illustrates the less common case: two published daily mean
discharge series match the same physical filters. The IDs below belong to this
station, not to all USGS stations.

| USGS time-series ID exposed as `variant` | Source description |
|---|---|
| `0df18b246e8f48ec8e6547a92070e94a` | Not supplied (`null`) |
| `4d186669708e4dc18f84d271efb953a1` | Not supplied (`null`) |

Both publish discharge in ft³/s, returned in m³/s. The available source
descriptions do not explain their relationship or establish a preferred series.
RivRetrieve cannot rank them. Source approval status is not a series variant,
and there is no public USGS Primary/Secondary selector.

Inspect the packaged series without contacting USGS:

```python
alternatives = rr.find(
    provider="usgs_nwis",
    station="02196000",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)

print(sorted(rr.series(alternatives)["variant"].to_list()))
```

Output:

```text
['0df18b246e8f48ec8e6547a92070e94a', '4d186669708e4dc18f84d271efb953a1']
```

Fetching without a choice retains all matching published series, and may discover
additional identities beyond the catalogue. Choose an ID explicitly when the
study requires that particular series. This example demonstrates selection, not
a recommendation to prefer the selected ID:

```python
all_result = rr.fetch(
    alternatives, start="2000-01-01", end="2000-01-07", cache="bypass"
)

chosen = rr.pick(alternatives, variant="0df18b246e8f48ec8e6547a92070e94a")
chosen_result = rr.fetch(
    chosen, start="2000-01-01", end="2000-01-07", cache="bypass"
)

print(all_result.data.height, all_result.data["series_id"].n_unique())
print(chosen_result.data.height, chosen_result.data["series_id"].n_unique())
print(rr.series(chosen_result)["variant"].to_list())
print(all_result.issues, chosen_result.issues)
```

Output:

```text
14 2
7 1
['0df18b246e8f48ec8e6547a92070e94a']
() ()
```

The unrestricted request returned fourteen rows across two series. The explicit
choice returned seven rows from one. RivRetrieve does not average the series or
select a winner. Multi-station retrieval does not require manually choosing an
ID at each station: select stations and physical facts, then fetch. Keep
`series_id` in analysis when several matching series are returned; station and
date alone need not uniquely identify a value.

## Time and data status

Continuous observations retain their published clock labels and explicit UTC
offsets. Returned `time` is timezone-naive; read it together with `time_zone`.
A source timestamp ending in `Z` has `time_zone="+00:00"`. Daily dates have
`time_zone="unknown"`, as in the first example. RivRetrieve does not infer a
station's zone or the bounds of a daily mean from metadata dates.

USGS's [Provisional Data Statement](https://waterdata.usgs.gov/provisional-data-statement/)
warns that provisional information is subject to revision, including substantial
changes after field inspections and measurements. RivRetrieve does not attach
source approval or qualifier fields to the returned observation table and does
not assign a quality judgement. Successful retrieval does not mean values are
approved. Retain source material with [receipts](../usage.md#receipts-optional)
when those source fields matter.

A source observation with a null value remains a row with `value=null`.
An absent observation remains absent; RivRetrieve does not fill gaps.
A failed request is reported separately in issues and can accompany successful
independent series. See [Issues](../usage.md#issues) before interpreting an empty
or partial result.

## Access, terms and citation

Personal credentials are not required for modest public requests. An optional
`USGS_API_KEY` can be supplied through the environment or working-directory
`.env` file; RivRetrieve sends it only to `api.waterdata.usgs.gov`. A personal
key permits more requests before USGS applies rate limits. Consult the
[USGS API-key guidance](https://api.waterdata.usgs.gov/docs/ogcapi/keys/) for
current access conditions; limits depend on the API and whether a key is used.

The USGS [copyrights and credits policy](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits)
states:

> USGS-authored or produced data and information are considered to be in the U.S. Public Domain.

USGS asks for proper credit. Its [water data citation page](https://waterdata.usgs.gov/citation/) gives this
form, with the bracketed dates replaced for the data used:

> U.S. Geological Survey, [2024], USGS Water Data for the Nation: U.S. Geological Survey National Water Information System database, accessed [April 8, 2024], at https://doi.org/10.5066/F7P55KJN.

## Sources

Source checks and example retrievals: 2026-09-22. Counts describe the packaged
catalogue. The [private verification archive](https://github.com/RivRetrieve/verification-evidence#readme)
retains the evidence, execution details and limits.
