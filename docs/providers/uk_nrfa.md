# United Kingdom (NRFA)

[Documentation index](../README.md) · [Usage](../usage.md)

The UK National River Flow Archive (NRFA), hosted by the UK Centre for Ecology &
Hydrology, publishes river-flow, stage, and gauging-station records across the
United Kingdom. RivRetrieve provides offline station discovery and live
retrieval through the NRFA API for ten flow and stage products (`gdf`, `ndf`,
`gmf`, `nmf`, `gauging-flow`, `gauging-stage`, `amax-flow`, `amax-stage`,
`pot-flow`, and `pot-stage`).

```python
import rivretrieve as rr

selection = rr.find(
    provider="uk_nrfa",
    station="39001",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)
gdf = rr.pick(selection, variant="gdf")

result = rr.fetch(gdf, start="2020-01-01", end="2020-01-05", cache="bypass")
```

This selects gauged daily mean flow (`gdf`) at station `39001` and returns the
published values in `m3/s` with `time_zone="unknown"` and any NRFA quality flags
attached under `uk_nrfa.observations`. Use `rr.metadata(selection)` for station
names, coordinates, river names, catchment areas, and station altitudes. See
[station metadata](../station-metadata.md) for the returned columns.

## Products and physical facts

The snapshot and series definitions preserve all ten API products separately under
namespace `uk_nrfa/data-type`:

- `gdf` and `ndf`: gauged and naturalised daily flow (`discharge` in `m3/s`,
  `daily` frequency, `mean` statistic). Daily `day_definition` (09:00 GMT water
  day vs calendar-day exceptions) and `time_zone` stay unestablished.
- `gmf` and `nmf`: gauged and naturalised monthly flow (`discharge` in `m3/s`,
  `monthly` frequency, `mean` statistic). Source `YYYY-MM` labels map to nominal
  `YYYY-MM-01 00:00:00` timestamps with `time_zone="unknown"` and verbatim
  `source_label` annotations. With that carrier, a January 1-31 window includes
  January's mean and a January 15-31 window does not.
- `amax-flow` and `amax-stage`: annual maximum flow (`discharge` in `m3/s`,
  `max` flow over October-September water years) and paired stage (`m`). On
  `amax-stage`, `statistic` remains unestablished because AMAX selection is
  defined by maximum flow rather than independent stage selection.
- `pot-flow` and `pot-stage`: peaks-over-threshold events in `m3/s` and `m`, with
  `frequency` and `statistic` unestablished.
- `gauging-flow` and `gauging-stage`: manual check gaugings in `m3/s` and `m`,
  with `frequency` and `statistic` unestablished.

Peak and gauging `T00:00:00` timestamps are kept verbatim without shifting dates
or treating every midnight timestamp as an unknown clock time. The snapshot
includes closed stations and only positively advertised station/product
associations. An omitted product is not declared unavailable, and a listing does
not guarantee continuous observations. Public record start and end dates remain
unknown.

## Stage reference and bank altitude

Stage series (`gauging-stage`, `amax-stage`, `pot-stage`) are measured in metres
relative to `gauge_zero`, with historical `vertical_datum` left unestablished.
Coordinates use the API's WGS84 decimal degrees unchanged, catchment areas are
in km², and station altitude (`station-level`) generally describes the banks of
the gauge in metres above Ordnance Datum or, in Northern Ireland, Malin Head.
Station altitude is not stage zero and must not be added to stage values. Missing
metadata stays null.

## Source annotations

Series definitions and response decoders preserve NRFA annotations without
filtering or altering observations:

- `uk_nrfa.observations`: observation-grain `source_label` (verbatim API string)
  and quality `flag` (`E` estimated, `S` suspect, or null when unflagged).
- `uk_nrfa.series_metadata`: series-grain `data_type_name`, `measurement_type`,
  and `source_period` tokens copied verbatim without inferring averaging duration
  or independent stage selection.
- `uk_nrfa.amax_rejection`: series-grain `rejected_amax_years` attached strictly
  to `amax-flow` and `amax-stage`.
- `uk_nrfa.peak_rejected_periods`: series-grain `rejected_periods` attached
  strictly to `amax-flow`, `amax-stage`, `pot-flow`, and `pot-stage`.

Null and empty rejection lists stay distinct, and water-year integer encoding and
period endpoint inclusivity remain uninterpreted.

Use is subject to the [NRFA API terms](https://eidc.ceh.ac.uk/licences/nrfa-data-terms-and-conditions-for-api-access-to-time-series-data-and-metadata/).
NRFA limits client caching of API responses to temporary performance storage of no
longer than 30 calendar days, so RivRetrieve evicts cached NRFA responses older
than 30 days automatically.
Offline station metadata reflects NRFA's in-principle support (recommended six-month
refresh) and does not establish a general licence to redistribute observations.
Attribute the source as **“Data from the UK National River Flow Archive”** and
follow the terms' academic referencing requirements.

[NRFA API help](https://nrfaapps.ceh.ac.uk/nrfa/nrfa-api.html)
