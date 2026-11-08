# Colombia IDEAM retrieval behavior

Deliver evidence-backed, tested observation retrieval for Colombia's
*Instituto de Hidrología, Meteorología y Estudios Ambientales* (`IDEAM`) Open Data
cloud object store provider, `co_ideam`, under
[Effort #724](https://github.com/RivRetrieve/RivRetrieve/issues/724) and
[Program #460](https://github.com/RivRetrieve/RivRetrieve/issues/460) without
silently dropping rows, fabricating coverage outside published observation bounds,
or coupling independent series requests. Completing the research updates, retrieval
stages, and source/synthetic verification described here completes #724; publishing
this vision alone does not complete the Effort. Work targets `port/co-ideam` and
leaves `main` unchanged until
[final review #728](https://github.com/RivRetrieve/RivRetrieve/issues/728). Keep
`co_ideam` registered as `CatalogueOnly()` during #724; public `LiveStages`
activation belongs to [#725](https://github.com/RivRetrieve/RivRetrieve/issues/725).

## Scope and established context

Build on the delivered [station catalogue (#722)](2026-11-06-co-ideam-offline-station-catalogue.md)
and [series definitions (#723)](2026-11-08-co-ideam-series-identity-and-physical-meaning.md)
at reviewed `port/co-ideam` revision `055666bd06fb4e1f8f523dbcadc1877553bf2615`.
Support anonymous HTTP `GET` acquisition across all `20` canonical river products
published under `https://datos.ideam.gov.co/s3-estacionesideam/observaciones/historicos/csv/`:

- **River discharge (`ideam.s3.historicos`, `10` products, native `m3/s` to `m3/s`):**
  `caudal_h` (`CAUDAL_H`), `q_media_d` (`Q_MEDIA_D`), `q_mx_d` (`Q_MX_D`),
  `q_mn_d` (`Q_MN_D`), `q_media_m` (`Q_MEDIA_M`), `q_mx_m` (`Q_MX_M`),
  `q_mn_m` (`Q_MN_M`), `q_media_a` (`Q_MEDIA_A`), `q_mx_a` (`Q_MX_A`), and
  `q_mn_a` (`Q_MN_A`).
- **River stage (`ideam.s3.historicos`, `10` products, native `cm` to `m`, `vertical_reference="gauge_zero"`):**
  `nivel_h` (`NIVEL_H`), `nv_media_d` (`NV_MEDIA_D`), `nv_mx_d` (`NV_MX_D`),
  `nv_mn_d` (`NV_MN_D`), `nv_media_m` (`NV_MEDIA_M`), `nv_mx_m` (`NV_MX_M`),
  `nv_mn_m` (`NV_MN_M`), `nv_media_a` (`NV_MEDIA_A`), `nv_mx_a` (`NV_MX_A`),
  and `nv_mn_a` (`NV_MN_A`).

Do not query `aquariuswebportal.ideam.gov.co`, uncalibrated `datos.gov.co` raw
sensor feeds (`bdmn-sqnh`, `vfth-yucv`, `pt9a-aamx`), or `observaciones/instantaneos/`
at runtime, and do not perform `ListObjectsV2` discovery calls during observation
retrieval. Continue the existing
[private research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/co-ideam-source-access.md)
following [provider-port step 4](../../docs/maintenance/provider-ports.md#4-retrieval-behavior).

## Acquisition behavior and independent per-series requests

IDEAM's Nutanix Objects store serves one full-history UTF-8 CSV per canonical
10-digit `station_id` and published `ETIQUETA` at deterministic URLs:

`GET https://datos.ideam.gov.co/s3-estacionesideam/observaciones/historicos/csv/{ETIQUETA}/{station_id}-{ETIQUETA}.csv`

No query parameters or date-window filters exist on S3 object downloads: every
object returns the complete published history (`85 B` single-row CSVs up to
`34.89 MB` / `933,125` hourly rows across the national corpus). Declare
`WindowDeclaration(WindowGranularity("none"), WindowRenderingVocabulary.NONE, StopConvention.INCLUSIVE)`
for all `20` products and let the shared engine clip parsed observations to the
caller's `RequestedWindow`.

Acquire each `(station_id, product_id)` pair as an independent HTTP `GET` over the
shared `Transport` (`minimum_interval_seconds=1.0`, `timeout_seconds=60.0`, safe
`GET` retry on transient `408`/`429`/`5xx`). Validate canonical 10-digit ASCII
station identifiers before constructing object URLs, and isolate any transport or
payload failure to the affected `(station_id, product_id)` pair so sibling products
and stations always survive.

## Observation normalization, approval labels, and folded civil timestamps

- **CSV contract and value fidelity:** Decode UTF-8 (`utf-8-sig`), enforce the
  exact 3-column header `fechaObservacion,valorObservado,nivelAprobacion` and
  exact 3-column row width, reject blank or non-finite numeric cells (`NaN`,
  `inf`), verify `YYYY-MM-DD HH:MM:SS` wall-clock timestamps in non-decreasing
  order, and enforce `YYYY-MM-01` on `monthly` series and `YYYY-01-01` on `yearly`
  series.
- **Zero, negative, and duplicate-hour preservation:** Preserve `0.0` flows and
  stages (`0016057010`, `0024057080`), negative river stages below local
  `gauge_zero` (`cm` converted to `m` via `admission`), negative backwater/tidal
  flows if published, `1992-1993` *Hora Gaviria* (`UTC-04:00`) `+01:00` shifted
  timestamps (`01:00:00` daily rows and `07:00`/`19:00` conventional readings),
  and duplicate `1993-02-06 23:00:00` fall-back rows (`0011107010-NIVEL_H`,
  `0035077140-CAUDAL_H`) without deduplication. Keep `time_zone="unknown"` on all
  returned rows.
- **`nivelAprobacion` source approval labels:** Preserve all published approval
  stages (`"Preliminar"`, `"En revisión"`, `"Definitivo"`, and legacy blank `""`)
  without filtering or ranking, consistent with `co_ideam/series.py::APPROVAL_VOCABULARY`.

## Locked design decisions: coverage, cache reuse, and HTTP 404 handling

Per maintainer review for #724, two retrieval semantics are explicitly locked and
recorded here and in `research/co-ideam-source-access.md`:

1. **Option 1A (Bounded `[first_obs, last_obs]` `coverage="interval"` with disjoint
   `OutcomeStatus.UNRESOLVED` pre/post tails):**
   - IDEAM S3 CSVs carry no separate metadata header declaring commissioning or
     active-reporting end dates, and IDEAM regenerates active S3 CSVs daily (both
     appending new `Preliminar` days and revising or removing recent `Preliminar`
     values, as witnessed on `0026177030-NV_MEDIA_D.csv` between `2026-11-06` and
     `2026-11-08` where `2026-11-05` revised from `155.5 cm` to `157.625 cm` while
     `2026-11-06..2026-11-07` were appended).
   - Emitting `coverage="observations"` would write no `CoverageInterval` entries
     in the local store, preventing `cache="reuse"` from serving historical queries
     offline and preventing `cache="refresh"` from retiring deleted `Preliminar`
     timestamps inside the active record. Conversely, claiming `coverage="interval"`
     over the entire caller `fetch_window` (`1900..present`) would falsely mark
     pre-commissioning history and not-yet-published recent days as permanently
     `EMPTY` under `cache="reuse"`.
   - For every valid non-empty CSV with chronological bounds `first_obs .. last_obs`,
     compute `covered_start = datetime.combine(first_obs.date(), time.min)` and
     `covered_end = datetime.combine(last_obs.date(), time.max)` when
     `fact.clipping_axis is ClippingAxis.CALENDAR_DATE` (the `6` daily `*_D`
     products, covering whole calendar dates including `1992-1993` *Hora Gaviria*
     `01:00:00` daily rows such as `0024057080-Q_MEDIA_D`), and
     `covered_start = first_obs`, `covered_end = last_obs` on the `14`
     `ClippingAxis.SOURCE_TIMESTAMP` products. Emit `OutcomeStatus.SUCCESS` with
     `coverage="interval"` and `InventoryCompleteness.COMPLETE` over
     `[covered_start, covered_end]`, plus disjoint `OutcomeStatus.UNRESOLVED`
     outcomes on any requested pre-`covered_start` (`<= covered_start - 1 us`) or
     post-`covered_end` (`>= covered_end + 1 us`) span.
   - Historical sub-windows inside `[covered_start, covered_end]` reuse the local
     store offline (`cache="reuse"`), requests extending beyond `covered_end`
     re-fetch automatically, `cache="refresh"` replaces revised or removed
     `Preliminar` values across `[covered_start, covered_end]`, and a hypothetical
     header-only `0`-row CSV emits `OutcomeStatus.UNRESOLVED` (`InventoryCompleteness.INCOMPLETE`)
     rather than `EMPTY`.
2. **Option 2A (Standard `FailedSourceRequest` / `source.http_not_found` on `HTTP 404` `NoSuchKey`):**
   - Selection via `rr.find(provider="co_ideam", ...)` already excludes the `7,750`
     unpublished `(station_id, product_id)` pairs using the packaged S3
     `ListObjectsV2` availability inventory.
   - If `fetch()` receives an `HTTP 404` (`NoSuchKey` XML from Nutanix Objects,
     either via direct `driver.drive` invocation on an unpublished pair or during a
     transient upstream bucket rebuild on a catalogued series), `fetch()` records a
     standard `FailedSourceRequest`. The shared driver classifies `404` as
     `OutcomeStatus.FAILED` with warning `Issue(code="source.http_not_found")` and
     invokes `retain_held_successes` so previously cached observations survive
     transient S3 regeneration gaps instead of being wiped as `NO_MATCH`.

## Verification

- Retain `co_ideam-retrieval-2026-11-08-v1` in `RivRetrieve/verification-evidence`
  and bind `40` real IDEAM S3 HTTP captures (`80` `.body` and `.receipt.json`
  members across `co_ideam-access-2026-11-06-v1`,
  `co_ideam-series-meaning-2026-11-08-v1`, and `co_ideam-retrieval-2026-11-08-v1`)
  under `maintenance/observations/co_ideam/retrieval`.
- Certify receipt integrity, request coordinates, Option 1A interval bounds,
  `2026-11-06 -> 2026-11-08` `0026177030-NV_MEDIA_D` in-place `Preliminar` revision
  and post-record extension, and Option 2A `NoSuchKey` `404` handling in both the
  private source-certification suite (`tests/source/test_co_ideam_retrieval.py`)
  and the public recorded replay suite (`tests/test_co_ideam_retrieval_recorded.py`).
- Cover synthetic unit and `driver.drive` local-store paths in
  `tests/test_co_ideam_retrieval.py` across all `20` products, `cache="bypass"`,
  `"reuse"`, and `"refresh"`, held-row retention on `404` and `503`, `0`-row
  header-only CSVs, duplicate `1993-02-06 23:00:00` rows, negative values, and
  malformed CSV isolation.
