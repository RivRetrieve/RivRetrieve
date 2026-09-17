# Recent streamflow for CAMELS-US gauges

[Documentation index](../README.md) · [Usage](../usage.md)

A study extending CAMELS-US may need more recent streamflow observations.
RivRetrieve can request USGS daily mean discharge for selected gauges. The returned data
are a starting point for that work, not an extended CAMELS dataset.

Newman et al. (2015), [section 2.2](https://doi.org/10.5194/hess-19-209-2015), describes
671 basins and daily USGS streamflow for 1980–2010. Some records were shorter.
That study period is not a claim about the endpoint of later CAMELS-US releases.
The official [CAMELS record](https://doi.org/10.5065/D6MW2F4D) links to the
[gauge-name file](https://zenodo.org/records/15529996/files/camels_name.txt) used here.

| Station ID | Name in CAMELS |
|---|---|
| `01013500` | Fish River near Fort Kent, ME |
| `01022500` | Narraguagus River at Cherryfield, ME |
| `01030500` | Mattawamkeag River near Mattawamkeag, ME |

## Request 2025 daily discharge

Keep identifiers as strings. This example requires network access but no credentials.
It reads catalogue facts first, then requests the inclusive 2025 calendar window.

```python
import rivretrieve as rr

selection = rr.find(provider="usgs_nwis", product="discharge_daily_mean")
selection = rr.pick(selection, station=["01013500", "01022500", "01030500"])
print(rr.as_frame(selection))

result = rr.fetch(selection, start="2025-01-01", end="2025-12-31")
print(result.data)
print(result.data.group_by("station_id").len().sort("station_id"))
print(result.issues)
print(result.provenance)
```

USGS publishes this daily product. RivRetrieve does not aggregate sub-daily values to
create it. Returned discharge uses m³/s. The timestamps retain source calendar dates,
paired with source-established zones or `unknown`. An unknown zone does not justify
assuming UTC. See [request windows](../usage.md#request-windows-and-utc).

Inspect issues, null values and dates before joining observations to a study.
An absent observation does not identify its cause. A source failure does not establish
an empty hydrological record. Row counts alone do not certify completeness or quality.
This example does not recover CAMELS quality flags, infill records, extend forcing,
convert discharge to basin-depth units, or produce a CAMELS-compatible export.

## Validation

A live public-API check on 2026-09-17 requested these three gauges for all of 2025.
It returned 1,095 rows, with 365 per gauge, `time_zone="unknown"` and no issues.
That observation describes that call, not future availability or scientific quality.
No retrieved dataset is distributed with these pages.

The repeatable documentation test checks these gauge selections offline. A separate
historical replay executes the [README retrieval](../../README.md#first-retrieval) for
station `07374000` on 2023-01-01 using committed USGS response bytes. That station is
not asserted to be a CAMELS member. The replay does not establish 2025 availability.
