# Australia BoM station catalogue and metadata

Settle scope and design for [Effort #644](https://github.com/RivRetrieve/RivRetrieve/issues/644)
(step 2 of the [provider-port guide](../../docs/maintenance/provider-ports.md))
for `au_bom`. This vision covers the catalogue's design: station discovery,
coordinates, metadata, products, and the `station_product` associations. It
does not implement `origins.py`, `generate_catalogue.py`, the `catalogue/`
artifact files, or tests — those are a separate implementation PR for this
same Effort, following the same vision-then-implementation split used for
[Austria's catalogue step](https://github.com/RivRetrieve/RivRetrieve/pull/640)
(vision) and [#642](https://github.com/RivRetrieve/RivRetrieve/pull/642)
(implementation).

The port belongs to [Program #334](https://github.com/RivRetrieve/RivRetrieve/issues/334).
Builds on the merged [source, scope and access vision](2026-11-01-au-bom-source-scope-and-access.md)
(Effort #643): `LiveStages`, 18 admitted `DMQaQc.Merged.*` series across
discharge (7), stage (6) and water temperature (5). This vision does not
reopen that scope.

## Station discovery: a network-wide method, not per-station calls

A single `getTimeseriesList` request per admitted series — filtered by
`parametertype_name` and the exact `ts_name`, with no `station_no` — returns
every station that actually has that series, network-wide, in one call. This
is a materially better discovery primitive than `getStationList` filtered by
`parametertype_name` alone, which only proves the parameter type is
associated with a station, not that the specific admitted series exists
there (confirmed live on 2026-11-02: `getStationList` gave 6,922 stations
associated with "Water Course Discharge," but the actual
`DMQaQc.Merged.DailyMean.24HR` series only exists at 5,786 of them).

Checked live for the three daily-mean series on 2026-11-02:

| Series | Network-wide stations |
|---|---|
| Discharge `DailyMean.24HR` | 5,786 |
| Stage `DailyMean.24HR` | 6,777 |
| Water temperature `DailyMean.24HR` | 2,852 |
| **Union of these three** | **8,120** |

This union of the three daily-mean series is the best current estimate of the
river-gauge station universe, and is close to #334's 2026-09-22 figures
(5,710 / 6,693 / 2,846 stations respectively), confirming the method is
stable.

**All 18 admitted series checked, not just the 3 daily means.** Re-run on
2026-11-02 for the remaining 15 series (hourly, daily max/min, monthly,
yearly, across all three quantities where each applies): every one of them
returns the **exact same station set** as its quantity's daily mean, with
zero stations added or missing — discharge 5,712, stage 6,698, water
temperature 2,848, in every series. This confirms #334's aggregation-table
claim directly rather than assuming it holds. One implementation gotcha
found while checking this: a `ts_name` request missing the
`DMQaQc.Merged.` prefix returns `HTTP 200` with a well-formed, **empty**
result (`[["ts_id","station_no"]]`, header only) — not an error. The
station-product association builder must construct exact `ts_name` strings
carefully; a silent typo there produces a quietly-empty series rather than a
visible failure.

**Coordinates and station name** come from `getStationList` filtered by
`parametertype_name`, run once per quantity (3 calls): between them these
cover nearly all of the 8,120-station union, with a small remainder (116
stations in a 2026-11-02 check) needing the discharge-filtered call too to
get full coverage. The implementation PR should run all three
`parametertype_name` filters and take the union, rather than assuming any one
alone is sufficient.

## Coordinate reference system: per-station, not one blanket value

`at_ehyd` declared `crs` as one `Documented(DocumentedValue("EPSG:4326"), Evidence(...))`
constant for every station, because the LFRZ OGC API Features collection
metadata explicitly states a single storage CRS for the whole network. BoM
gives no equivalent single statement, because **BoM's stations genuinely do
not share one coordinate datum** — but this is resolved, not an open
question, once the delivered coordinates are checked against each station's
own reference system rather than assumed to be uniform.

- `getStationList`'s `station_georefsystem` field is **not constant**
  network-wide. Checked live on 2026-11-02 across 6,939 discharge-filtered
  stations: 14 distinct values, dominated by `GDA94 2D` (5,590) and
  `WGS84 (3D)` (945), with a minority on legacy or projected systems —
  `AGD66` (128), various `AMG Zone *`/`MGA Zone *` entries (around 100
  combined), and `---`/unknown (104).
- BoM's self-documenting endpoint (`request=getrequestinfo`, which lists
  every request's exact parameters and fields) states that `getStationList`'s
  `crs` *request parameter* only controls bbox-filtering behaviour, not the
  datum of returned coordinates — so toggling it (tested: `global`,
  `localxy`, `regional`) correctly made no difference and doesn't resolve
  the question by itself.
- The resolving check: compare `station_latitude`/`station_longitude`
  against the separate `station_local_x`/`station_local_y` fields (BoM's own
  "local station reference system," per `getrequestinfo`), across stations
  on different `station_georefsystem` values. Result, confirmed on multiple
  stations per case:
  - **Geographic datums** (`WGS84`, `GDA94`, and — the important case —
    `AGD66`): local and global coordinates are **byte-identical**. BoM is
    not reprojecting these; the "global" fields are each station's own
    original datum, copied through unchanged.
  - **Projected datums** (`MGA Zone *`, `AGD66`-based `AMG Zone *`): local
    and global differ, because local is in metres (e.g. `293019.3,
    6122961.1`) and global is in degrees — necessarily a projection inverse,
    which for `MGA` zones (built on `GDA94`) naturally yields `GDA94`
    coordinates, and for `AMG` zones (built on `AGD66`) yields `AGD66`
    coordinates.
  - Net effect: an `AGD66`-tagged station's delivered "global" coordinates
    carry `AGD66`'s real, roughly 200-metre offset from `GDA94`/`WGS84` in
    this part of Australia, **uncorrected**. This is a genuine source-data
    heterogeneity, not a documentation gap this vision failed to find.

**Recommendation for the implementation PR:** `STATION_CATALOG_SCHEMA.crs` is
a per-station column, not a single provider-wide constant — use that. Add a
`Field(NativeColumn("station_georefsystem"), <conversion>)` origin for `crs`
with a small conversion mapping each station's own `station_georefsystem`
value to its EPSG code, analogous to `za_dws`'s custom
`UnsignedDmsConversion`:

| `station_georefsystem` | `crs` |
|---|---|
| `WGS84`, `WGS84 (3D)` | `EPSG:4326` |
| `GDA94 2D`, `GDA94 3D`, `MGA Zone *` | `EPSG:4283` |
| `AGD66`, `AMG Zone *` | `EPSG:4202` |
| `---` / unrecognized | withheld as unknown, not guessed |

This preserves the real heterogeneity the source states, station by station,
instead of either asserting one CRS for a network that doesn't have one, or
giving up with `NotPublished` for stations where the datum is actually known.

## Station metadata is thin

Checked live on 2026-11-02: `catchment_name` returned `"---"` and
`river_name` returned empty for all 6,922 discharge-filtered stations
sampled. `object_type` is available (e.g. "Climate station;Surface
water;Water quality;General") but is a mixed-purpose tag, not a reliable
river-gauge filter on its own — the `station_product` associations built
from actual series existence (above) are the right filter, not `object_type`.

Unlike `at_ehyd` (dated gauge-zero and catchment-area history) or `br_ana`
(drainage area), `au_bom`'s descriptive station metadata is effectively
limited to station name and coordinates. This is a source fact to record,
not a gap for RivRetrieve to fill with an inferred value.

## Products: formalizing the 18 series settled in Effort #643

`station_product` associations presuppose products. The implementation PR's
`PRODUCT_CATALOG_SCHEMA` rows should be exactly the 18 series already
admitted in the merged source-access vision — no new scope here:

| Quantity | Series (frequency/statistic) | Count |
|---|---|---|
| Discharge | Hourly mean, daily mean (`24HR`+`09HR`), daily max, daily min, monthly mean, yearly mean | 7 |
| Stage | Hourly mean, daily mean (`24HR` only), daily max, daily min, monthly mean, yearly mean | 6 |
| Water temperature | Daily mean, daily max, daily min, monthly mean, yearly mean (no hourly) | 5 |

## `station_product.availability`: available or unknown, never unavailable

Follow `at_ehyd`'s convention: a station-product pair is `"available"` only
where the network-wide `getTimeseriesList` call for that exact series
directly witnessed the station; everywhere else it is `"unknown"`, never
`"unavailable"`. A station not appearing in a series' network-wide list has
not been proven to lack that series for its entire history — it is simply
not witnessed by this catalogue check.

## Registration: two hardcoded allowlists, plus the manifest

Registering `au_bom`'s catalogue needs three separate edits, none of which
implies the others:

1. One line, `"au_bom",`, in `BUILTIN_PROVIDER_IDS`
   (`src/rivretrieve/_internal/provider_manifest.py`).
2. `"au_bom"` added to `ACQUISITION_PROVENANCE_ENROLLED_PROVIDERS`
   (`src/rivretrieve/_internal/catalogues/artifact.py`) — without this,
   `acquisition_provenance` stays optional rather than required, which would
   let a build silently skip the evidence chain.
3. `ProviderId("au_bom")` added to `ORIGIN_GATE_ENROLLED_PROVIDERS`
   (`src/rivretrieve/_internal/catalogue_origins.py`) — without this,
   `enforce_catalogue_origins` refuses the build outright with a
   `FatalContractError`.

**Recommendation:** register immediately in all three places, following
`at_ehyd`'s path rather than `za_dws`'s deferred, test-fixture-only
registration. `za_dws`'s deferral appears tied to a specific disclosure/legal
review for that source (its `origins.py` notes "owner disclosure approval"
needed before packaging generated metadata); nothing found so far about BoM
suggests a comparable concern — BoM's Water Data Online content carries a
stated Creative Commons Attribution Australia licence (found in Effort #643's
research). This is a recommendation, not something this vision settles
unilaterally; confirm it holds before the implementation PR registers
`au_bom` in all three places at once.

## Prerequisite for the implementation PR: retained evidence, not live calls

Every existing provider's `generate_catalogue.py` is a pure transformer over
already-retained, already-receipted evidence (a `selection.json` plus a
`RetainedInputReceipt` from the private `verification-evidence` repository),
not a script that calls the live API itself — `at_ehyd`'s
`maintenance/catalogue/at_ehyd/official/selection.json` is the model. Before
the implementation PR can produce a real, buildable `au_bom` catalogue, the
representative BoM responses this vision and Effort #643 relied on (station
lists, network-wide timeseries lists) need to go through the archive's
intake process (`docs/maintenance/evidence.md`) and get a `selection.json` of
their own. This vision names the prerequisite; it does not perform the
intake.

## Completion

Post a concise scope update on #644 referencing this vision, including the
resolved CRS mapping and the confirmed station counts for all 18 series.
Keep #644
open until the implementation PR (origins.py, generate_catalogue.py, the
`catalogue/` artifact, the three registration edits, and tests) is merged.
