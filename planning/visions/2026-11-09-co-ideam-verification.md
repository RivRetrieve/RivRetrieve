# Colombia IDEAM verification

Verify the integrated Colombia IDEAM provider (`co_ideam`) against genuine
retained source evidence, close remaining shared-contract verification gaps,
and record the external CAMELS-COL hydrological cross-check on `port/co-ideam`.
Delivering this vision and its controlled verification completes
[Effort #726](https://github.com/RivRetrieve/RivRetrieve/issues/726) under
[Program #460](https://github.com/RivRetrieve/RivRetrieve/issues/460);
publishing this vision alone does not complete the Effort.

Work targets `port/co-ideam` and leaves `main` unchanged.
[Effort #727](https://github.com/RivRetrieve/RivRetrieve/issues/727) delivers
the dedicated user documentation (`docs/providers/co_ideam.md`).
[Effort #728](https://github.com/RivRetrieve/RivRetrieve/issues/728) covers
final review and merge into `main` once Steps 1 through 7 and their acceptance
receipts are complete.

## Verify the delivered scope

Steps [#721](https://github.com/RivRetrieve/RivRetrieve/issues/721) through
[#725](https://github.com/RivRetrieve/RivRetrieve/issues/725) are delivered on
`port/co-ideam` at revision `8a92a51f29ac255f84cfb186a281a8df98c9a3f8`:

- Offline discovery exposes `1,372` canonical 10-digit flowing-watercourse
  gauges (`19,690` `"available"` and `7,750` `"unavailable"` station-product
  pairs across `20` products; `27,440` pairs total), excluding dead registry
  rows without S3 hydrological files, `Embalse`/`Laguna` standing-water stage
  stations, `Meteorológica` stations, and legacy Socrata `HIS_*` mirrors.
- `providers/co_ideam/declaration.py` wires `LiveStages`
  (`required_credentials=()`) across all `10` discharge (`m3/s -> m3/s`) and
  `10` stage (`cm -> m`, `factor=0.01`, `vertical_reference="gauge_zero"`)
  products on IDEAM's Nutanix Objects S3 portal
  (`https://datos.ideam.gov.co/s3-estacionesideam/observaciones/historicos/csv/{ETIQUETA}/{station_id_10digit}-{ETIQUETA}.csv`).
- `providers/co_ideam/parse.py` enforces strict 3-column UTF-8 CSV structure,
  `ClippingAxis.CALENDAR_DATE` on the `6` daily products (`*_d`),
  `ClippingAxis.SOURCE_TIMESTAMP` on `caudal_h`, `nivel_h`, and the `12`
  monthly/annual products (`*_m`, `*_a`), Option 1A bounded `[first_obs, last_obs]`
  `coverage="interval"` with disjoint pre-record and post-record `UNRESOLVED`
  sub-spans, and Option 2A `FailedSourceRequest` (`source.http_not_found`) with
  held-row retention on `HTTP 404` `NoSuchKey` XML responses.

Follow [provider-port step 6](../../docs/maintenance/provider-ports.md#6-verification),
the [testing guide](../../docs/maintenance/testing.md), and the
[evidence guide](../../docs/maintenance/evidence.md). Build on the existing
`co_ideam` suites and the
[continuing private research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/co-ideam-source-access.md).

## Close remaining public-replay and shared-contract gaps

Assess and verify the complete path from offline discovery and request planning
through unit harmonisation, clipping, provenance, bundle round-trip, local store
reuse, and distribution packaging:

- **End-to-end public replay across all `20` products and documented S3
  boundaries:** Replay all `20` products at witness station `0011017010`
  through `LiveBoundaryProbe` and `rr.find` / `rr.fetch`, alongside *Hora
  Gaviria* `1992-08-01 01:00:00` `CALENDAR_DATE` clipping on `0024057080`,
  folded `1993-02-06 23:00:00` duplicate timestamps on `0011107010` (`nivel_h`)
  and `0035077140` (`caudal_h`), paired `2026-11-06` -> `2026-11-08` `Preliminar`
  regeneration on `0026177030` (`nv_media_d`), `85`-byte 1-row CSV witnesses
  (`0026157160` `nv_mn_a`, `0012047010` `q_media_a`), blank `nivelAprobacion`
  with CRLF line endings (`0011037020` `q_mx_m`), zero-stage `0.0 cm -> 0.0 m`
  (`0026177030` `nivel_h`), `rr.cache_status()` / `rr.audit_cache()` /
  `rr.to_bundle()` / `rr.from_bundle()`, and `HTTP 404` `NoSuchKey` sibling
  survival (`tests/test_co_ideam_recorded_public.py`).
- **Shared cross-provider contracts:** Enroll `co_ideam` in the packaged
  reduced-carrier (`27,440` pairs, `0` published record boundary dates) and
  `Creative Commons Attribution | Share Alike 4.0 International` / IDEAM
  citation audit (`tests/test_package.py`), the public selection/result bundle
  and `ReceiptAuthorship.STORE_EXCERPT` cache round-trip contract
  (`tests/test_public_representative_source_series.py`), and live numeric-cell
  finiteness, overflow, boolean, and blank-cell rejection
  (`tests/test_live_numeric_values.py`), complementing the existing
  all-provider catalogue rebuild (`tests/test_catalogue_origin_certification.py`)
  and metadata packaging (`tests/test_station_metadata_packaging.py`) coverage.

## Record the CAMELS-COL hydrological cross-check

Record the bounded empirical comparison against the published CAMELS-COL
dataset (Jimenez et al., Zenodo `doi:10.5281/zenodo.23598410` / concept
`doi:10.5281/zenodo.14947146`) in the private research archive
(`research/co-ideam-camels-comparison.md` and
`research/co-ideam-source-access.md`):

- Confirm exact station identity overlap (`346 / 346` CAMELS-COL `gauge_id`
  values match canonical 10-digit `co_ideam` stations with `q_media_d`
  `"available"` when zero-padded via `zfill(10)`).
- Compare `1981-01-01` through `2022-12-31` daily mean discharge (`q_media_d`,
  `m3/s`) retrieved live via `rr.find` and `rr.fetch` (`<= 1 req/s`) across a
  reproducible `10`-station random sample (`random.Random(42)`, `127,265`
  overlapping station-days across `4` Colombian hydrographic regions), and plot
  preserved-gap daily hydrographs over calendar year `2000` (`3,559`
  overlapping station-days, `0.0 m3/s` maximum difference, identical missing-day
  gaps).
- Frame the check explicitly as a same-publisher, cross-portal consistency check
  (IDEAM DHIME February 2023 frozen extraction versus live IDEAM S3 historical
  `Q_MEDIA_D` CSVs), accounting for 3-decimal `%.3f` formatting (`<= 0.0005 m3/s`),
  *Hora Gaviria* (`2,521 / 2,521` exact daily matches across `1992-05-02` to
  `1993-02-06`), and post-February-2023 AQUARIUS rating-curve revisions on
  `Preliminar` and newly promoted `Definitivo` epochs (`2016-2022`), without
  promoting withheld `time_zone` or `day_definition` facts to `known` or adding
  CAMELS-COL files as repository dependencies.
