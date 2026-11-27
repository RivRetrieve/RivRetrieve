# Ireland: OPW

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `ie_opw` |
| Country | Ireland |
| Published by | Office of Public Works (OPW), Hydrometric Section |
| Read from | Public OPW Hydro-Data service (`waterlevel.ie/hydro-data`) |
| Quantities | Discharge, stage, water temperature |
| Stations in the catalogue | 385 river gauges (`00001..41000`). Availability depends on station and quantity |
| Station metadata | Station name, water-body name, and drainage area. See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | None |
| Licence stated by OPW | Creative Commons Attribution 4.0 International (CC BY 4.0); source attribution required |
| Agency documentation | [Hydro-Data portal](https://waterlevel.ie/hydro-data/), [Licence](https://waterlevel.ie/hydro-data/html/licence.html), [Quality codes](https://waterlevel.ie/hydro-data/html/qualitycodes.html), [Data types](https://waterlevel.ie/hydro-data/html/datatypes.html), [Flow collection](https://waterlevel.ie/hydro-data/html/flowdatacollection.html), [Water level collection](https://waterlevel.ie/hydro-data/html/wldatacollection.html), [Water temperature collection](https://waterlevel.ie/hydro-data/html/tempcollectionprocess.html), [API notes](https://waterlevel.ie/page/api/) |

Retrieve one week of daily mean discharge at station `01041`, Sandy Mills on the
River Deele:

```python
import rivretrieve as rr

selection = rr.find(
    provider="ie_opw",
    station="01041",
    quantity="discharge",
    frequency="P1D",
    statistic="mean",
)

result = rr.fetch(selection, start="2025-11-10", end="2025-11-16", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print(result.issues)
print(rr.annotations(result, schema="ie_opw.series").head(3)["quality_code"].to_list())
```

Output:

```text
time,time_zone,value,unit
2025-11-10T00:00:00.000000,+00:00,6.37,m3/s
2025-11-11T00:00:00.000000,+00:00,11.117,m3/s
2025-11-12T00:00:00.000000,+00:00,11.297,m3/s
7
()
[31, 31, 31]
```

The request returns seven UTC calendar-day mean discharge rows (`[00:00Z, 24:00Z]`,
`time_zone="+00:00"`) in `m3/s`, converted from OPW's `cumec` unit. The preview
prints the first three rows, and `rr.annotations(result, schema="ie_opw.series")`
returns `quality_code=31` (flow estimated from a rating curve considered good
quality with inspected water level data) on those three days. The empty tuple
`()` in `result.issues` shows no transport, parsing, or coverage issues occurred
for this fetch.

`cache="bypass"`, the default for live `rr.fetch` calls, requests OPW Hydro-Data
directly without reading or writing a local cache. Passing `cache="reuse"` caches
per-station downloads so repeated historical queries (including daily mean/min/max
triplets from the same `year.json` endpoint) reuse the cached payload without
making extra HTTP requests. This output was checked live on 2026-11-24; OPW can
revise historical discharge values after rating-curve audits. See
[Usage](../usage.md) for general selection and result handling.

## Who measures, and who publishes

The Office of Public Works (OPW) Hydrometric Section operates the national hydrometric
monitoring network and publishes hydrometric records through [Hydro-Data](https://waterlevel.ie/hydro-data/).
OPW notes that its hydrometric operations are certified under ISO 9001:2015, while
its published data carry no guarantee of accuracy and require independent user
verification for critical applications.

No API key or account is required. RivRetrieve searches the packaged station and
series catalogue offline; `rr.fetch` then retrieves data from OPW's public
`waterlevel.ie/hydro-data/data/internet/stations/` endpoints. Station identifiers
are five-digit OPW station numbers preserved as strings with leading zeros, such
as `"01041"` and `"07012"`. Coordinates use `EPSG:4326` from OPW's published
GeoJSON station feed (`https://waterlevel.ie/geojson/`).

The packaged `ie_opw` catalogue contains `385` flowing river and stream gauges
filtered from `571` entries in OPW's static `stations.json` snapshot (2026-11-23):

- **Reference-number ceiling (`00001..41000`):** OPW's API terms limit automated
  republication to stations with reference numbers between `00001` and `41000`.
  All `76` stations above `41000` (`80101..83801`, rain gauges) are excluded.
- **Non-river and tidal exclusions within `00001..41000` (`110` gauges):** Excluded
  entries comprise `69` tidal, coastal, or estuarine gauges (`28` classified
  `Stn_Class="Tidal"`, `16` estuarine `WTO_OBJECT` gauges, and `25` additional
  coastal, polder, or tidal river-mouth stations), `31` standing lakes and lagoons
  (including Lough Corrib gauges such as `30089` Angligham, Lough Derg, Lough Ree,
  Lough Conn, and Lady's Island Lake), `4` reservoirs, hydro headraces, and
  turloughs (`16073` Marlfield Reservoir, `19094` Inniscarra Headrace, `19095`
  Carrigadrohid Headrace, and `29002` Rahasane Turlough), and `6` canal lock, bog,
  or landfill monitoring sites (`09110`, `14056`, `25058`, `26374`, `27092`,
  `30034`).
- **EPA-numbered river stations hosted on OPW:** Five flowing river stations in
  the Dublin area carrying Environmental Protection Agency numbers (`09045`
  Botanic Gardens Backup, `10047` Glenavon Park, `10048` Cherry Wood, `10049`
  Meadow Vale Park, and `10050` Brides Glen) are published on OPW Hydro-Data and
  retained in `ie_opw`. A future `ie_epa` provider may mirror these gauges.
- **Excluded Hydro-Data endpoints:** Spot flow-gauging measurements (`gaugings.json`),
  annual/hydrometric-year summaries (`annual_statistics.json`), and the 5-week
  live chart API (`waterlevel.ie/data/`) are outside RivRetrieve's scope.

Station metadata across the `385` river gauges exposes `station_name` (`385` gauges),
`WTO_OBJECT` as `water_body_name` (`383` present, `2` blank as `source_null` at
`09045` and `14124`), and `CATCHMENT_SIZE` in inline `km²` as `drainage_area`
(`380` present, including verbatim `"0.00 km²"` preserved at `25340`, `27011`, and
`30017`; `5` blank as `source_null`). `elevation` is omitted (`no_metadata`)
because `station_elevation` is blank across river stations and `station_gauge_datum`
records local staff-gauge zero height above Ordnance Datum rather than station
elevation.

## What you can retrieve

OPW Hydro-Data exposes two observation routes per measured parameter (`Q` discharge,
`S` water-level stage, and `TWater` water temperature): a daily summary JSON file
(`year.json` bundling mean, minimum, and maximum statistics) and an instantaneous
time-series ZIP archive (`*_complete.zip` holding a semicolon-delimited CSV).

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | `Q/year.json` (`WEB.Day.Mean`) | Daily | Mean | `cumec` | `m3/s` |
| `discharge` | `Q/year.json` (`WEB.Day.Min`) | Daily | Minimum | `cumec` | `m3/s` |
| `discharge` | `Q/year.json` (`WEB.Day.Max`) | Daily | Maximum | `cumec` | `m3/s` |
| `discharge` | `Q/Discharge_complete.zip` (`WEB.Cmd.Runoff`) | Unknown | Instantaneous | `cumec` | `m3/s` |
| `stage` | `S/year.json` (`WEB.Day.Mean`) | Daily | Mean | `m` | `m` |
| `stage` | `S/year.json` (`WEB.Day.Min`) | Daily | Minimum | `m` | `m` |
| `stage` | `S/year.json` (`WEB.Day.Max`) | Daily | Maximum | `m` | `m` |
| `stage` | `S/Waterlevel_complete.zip` (`WEB.Cmd.P-Continuous.Absolute`) | Unknown | Instantaneous | `m` | `m` |
| `temperature` | `TWater/year.json` (`WEB.Day.Mean-Water-Temp`) | Daily | Mean | `°C` | `degC` |
| `temperature` | `TWater/year.json` (`WEB.Day.Min-Water-Temp`) | Daily | Minimum | `°C` | `degC` |
| `temperature` | `TWater/year.json` (`WEB.Day.Max-Water-Temp`) | Daily | Maximum | `°C` | `degC` |
| `temperature` | `TWater/WaterTemperature_complete.zip` (`WEB.Cmd.P-Water-Temp`) | Unknown | Instantaneous | `°C` | `degC` |

RivRetrieve maps `cumec` to `m3/s` (without numerical scaling), preserves `m`
for stage, and normalizes `°C` to `degC`. Instantaneous `*_complete.zip` series
leave frequency unknown (`not_established`) because native cadences mix 15-minute
discharge/stage, 1-hour water temperature, and multi-decade historical logging
intervals (for example, hourly Boyne records at `07012` Slane Castle starting
`1940-06-27`).

Inspect available stations, candidate series, and station metadata offline before
fetching:

```python
river_deele = rr.find(provider="ie_opw", station="01041")
series_table = rr.series(river_deele)
station_info = rr.metadata(river_deele)
```

The packaged catalogue holds `3,788` available series and `832` confirmed
unavailable series (`0` unknown) across all `385` river stations (`4,620`
station-product pairs), based on full-network checks of OPW's `stations.json`,
`layers/{10,20,30}/index.json`, daily `year.json` files, and unindexed
`*_complete.zip` archives (checked on 2026-11-27): `197` gauges provide daily
mean discharge (`176` daily min/max and instantaneous discharge), `385` provide
daily min/max and instantaneous stage (`384` daily mean stage, with `07003`
all-null for mean), and `381` provide daily and instantaneous water temperature.
Confirmed unavailable series are excluded from `rr.find`. Daily triplets from `{param}/year.json`
share a single HTTP file per parameter and station, so selecting `P1D` mean,
min, and max with `cache="reuse"` performs one download per parameter.

Note on archive freshness: OPW rebuilds `*_complete.zip` archives overnight, so
live daily `year.json` files can include recent days slightly ahead of the
latest timestamp inside `*_complete.zip`.

## Stage references, water temperature caveats, and flow ratings

- **Stage above Ordnance Datum (`above_sea_level`, unknown vertical datum):**
  OPW Hydro-Data publishes river water levels (`S`) in metres (`m`) referenced to
  Ordnance Datum (`vertical_reference="above_sea_level"`), rather than height above
  a local gauge zero. Genuine negative water-level readings occur below Ordnance
  Datum at low-elevation coastal stretches (for example down to `-0.742 m` at
  `30061` Wolfe Tone Br) and are preserved without clamping. Because OPW's
  `stations.json` mixes `Malin Head OSGM15`, `Poolbeg`, and unlabelled
  `Malin Head` Ordnance Datum levels across sites during an ongoing datum update,
  RivRetrieve leaves `vertical_datum` unknown and never applies an inter-datum
  shift. Check each site's datum on Hydro-Data before comparing absolute water
  elevations across gauges.
- **Rating-derived discharge (`Q`):** OPW does not measure flow continuously;
  discharge is computed from water level via stage-discharge rating curves built
  from field velocity-area gaugings (`ISO 748:2021`). Weed growth, siltation,
  channel works, downstream backwater, and rating extrapolation at flood peaks can
  introduce uncertainty reflected in OPW's quality codes.
- **Uncalibrated water temperature (`TWater`):** OPW documents that Hydro-Data
  water temperature is collected solely as a pressure-transducer compensation
  by-product in varied installations (such as stilling wells or bed conduits) and
  is **neither calibrated nor quality-controlled** (typically tagged `quality_code=254`).
  Closed stations (such as `06025` Burley) or Layer-20-absent stations (such as
  `18121` Shronebeha) may return empty or unmeasured responses when requested.

## Time, missing values, and quality annotations

All Hydro-Data timestamps use fixed UTC (`+00:00`, trailing `Z`). Daily
`year.json` rows represent UTC calendar days `[00:00Z, 24:00Z]` stamped at day
start (`00:00:00Z`, `timestamp_anchor="start"`, `day_definition="+00:00"`).
Instantaneous `*_complete.zip` rows keep exact measurement timestamps
(`timestamp_anchor="measurement_time"`). `rr.to_utc(result)` operates cleanly on
all `ie_opw` series.

Missing intervals in OPW payloads appear as blank/null `Value` entries paired with
sentinel `Quality Code` `-1` or `255` (common on decommissioned or intermittent
records such as `06025` Burley). RivRetrieve omits unmeasured null cells from
`result.data` rather than interpolating values, while preserving every unmeasured
row (`measured=False`, `quality_code=-1` or `255`) inside the observation
annotation table. If every row in a requested window or file is unmeasured,
`result.data` is empty and the series retrieval status is `"empty"`.

Two observation-grain annotation schemas (`scope="observation"`) attach OPW's
native flags verbatim:

- **`ie_opw.series`** (all `12` products): `quality_code` (`Int64`), preserving
  OPW's integer WISKI Quality Code verbatim (`31`/`32` inspected/corrected good
  quality; `36` fair rating; `41`/`42`/`46` poor; `56` extrapolated rating; `96`
  provisional rating; `101` unreliable; `151` unusable dry channel or logger
  malfunction; `254` unchecked imported/provisional data; `-1`/`255` missing;
  plus other numeric WISKI codes emitted by OPW).
- **`ie_opw.daily_stage`** (`stage_daily_mean`, `stage_daily_min`,
  `stage_daily_max`): `quality_code` (`Int64`) and `aggregation_accuracy_pct`
  (`Float64`, from OPW's `Aggregation Accuracy %` column on `S/year.json`).

Use `rr.annotations(result, schema="ie_opw.series")` or
`result.to_polars(annotations=True)` to inspect quality codes alongside values;
see [Usage](../usage.md#source-annotations).

## Terms and citation

OPW publishes Hydro-Data (`00001..41000`) under the [Creative Commons Attribution
4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)
licence, in line with Irish Government PER Circular 12 of 2016 and `data.gov.ie`.
Derived works must attribute OPW, reference `waterlevel.ie/hydro-data/`, and
include OPW's disclaimer:

> Contains Irish Public Sector Information licensed under a Creative Commons Attribution 4.0 International (CC BY 4.0) licence (source http://waterlevel.ie/hydro-data/ - provided by the Office of Public Works.)

Both `rr.describe("ie_opw")` and `result.provenance` expose `license="CC BY 4.0"`
and this attribution string. Stations with reference numbers outside `00001..41000`
may not be reused or republished without express OPW permission and are excluded
from RivRetrieve. OPW's API page also asks operators of automated systems reading
Hydro-Data regularly to notify `waterlevel@opw.ie` of their intention, server IP
address, and URL; RivRetrieve limits live requests to at most one request per
second and caches full per-station responses when `cache="reuse"` is used.

## Sources

Publisher documents and endpoints verified on 2026-11-23 and live example tested
on 2026-11-24:

- [OPW Hydro-Data portal (`waterlevel.ie/hydro-data/`)](https://waterlevel.ie/hydro-data/): station registry (`stations.json`), parameter layers (`layers/{10,20,30}/index.json`), daily `year.json`, and instantaneous `*_complete.zip` archives.
- [OPW GeoJSON station feed (`waterlevel.ie/geojson/`)](https://waterlevel.ie/geojson/): `EPSG:4326` gauge coordinates.
- [OPW Hydro-Data licence page](https://waterlevel.ie/hydro-data/html/licence.html) and [OPW API page](https://waterlevel.ie/page/api/): CC BY 4.0 terms, `00001..41000` republication scope, and automated-access courtesy notice.
- [OPW quality codes](https://waterlevel.ie/hydro-data/html/qualitycodes.html) and [data types](https://waterlevel.ie/hydro-data/html/datatypes.html): integer quality code definitions, ISO 9001:2015 verification caveats, and summary statistics.
- [OPW flow](https://waterlevel.ie/hydro-data/html/flowdatacollection.html), [water level](https://waterlevel.ie/hydro-data/html/wldatacollection.html), and [water temperature collection](https://waterlevel.ie/hydro-data/html/tempcollectionprocess.html): rating-curve estimation, Poolbeg/Malin Head Ordnance Datum notes, and uncalibrated pressure-transducer water temperature warnings.

The station registry snapshot was checked on 2026-11-23, and the full-network
series availability census was checked on 2026-11-27. The live example output
was retrieved on 2026-11-24.
