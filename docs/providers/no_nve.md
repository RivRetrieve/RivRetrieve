# Norway: NVE

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `no_nve` |
| Country | Norway |
| Published by | Norges vassdrags- og energidirektorat (NVE), the Norwegian Water Resources and Energy Directorate |
| Quantities | Discharge, stage, water temperature |
| Stations in the catalogue | 4,902 locations; 3,804 have catalogued series for the supported quantities and resolutions |
| Credentials | Required for retrieval: `NVE_API_KEY`; see [Credentials and requests](#credentials-and-requests) |
| Licence stated by NVE | Norwegian Licence for Open Government Data (NLOD) |
| Agency documentation | [HydAPI documentation](https://hydapi.nve.no/UserDocumentation/) |

Set `NVE_API_KEY` in the environment before running Python, using a key obtained
from NVE. Catalogue browsing works without it. Retrieve one week of published
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
print([(issue.severity, issue.code) for issue in result.issues])
```

Output:

```text
time,time_zone,value,unit
2024-01-01T11:00:00.000000,+00:00,401.750,m3/s
2024-01-02T11:00:00.000000,+00:00,415.396,m3/s
2024-01-03T11:00:00.000000,+00:00,444.500,m3/s
7
[('info', 'source_quality_code'), ('info', 'source_correction_code')]
```

The request returned seven daily means in m³/s. The preview shows three values
rounded to three decimal places. Both endpoint dates are included. RivRetrieve
reads the published means; it does not calculate them from more frequent observations.
The two informational issues retain source quality and correction codes without
interpreting them. They do not mean that the request failed or that RivRetrieve
approved the observations.

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

NVE's publication guidelines allow restrictions on recent observations, including
in regulated catchments and at hydropower installations. They specify a 14-day
withholding period for stage and discharge where those restrictions apply; owner
consent can allow earlier publication. Owners of privately collected data that
are not required by a public authority can decide what to publish. HydAPI access
does not promise an unrestricted real-time record at every station.

## Credentials and requests

NVE describes HydAPI as a free service. Request a key at
[hydapi.nve.no/Users](https://hydapi.nve.no/Users), entering an email address and
accepting the terms. Store the key securely: NVE says it cannot be retrieved later.
See [credential configuration](../usage.md#supplied-credentials) to supply it through
`NVE_API_KEY`. `rr.providers()` reports `ready` when the required credential is
configured; this does not test whether NVE accepts the key.

NVE limits requests per key and the number of observations in a response. Its
user documentation does not give numeric limits. RivRetrieve sends separate
observation requests for each station, quantity, resolution and version. It
requests a slightly wider period than selected, then clips the returned rows.
For Norway, it does not automatically subdivide that period to meet the source's
observation-count limit. If NVE reports that a response is too large, request
shorter periods, as its documentation advises. Check the returned issues rather
than treating a failed request as missing observations.

## What you can retrieve

| Quantity filter | Source unit | Returned unit |
|---|---|---|
| `discharge` | m³/s | m³/s (`m3/s`) |
| `stage` | m | m |
| `temperature` | °C | °C (`degC`) |

These units require no numerical scaling. Stage is water level; RivRetrieve has
not established its vertical reference or datum.

HydAPI publishes raw, hourly and daily resolutions. RivRetrieve establishes
`frequency="hourly"` or `frequency="daily"` from the published resolution.
For raw resolution, frequency remains unknown. The source method establishes
`statistic="mean"` or `statistic="instantaneous"` separately. An hourly or daily
series can contain instantaneous values; its resolution alone does not establish
an averaging operation. Use both frequency and statistic filters for daily means,
as in the example. RivRetrieve does not derive additional statistics.

The catalogue contains daily mean discharge at 1,620 stations, daily mean stage
at 2,790, and daily mean temperature at 1,153. These counts can overlap and describe
the packaged snapshot, not an exhaustive current inventory. A station being listed
does not guarantee observations for every quantity or requested period. A successful
short request does not establish continuous historical coverage.

## Source versions

HydAPI can publish several versions of a station's series. `variant` is the
published version number, represented as a string. RivRetrieve keeps those
records separate; a larger version number is not a RivRetrieve quality ranking.
Without an explicit version choice, retrieval checks current source metadata and
requests all versions matching the selection's physical filters. Each version can
return values, an empty record, or a separate failure.

Inspect the example's catalogue candidate and select its published version:

```python
print(rr.series(selection).select("station_id", "variant", "frequency", "statistic").rows())

version_one = rr.pick(selection, variant="1")
print(rr.series(version_one).select("station_id", "variant").rows())
print(rr.series(result).select("station_id", "variant").rows())
```

Output:

```text
[('2.605.0', '1', 'daily', 'mean')]
[('2.605.0', '1')]
[('2.605.0', '1')]
```

Here the catalogue and retrieved record both identify version `1`. `pick` narrows
the selection; it does not make another observation request. Passing that narrowed
selection to `fetch` requests only that version, without substituting another
version when observations are unavailable.

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
[verification record](../verification/norway-provider/README.md) retains commands,
source checks, exact output and the limits of these checks.
