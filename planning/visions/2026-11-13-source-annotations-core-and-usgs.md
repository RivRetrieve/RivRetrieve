# Source annotations core and USGS

Preserve source-published annotations alongside river observations so users can
inspect source judgement without reparsing responses. Keep source vocabulary and
native types. Do not invent quality scores, interpret flags, or filter measurements
based on them.

This vision delivers [Effort #812](https://github.com/RivRetrieve/RivRetrieve/issues/812)
and includes the [USGS migration #813](https://github.com/RivRetrieve/RivRetrieve/issues/813).
Implementation completes those issues only when the shared capability and genuine
USGS evidence checks pass. Publishing this document does not complete either issue.
The [approved Program decisions](https://github.com/RivRetrieve/RivRetrieve/issues/809#issuecomment-6860795374)
and [USGS selection](https://github.com/RivRetrieve/RivRetrieve/issues/812#issuecomment-6860858138)
record the agreed scope.

## Public behavior

Support two annotation grains through one `annotations=` convention:

- Observation annotations are available through `result.to_polars(annotations=...)`
  and `result.to_pandas(annotations=...)`.
- Non-identity series attributes are available through
  `rr.series(result, annotations=...)`. Stream selectors remain in
  `SourceSeries.variant`; annotation changes do not create a new series.

`annotations=` accepts `False` (default), `True`, or one/several column names.
Unknown names raise. Defaults retain the existing harmonized schemas;
`result.data` remains deterministic with its ten canonical columns and no random
`occurrence_id`. Fields with different source meanings must not silently merge
because they share a name. Resolve collision handling without weakening the
agreed column-selection interface.

Expose plain native Polars dtypes, including `String`, `Int64`, and `List(String)`,
without `{present, value}` wrapper structs. `rr.annotations(result)` returns a
Polars field catalog with scope, schema identifier, field name, dtype, row and
unmeasured-slot counts, a verified short description, and an official reference.
`rr.annotations(result, schema=...)` returns that schema's Polars table directly.
It includes source slots without measurements, marked `measured=False`, and avoids
cross-route null padding. The widened measurement view must not fabricate
measurements for these slots or multiply existing measurement rows.

Every shipped annotation column needs a verified short field description and an
official source reference. Placeholder descriptions such as "unknown" are not
acceptable. Exhaustive in-library dictionaries for every code value are not required.
Keep null values, absent rows, and failed requests distinct; do not manufacture
source facts to fill gaps.

## Shared implementation scope

Carry annotations through live retrieval, accumulated cache reuse, manual refresh,
compiled bulk-store reads and writes, `pick`, `to_utc`, and `to_bundle` / `from_bundle`.
Retain correct associations through clipping, unit conversion, time conversion,
selection, duplicate handling, and roundtrips. Keep measurements self-contained:
there is no mandatory `source_slots` table. Materialize annotation tables only for
routes declaring annotation fields. Deduplicate repeated page deliveries only when
both measurement and annotations agree.

Store observation and unmeasured-slot annotation tables in partitioned Parquet,
covered by `integrity.json`, for both accumulated and compiled stores. Store
non-identity series attributes once in `manifest.json`, not on every observation
row. Keep manifests metadata-sized; do not embed annotation tables as base64 Arrow
IPC. Preserve selective reading and the shared atomic publication and integrity
contracts, including reuse of unchanged partitions.

Manual `cache="refresh"` and `rr.download` replace annotations within proven
successful coverage or applicable snapshot keys. An annotation-only change, such
as a USGS approval update with an unchanged value, must be observable after a
successful refresh. Failed refreshes preserve held data and annotations. Retain
the established distinction between live scoped replacement and compiled snapshot
replacement. Nothing refreshes automatically.

Bump accumulated-store, compiled-store, and bundle format versions cleanly. Refuse
older incompatible formats with explicit recovery guidance (`clear_cache` or
`download` for stores); do not add compatibility shims that pretend discarded
annotations can be recovered. Existing providers on `main` must still compile and
pass their applicable tests immediately, without requiring their full annotation
migrations in this Effort.

The implementing agent chooses the exact Parquet file names and layout within
partitions and the deterministic internal row/slot linking mechanism. These must
preserve one-to-one measurement associations, legitimate duplicates, unmeasured
slots, and stable public results. No particular hash, ordinal, or intermediate
identity model is prescribed.

## USGS end-to-end adoption

USGS is the one provider migrated and verified end-to-end in this Effort:

- Preserve OGC `approval_status` and `qualifier`, currently identified as validated
  and dropped by the parser. Establish scalar-versus-list `qualifier` applicability
  from genuine source evidence rather than assuming the prototype's encoding.
- Preserve exact repeated-page deduplication while retaining records whose
  annotations differ. Annotation changes must not alter stream identity.
- Audit series attributes, including `sublocation_identifier`, and other omitted
  OGC fields for applicable observation or non-identity series annotations.
- Bind source-backed descriptions and official references, and document the USGS
  workflow motivating [#621](https://github.com/RivRetrieve/RivRetrieve/issues/621).
- Retire QC-flag informational issues when their information is exposed through
  annotations. Keep retrieval, structural, coverage, and provenance diagnostics.

Source research determines which audited fields genuinely belong in these grains;
it is not permission to add inferred products or a generic metadata framework.

## Evidence of completion

Protect the public behavior and shared stage contracts with source-independent
checks. Demonstrate unchanged default schemas, selected/all annotation views,
unknown-field refusal, field discovery, direct schema access, and preservation
through retrieval, offline reuse, selection, UTC conversion, and bundles.
Demonstrate successful annotation-only refresh, failed-refresh preservation,
duplicate-delivery behavior, integrity refusal, and format-version refusal.
Shared checks must also exercise compiled stores and unmeasured slots even though
USGS is the selected real-provider migration.

Follow [the testing guide](../../docs/maintenance/testing.md) and
[the evidence guide](../../docs/maintenance/evidence.md). Verify USGS against genuine
archive inputs using independently reviewed revisions and the archive's maintained
checks. Missing mandatory evidence is blocked, not a passing synthetic substitute.
Keep controlled material out of the public repository and artifacts.

The earlier experiment reported bounded USGS and MLIT retained-source replay;
refresh controls were synthetic. That history is supporting context, not acceptance
of this implementation or proof of production-scale performance. Selecting USGS
does not certify other providers' source annotations.

Update `docs/architecture.md`, `docs/design/observation-store-layout.md`, and
`docs/maintenance/provider-ports.md`, along with public interface documentation and
the USGS usage explanation affected by this change. Run affected source-independent
checks and broader checks appropriate to the changed shared boundaries.

## Boundaries

Other provider annotation migrations remain separate Program Efforts. Shared format
and contract updates needed to keep them working are included here. Station-grain
metadata belongs to #602. Do not add interval-range annotation tables, a mandatory
slot table for every measurement, catalogue-wide annotation prefetch, automatic
refresh, or observation flags in the packaged station catalogue. Existing acquisition
scope remains the basis for collecting annotations.

Routine implementation choices remain with the implementing agent. The confirmed
outcomes above, source fidelity, and genuine-evidence acceptance are the constraints.
