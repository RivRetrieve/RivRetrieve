# Thailand: ThaiWater

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `th_thaiwater` |
| Country | Thailand |
| Published by | Hydro-Informatics Institute (HII), through ThaiWater, คลังข้อมูลน้ำแห่งชาติ (the National Hydroinformatics Data Center) |
| Read from | ThaiWater's public API (`api-v3.thaiwater.net`) |
| Station agencies | HII, Royal Irrigation Department, Friend in Need (of "Pa") Volunteers Foundation, Electricity Generating Authority of Thailand |
| Quantities | Discharge and stage |
| Stations in the catalogue | 825. Availability depends on quantity and period |
| Station metadata | Coordinates only. See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | No personal credentials required |
| Terms | No licence or citation request found for the API; see [Terms and citation](#terms-and-citation) |
| Agency documentation | [ThaiWater](https://www.thaiwater.net/), [ThaiWater data standards](https://standard.thaiwater.net/docs/) |

Retrieve three days of stage at station `1`, a telemetered water-level station in
Bangkok that ThaiWater names Klong Ladprao Bang Bua Temple:

```python
import rivretrieve as rr

selection = rr.find(provider="th_thaiwater", station="1", quantity="stage")

result = rr.fetch(selection, start="2024-06-01", end="2024-06-03", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print([(issue.severity, issue.code) for issue in result.issues])
```

Output:

```text
time,time_zone,value,unit
2024-06-01T00:00:00.000000,unknown,1.354,m
2024-06-01T00:10:00.000000,unknown,1.346,m
2024-06-01T00:20:00.000000,unknown,1.341,m
432
[('info', 'provenance.license_not_established'), ('info', 'provenance.citation_not_established')]
```

The request returned 432 stage values in metres for June 1 to 3, 2024. Both endpoint
dates are included. In this response the values are 10 minutes apart, which gives 144
rows per day. That spacing describes this response, not an established sampling
interval; see [What you can retrieve](#what-you-can-retrieve).

The time zone is `unknown`; see [Time and data status](#time-and-data-status).
The two informational issues say that RivRetrieve has no established
licence or citation for this provider. They are not retrieval problems; see
[Terms and citation](#terms-and-citation).

`cache="bypass"` requests the source rather than a local cache. This output was checked
on 2026-09-24. ThaiWater can revise its data, so later retrievals may differ.
Run the examples on this page in order in the same Python session.
See [Usage](../usage.md) for general selection and result handling.

## Who measures, and who publishes

คลังข้อมูลน้ำแห่งชาติ, the National Hydroinformatics Data Center, gathers water and
weather data from Thai agencies into one database. It provides those data through the
ThaiWater website and mobile app. RivRetrieve reads ThaiWater's public API.
The Hydro-Informatics Institute (HII), a public organisation under Thailand's Ministry
of Higher Education, Science, Research and Innovation, developed the data center and
publishes ThaiWater. HII describes its role as collecting and analysing
water-resources information for other agencies to use.

ThaiWater's own pages do not give one consistent count of contributing agencies.
On 2026-09-24, the site's "supported by" (สนับสนุนข้อมูลโดย) panel said 54 agencies
supply data. Its history text, in two versions, said the data center links data from
52 agencies and from 53 agencies, each across 12 ministries.

ThaiWater's station list names an agency for each station. It uses the word agency
(หน่วยงาน). The pages checked do not say whether that agency owns the station,
operates its sensor, or made the measurement. Read it as the agency to which ThaiWater
attributes the station. The 825 stations in RivRetrieve's catalogue are attributed to:

| Agency | Stations |
|---|---:|
| Hydro-Informatics Institute | 329 |
| Royal Irrigation Department | 328 |
| Friend in Need (of "Pa") Volunteers Foundation | 95 |
| Electricity Generating Authority of Thailand | 73 |

Station `1` in the example is attributed to HII. The catalogue holds the 825 telemetered
water-level stations that ThaiWater listed on 2026-08-02. ThaiWater's list changes;
on 2026-09-24 it listed 804. Neither list is a complete inventory of Thai river gauging.

## What you can retrieve

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `stage` | `value` | Unknown | Unknown | m | m |
| `discharge` | `discharge` | Unknown | Unknown | m³/s | m³/s |

These units require no numerical scaling. ThaiWater labels stage in metres above
mean sea level (ม.รทก.). The water-data exchange standard published at
[standard.thaiwater.net](https://standard.thaiwater.net/docs/) defines that unit with
reference to Royal Thai Survey Department benchmarks. RivRetrieve records stage as
above sea level but has not established which vertical datum each station's values use.

RivRetrieve returns the values ThaiWater publishes. It does not calculate hourly or
daily values, and the frequency and statistic filters do not match these records.
The API does not state a sampling frequency or whether each value is an instantaneous
reading or an average. Do not treat the 10-minute spacing in a response as an
established sampling interval, averaging period or promise of continuous coverage.
The same standard describes 10-minute water levels as readings at the labelled time,
but RivRetrieve has not established that the API values follow that standard.

Every catalogue station lists both stage and discharge. Test requests covering parts
of June to September 2026 found stage values at 813 stations and discharge values at
283. At the other stations, availability is unknown, and the quantity remains
selectable. A station being listed does not guarantee data for every quantity or
requested period.

ThaiWater publishes stage and discharge together, and a station without discharge
values can still publish timestamps with an empty discharge field. RivRetrieve keeps
those as rows with a null value. At station `1`, discharge for the same three days
returns rows, but no values:

```python
discharge = rr.find(provider="th_thaiwater", station="1", quantity="discharge")

discharge_result = rr.fetch(discharge, start="2024-06-01", end="2024-06-03", cache="bypass")

print(discharge_result.data.height)
print(discharge_result.data["value"].null_count())
print([str(outcome.status) for outcome in discharge_result.outcomes])
```

Output:

```text
432
432
['success']
```

All 432 discharge rows are null, and the request succeeded. A null value means that
ThaiWater published the timestamp without a discharge value. It differs from an absent
row, where the source supplied no timestamp, and from a failed request, which is
reported as an issue.

## Requests

If you request a period extending into the future, ThaiWater can return future
timestamps with null values. RivRetrieve preserves these source-published rows.
They are not future measurements, and null does not mean zero. Omit `end` to
request through the caller machine's current local date.

RivRetrieve requests two extra days on each side of the requested dates, then returns
only the requested period. The three-day example above therefore asked ThaiWater for
May 30 to June 5, 2024. Each request to ThaiWater covers at most 365 calendar dates,
counting both ends, and RivRetrieve splits longer periods into several requests. That
size is a conservative working choice. RivRetrieve has not found a documented maximum
period, and none has been measured.

Stage and discharge come from the same ThaiWater response, but RivRetrieve requests each
selected quantity separately. Selecting both quantities at a station therefore sends the
same request twice.

## Time and data status

The API gives times such as `2024-06-01 00:10` without a time zone. RivRetrieve keeps
them as source clock labels and returns `time_zone="unknown"`. Do not assign UTC or
Thailand time from the station's location. `rr.to_utc` raises an error for these rows
because it cannot determine the offset.

RivRetrieve found no quality flag or provisional marker in the API response. It makes no
quality judgement of its own. A returned number therefore does not establish that
ThaiWater or the station agency has checked it.

If ThaiWater answers a request with an explicit failure message, RivRetrieve returns
an `error` issue with that message and no rows for the request. Check
[issues](../usage.md#issues) alongside row counts before interpreting gaps or empty results.

## Terms and citation

RivRetrieve has not found a licence or citation request for the API it reads. On
2026-09-24, the ThaiWater site linked cookie and privacy policies and a privacy notice,
but no data terms. Its pages carry HII copyright notices, such as:

> Copyright © 2024 Hydro - Informatics Institute,All rights reserved.

Not finding a licence does not establish that the data are free to reuse, or that no
terms apply.

HII also publishes a separate water-level dataset from its telemetry network
(สถานีโทรมาตร สสน.) in Thailand's [Government Data Catalog](https://gdcatalog.go.th/dataset/gdpublish-water-level),
distributed as downloadable files. That listing gives its licence as
**Creative Commons Attribution Non-Commercial**. RivRetrieve has not established
whether that licence applies to the API responses, or to stations attributed to other
agencies. Check with HII and the station agency before commercial use or redistribution.

When citing retrieved data, identify ThaiWater and HII as the publishers, and record
the station, its agency, the quantity, the requested period and the access date. This
is practical guidance, not an official ThaiWater citation.

## Sources

| Source | Checked |
|---|---|
| [ThaiWater](https://www.thaiwater.net/) and its site application | 2026-09-24 |
| ThaiWater station list (`waterlevel_load` in the public API) | 2026-09-24 |
| [HII](https://www.hii.or.th/) | 2026-09-24 |
| [ThaiWater data standards](https://standard.thaiwater.net/docs/): date and time format, data periods, water-level measurement | 2026-09-24 |
| [Government Data Catalog: ระดับน้ำ (water level)](https://gdcatalog.go.th/dataset/gdpublish-water-level) | 2026-09-24 |

Station counts and agencies come from the packaged catalogue. The examples were run
against the live API on 2026-09-24. They verify one station, two quantities and one
period, not service-wide availability. The
[private verification archive](https://github.com/RivRetrieve/verification-evidence#readme) retains commands,
source checks, exact output and the limits of these checks.
