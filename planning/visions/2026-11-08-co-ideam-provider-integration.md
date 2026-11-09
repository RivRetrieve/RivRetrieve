# Colombia IDEAM provider integration

Make Colombia IDEAM hydrological observations available through RivRetrieve's
public selection, retrieval, and cache interfaces under `co_ideam`. Deliver the
agreed scope for
[Effort #725](https://github.com/RivRetrieve/RivRetrieve/issues/725) and
[Program #460](https://github.com/RivRetrieve/RivRetrieve/issues/460).
Completing this integration and its applicable verification completes #725;
publishing this vision alone does not.

Work targets `port/co-ideam` and leaves `main` unchanged until
[final review #728](https://github.com/RivRetrieve/RivRetrieve/issues/728)
approves merging. Full-provider verification remains in
[#726](https://github.com/RivRetrieve/RivRetrieve/issues/726), and the dedicated
provider documentation page remains in
[#727](https://github.com/RivRetrieve/RivRetrieve/issues/727). Those separate
Efforts do not defer checks required to establish correct public integration.

## Build on the delivered provider work

At target `port/co-ideam` revision `48d0ba80366733267c96596393d28be14ac54cea`,
[#721](https://github.com/RivRetrieve/RivRetrieve/issues/721),
[#722](https://github.com/RivRetrieve/RivRetrieve/issues/722),
[#723](https://github.com/RivRetrieve/RivRetrieve/issues/723), and
[#724](https://github.com/RivRetrieve/RivRetrieve/issues/724) are complete:

- The packaged catalogue supports offline discovery of `1,372` canonical
  10-digit flowing-watercourse station identities across `20` discharge and
  stage products (`19,690` `"available"` and `7,750` `"unavailable"` pairs),
  keeping horizontal `crs="unknown"` explicit.
- `providers/co_ideam/series.py` defines distinct source identities
  (`namespace="co_ideam.s3_historicos_csv"`, `published_id=etiqueta`) and
  established physical facts across all `20` products, converting stage from
  `cm` to `m` (`factor=0.01`, `vertical_reference="gauge_zero"`) and keeping
  `time_zone`, `day_definition`, `timestamp_anchor`, `label_time`, and
  `temporal_support` explicitly unestablished.
- `providers/co_ideam/{config,fetch,parse}.py` implement per-series S3 CSV
  coordinates, `WindowGranularity.SOURCE_FIXED` acquisition (`CALENDAR_DATE` on
  the `6` daily products; `SOURCE_TIMESTAMP` on `caudal_h`, `nivel_h`, and the
  `12` monthly and annual products), per-series failure isolation, UTF-8 / UTF-8-BOM CSV
  parsing across all `nivelAprobacion` labels (`Preliminar`, `En revisión`,
  `Definitivo`, and `""`), Option 1A bounded `[first_obs, last_obs]` interval
  coverage with `UNRESOLVED` pre-record and post-record sub-spans, and Option 2A
  standard `FailedSourceRequest` handling on HTTP `404` Nutanix `NoSuchKey` XML
  responses.
- `providers/co_ideam/declaration.py` still declares `CatalogueOnly()`, leaving
  public observation retrieval disabled.

Use the delivered
[source scope](2026-11-06-co-ideam-source-scope-and-access.md),
[catalogue](2026-11-06-co-ideam-offline-station-catalogue.md),
[series](2026-11-08-co-ideam-series-identity-and-physical-meaning.md), and
[retrieval](2026-11-08-co-ideam-retrieval-behavior.md) contracts and their
retained evidence. Follow
[provider-port step 5](../../docs/maintenance/provider-ports.md#5-provider-integration)
and continue the existing
[private IDEAM research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/co-ideam-source-access.md).
Do not restart completed research or create a parallel evidence archive.

## Deliver working public retrieval

Connect `config()`, `window_declarations()`, `fetch`, and `parse` to
`LiveStages` in `src/rivretrieve/_internal/providers/co_ideam/declaration.py`
with `required_credentials=()`. Because each IDEAM S3 CSV file serves exactly
one `(station_id, etiqueta)` product, keep `shared_acquisition_products` unset
so requests run only for selected products and isolate failures per series.
Reuse shared discovery, transport, unit conversion, clipping, assembly, receipt
recording, and local store machinery across all `20` agreed discharge and stage
products:

- **Discharge (`10` products, `m3/s`):** `caudal_h`, `q_media_d`,
  `q_mx_d`, `q_mn_d`, `q_media_m`, `q_mx_m`, `q_mn_m`, `q_media_a`, `q_mx_a`,
  and `q_mn_a`.
- **Stage (`10` products, `cm` to `m`, `vertical_reference="gauge_zero"`):**
  `nivel_h`, `nv_media_d`, `nv_mx_d`, `nv_mn_d`, `nv_media_m`, `nv_mx_m`,
  `nv_mn_m`, `nv_media_a`, `nv_mx_a`, and `nv_mn_a`.

Preserve canonical 10-digit station IDs and distinct `etiqueta` series
identities. Do not aggregate sub-daily `CAUDAL_H` or `NIVEL_H` rows into daily
values, splice different `etiqueta` products together, select a preferred series
when multiple products match a broad query, filter out `Preliminar` or
`En revisión` observations, or expose sediment series (`CONC_SED_SUS_D`,
`TRANSP_MAT_SUSP_D`) or non-flowing reservoir/lagoon gauges.

Follow the standard `rr.fetch(..., start=..., end=...)` contract without adding
new public options, custom rate-limiter infrastructure, or provider-specific
issue suppression. Update shipped capability summaries
(`docs/_generated/reference-tables.md`), the selectable station coverage map
(`docs/scripts/coverage_map.py` and `docs/assets/coverage-map.png`), and the
root `README.md` provider table (`1,372` selectable stations, `Open` access,
removing Colombia from `Countries coming soon`) so repository-wide capability
contracts reflect live `co_ideam` retrieval while keeping the dedicated
`docs/providers/co_ideam.md` guide scoped to #727.

## Preserve source meaning, provenance, and cache semantics

Public retrieval must preserve the established series facts, absence states, and
store invariants end-to-end:

- Convert stage from `cm` to `m` (`factor=0.01`,
  `vertical_reference="gauge_zero"`), preserving negative stages below gauge
  zero and zero discharge or stage values without clamping.
- Preserve `"unknown"` row time zones, exact naive wall-clock timestamps
  (including 1992 to 1993 *Hora Gaviria* `01:00:00` daily shifts and folded
  `1993-02-06 23:00:00` duplicate timestamps on `CAUDAL_H` and `NIVEL_H`),
  calendar-date clipping on the `6` daily products, and source-timestamp
  clipping on `CAUDAL_H`, `NIVEL_H`, and the `12` monthly and annual products.
- Enforce physical-predicate selection honestly: querying
  `quantity="discharge", frequency="daily", statistic="mean"` selects only
  `q_media_d` while withholding `caudal_h` (`frequency` and `statistic` are
  `not_established`), and querying a concrete `time_zone` returns an empty
  selection because IDEAM S3 CSVs do not publish UTC offsets.
- Reuse cached observations offline (`0` network requests) when queries fall
  inside the bounded Option 1A `[covered_start, covered_end]` span (including
  `CALENDAR_DATE` expansion to `[first_date 00:00:00, last_date 23:59:59.999999]`
  when a first daily row carries a `01:00:00` *Hora Gaviria* timestamp), emit
  disjoint `UNRESOLVED` outcomes on pre-record and post-record sub-spans so
  unpublished dates are never cached as empty, merge appended rows and replace
  in-place `Preliminar` value revisions on refresh or extension, treat `0`-row
  header-only CSVs as `UNRESOLVED`, isolate Option 2A HTTP `404` `NoSuchKey`
  failures per series while retaining held cached rows, and attach verified
  `Creative Commons Attribution | Share Alike 4.0 International` (`CC BY-SA 4.0`)
  license and IDEAM citation statements to `ObservationResult.provenance`.

## Verification and handoff

Verify observable behavior through public selection and retrieval alongside
updated repository contracts:

- Offline discovery (`rr.find`, `rr.pick`, `rr.series`, `rr.metadata`,
  `rr.describe`) remains network-free after `LiveStages` registration.
- Public synthetic integration tests (`tests/test_co_ideam_public.py`) cover all
  `20` products without credentials, `cm` to `m` `gauge_zero` stage conversion,
  physical-predicate filtering, provenance statements, Option 1A `cache` modes
  (`reuse`, `bypass`, `refresh`), in-place `Preliminar` revision updates,
  folded `1993-02-06 23:00:00` duplicate timestamps, `0`-row `UNRESOLVED`
  responses, Option 2A HTTP `404` / `503` sibling survival and held-row
  retention, and `on_issue` (`raise`, `warn`, `ignore`) behavior.
- Genuine recorded public replay (`tests/test_co_ideam_recorded_public.py`)
  exercises retained IDEAM S3 HTTP captures through public `rr.find`, `rr.pick`,
  and `rr.fetch` alongside `LiveBoundaryProbe` verification for all `20`
  products, comparing returned rows against independently parsed publisher CSV
  bytes without embedding private response bodies in public code.
- Repository-wide reference, boundary-probe obligation, coverage-map, and
  wheel/sdist packaging checks pass alongside private source-certification
  checks under the [evidence process](../../docs/maintenance/evidence.md).
