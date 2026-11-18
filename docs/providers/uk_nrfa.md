# United Kingdom (NRFA)

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `uk_nrfa` |
| Country | United Kingdom |
| Published by | UK National River Flow Archive (NRFA), hosted by the UK Centre for Ecology & Hydrology (UKCEH) |
| Read from | NRFA web service API (`nrfaapps.ceh.ac.uk/nrfa/ws`) |
| Quantities | Discharge and stage (ten published flow and stage products) |
| Stations in the catalogue | 1,604 (all have at least one selectable series; availability varies by product and period) |
| Station metadata | Station name, water-body name, catchment area, and station altitude. See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | None |
| Terms | Click-Through Licence for NRFA API access (30-day client cache limit; attribution required). See [Terms and citation](#terms-and-citation) |
| Agency documentation | [NRFA API help](https://nrfaapps.ceh.ac.uk/nrfa/nrfa-api.html), [NRFA glossary](https://nrfa.ceh.ac.uk/help/nrfa-glossary) |

Retrieve five days of gauged daily mean discharge at station `39001`, Thames at Kingston:

```python
import rivretrieve as rr

selection = rr.find(
    provider="uk_nrfa",
    station="39001",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)
print(sorted(rr.series(selection)["published_id"].to_list()))

gdf = rr.pick(selection, variant="gdf")
result = rr.fetch(gdf, start="2020-01-01", end="2020-01-05", cache="bypass")

preview = (
    result.to_polars(annotations=["source_label", "flag"])
    .select("time", "time_zone", "value", "unit", "source_label", "flag")
    .head(3)
)
print(preview.write_csv(), end="")

print(result.data.height)
print(result.issues)
```

Output:

```text
['gdf', 'ndf']
time,time_zone,value,unit,source_label,flag
2020-01-01T00:00:00.000000,unknown,157.3,m3/s,2020-01-01,S
2020-01-02T00:00:00.000000,unknown,135.5,m3/s,2020-01-02,S
2020-01-03T00:00:00.000000,unknown,130.7,m3/s,2020-01-03,S
5
()
```

Station `39001` publishes both gauged (`gdf`) and naturalised (`ndf`) daily mean
discharge, so `rr.find(...)` lists both identifiers in the `published_id` column
of `rr.series(selection)`. Calling `rr.pick(selection, variant="gdf")` selects
only the gauged series (`variant` matches NRFA's published data-type identifier);
fetching `selection` without picking returns rows for both products.

The request returned five daily mean flows in `m3/s` for 1 to 5 January 2020
with `time_zone="unknown"` and NRFA observation annotations (`source_label` and
`flag`). All three preview rows carry `flag="S"` (suspect in NRFA's flag
vocabulary), which RivRetrieve preserves without filtering or ranking values.
The empty tuple `()` means retrieval completed without transport, structure, or
policy issues; it does not mean the observations are unflagged or continuous
outside this window.

`cache="bypass"` requests NRFA's service directly rather than reading or writing
a local cache. This output was checked live on 2026-11-18. Because NRFA updates
the archive periodically and can revise historical records, a later retrieval
need not match these values identically, and successful retrieval for these five
days does not establish continuous coverage. See [Usage](../usage.md) for
general selection and result handling.

## Who measures, and who publishes

The UK National River Flow Archive (NRFA), hosted by the UK Centre for Ecology &
Hydrology (UKCEH), collates, quality-controls, and publishes hydrometric records
from monitoring networks across Great Britain and Northern Ireland. Regional
measuring authorities collect the field observations and supply them to NRFA,
including the Environment Agency (England), Natural Resources Wales, the
Scottish Environment Protection Agency, and the Department for Infrastructure -
Rivers (Northern Ireland). NRFA is the national archive publisher rather than the
field operator of every gauge.

RivRetrieve reads the curated archive served by NRFA's web service API at
retrieval time, rather than real-time operational telemetry. `uk_nrfa` remains
separate from Environment Agency operational feeds and does not stitch live
telemetry onto archive records. Access is open and requires no API key or user
credentials.

RivRetrieve discovers stations and supported products from a packaged offline
catalogue snapshot. Station identifiers are NRFA integer gauge numbers stored as
strings without leading zeros, such as `"39001"` (Thames at Kingston) and
`"201002"` (Fairywater at Dudgeon Bridge in Northern Ireland).

Rainfall products, runoff-depth conversions, numbered bulk peak-flow releases
(such as WINFAP/FEH release packages), and enquiry-only records are outside
`uk_nrfa`'s scope. No water-temperature product was found in the NRFA API
documentation reviewed; RivRetrieve makes no claim about whether UKCEH holds
water-temperature data outside the API.

## What you can retrieve

RivRetrieve keeps all ten supported NRFA API data types separate under
namespace `uk_nrfa/data-type`. The `Source field / variant` column lists NRFA's
API `data-type` identifier (`published_id` and `product_id` in `rr.series(...)`,
matched by `variant=...`):

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | `gdf` (Gauged Daily Flow) | Daily | Mean | m3/s | m3/s |
| `discharge` | `ndf` (Naturalised Daily Flow) | Daily | Mean | m3/s | m3/s |
| `discharge` | `gmf` (Gauged Monthly Flow) | Monthly | Mean | m3/s | m3/s |
| `discharge` | `nmf` (Naturalised Monthly Flow) | Monthly | Mean | m3/s | m3/s |
| `discharge` | `amax-flow` (Annual Maxima - Flow) | Unknown | Maximum | m3/s | m3/s |
| `stage` | `amax-stage` (Annual Maxima - Stage) | Unknown | Unknown | m | m |
| `discharge` | `pot-flow` (Peaks Over Threshold - Flow) | Unknown | Unknown | m3/s | m3/s |
| `stage` | `pot-stage` (Peaks Over Threshold - Stage) | Unknown | Unknown | m | m |
| `discharge` | `gauging-flow` (Gauging - Flow) | Unknown | Unknown | m3/s | m3/s |
| `stage` | `gauging-stage` (Gauging - Stage) | Unknown | Unknown | m | m |

Discharge is published in `m3/s` and stage in `m`, so RivRetrieve returns
numeric values without unit conversion.

- **Daily and monthly flows (`gdf`, `ndf`, `gmf`, `nmf`):** Gauged series
  (`gdf`, `gmf`) preserve observed river flows (1,574 stations in the packaged
  snapshot), while naturalised series (`ndf` at 123 stations, `nmf` at 336
  stations) reflect NRFA adjustments for artificial influences such as
  abstractions and reservoirs. Monthly flows (`gmf`, `nmf`) are fetched directly
  from NRFA's published monthly series rather than computed locally from daily
  flows.
- **Annual maxima (`amax-flow`, `amax-stage`):** NRFA selects annual maxima over
  an October to September water year (949 stations advertise `amax-flow`; 917
  advertise `amax-stage`). RivRetrieve sets `statistic="max"` on `amax-flow` and
  leaves `frequency` unknown because water-year event selection is neither a
  calendar-year aggregate nor a uniform interval. On `amax-stage`, `statistic`
  also remains unknown (even though NRFA's response header sets
  `measurement-type` to `"Maximum"` and `period` to `"PT15M"`) because NRFA
  defines AMAX events by maximum water-year flow rather than establishing an
  independent maximum-stage selection rule.
- **Peaks over threshold (`pot-flow`, `pot-stage`):** Flood peaks exceeding a
  station threshold (894 stations advertise `pot-flow`; 865 advertise
  `pot-stage`). Both `frequency` and `statistic` remain unknown, and NRFA's
  `PT15M` header token is kept in annotations without treating every event as a
  15-minute average.
- **Check gaugings (`gauging-flow`, `gauging-stage`):** Manual field gaugings
  used for rating-curve calibration and validation (910 stations advertise each
  product). Both `frequency` and `statistic` remain unknown, and NRFA's `PT1S`
  header token is kept verbatim without implying continuous one-second
  sampling.

Because `amax-stage`, `pot-flow`, `pot-stage`, `gauging-flow`, and
`gauging-stage` have no established `frequency` or `statistic`, do not filter on
those arguments when selecting them. Use `rr.find(provider="uk_nrfa", station=..., variant=...)`
or narrow an existing selection with `rr.pick(selection, variant=...)`. See
[Series selection](../usage.md#when-an-agency-publishes-more-than-one-version) for
details.

## Availability and archive updates

The packaged catalogue snapshot (2026-11-06) retains 1,604 stations, including
closed stations, and 9,052 positively advertised station-product associations.
Only positively advertised products appear in the catalogue; an omitted product
is not declared unavailable, and a station listing does not guarantee
observations for any requested period or continuous gap-free records.

The packaged catalogue does not publish start or end dates for station records
because NRFA's station summary mixes dates, year-months, and timestamps whose
exact coverage meaning is undocumented.

Historical depth varies by station and product, reaching back to 1883 at
long-running gauges such as `39001` (Thames at Kingston). Recent observations
trail real time because NRFA updates the archive periodically rather than
publishing real-time telemetry. NRFA's API terms also note that time-series
data and metadata change through rolling archive updates. Response timestamps
reflect when NRFA generated the response rather than an immutable dataset
version, so current retrievals can differ from earlier frozen datasets such as
CAMELS-GB.

## Stage reference and station metadata

Stage series (`amax-stage`, `pot-stage`, `gauging-stage`) are returned in metres
(`m`) relative to the station's local `gauge_zero`
(`vertical_reference="gauge_zero"`), which at some stations includes an arbitrary
datum offset. Historical stage `vertical_datum` (including any datum resets over
a station's lifetime) remains unknown (`vertical_datum` is `None` in
`rr.series(...)`).

Station coordinates (`latitude`, `longitude`) preserve NRFA's decimal-degree
values unchanged in `EPSG:4326` (WGS84), confirmed by NRFA across Great Britain,
Northern Ireland, and closed stations.

`rr.metadata(selection)` returns offline station attributes from the packaged
snapshot: station name (`name`), river name (`river`), catchment area
(`catchment-area` in `km²`), and station altitude (`station-level` in `m`, which
is `null` at 64 stations in the snapshot). See [Station metadata](../station-metadata.md)
for column structure and decoding.

Station altitude (`station-level`) generally describes the banks at the gauging
station. In the packaged catalogue, `elevation_datum` in
`rr.metadata(selection)` is `["Ordnance Datum"]` for 1,550 stations (mainland
Britain and surrounding islands) and `["Malin Head"]` for 54 stations (Northern
Ireland), shown as `"Ordnance Datum"` and `"Malin Head"` in `source_datum` when
`view="source"`. RivRetrieve assigns these datums from NRFA's six-digit
regional station numbering within the UK inventory without strengthening
`"Ordnance Datum"` to a specific vertical CRS. Station altitude is not gauge
zero and must never be added to stage values.

## Time, annotations, and missing data

Although NRFA's API help notes that time-series date and time values are in
UTC, RivRetrieve sets `time_zone="unknown"` across all ten products
(`rr.to_utc(...)` refuses `unknown` time zones rather than assuming a uniform
offset):

- Daily `gdf` and `ndf` responses publish `YYYY-MM-DD` dates, and NRFA describes
  the standard UK water day as starting at 09:00 GMT with calendar-day
  exceptions; which definition applies at a given station and period remains
  unestablished (`day_definition` is `None`).
- Monthly `gmf` and `nmf` responses publish `YYYY-MM` labels without a time of
  day or offset.
- Peak and check-gauging responses (`amax-flow`, `amax-stage`, `pot-flow`,
  `pot-stage`, `gauging-flow`, `gauging-stage`) publish `YYYY-MM-DDTHH:MM:SS`
  strings without a UTC offset. NRFA documentation notes that midnight timestamps
  can indicate unknown clock times in some peak contexts, but JSON responses do
  not distinguish unknown clocks from genuine midnight events, so RivRetrieve
  preserves `T00:00:00` timestamps unchanged without shifting dates.

Window selection follows each product's label resolution:

- **Daily, peak, and check-gauging products:** Bare start and end dates cover
  the full calendar days (`00:00:00` to `23:59:59`). When explicit clock times
  are supplied, daily products (`gdf`, `ndf`) still select whole calendar days,
  whereas peak and check-gauging products clip to the exact timestamps.
- **Monthly products (`gmf`, `nmf`):** RivRetrieve places `YYYY-MM` labels at
  `YYYY-MM-01T00:00:00` in `time` while preserving the original `"YYYY-MM"`
  string in `source_label`. Under that convention, `start="2020-01-01"` to
  `end="2020-01-31"` includes January (`2020-01`), whereas
  `start="2020-01-15"` to `end="2020-03-15"` excludes January (`2020-01-01`)
  and returns February and March (`2020-02-01` and `2020-03-01`). Because
  NRFA's API compares monthly bounds against month-end dates and drops partial
  trailing months, RivRetrieve fetches `gmf` and `nmf` without server date
  filters and clips to your requested window locally.

RivRetrieve preserves NRFA quality flags, header metadata, and peak-flow
rejection metadata verbatim without dropping or altering observations:

- `uk_nrfa.observations`: attaches `source_label` (verbatim API date, month, or
  timestamp string) and `flag` (`"E"` for estimated, `"S"` for suspect, or
  `null` when unflagged) to each observation row.
- `uk_nrfa.series_metadata`: attaches `data_type_name`, `measurement_type`
  (`"Mean"`, `"Measured"`, or `"Maximum"`), and `source_period` (`"P1D"`,
  `"P1M"`, `"PT15M"`, or `"PT1S"`) from the response header to each retrieved
  series.
- `uk_nrfa.amax_rejection`: attaches `rejected_amax_years` (`List(Int64)`,
  nullable) strictly to `amax-flow` and `amax-stage`.
- `uk_nrfa.peak_rejected_periods`: attaches `rejected_periods` (`List(String)`,
  nullable) strictly to `amax-flow`, `amax-stage`, `pot-flow`, and `pot-stage`.

Pass `annotations=True` to `result.to_polars(...)` or `result.to_pandas(...)` to
include observation annotations, `rr.series(result, annotations=True)` to join
series annotations, or `rr.annotations(result)` to inspect all attached schemas.
When a retrieval returns zero rows (`result.data.is_empty()`),
`uk_nrfa.observations` has no rows and is omitted from the result, so passing
specific observation column names such as `annotations=["flag"]` raises a
`ValueError`; check `result.data.is_empty()` or use `annotations=True` when
handling potentially empty windows. See [Source annotations](../usage.md#source-annotations)
for general usage.

Peak rejection lists are retrieved from NRFA's station-level
`peak-flow-metadata` endpoint and are preserved as published. `null` metadata and
empty lists (`[]`) stay distinct, and RivRetrieve leaves water-year integer
encoding, period endpoint inclusivity, and stage-specific rejection judgement
uninterpreted.

Missing data and retrieval failures remain distinct:

- Dates omitted from NRFA's `data-stream` stay absent (no rows are fabricated),
  even when the response `interval` header spans those dates.
- Any explicit JSON `null` values in `data-stream` are kept as rows with
  `value=null`.
- For an advertised product, a window with no published observations
  (`data-stream: []`) returns zero rows, records `['empty']` in the `outcomes`
  column of `rr.series(result)` (with `status="empty"` on `result.outcomes`),
  and emits no error in `result.issues`.
- Requesting an unadvertised `variant` at a catalogued station (such as
  `variant="ndf"` at station `"6007"`) emits a `selection.unresolved_inventory`
  warning in `rr.find(...)`; `rr.fetch(...)` then checks the station's
  advertised products and reports `source.no_match` warnings with zero rows.
  Station identifiers absent from the packaged catalogue raise
  `UnknownStationError` offline in `rr.find(...)`.
- Server errors, malformed payloads, or HTTP failures during `rr.fetch(...)`
  record a `failed` outcome on `result.outcomes` and an entry in
  `result.issues` without discarding other successful series in the same
  request. Check [Issues](../usage.md#issues) before interpreting an empty
  result.

## Terms and citation

Use of NRFA data and metadata through the API is governed by the
[NRFA API terms and conditions](https://eidc.ceh.ac.uk/licences/nrfa-data-terms-and-conditions-for-api-access-to-time-series-data-and-metadata/).
NRFA's website also hosts a separate non-API terms page; RivRetrieve records and
follows the API-specific terms linked directly from NRFA's API documentation.

Clause 3.5 of the NRFA API terms limits client caching to temporary performance
storage of no longer than 30 calendar days. RivRetrieve sets `cache="bypass"` by
default for live retrievals and evicts cached NRFA responses older than 30
calendar days whenever caching is active (`cache="reuse"` or `cache="refresh"`);
expired entries remain on disk until the next cached call or
`rr.clear_cache("uk_nrfa")`.

The packaged offline station catalogue reflects NRFA's in-principle support for
offline discovery (with a recommended six-month metadata refresh). RivRetrieve
does not automatically refresh the packaged catalogue at runtime, and offline
station metadata does not grant a general licence to redistribute observations.

Attribute retrieved data as:

> Data from the UK National River Flow Archive

Both `rr.describe("uk_nrfa")` and `result.provenance` provide:

- `citation`: `Data from the UK National River Flow Archive`
- `license`: `Click-Through Licence for Access to UK National River Flow Archive Data Available from the UK Centre for Ecology & Hydrology`

Academic and scientific publications must also follow the terms' scientific
referencing and DOI citation requirements.

## Sources

Official publisher pages and references checked during this port (2026-11-06 and
2026-11-16) and verified reachable on 2026-11-18:

- [NRFA API help](https://nrfaapps.ceh.ac.uk/nrfa/nrfa-api.html): `/station-ids`, `/station-info`, `/time-series`, `data-type` metadata, UTC note, and `E`/`S` flags.
- [NRFA API terms and conditions](https://eidc.ceh.ac.uk/licences/nrfa-data-terms-and-conditions-for-api-access-to-time-series-data-and-metadata/): 30-day cache limit, rolling data updates, and attribution requirements.
- [Gauged daily flow data](https://nrfa.ceh.ac.uk/data/about-data/daily-flow-data/gauged-daily-flow-data) and [Naturalised flow series](https://nrfa.ceh.ac.uk/data/about-data/daily-flow-data/naturalised-flow-series): daily flow definitions and 09:00 GMT water-day conventions.
- [Derived data series](https://nrfa.ceh.ac.uk/data/about-data/daily-flow-data/derived-data-series): gauged and naturalised monthly mean flows.
- [Annual maximum](https://nrfa.ceh.ac.uk/data/about-data/peak-flow-data/data-types/annual-maximum), [Peaks over threshold](https://nrfa.ceh.ac.uk/data/about-data/peak-flow-data/data-types/peaks-over-threshold-pot), [Missing and rejected data](https://nrfa.ceh.ac.uk/data/about-data/peak-flow-data/data-types/missing-and-rejected-data), and [Ratings and datums](https://nrfa.ceh.ac.uk/data/about-data/peak-flow-data/data-types/ratings-datums): peak-flow selection, water years, rejection metadata, and gauge-zero references.
- [Hydrometric information](https://nrfa.ceh.ac.uk/data/about-data/gauging-station-information/hydrometric-information), [Locational information](https://nrfa.ceh.ac.uk/data/about-data/gauging-station-information/locational-information), [Station number](https://nrfa.ceh.ac.uk/data/about-data/gauging-station-information/station-number), [Hydrometric areas](https://nrfa.ceh.ac.uk/data/about-data/gauging-station-information/hydrometric-areas), and [NRFA glossary](https://nrfa.ceh.ac.uk/help/nrfa-glossary): station numbering, bank altitudes, Ordnance Datum / Malin Head, and check gaugings.
- Coxon et al. (2020), CAMELS-GB (*Earth System Science Data* 12, 2459-2483, [doi:10.5194/essd-12-2459-2020](https://doi.org/10.5194/essd-12-2459-2020)): ten-gauge shared-source consistency check of `gdf` against pre-2020 NRFA extracts (not independent measurement validation or coverage of the other nine products).

The station and product counts describe the packaged catalogue snapshot
(2026-11-06). The opening example was checked live on 2026-11-18 and does not
establish continuous coverage. Detailed verification records remain in the
[private verification archive](https://github.com/RivRetrieve/verification-evidence#readme).
