# Finland SYKE station catalogue and metadata

Settle scope and design for [Effort #754](https://github.com/RivRetrieve/RivRetrieve/issues/754)
(step 2 of the [provider-port guide](../../docs/maintenance/provider-ports.md))
for `fi_syke`. This vision covers the catalogue's design: station discovery,
coordinates, metadata, products, and the `station_product` associations. It
does not implement `origins.py`, `generate_catalogue.py`, the `catalogue/`
artifact files, or tests — those are a separate implementation PR for this
same Effort, following the same vision-then-implementation split used for
Austria's catalogue step (PR #640 vision, PR #642 implementation) and
`au_bom`'s (`2026-11-02-au-bom-station-catalogue-and-metadata.md`).

**Correction, 2026-11-07 (during implementation, same Effort):** the "Station
discovery" section below settles on the union of `Paikka` rows (2,543 sites,
one row per quantity-specific record) as the station universe, which still
holds. It does not yet settle station *identity* — building the catalogue
found that `Paikka_Id` (not `Nro`) is the real per-installation identifier.
Checked against SYKE's own public WFS (one feature per `Paikka_Id`, in
separate per-quantity layers) and independently against CAMELS-Finland, both
confirmed `Paikka_Id`. `Nro` (SYKE's site code) is not a stable
per-installation key: the same `Nro` can name a site discontinued decades ago
and an unrelated, currently active site tens of kilometres away. The
catalogue's `station_id` is `Paikka_Id`; a station therefore has exactly one
admitted product, not potentially several. Full detail in
`research/fi-syke-station-identity-correction.md` (verification-evidence).

The port belongs to [Program #353](https://github.com/RivRetrieve/RivRetrieve/issues/353).
Builds on the merged [source, scope and access vision](2026-11-07-fi-syke-source-scope-and-access.md)
(Effort #753): `LiveStages`, three admitted entity sets — discharge
(`Virtaama`), stage (`Vedenkorkeus`), surface water temperature
(`LampoPintavesi`) — each with exactly one frequency and row shape. This
vision does not reopen that scope.

## Station discovery: the union of three filtered site lists

Unlike `au_bom`, where series existence had to be checked separately from the
station list, SYKE's single `Paikka` entity set already carries `Suure_Id`
per row, so filtering it directly by the three admitted quantities *is* the
discovery method — no separate per-series existence check is needed. Checked
live on 2026-11-07, paging the full filtered list through `odata.nextLink`:

| `Suure_Id` | Quantity | Sites |
|---|---|---|
| 2 | Discharge (`Virtaama`) | 711 |
| 1 | Stage (`Vedenkorkeus`) | 1,753 |
| 11 | Surface water temperature (`LampoPintavesi`) | 79 |
| **Union of the three** | | **2,543** |

This matches step 1's per-quantity counts exactly and is the river-gauge
station universe for this catalogue. `Paikka` has no catchment-area field
(confirmed in step 1 and again here).

## Coordinate reference system: two real datums, confirmed numerically

`Paikka` gives every site **four** coordinate representations:
`KoordErTmIta`/`KoordErTmPohj`, `KoordYkIta`/`KoordYkPohj`,
`KoordPkIta`/`KoordPkPohj`, and packed-string `KoordLat`/`KoordLong`.
`TauluKuvaus`/`SarakeKuvaus` document none of them — every description field
for every one of these columns is `null`, confirmed live today. Rather than
infer meaning from the field-name abbreviations alone, I cross-checked the
actual published numbers with `pyproj` against a sample of discharge sites:

- `KoordYk` (treated as EPSG:2393, the YKJ grid) and `KoordLat`/`KoordLong`
  (unpacked from degrees-minutes-seconds) agree to within 6–30 m — consistent
  with the DMS string's own whole-second rounding at these latitudes. They
  are the same point in the same legacy datum (KKJ, Hayford 1924), one as a
  projected grid and one as packed geographic degrees.
- `KoordPk` equals `KoordYk` exactly for sites in KKJ zone 3, and differs for
  others by exactly a zone-boundary shift: its easting's leading digit is
  the station's own local KKJ Gauss-Krüger zone (1–4), while `KoordYk`
  always re-expresses the same point in the nationally-uniform zone-3
  system. `Pk` and `Yk` are the same KKJ/Hayford point in two projections of
  one datum, not two different surveys.
- `KoordErTm` (treated as EPSG:3067, ETRS-TM35FIN) disagrees with the
  KKJ-family point by **170–230 m**, consistently, across every site
  sampled — far beyond rounding, and matching Finland's documented official
  KKJ→ETRS89 datum shift. This is a genuinely different datum (ETRS89), not
  a re-projection of the same survey.

This is not per-station CRS variation the way `au_bom`'s
`station_georefsystem` varied station by station; SYKE publishes **every**
station in two real datums simultaneously (legacy KKJ/Hayford, three
encodings; modern ETRS89, one encoding), with no field naming which is
primary.

**Recommendation:** use `KoordErTm` (EPSG:3067) as the catalogue's native
coordinate source, inverse-projected to geographic **ETRS89 (EPSG:4258)** —
not WGS84 (EPSG:4326, a different datum) — following the same convention
`au_bom` used (copy a geographic datum straight through; inverse-project a
*projected* coordinate onto its own underlying datum, never reproject across
datums). ETRS89 is Finland's current official national geodetic system (KKJ
was officially superseded around 2005), an externally-documented, not
station-specific, convention of the same kind `at_ehyd` relied on for its
MGA/AMG zones. Record the legacy KKJ-family coordinates
(`KoordYk`/`KoordPk`/`KoordLat`/`KoordLong`) in the research record as a
verified source fact rather than silently discarding them; they are not
used as the catalogue's `crs` by this recommendation.

## Station metadata: richer than `au_bom`'s, but still no catchment area

Checked live on 2026-11-07 across all 2,543 union sites: station name
(`Nimi`), municipality (`KuntaNimi`), water body name (`VesalNimi`), and main
water body / river name (`PaaVesalNimi`) are populated on **every** site
(2,543/2,543). Lake name/number (`JarviNimi`/`JarviNro`) are populated on
1,536 sites (60%) — correctly conditional, since not every gauge sits on a
named lake. A topographic map-sheet reference (`Karttalehti`) is populated on
2,358 sites (93%).

Unlike `au_bom` (name and coordinates only), `fi_syke` publishes a real river
or water-body name for every station — useful station metadata RivRetrieve
should carry. No catchment-area field exists anywhere in `Paikka`, matching
step 1's finding; this remains a source fact to record, not a gap to fill
with an inferred value.

## Station status: five codes, a design decision still open

`Tila_Id` names five statuses, confirmed live via the `Tila` entity set: `1`
Jatkuva (continuing), `2` Lopetettu (discontinued), `3` Satunnainen
(occasional), `4` Ei poiminnassa (not currently collected), `5`
Määräaikainen (fixed-term). Every admitted site carries one of these.
Whether to expose `Tila_Id` as a catalogue fact, and if so how (a raw code
mapped to an enum, a boolean "active" derived from it, or left out of the
catalogue and only used internally to shape `availability`), is left to the
implementation PR to decide and justify, not settled here.

## Products: three rows, formalizing Effort #753's scope

`station_product` associations presuppose products. The implementation PR's
`PRODUCT_CATALOG_SCHEMA` should be exactly the three series already admitted
in the merged source-access vision — no new scope here:

| Quantity | Native unit | Native table | Statistic |
|---|---|---|---|
| Discharge | m³/s | `Virtaama` | Unknown — no table states whether `Arvo` is a daily mean |
| Stage | cm (convert to m) | `Vedenkorkeus` | Unknown, same reason |
| Surface water temperature | °C | `LampoPintavesi` | Unknown, same reason |

Each has exactly one frequency (daily); step 1 already confirmed no
sub-daily or monthly variant exists for any of the three.

## `station_product.availability`: available or unknown, never unavailable

Follow `au_bom`'s and `at_ehyd`'s convention: a station-product pair is
`"available"` only where the per-quantity `Paikka` filter directly witnessed
the station for that `Suure_Id` (the network-wide witness here, since
`Paikka` itself carries `Suure_Id`), everywhere else `"unknown"`, never
`"unavailable"`. A station not appearing in a quantity's filtered list has
not been proven to lack that quantity for its entire history.

## Registration: two hardcoded allowlists, plus the manifest

Registering `fi_syke`'s catalogue needs three separate edits, none implying
the others, matching `au_bom`'s exact registration shape:

1. One line, `"fi_syke",`, in `BUILTIN_PROVIDER_IDS`
   (`src/rivretrieve/_internal/provider_manifest.py`).
2. `"fi_syke"` added to `ACQUISITION_PROVENANCE_ENROLLED_PROVIDERS`
   (`src/rivretrieve/_internal/catalogues/artifact.py`) — without this,
   `acquisition_provenance` stays optional rather than required.
3. `ProviderId("fi_syke")` added to `ORIGIN_GATE_ENROLLED_PROVIDERS`
   (`src/rivretrieve/_internal/catalogue_origins.py`) — without this,
   `enforce_catalogue_origins` refuses the build with a
   `FatalContractError`.

**Recommendation:** register immediately in all three places, following
`at_ehyd`'s and `au_bom`'s path rather than `za_dws`'s deferred,
fixture-only registration — step 1 already confirmed CC BY 4.0 terms with no
comparable legal concern found for this source. This is a recommendation,
not something this vision settles unilaterally.

## Prerequisite for the implementation PR: retained evidence, not live calls

Every existing provider's `generate_catalogue.py` is a pure transformer over
already-retained, already-receipted evidence (a selection file plus a
`RetainedInputReceipt` from the private `verification-evidence` repository),
never a script that calls the live API itself. Step 1 only retained small
receipts (status/size/hash/count) inline in a research-record markdown file,
not a full archived, receipted collection. Before the implementation PR can
produce a real, buildable `fi_syke` catalogue, representative SYKE responses
(the three filtered `Paikka` lists, and the `Suure`/`TauluKuvaus`/`Tila`
reference tables) need to go through the private archive's capture →
manifest → `intake` → `publish` process (`docs/maintenance/evidence.md`),
registering a real collection in `verification-evidence`'s
`inventory/collections.json` — mirroring `au_bom`'s
`au_bom-catalogue-2026-11-02-v1` collection. This vision names the
prerequisite; it does not perform the intake.

## Completion

Post a concise scope update on #754 referencing this vision, including the
resolved coordinate-datum finding and the confirmed 2,543-site union. Keep
#754 open until the implementation PR (`origins.py`, `generate_catalogue.py`,
the `catalogue/` artifact, the three registration edits, and tests) is
merged.
