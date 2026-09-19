# Recent streamflow for CAMELS-US gauges

[Documentation index](../README.md) · [Usage](../usage.md)

The CAMELS-US dataset ends in 2014, so studies that use it often need the years since. This example
retrieves 2025 daily streamflow for three CAMELS gauges, as a starting point for extending the
series yourself.

The gauge names come from the [CAMELS gauge list](https://zenodo.org/records/15529996/files/camels_name.txt)
in the [official CAMELS record](https://doi.org/10.5065/D6MW2F4D).
See [Newman et al. (2015)](https://doi.org/10.5194/hess-19-209-2015) for the study.

| Station ID | Name in CAMELS |
|---|---|
| `01013500` | Fish River near Fort Kent, ME |
| `01022500` | Narraguagus River at Cherryfield, ME |
| `01030500` | Mattawamkeag River near Mattawamkeag, ME |

## Request 2025 daily discharge

You get one row per gauge and day of 2025, with discharge in m³/s. Keep identifiers as strings.
This example requires network access but no credentials. It reads catalogue facts first, then
requests the inclusive 2025 calendar window.

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

USGS publishes this daily product; RivRetrieve does not aggregate sub-daily values to create it.
The timestamps retain source calendar dates, paired with source-established zones or `unknown`, and
an unknown zone does not justify assuming UTC. See [time windows](../usage.md#time-windows).

Before combining these observations with existing CAMELS records, check the dates, null values and
issues, and whether each gauge returned the period your study needs.
