# Vision: catalogue origins

Program: https://github.com/RivRetrieve/RivRetrieve/issues/6
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/8

## Goal / Why

A null in the packaged catalogue means two incompatible things and nothing can tell them
apart: *the source publishes nothing*, or *we never asked*. `CONTEXT.md` defines
[[unknown]] as "a representable state meaning the source does not tell us", and the
shipped catalogue cannot substantiate that claim for a single cell.

This is not hypothetical. Verified in the committed artefacts:

- `usgs_nwis` carries `begin_date` as a key on all 26,231 station blobs, every one `None`,
  so `start_date` is null for the whole provider. USGS publishes period of record; the site
  service returns it under `seriesCatalogOutput=true` and our generator calls the default
  output. The catalogue states, indistinguishably from fact, that USGS has no start dates.
- `br_ana`'s 52,145 `station_products` rows say `availability = unknown` with the reason
  *"ANA catalogue does not expose per-variable station availability"*, while every one of its
  station blobs in the same file carries populated `has_discharge`, `has_stage` and
  `has_water_temperature`. The stated reason is contradicted by a column we ship ourselves.
- `dec_coord_datum_cd` and `alt_datum_cd` arrive in the USGS response we already make and are
  discarded, so 26,231 coordinates and elevations ship with their reference thrown away.
- `country` is a Python constant in every generator (`COUNTRY = "United States"`,
  `usgs_nwis/generate_catalogue.py:35`), never read from any source, stamped onto all 64,069
  rows. It is the one guaranteed column that is 100% populated and 100% invented.
- `no_nve` carries an `active` key on all 4,889 stations, all null.
- `jp_mlit`'s 1,024 shipped stations came from `generate_catalogue_from_live`, which appears
  in **zero** tests, keeps failed scrapes with `None` fields, and prints a warning.
- 284,399 of 328,400 `station_products` rows are `unknown`. Only `no_nve` carries real
  availability.

The tier system the review document proposes (`docs/design/provider-redesign-review.md` §6.1)
would catch none of this. It is already implemented: `validate_catalogue` raises on any null
in a `nullable=False` column and the six guaranteed columns are already non-nullable and
fully populated. Every defect above sits in a best-effort column that is legally empty under it.

Success means an empty cell is a claim somebody made and the build checked, generation is
reproducible so a shipped catalogue can be verified against its inputs, and the canonical
surface carries only what genuinely harmonises across thirteen sources.

Governed by [ADR 0012](../../docs/adr/0012-a-catalogue-column-declares-its-origin.md),
[0013](../../docs/adr/0013-the-catalogue-is-built-from-a-committed-native-table.md),
[0014](../../docs/adr/0014-catalogue-metadata-is-croissant.md),
[0015](../../docs/adr/0015-the-canonical-station-catalogue-is-identity-and-geometry.md).

## Scope — In

1. **A native table per provider.** One row per station, columns named and valued exactly as
   the source names and values them, no renaming, no unit conversion, no harmonising.
   Committed as Parquet, which is self-describing, so no schema is authored per provider.
   Replaces the opaque per-row `metadata` JSON string.

2. **Origin declarations, one file per provider.** Each canonical column declares how *this*
   provider fills it, in one of three forms:
   `Field(native_column)` · `NotPublished(evidence=<doc link>)` · `NativeOnly(field, decision)`.

3. **The build gate.** Four rules, engine-owned, identical for all thirteen:
   an undeclared column fails; an origin naming a native column absent from the native table
   fails; a null where the native column held a value fails; a `NotPublished` claim with no
   evidence link fails.

4. **`refresh` split from `build`.** `refresh` touches the network and writes the native
   table, committed as a reviewable diff. `build` is a pure function of the committed native
   table plus origins, no network, runs in CI on every pull request, byte-identical output
   except `built_at`. `retrieved_at` is stamped per row by `refresh`; `built_at` by `build`
   and excluded from the reproducibility comparison.

5. **Carry-forward on partial refresh failure.** A station whose request fails keeps its
   previous value with its own older `retrieved_at`, so staleness is a per-row fact. A station
   that fails with no previous value aborts the refresh. Failures are returned as
   [[issue]]s, never printed.

6. **A Croissant descriptor** as the catalogue's metadata, carrying `license`, `citation`,
   `version`, `datePublished` and `distribution` with `sha256`, extended with one property
   `rr:notPublished` for documented absence. dbt's `loaded_at_field` / `warn_after` /
   `error_after` vocabulary for staleness, replacing the bare `catalogue_version` date.

7. **The canonical station catalogue reduced to five columns:**
   `provider_id | station_id | latitude | longitude | crs`.
   Removed: `name`, `country`, `elevation_m`, `drainage_area_km2`, `metadata`, and the
   station-level `start_date` / `end_date`. Never added: `river_name`, `status`,
   `observed_properties`, station timezone. `crs` is new, per station, EPSG identifiers,
   `unknown` where the source states no datum, on the terms ADR 0006 set for time.

8. **Coverage dates live only in `station_products`**, where sources state them.
   `stations.start_date` would require a minimum across parameters, which is maths on a value
   the source never stated.

9. **Closing every gap the gate proves.** The build stays red until all thirteen are declared,
   so this is not optional follow-up: USGS moves to `seriesCatalogOutput=true` (fixing 26,231
   null start dates and 157,386 unknown availability rows together) and stops discarding
   `dec_coord_datum_cd`; `br_ana` availability comes from its `has_*` flags; every other
   provider is checked against its source's documentation.

10. **Deletions.** The 39 pydantic models across 13 `metadata.py` files (540 lines) and the
    `metadata` column they serialise into. `jp_mlit`'s untested live path gains tests.

11. **Native tables ship in the wheel**, so the material removed from the canonical table
    remains reachable. Subject to the risk in Open questions.

## Scope — Out (explicit non-goals)

- **The live catalogue path**, `stations(source="live")`. Moved to the Program Map's Fog. It is
  freshness at query time; this vision is what the packaged catalogue promises and how it is built.
- **Establishing redistribution rights.** Now Effort ticket **#51**. It blocks item 11 above.
- **The public query surface.** Ticket **#14**, commented with this vision's constraints. The
  engine owning query routing across the four tables is settled there, not here.
- **The on-disk layout for retrieved observations**, the bulk store, consent gate and cache
  interface. Ticket **#12**. A maintainer-time catalogue input is not a bulk observation store.
- **Porting any provider's observation stages.** Eleven remain [[catalogue-only]]; this work is
  independent of that and applies to all thirteen catalogues now.
- **Interpreting any licence.** ADR 0004 stands. Croissant carries `license_url` and
  `license_text` verbatim; we never classify.
- **`observed_properties` as a stored column.** Filtering by what a gauge measures resolves
  through `station_products`, so it cannot drift from what it would have been copied from.
- **A station timezone column and the UTC helper.** ADR 0015 answers ADR 0007's deferred
  question: no. Only USGS publishes a per-station zone and its abbreviations are inadmissible.
- **Reprojection.** All thirteen publish decimal degrees. A future provider publishing only a
  national grid is a real decision this vision does not pre-empt.
- **Building the `NativeOnly` class** until a column needs it. The term is defined; there are
  zero instances under the five-column schema.
- **Filing the Croissant extension upstream.** Ask whether the vocabulary exists; propose only
  after this ships. See ADR 0014.

## Constraints

- **Binding ADRs:** 0004 (never interpret licences), 0005 (unknown is first-class, nothing
  derived), 0006 (a value travels with its qualifier column), 0007 (zone values, and its
  deferred catalogue question answered by 0015), 0012–0015 written for this vision.
- **`AGENTS.md:11`:** harmonise identity and physics, never harmonise judgement. This is the
  test for what earns a canonical column. Grain is a separate axis from vocabulary: a canonical
  column may be per-station.
- **Nothing is computed that the source did not state.** Applies to dates, countries, zones,
  catchment areas and coverage minima alike.
- **`build` must be pure.** Any wall-clock value other than `built_at` entering the artefact
  breaks the property CI depends on.
- **No per-provider schema authoring.** Parquet carries types in its footer. A source adding a
  field must change nothing; a source renaming a field an origin references must fail loudly.
- **Failures are [[issue]]s**, returned and assertable, never `print`.
- **EPSG identifiers** for `crs`. National systems are already in that registry
  (`EPSG:2056` LV95, `EPSG:21781` LV03, `EPSG:4301` Tokyo Datum, `EPSG:4326` WGS 84).
- **Generators are maintainer-only** and not imported during normal package use. That stays true.
- **Reproducibility asymmetry to respect:** only `ch_foen` (246), `lt_lhmt` (97) and `pl_imgw`
  (1,301) build from committed inputs today. The other ten, 62,425 stations, require live calls.
  The legacy repo does not close this: `usa_sites.csv` has 24,527 rows of id and coordinates
  only against 26,231 richer packaged rows.
- **Scale:** 13 providers, 61 products, 64,069 stations, 328,400 station-products, 5.9 MB of
  packaged Parquet. `jp_mlit` refresh is ~1,029 requests at 0.3 s.

## Acceptance criteria (vision-level "done")

1. Every canonical column has an origin for every one of the thirteen providers. Removing any
   one origin fails the build with a message naming the column and provider.
2. Each of the four gate rules has a test that fails on a deliberately broken declaration.
3. `build` runs in CI with the network unavailable and produces artefacts byte-identical to the
   committed ones, `built_at` excepted.
4. `stations.parquet` has exactly the columns
   `provider_id, station_id, latitude, longitude, crs` for all thirteen.
5. Zero `NotPublished` declarations without a resolvable evidence link, enforced by the gate.
6. `usgs_nwis` `station_products` carries real availability and per-parameter coverage dates
   for all six products; its 157,386 `unknown` rows are gone.
7. `br_ana` availability is derived from `has_discharge` / `has_stage` /
   `has_water_temperature`; its 52,145 `unknown` rows are gone.
8. `crs` is populated wherever the source states a datum (at minimum `usgs_nwis` from
   `dec_coord_datum_cd`) and `unknown` elsewhere, with an origin either way.
9. A `refresh` in which a station's request fails carries that station forward with its prior
   `retrieved_at`, proven by a test that injects the failure; a station failing with no prior
   value aborts the refresh.
10. `jp_mlit`'s live enrichment path has tests. `_fetch_site_detail` currently appears in none.
11. The 39 pydantic metadata models, the 13 `metadata.py` files and the `metadata` column are
    deleted from the catalogue path.
12. The built wheel contains a native table per provider, and `dec_coord_datum_cd`, `alt_va`,
    `alt_datum_cd`, `drain_area_va`, `station_nm`, `tz_cd` and each provider's river field are
    readable from it.
13. The Croissant descriptor validates against the spec, and `rr:notPublished` is the only
    non-standard property.
14. No `country` column exists anywhere in the canonical catalogue.

## Decomposition hints

- **Engine first, one provider as tracer bullet.** Build the origin types, the native table
  contract and the four gate rules against `lt_lhmt`: 97 stations, 2 products, builds from a
  committed fixture, so it is reproducible from day one and the whole loop closes without a
  network call.
- **Then the other two reproducible providers**, `ch_foen` (246) and `pl_imgw` (1,301), which
  exercise a second and third transport shape without introducing live-refresh risk.
- **Do the schema reduction early and once.** It is breaking, and every later step that touches
  the station table should be built against five columns rather than migrated to them.
- **Then the highest-payoff provider,** `usgs_nwis`. One request change closes 183,617 empty
  cells and it is the largest catalogue, so it stresses the gate at scale.
- **Then `br_ana`**, where the fix is lifting flags already present, and the interesting part is
  that the gate must refuse the existing false reason string.
- **`jp_mlit` last and treat it as the risky slice.** Untested scrape, 1,029 requests, the
  carry-forward path, and the mixed-datum `crs` case all land together.
- **The Croissant descriptor comes after origins exist**, since it serialises them.
- **The remaining seven providers** are the same shape repeated; parallelise once the gate is
  stable.
- Deleting the pydantic models and `metadata` column is the last step per provider, once its
  native table is committed and its origins pass.

## Open questions / risks

- **Redistribution rights are unestablished, and this blocks Scope-In item 11.** Native tables
  ship in the wheel, which publishes more of each agency's data verbatim under our name. Effort
  ticket **#51** owns this. If the answer is unfavourable for a provider, the fallback (exclude
  its native table, exclude its catalogue, or fetch what we cannot ship) is unspecified.
- **`tests/test_data/pl_imgw_stations.csv` has no recorded provenance.** It came from
  `cached_site_data/poland_sites.csv` in the legacy repo, which records no source and no terms
  for that directory. Establishing where it came from precedes asking what governs it. Poland's
  own `--live` path is worse: 913 stations, 314 without coordinates, against 1,301 committed.
- **Refreshing ten providers requires live calls that may fail or return less than the committed
  catalogue.** `fr_hubeau` and `za_dws` packaged catalogues are already larger than the legacy
  CSVs by 1,611 and 1,569 stations respectively; a degraded refresh would be a visible regression
  in the diff, but somebody has to notice and refuse it.
- **Freshness thresholds are not chosen.** `warn_after` / `error_after` per provider needs a view
  on how fast each source's station list actually moves, which nobody has.
- **How many `NotPublished` claims will survive honest review is unknown.** The declaration work
  is thirteen providers times five columns, but each one may surface a source field nobody knew
  about, as USGS and Brazil already did.
- **`NativeOnly` has zero instances** under the five-column schema. Defined as a term, not built.
  If nothing needs it by the end, reconsider whether it belongs in the glossary.
- **The canonical table is not human-readable.** Choosing a gauge requires joining the native
  table for a label. Accepted in ADR 0015; watch whether it makes the public surface in #14
  awkward enough to reopen.
- **Repo growth.** Native tables partly replace the `metadata` blob already inside
  `stations.parquet`, so the net is closer to doubling 5.9 MB than multiplying it, but this is an
  estimate rather than a measurement.
