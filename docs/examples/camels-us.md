# Recent streamflow for CAMELS-US gauges

[Documentation index](../README.md) · [Usage](../usage.md)

The CAMELS-US version 1.2 record lists time-series coverage through 31 December
2014. This example retrieves 2025 daily discharge from USGS for three CAMELS
gauges, as a starting point for extending a streamflow study beyond that period.

The identifiers and names come from the
[CAMELS gauge list](https://zenodo.org/records/15529996/files/camels_name.txt).

| Station ID | Name in CAMELS |
|---|---|
| `01013500` | Fish River near Fort Kent, Maine |
| `01022500` | Narraguagus River at Cherryfield, Maine |
| `01030500` | Mattawamkeag River near Mattawamkeag, Maine |

## Request 2025 daily discharge

Install RivRetrieve with `uv add rivretrieve`. Run the Python blocks below in
order in the same session. Retrieval needs network access but no credentials.
Keep gauge identifiers as strings so their leading zeros survive.

`find` filters established physical facts in the packaged catalogue. `pick` keeps
these three gauges. `fetch` requests the inclusive 2025 calendar window and retains
all matching source identities, including identities first published in the response.

```python
import rivretrieve as rr

selection = rr.find(
    provider="usgs_nwis", quantity="discharge", frequency="daily", statistic="mean"
)
selection = rr.pick(selection, station=["01013500", "01022500", "01030500"])
result = rr.fetch(selection, start="2025-01-01", end="2025-12-31")

print(result.issues)

# Output:
# ()
```

USGS publishes these daily means; RivRetrieve does not calculate them from
instantaneous observations. Values are converted from ft³/s to m³/s. Daily labels
retain source calendar dates with `time_zone="unknown"` in these responses.
Do not treat them as UTC instants or infer which 24 hours each daily mean represents.

## Inspect source series and coverage

`series` shows the opaque USGS series identifiers. These are available from the
packaged catalogue before retrieval. A series identifier is a source identity,
not a harmonised quality rating.

```python
source_series = rr.series(result)
print(source_series.select("station_id", "identity_namespace", "published_id").sort("station_id").rows())

# Output:
# [('01013500', 'USGS.WaterData.time_series_id', 'aa8ac20eb72d4fa58ea9c0eaf61e10ee'), ('01022500', 'USGS.WaterData.time_series_id', '02fec7bdbbe64d49a3d5414cabfa7ea8'), ('01030500', 'USGS.WaterData.time_series_id', 'b997d85e35254d278725c7506bf74fab')]
```

Keep `series_id` in grouping and joins. A gauge can publish multiple matching
series; selecting daily mean discharge does not choose a preferred one.
This summary checks each series separately, including null values and returned dates.

```python
import polars as pl

coverage = (
    result.data.group_by("station_id", "series_id")
    .agg(
        pl.len().alias("rows"),
        pl.col("time").min().dt.date().cast(pl.String).alias("first"),
        pl.col("time").max().dt.date().cast(pl.String).alias("last"),
        pl.col("value").null_count().alias("nulls"),
    )
    .sort("station_id", "series_id")
)
print(coverage.select("station_id", "rows", "first", "last", "nulls").rows())

# Output:
# [('01013500', 365, '2025-01-01', '2025-12-31', 0), ('01022500', 365, '2025-01-01', '2025-12-31', 0), ('01030500', 365, '2025-01-01', '2025-12-31', 0)]
```

These outputs come from USGS responses retrieved on 22 September 2026. Automated
tests execute every block against those exact saved responses without contacting
USGS. A later live request can differ.

Before combining observations with CAMELS records, check:

- Units and daily time definitions on both sides.
- Returned dates and gaps for each source series, not only its first and last date.
- Null values, missing rows and request issues separately. A failed request is not
  evidence that a gauge has no observations.
- Whether the source series are suitable for the study. Matching physical filters
  do not establish scientific interchangeability. Source quality flags are not
  added to harmonised observations.

For a larger study, pass more gauge identifiers to `pick` and change the dates
in `fetch`. Check each returned source series and its issues before combining
results. The packaged catalogue is a snapshot, not a guarantee of historical or
current data availability.

The [usage guide](../usage.md) explains issues, time handling and cache reuse.

## Save the observations and their context

Parquet saves the observation table, including `series_id`, `facts_id` and time zones.
A versioned bundle also retains the source definitions, inventory, outcomes,
provenance and issues needed to interpret it.

```python
from pathlib import Path

result.data.write_parquet("usgs_daily_2025.parquet")
bundle_path = Path("usgs_daily_2025.rrbundle")
bundle_path.write_bytes(rr.to_bundle(result))
restored = rr.from_bundle(bundle_path.read_bytes())
print(restored.data.height)

# Output:
# 1095
```

## Citing CAMELS and USGS

The [CAMELS version 1.2 record](https://zenodo.org/records/15529996) gives separate
citations for the time series and catchment attributes. Cite the parts you use.

For streamflow and forcing time series:

- Newman et al. (2014). *A large-sample watershed-scale hydrometeorological dataset
  for the contiguous USA*. UCAR/NCAR.
  [doi:10.5065/D6MW2F4D](https://doi.org/10.5065/D6MW2F4D)
- Newman et al. (2015). *Development of a large-sample watershed-scale
  hydrometeorological dataset for the contiguous USA: dataset characteristics and
  assessment of regional variability in hydrologic model performance*.
  [doi:10.5194/hess-19-209-2015](https://doi.org/10.5194/hess-19-209-2015)

For catchment attributes:

- Addor et al. (2017). *Catchment attributes for large-sample studies*. UCAR/NCAR.
  [doi:10.5065/D6G73C3Q](https://doi.org/10.5065/D6G73C3Q)
- Addor et al. (2017). *The CAMELS data set: catchment attributes and meteorology
  for large-sample studies*.
  [doi:10.5194/hess-21-5293-2017](https://doi.org/10.5194/hess-21-5293-2017)

The observations retrieved here come from USGS, not from the CAMELS archive.
Cite USGS and RivRetrieve as well, and retain the result provenance.
