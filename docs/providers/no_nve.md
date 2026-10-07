# Norway: NVE

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `no_nve` |
| Country | Norway |
| Published by | Norges vassdrags- og energidirektorat (NVE), the Norwegian Water Resources and Energy Directorate |
| Quantities | Discharge, stage, water temperature |
| Stations in the catalogue | 4,902 locations; 3,804 have catalogued series for the supported quantities and resolutions |
| Station metadata | Station name, water-body name, drainage area and elevation. See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | Required for retrieval: `NVE_API_KEY`; see [Credentials and requests](#credentials-and-requests) |
| Licence stated by NVE | Norwegian Licence for Open Government Data (NLOD) |
| Agency documentation | [HydAPI documentation](https://hydapi.nve.no/UserDocumentation/) |

Set `NVE_API_KEY` in the process environment or a private `.env` file in the
directory from which Python runs, using a key obtained from NVE. Catalogue browsing
works without it. Retrieve one week of published
daily mean discharge at station `2.605.0`:

```python
import rivretrieve as rr

selection = rr.find(
    provider="no_nve",
    station="2.605.0",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)

result = rr.fetch(selection, start="2024-01-01", end="2024-01-07", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(float_precision=3), end="")

print(result.data.height)
for issue in result.issues:
    print(f"{issue.severity}: {issue.message}")
```

Output:

```text
time,time_zone,value,unit
2024-01-01T11:00:00.000000,+00:00,401.750,m3/s
2024-01-02T11:00:00.000000,+00:00,415.396,m3/s
2024-01-03T11:00:00.000000,+00:00,444.500,m3/s
7
info: no_nve published source quality code 2 without RivRetrieve interpretation
info: no_nve published source correction code 0 without RivRetrieve interpretation
```

The request returned seven daily means in m³/s. The preview shows three values
rounded to three decimal places. Both endpoint dates are included. RivRetrieve
reads the published means; it does not calculate them from more frequent observations.
The two informational messages report source metadata, not retrieval problems.
NVE calls quality code `2` **PrimaryControlled** and correction code `0` **No changes**.
These are NVE’s descriptions of the observations, not a RivRetrieve quality
judgement. They are separate from the series version, which is `1` in this example.

`cache="bypass"` requests HydAPI rather than a local cache. This output was checked
on 2026-09-23. NVE can revise historical observations, so later retrievals may
return different values. Run the examples in order in the same Python session.
See [Usage](../usage.md) for general selection and result handling.

## Who measures, and who publishes

NVE is responsible for Norway's national hydrological observation networks and
databases. It operates monitoring stations and publishes historical and current
observations through HydAPI, its programming interface for hydrological data.
RivRetrieve reads HydAPI.

NVE does not own or produce every measurement in that archive. The network also
includes stations owned by river-regulation operators. Owners of regulation
facilities carry out and fund hydrological investigations required by NVE; NVE
checks and archives the mandated data. Keep that distinction when describing
the origin of a station's record.

NVE may withhold recent observations from public access, including in regulated
catchments and at hydropower installations. Its publication guidelines specify
a 14-day withholding period for stage and discharge where those restrictions
apply. The station owner may permit earlier publication. Owners of privately collected data that
are not required by a public authority can decide what to publish. HydAPI access
does not promise an unrestricted real-time record at every station.

## Credentials and requests

NVE describes HydAPI as a free service. Request a key at
[hydapi.nve.no/Users](https://hydapi.nve.no/Users), entering an email address and
accepting the terms. Store the key securely: NVE says it cannot be retrieved later.
Set `NVE_API_KEY` in the process environment or a private `.env` file in the
directory from which Python runs. Process variables take precedence, including
blank values. Keep credentials out of code, version control, logs and shared files.
See [credential configuration](../usage.md#supplied-credentials) for details.
`rr.providers()` reports `ready` when the credential is present locally; it does
not authenticate with NVE or prove that the key is accepted.

NVE limits requests per key and the number of observations in a response. Its
user documentation does not give numeric limits. RivRetrieve sends separate
observation requests for each station, quantity, resolution and version. It
requests a slightly wider period than selected, then clips the returned rows.
For Norway, it does not automatically subdivide that period to meet the source's
observation-count limit. If NVE reports that a response is too large, request
shorter periods, as its documentation advises. Check the returned issues rather
than treating a failed request as missing observations.

## What you can retrieve

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | Raw resolution | Unknown | Mean or instantaneous, depending on series | m³/s | m³/s |
| `discharge` | Hourly resolution | Hourly | Mean or instantaneous, depending on series | m³/s | m³/s |
| `discharge` | Daily resolution | Daily | Mean or instantaneous, depending on series | m³/s | m³/s |
| `stage` | Raw resolution | Unknown | Mean or instantaneous, depending on series | m | m |
| `stage` | Hourly resolution | Hourly | Mean or instantaneous, depending on series | m | m |
| `stage` | Daily resolution | Daily | Mean or instantaneous, depending on series | m | m |
| `temperature` | Raw resolution | Unknown | Mean or instantaneous, depending on series | °C | °C |
| `temperature` | Hourly resolution | Hourly | Mean or instantaneous, depending on series | °C | °C |
| `temperature` | Daily resolution | Daily | Mean or instantaneous, depending on series | °C | °C |

These units require no numerical scaling. Stage is water level; RivRetrieve has
not established its vertical reference or datum.

HydAPI publishes raw, hourly and daily resolutions. RivRetrieve establishes
`frequency="hourly"` or `frequency="daily"` from the published resolution.
For raw resolution, frequency remains unknown. The source method establishes
`statistic="mean"` or `statistic="instantaneous"` separately. An hourly or daily
series can contain instantaneous values; its resolution alone does not establish
an averaging operation. Use both frequency and statistic filters for daily means,
as in the example. RivRetrieve does not derive additional statistics.

Of the 4,902 catalogue locations, 3,804 list series for the supported quantities
and resolutions. The other 1,098 list other parameters, such as groundwater level
and temperature, air temperature, precipitation or snow. Their presence in the
catalogue does not make those parameters retrievable through RivRetrieve.

The catalogue contains daily mean discharge at 1,620 stations, daily mean stage
at 2,790, and daily mean temperature at 1,153. These counts can overlap and describe
the packaged snapshot, not an exhaustive current inventory. A station being listed
does not guarantee observations for every quantity or requested period. A successful
short request does not establish continuous historical coverage.

## Source versions

HydAPI can publish several versions of a station's series. `variant` is the
published version number, represented as a string. Version numbers identify
records at a particular station and quantity; they are not global quality codes.
RivRetrieve keeps those records separate. A larger number is not a quality ranking,
and no universal meaning for each version number has been established.
Without an explicit version choice, retrieval checks current source metadata and
requests all versions matching the selection's physical filters. Each version can
return values, an empty record, or a separate failure.

The example returned version `1` at station `2.605.0`. Another station,
`109.42.0`, has three catalogued versions of daily mean discharge:

| Station | Quantity | `variant` | Frequency | Statistic |
|---|---|---|---|---|
| `109.42.0` | Discharge | `1` | Daily | Mean |
| `109.42.0` | Discharge | `2` | Daily | Mean |
| `109.42.0` | Discharge | `3` | Daily | Mean |

These numbers identify versions at this station, not quality levels. Inspect them
before making a version-specific request:

```python
print(rr.series(result).select("station_id", "variant").rows())

other_station = rr.find(
    provider="no_nve", station="109.42.0", quantity="discharge",
    frequency="daily", statistic="mean",
)
print(rr.series(other_station).select("station_id", "variant").sort("variant").rows())

version_two = rr.pick(other_station, variant="2")
print(rr.series(version_two).select("station_id", "variant").rows())
```

Output:

```text
[('2.605.0', '1')]
[('109.42.0', '1'), ('109.42.0', '2'), ('109.42.0', '3')]
[('109.42.0', '2')]
```

The second and third lines describe catalogue candidates, not newly retrieved
observations. `pick` narrows the selection; it does not make an observation request.
Passing `version_two` to `fetch` requests only that station's version `2`, without
substituting another version when observations are unavailable. This choice does
not select quality code `2` or assert that this version is preferable.

## Time and data status

HydAPI timestamps carry explicit UTC labels. RivRetrieve returns their wall-clock
values in `time`, paired with `time_zone="+00:00"`. Read both columns together:
the datetime column itself is timezone-naive. The daily values above are labelled
at 11:00 UTC. That clock label does not establish the averaging interval or its
start and end. NVE's documentation gives conflicting wording for the daily time
basis; RivRetrieve leaves exact daily boundaries and interval anchors unknown.

HydAPI observations carry `quality` and `correction` codes. RivRetrieve does not
filter observations by those codes, interpret them as a quality ranking, or add
per-row quality columns to `result.data`. Informational issues summarize the
published codes, their counts and first and last source timestamps. Those summaries
can include the extra dates requested around the selected period, so their counts
need not equal the returned row count. Optional [receipts](../usage.md#receipts-optional)
retain the observation response bytes when the original per-row codes are needed.

A published null remains a row with `value=null`. An absent observation supplies
no row. A failed request remains an issue and an identified outcome alongside
independent successful records. Check [issues](../usage.md#issues) before interpreting
gaps or empty results. Neither a returned number nor the absence of retrieval errors
establishes the source's approval of its quality.

## Terms and citation

NVE's [HydAPI documentation](https://hydapi.nve.no/UserDocumentation/) licenses
the data under the [Norwegian Licence for Open Government Data (NLOD)](https://data.norge.no/nlod/en).
It states that the data are provided "as is" and may contain errors or omissions.
The verified observation response includes the licence URL in its JSON metadata.

NVE asks:

> When using data from this service, if possible, please refer to this service as origin of data.

The linked [NLOD 2.0 terms](https://data.norge.no/nlod/en/2.0) permit reuse, including
commercial reuse, subject to their conditions. They require attribution and a
licence reference, links to the source and licence where practical, and a clear
indication of changes. Where the licensor has not specified attribution wording,
the licence gives:

> Contains data under the Norwegian licence for Open Government data (NLOD) distributed by [name of licensor].

Identify NVE HydAPI as the publication service, and retain the station, quantity,
version, requested period and access date to make the retrieved record traceable.
These record details are practical citation guidance, not an official NVE citation
template. NLOD's compatibility provisions distinguish databases from other material;
do not assume an unqualified equivalence with CC BY 3.0.

## Sources

Publisher pages checked on 2026-09-23:

- [NVE Hydrology](https://www.nve.no/hydrology/), [station network](https://www.nve.no/vann-og-vassdrag/hydrologiske-data/vannstand-og-vannforing/stasjonsnettet/), [mandated hydrological investigations](https://www.nve.no/vann-og-vassdrag/hydrologiske-data/hydrologiske-paalegg/): responsibilities and measurement producers.
- [Publication guidelines](https://www.nve.no/vann-og-vassdrag/hydrologiske-data/retningslinjer-for-publisering-av-hydrologiske-data-i-nve/): restrictions on historical and recent data.
- [HydAPI documentation](https://hydapi.nve.no/UserDocumentation/), [key registration](https://hydapi.nve.no/Users): access, source versions, timestamps, codes, limits and terms.
- [NLOD](https://data.norge.no/nlod/en), [NLOD 2.0](https://data.norge.no/nlod/en/2.0): reuse and attribution conditions.

The station counts describe the packaged catalogue. Live public retrieval and the
recording path were checked on 2026-09-23. The
[private verification archive](https://github.com/RivRetrieve/verification-evidence#readme) retains commands,
source checks, exact output and the limits of these checks.
