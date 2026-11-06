# United Kingdom (NRFA)

The UK National River Flow Archive (NRFA), hosted by the UK Centre for Ecology &
Hydrology, publishes river-flow and gauging-station information. RivRetrieve
provides offline station discovery and metadata. Observation retrieval is not
implemented; `rr.fetch` raises `ObservationsUnavailableError` for this provider.

```python
import rivretrieve as rr

stations = rr.find(provider="uk_nrfa")
metadata = rr.metadata(stations)
```

This selects advertised flow and stage products and returns station names,
coordinates, river names, catchment areas and station altitudes. See
[station metadata](../station-metadata.md) for the returned columns.

The snapshot preserves the ten API products separately: `gdf`, `ndf`, `gmf`,
`nmf`, `gauging-flow`, `gauging-stage`, `amax-flow`, `amax-stage`, `pot-flow`
and `pot-stage`. It includes closed stations and only positively advertised
station/product associations. An omitted product is not declared unavailable.
A listing does not guarantee successful retrieval or continuous observations.
There is no automatic refresh.

Coordinates use the API's WGS84 decimal degrees unchanged. Catchment areas are
in km². Station altitude generally describes the banks of the gauge, in metres
above Ordnance Datum or, in Northern Ireland, Malin Head. It is not stage zero.
Missing metadata stays null. Public record start and end dates remain unknown:
the source's native bounds include month labels and timestamps, and their exact
coverage meaning is not established.

Use is subject to the [NRFA API terms](https://eidc.ceh.ac.uk/licences/nrfa-data-terms-and-conditions-for-api-access-to-time-series-data-and-metadata/).
NRFA has expressed in-principle support for offline station metadata and recommends
refreshing it every six months. This does not establish a general licence to
redistribute observations. Attribute the source as **“Data from the UK National
River Flow Archive”** and follow the terms' academic referencing requirements.

[NRFA API help](https://nrfaapps.ceh.ac.uk/nrfa/nrfa-api.html)
