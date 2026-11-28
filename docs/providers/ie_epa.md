# Ireland: EPA HydroNet

| Field | Value |
| --- | --- |
| Provider | `ie_epa` |
| Publisher | Environmental Protection Agency (EPA), HydroNet |
| Access | Catalogue only; observation retrieval is not yet available |
| Licence | CC BY 4.0 |

This page describes the packaged station catalogue. Retrieval, series meaning
and the full user guide come in later steps of the port.

## Terms

HydroNet data is licensed under CC BY 4.0. Use is subject to the notes, warnings
and conditions in the
[HydroNet disclaimer](https://epawebapp.epa.ie/Hydronet/output/html/disclaimer.html)
and [FAQ](https://epawebapp.epa.ie/Hydronet/output/html/FAQ.html). The disclaimer
asks users to make anyone they pass the data to aware of those conditions.

## Stations

The catalogue lists 385 river and stream gauges run by the EPA (snapshot of
2026-11-27): 129 active, 215 inactive and 41 suspended. A register station is
included when `RESPONSIBLE_BODY` is `Environmental Protection Agency`,
`object_type` is exactly `General;Surface water`, and its HydroNet station file
list names at least one water-level (`S`) or discharge (`Q`) `.zip` file other
than `Q/complete_gaugings.zip`.

`station_id` is the HydroNet `station_no` exactly as published, including
leading zeros and letter suffixes such as `34109A`.

The catalogue excludes:

- stations run by other bodies, even where HydroNet hosts their files
  (`26243`, `06036`, `38010`, `30111`, `18027`, `14049`);
- lakes, reservoirs and springs;
- stations with spot gaugings only;
- stations whose file list names no files, including `09045`.

`10047`–`10050` will also be published by `ie_opw`, the Office of Public Works
provider, which is still in development. `09045` will be available only
there.

Coordinates are HydroNet's `station_latitude` and `station_longitude`. No EPA or
data.gov.ie statement gives their reference system, so `crs` is `unknown`.

## Products

| Product | HydroNet file | Quantity | Unit |
| --- | --- | --- | --- |
| `stage_daily` | `S/complete_daymean.zip` | stage | m |
| `stage_15min` | `S/complete_15min.zip` | stage | m |
| `discharge_daily` | `Q/complete_daymean.zip` | discharge | m³/s |
| `discharge_15min` | `Q/complete_15min.zip` | discharge | m³/s |

Frequency, statistic and timestamp conventions are not yet established and
remain `unknown`.

## Availability

HydroNet publishes no availability field. RivRetrieve reads it from each
station's file list:

- **available**: the list names the product's full-history file. A listed file
  counts as published even when it holds no values at capture. For example,
  `37016` and `33008` list `Q/complete_daymean.zip` but the files were empty on
  2026-11-27.
- **unknown**: the list does not name the file. A missing file is not an EPA
  statement that the series does not exist, so RivRetrieve never marks it
  `unavailable`. Unknown pairs can still be selected.

Rolling files (`1year_daymean.zip`, `3_months.zip`) never set availability.
The register's free-text `DATA_AVAILABLE` field is not used either, because it
disagrees with the file lists at about 40 stations. For example, level-only
`25046` says "Water Level and Flow".

On 2026-11-27, 1,352 station-products were available and 188 unknown.

## Station metadata

`rr.metadata` reports `station_name`, the water body `WTO_OBJECT` as written,
and `CATCHMENT_SIZE` with its inline km² unit. Blank sizes are reported as
source nulls; `0.00 km²` values are kept as published. Elevation is not
reported: `station_gauge_datum` is a water-level datum, not a ground elevation.
