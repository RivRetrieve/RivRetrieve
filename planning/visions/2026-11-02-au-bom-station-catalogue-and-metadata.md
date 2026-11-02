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
stable. **Not yet verified:** whether the other 15 admitted series (hourly,
daily max/min, monthly, yearly) are published at the same stations as their
quantity's daily mean, or at a smaller subset. Issue #334's aggregation table
reports identical station counts per quantity across frequencies, but this
vision doesn't re-run all 18 network-wide calls to confirm it — the
implementation PR builds the full `station_products` table from all 18 calls
directly, which checks this as a side effect. Record the actual counts there
rather than trusting this vision's 3-series shortcut.

**Coordinates and station name** come from `getStationList` filtered by
`parametertype_name`, run once per quantity (3 calls): between them these
cover nearly all of the 8,120-station union, with a small remainder (116
stations in a 2026-11-02 check) needing the discharge-filtered call too to
get full coverage. The implementation PR should run all three
`parametertype_name` filters and take the union, rather than assuming any one
alone is sufficient.

## Coordinate reference system: an open question, not a settled fact

`at_ehyd` could declare `crs` as `Documented(DocumentedValue("EPSG:4326"), Evidence(...))`
because the LFRZ OGC API Features collection metadata explicitly states the
storage CRS. **BoM gives no equivalent explicit statement found so far, and
the evidence here is more ambiguous than that case:**

- `getStationList`'s `station_georefsystem` field is **not constant**
  network-wide. Checked live on 2026-11-02 across 6,939 discharge-filtered
  stations: 14 distinct values, dominated by `GDA94 2D` (5,590) and
  `WGS84 (3D)` (945), with a long tail of legacy or projected systems —
  `AGD66` (128), various `AMG Zone *`/`MGA Zone *` entries (around 100
  combined), and `---`/unknown (104).
- Despite that, `station_latitude`/`station_longitude` are always plain
  decimal-degree values in valid Australian ranges regardless of the tagged
  `station_georefsystem` — confirmed by direct comparison across stations
  tagged `WGS84 (3D)`, `MGA Zone 54`, `AGD66` and `WGS84`. None of them
  returned raw projected eastings/northings.
- Tested whether the service's `crs` request parameter (accepted values:
  `global`, `localxy`, `regional` — not EPSG codes) changes the delivered
  `station_latitude`/`station_longitude` for an `AGD66`-tagged station: it
  does not. All three modes returned byte-identical coordinate values.

This leaves genuine ambiguity: `station_georefsystem` may simply record each
station's **original survey datum** for provenance, while delivered
coordinates are already uniformly reprojected to one modern datum (in which
case declaring `GDA94`/`WGS84` network-wide would be safe, since the two are
within about a metre of each other) — or the `AGD66`/`AMG`/`MGA`-tagged
stations' delivered coordinates may still carry their original datum's
positional offset (`AGD66` differs from `GDA94`/`WGS84` by roughly 200
metres in this part of Australia), in which case declaring one CRS for the
whole network would be wrong for that minority of stations. Neither BoM's
public site content nor the KiWIS service's own parameters resolved this
during this check.

**Recommendation for the implementation PR:** do not use `Documented` for
`crs` the way `at_ehyd` did. Either find explicit documentation (BoM's water
data API reference, if one exists beyond what this vision checked) stating
the delivered-coordinate datum, or use `NotPublished`/`Withheld` the way
`za_dws` did when a provider's coordinate datum is genuinely unresolved, and
record the `station_georefsystem` ambiguity itself as a recorded unknown. Do
not assume `GDA94`/`WGS84` "because most stations say so."

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

Post a concise scope update on #644 referencing this vision and its open
questions (CRS, the un-reverified 15-of-18 series station counts). Keep #644
open until the implementation PR (origins.py, generate_catalogue.py, the
`catalogue/` artifact, the three registration edits, and tests) is merged.
