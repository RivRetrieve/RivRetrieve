# usgs_nwis Provider Port Notes

This is a historical WaterServices implementation record. Current provider behavior
is described in the USGS provider documentation. Original recordings are retained
in the private source archive; their paths below identify historical inputs.


The USGS provider reads NWIS Water Services directly, without credentials.
See [Architecture](../architecture.md) for the shared retrieval stages.

## Requests and products

Observation requests use `https://waterservices.usgs.gov/nwis/dv/` for daily
values and `https://waterservices.usgs.gov/nwis/iv/` for instantaneous values.
Both send `format=json`, `sites`, `startDT`, `endDT`, and `parameterCd`.
Daily requests also send `statCd`.

On 2026-09-19, the instantaneous URL returned HTTP 301 to
`https://nwis.waterservices.usgs.gov/nwis/iv/`; the daily URL answered directly.
The shared transport follows redirects. The original host remains the requested
URL in [fetch](../../src/rivretrieve/_internal/providers/usgs_nwis/fetch.py)
and [acquisition provenance](../../src/rivretrieve/_internal/providers/usgs_nwis/origins.py).

| Product | Endpoint | Parameter | Statistic | Native unit | Returned unit |
| --- | --- | --- | --- | --- | --- |
| `discharge_daily_mean` | `dv` | `00060` | `00003` | ft³/s | m³/s |
| `discharge_instantaneous` | `iv` | `00060` | none | ft³/s | m³/s |
| `stage_daily_mean` | `dv` | `00065` | `00003` | ft | m |
| `stage_daily_max` | `dv` | `00065` | `00001` | ft | m |
| `stage_daily_min` | `dv` | `00065` | `00002` | ft | m |
| `stage_instantaneous` | `iv` | `00065` | none | ft | m |

The shared conversion stage multiplies discharge by `0.028316846592` and stage
by `0.3048`. These are source-published products, not locally aggregated series.
The engine supplies inclusive date bounds; fetch sends one request per
station-product pair for those rendered bounds. It does not impose annual windows.
Source-call failures become shared issues for the affected series; HTTP 404 uses
`source.http_not_found`.

## Time and rows

Instantaneous values carry an offset. Parse keeps the source wall-clock timestamp
and puts its offset in `time_zone`. The [instantaneous recording](https://github.com/RivRetrieve/verification-evidence)
contains `2023-01-01T00:00:00.000-06:00`. The [DST recording](https://github.com/RivRetrieve/verification-evidence)
changes from `01:45-06:00` to `03:00-05:00` on 2023-03-12.

Daily values are local-date labels with no stated zone. The [daily recording](https://github.com/RivRetrieve/verification-evidence)
contains `2023-01-01T00:00:00.000`; parse retains midnight and reports `unknown`.
The payload's `sourceInfo.timeZoneInfo` describes the station. It is not applied
to daily values. A midnight label does not establish the daily interval's zone.

Rows contain only `time`, `time_zone`, `station_id`, `product_id`, and `value`.
Parse does not convert to UTC or emit qualifier, raw-value, or series-annotation
columns. Qualifiers remain in the source bytes, available through receipts.
`to_utc` is separate and rejects rows with an unknown zone.

Parse takes station and product identity from the payload's tagged pair and
semantics from the product configuration. It does not validate returned station,
parameter, statistic, or unit metadata. Invalid numeric values and no-data
sentinels are dropped with issues.

Service documentation: [daily values](https://waterservices.usgs.gov/docs/dv-service/daily-values-service-details/)
and [instantaneous values](https://waterservices.usgs.gov/docs/instantaneous-values/instantaneous-values-details/).

## Catalogue

The retained historical native table contains 26,258 stations and 2,036,546 aligned
source-series rows from the 50 states plus DC. Catalogue refresh requests RDB
from `https://waterservices.usgs.gov/nwis/site/`, using `siteType=ST`,
`hasDataTypeCd=dv`, `parameterCd=00060,00065`, and each `stateCd`.
Separate passes use `seriesCatalogOutput=true` and `siteOutput=expanded`.
The generator checks matching station sets and shared fields. It retains the
42 expanded fields as strings, twelve aligned series-field lists, and a retrieval
instant. Canonical builds read the attested native table offline.

`site_no` supplies `station_id`; `provider_id` is the authored constant
`usgs_nwis`. Decimal coordinates become floats without reprojection.
The datum mapping is NAD27→EPSG:4267, NAD83→EPSG:4269, OLDHI→EPSG:4135,
WGS72→EPSG:4322, and WGS84→EPSG:4326; other tokens become `unknown`.
Availability matches the exact `(data_type_cd, parm_cd, stat_cd)` series key:
`dv` for daily products, `uv` with an empty statistic for instantaneous products.
Agreeing nonblank coverage dates are retained; blank or conflicting dates remain
null with an explicit reason.

Drainage fields remain native strings. `drain_area_va` is published in square
miles in the [USGS site-service documentation](https://waterservices.usgs.gov/docs/site-service/site-service-details/).
Catalogue generation does not convert drainage areas. See [station metadata](../station-metadata.md)
for the separate packaged projection.
