# Recent streamflow for CAMELS-US gauges

[Documentation index](../README.md) · [Usage](../usage.md)

The pionerring CAMELS-US dataset has been used in thousands of hydrological studies since its
publication by [Addor et al. (2015)](https://doi.org/10.5194/hess-21-5293-2017). However, the
dataset ends in 2014, so studies that use it often need the years since.
This example retrieves 2025 daily streamflow for three CAMELS gauges, as a starting point for
extending the series yourself.

The gauge names come from the
[CAMELS gauge list](https://zenodo.org/records/15529996/files/camels_name.txt). The papers and data
records to cite are listed at the [end of this page](#citing-camels-and-usgs).

| Station ID | Name in CAMELS |
|---|---|
| `01013500` | Fish River near Fort Kent, ME |
| `01022500` | Narraguagus River at Cherryfield, ME |
| `01030500` | Mattawamkeag River near Mattawamkeag, ME |

## Request 2025 daily discharge

You get one row per gauge and day of 2025, with discharge in m³/s. Remember to keep identifiers
as strings.
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

USGS publishes this daily product. The timestamps retain source calendar dates, paired with
source-established zones or `unknown`, and
an unknown zone does not justify assuming UTC. See the [usage guide](../usage.md) on time windows.

## More gauges, more years

The same three calls work for the whole CAMELS set: pass every gauge identifier to `pick`, and
widen the window. Two things help when the request grows:

```python
gauges = [line.split(";")[0] for line in open("camels_name.txt").read().splitlines()[1:]]

selection = rr.pick(rr.find(provider="usgs_nwis", product="discharge_daily_mean"), station=gauges)
result = rr.fetch(selection, start="1980-01-01", end="2025-12-31", cache="reuse")
```

`cache="reuse"` keeps what you already retrieved, so a second run only asks for what is missing.
Check `result.issues` afterwards: a gauge that failed is not the same as a gauge with no data.

## Saving and combining

`result.data` is a Polars frame. Write it out, or convert it for pandas users:

```python
result.data.write_parquet("usgs_daily_2025.parquet")
frame = result.data.to_pandas()
```

Before merging with existing CAMELS records, check that:

- the **units** match. RivRetrieve returns m³/s; confirm what your CAMELS copy uses before joining.
- the **dates** line up, including how each side treats a day boundary.
- **null values** and `result.issues` are understood, gauge by gauge.
- each gauge actually returned the period your study needs.

## Citing CAMELS and USGS

CAMELS asks for a data citation and an associated paper for each part of the dataset. For the
streamflow and forcing time series:

- Newman, A., Sampson, K., Clark, M. P., Bock, A., Viger, R. J., Blodgett, D. (2014). A
  large-sample watershed-scale hydrometeorological dataset for the contiguous USA. Boulder, CO:
  UCAR/NCAR. [doi:10.5065/D6MW2F4D](https://doi.org/10.5065/D6MW2F4D)
- Newman, A. J., Clark, M. P., Sampson, K., Wood, A., Hay, L. E., Bock, A., Viger, R. J.,
  Blodgett, D., Brekke, L., Arnold, J. R., Hopson, T., Duan, Q. (2015). Development of a
  large-sample watershed-scale hydrometeorological dataset for the contiguous USA: dataset
  characteristics and assessment of regional variability in hydrologic model performance.
  *Hydrology and Earth System Sciences*, 19, 209–223.
  [doi:10.5194/hess-19-209-2015](https://doi.org/10.5194/hess-19-209-2015)

And for the catchment attributes:

- Addor, N., Newman, A., Mizukami, M., Clark, M. P. (2017). Catchment attributes for large-sample
  studies. Boulder, CO: UCAR/NCAR.
  [doi:10.5065/D6G73C3Q](https://doi.org/10.5065/D6G73C3Q)
- Addor, N., Newman, A. J., Mizukami, N., Clark, M. P. (2017). The CAMELS data set: catchment
  attributes and meteorology for large-sample studies. *Hydrology and Earth System Sciences*, 21,
  5293–5313. [doi:10.5194/hess-21-5293-2017](https://doi.org/10.5194/hess-21-5293-2017)

The gauge list linked above comes from version 1.2 of the
[CAMELS record on Zenodo](https://zenodo.org/records/15529996), published in 2022, which carries
these same citations.

The observations you retrieve here come from USGS, which states its own terms and citation, so
cite USGS and RivRetrieve as well.
