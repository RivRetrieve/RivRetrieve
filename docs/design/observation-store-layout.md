# Observation store layout

## Status and authority

This document is the normative observation-store format contract. `MUST`, `MUST NOT`,
`REQUIRED`, `SHOULD`, and `MAY` have their RFC 2119 meanings. The machine-readable
manifest schema is `src/rivretrieve/_internal/store/manifest.schema.json`; the valid and
intentionally invalid conformance stores are rooted at
`tests/test_data/observation_store_conformance/`. Supported stores must implement this
contract. Refusal fixtures also include unsupported formats. Runtime validation checks
the typed source-series records and their references.

The revision-5 contract below applies to stores produced by compiling a publisher
artifact. The accumulated-store revision-7 section specifies live-provider parse output
and names its separately addressable manifest schema.

This contract specifies data at rest. It does not specify or implement a store reader,
a compiler, a provider port, or download behaviour.

## Physical layout

Stores use Hive-partitioned Parquet with partition keys `product` and `year`.
Directories have the form `product=<product_id>/year=<YYYY>/`, with one Parquet file
per partition and rows sorted by `station_id`. The canonical partition identifier
`product=<product_id>/year=<YYYY>` keys the manifest's per-partition row counts.

The store root contains one manifest named `manifest.json` and the partition tree. A
`product_id` is the internal RivRetrieve product route and `YYYY` is the four-digit
year of the row's native source wall-clock timestamp. A partition directory contains
exactly one file with the `.parquet` suffix; the file's basename is not part of the
format contract. The Parquet basename is deliberately unspecified and MUST NOT be fixed
to `data.parquet` or any other name. Empty partitions MUST NOT be materialised.

The complete required physical Parquet row schema has these engine-facing columns, with
the exact names shown:

| Column | Required representation |
|---|---|
| `station_id` | The source station identifier represented as a non-empty string. |
| `time` | The source-published naive wall-clock timestamp, represented as a Parquet timestamp without a time zone. |
| `time_zone` | The source-published zone, or the canonical `unknown` token only where the source establishes none. |
| `value` | The source value in its native unit, nullable only as allowed by `value_state`. |
| `value_state` | One of the three stored-row tokens specified below. |
| `series_id` | Concrete source-series identity declared in the manifest. |
| `facts_id` | Physical-fact segment declared for that series. |
| `source_unit` | Exact source-unit value established by that fact segment. |

The partition path supplies `product` and `year`; they need not be duplicated as physical
Parquet columns. A reader MUST treat the Hive partition values as columns. Additional
provider-native columns are permitted and are governed by source-column disposition.
The required physical names are exactly `station_id`, `time`, `time_zone`, `value`,
`value_state`, `series_id`, `facts_id`, and `source_unit`; `source_time` and `native_value` are not format column names.

Revision `5` fixes the physical encoding of the engine-facing columns: they MUST be the
first eight fields of the Parquet schema, in the order shown in the table above;
`station_id`, `time_zone`, `value_state`, `series_id`, `facts_id`, and `source_unit` MUST be UTF-8 string fields; `time` MUST be a
microsecond-precision timestamp without a time zone; and `value` MUST be a 64-bit binary
floating-point field. Additional provider-native columns follow that prefix.
Rows MUST be nondecreasing by `station_id` under bytewise UTF-8 ordering. Ordering among
rows with the same `station_id` is not part of this format version. The pair of partition
identifier and physical row position identifies a stored row. Duplicate source rows MUST
be preserved; a reader or validator MUST NOT reject rows merely because they are
duplicates.

## Value states

Stored rows carry a `value_state` column whose exact token set is `published_null`, `published_blank`, and `published_value`; no record is represented by row absence within a declared source-series/fact/day case universe.

The declared source-series/fact/day case universe is the explicit set of cases supplied to
conformance or certified compilation. It MUST NOT be inferred from a store's minimum and
maximum dates, and it MUST NOT be expanded by fabricating placeholder rows. Within that
universe, these are the only legal combinations:

| Source statement | Physical row | `value_state` | `value` |
|---|---|---|---|
| No record | absent | not applicable | not applicable |
| Published record with a null value | present | `published_null` | null |
| Published record with a blank value field | present | `published_blank` | null |
| Published record with a value | present | `published_value` | non-null native value |

A present row with any other `value_state`, a non-null value beside `published_null` or
`published_blank`, or a null value beside `published_value` is malformed. Null and blank
remain distinguishable through `value_state`; no-record remains distinguishable through
row absence relative to the declared universe. A compiler MUST establish the distinction
before parsing or typing can collapse it.

## Source-column disposition and preservation

Each record has `source_column`, a `disposition` drawn from exactly `retained`, `reconstructible`, and `deliberately_discarded`, `reconstruction_rule` containing the reconstruction rule and required when and only when the disposition is `reconstructible`, and `rationale` required when and only when the disposition is `deliberately_discarded`; completeness means every source column of the declared source schema appears exactly once.

`source_column` values MUST be unique within the disposition list. A `retained` record
MUST contain neither `reconstruction_rule` nor `rationale`. A `reconstructible` record
MUST contain `reconstruction_rule` and MUST NOT contain `rationale`. A
`deliberately_discarded` record MUST contain `rationale` and MUST NOT contain
`reconstruction_rule`. Empty rules and rationales do not satisfy the requirement.

Compile preserves by default. Every published observation cell, including a quality
field or other field RivRetrieve does not read, MUST be retained unless the manifest
declares it reconstructible or deliberately discarded. A field is reconstructible only
when its exact source value can be recovered deterministically from retained fields by
the stated rule. Convenience, current reader use, and conversion to a canonical value
are not rationales for discard. A compiler MUST refuse a source schema with an absent,
duplicate, unknown, or retyped column before publishing a store. Certified compilation
MUST compare the observed source schema with the declared schema and enforce disposition
closure mechanically.

Provider-native columns retain the source's vocabulary and values. When a native name
collides with an engine-facing column or cannot be represented faithfully as a Parquet
field name, revision `5` compilation MUST refuse the source schema. It MUST NOT silently
rename, overwrite, or drop the column.

## Bounded certified compilation

A large publisher source is consumed as an ordered `ObservationBatchStream`. Every batch is checked against the complete engine and retained-source schema before its deterministic Parquet row group is written. Product/year partitions are strictly increasing and station identifiers are bytewise nondecreasing within a partition. The writer preserves observation duplicates. A provider may remove only exact full-row overlap when its declared publication artifacts overlap.

Source-unit names are checked for global uniqueness with a temporary disk-backed journal. Accepted and emitted counts must agree in each batch and globally. The journal is not part of the published store.

Certification performs a second bounded decode of the unchanged publisher artifacts and compares every physical field exactly with the staged Parquet row groups. Manifest validation also scans required physical fields in bounded Arrow batches. Only simultaneous complete source and store exhaustion permits atomic publication and artifact deletion.

## Native representation and the read boundary

Values are stored in source units. Timestamps are stored as source wall-clock values,
without converting them to UTC or attaching an inferred zone. Unit conversion occurs
only on read through the existing convert stage. Exact clipping to the
requested closed wall-clock window also occurs only on read through that convert stage. A storage scan MAY use a conservative time predicate to reduce I/O, but
it MUST return a superset sufficient for convert to remain the authority for clipping.

Standardising the container does not author new measurements, interpret quality codes,
or promote source-only fields into the returned observation frame. Quality fields remain
preserved native cells and may be reached through a store-excerpt receipt; they are not
native annotations in the observation frame.

## Manifest semantics

The manifest is UTF-8 JSON and is validated against
`src/rivretrieve/_internal/store/manifest.schema.json`. The schema owns the exact JSON
property spelling. It MUST require exactly one value for each semantic field below:

| Semantic field | Canonical form and meaning |
|---|---|
| Format version | The positive integer format revision. This contract is revision `5`; an implementation recognises only revisions it explicitly supports. |
| Provider identity | The exact non-empty provider id whose declared bulk configuration and unit conversion may read the store. Validation MUST refuse a different requested provider before reading rows. |
| Compiler version | A non-empty PEP 440 version string identifying the RivRetrieve compiler that produced the store. |
| UTC build time | An RFC 3339 UTC instant in `YYYY-MM-DDTHH:MM:SS.ffffffZ` form, recording completion of the staged build before publication. |
| Source vintage | A source-dated release or coverage-end date in `YYYY-MM-DD` form, according to the provider declaration. It is derived from an exact publisher label, never from retrieval time, build time, freshness judgement, or filesystem timestamp. |
| Publisher-artifact URLs | Each absolute `https` URL actually used to retrieve an artifact, retained in deterministic download order without semantic rewriting. A single-artifact store uses `publisher_artifact`; a multi-artifact store uses `publisher_artifacts`. |
| Publisher-artifact checksums | For every URL, `sha256:` followed by exactly 64 lowercase hexadecimal digits for those complete artifact bytes. |
| Source-schema fingerprint | `sha256:` followed by exactly 64 lowercase hexadecimal digits for the compiler's deterministic canonical encoding of the declared ordered source schema, including source column names and source data types. |
| Per-partition row counts | A JSON object whose keys are canonical partition identifiers and whose values are positive JSON integers equal to the Parquet row counts. |
| Source-column dispositions | The complete list of disposition records specified above. |
| Series and evidence | Required `series`, `inventories`, `outcomes`, `issues`, and `source_calls` arrays, described below. |

The source-schema fingerprint MUST cover both the ordered source column names and the
source data types; hashing column names alone is nonconforming.

Revision `5` fixes that canonical encoding: the ordered `columns` list is serialised as
JSON with object keys sorted, no insignificant whitespace, and non-ASCII characters left
unescaped, then encoded as UTF-8 and hashed with SHA-256; the manifest records the digest
with the `sha256:` prefix. A reader MUST recompute the fingerprint under this encoding and
MUST refuse a store whose recorded fingerprint disagrees.

The partition-count object MUST contain exactly one key for every materialised partition
and no other key. Each key MUST have the form
`product=<product_id>/year=<YYYY>` and MUST equal its partition's relative directory path
without a trailing slash. The product and year encoded by a row's partition MUST agree
with the row's product and native wall-clock year. Every declared count MUST equal the
physical Parquet row count. Canonical partition identifiers, source-column names, and
disposition records MUST be unique where this document requires uniqueness.

The artifact checksum makes provenance identifiable: it proves which downloaded bytes
were compiled. It does not make provenance reproducible, retain the artifact, prove the
publisher will continue serving it, or allow reconstruction from the checksum. The
artifact and intermediates are deleted only after certified compilation succeeds;
only URL, publisher-dated vintage, checksum, and schema fingerprint survive in
the manifest.

## Source identity and evidence

Both manifest kinds MUST contain `series`, `inventories`, `outcomes`, `issues`, and
`source_calls`. These records are validated with the domain models in
`src/rivretrieve/_internal/source_series.py`, the issue model and source-call decoder.

- `series` holds concrete identities with provider, station and internal product route,
  source namespace and published identifier, optional variant, and physical-fact segments.
  Each fact carries its evidence state. `known`, `source_silent`, and `not_established`
  remain distinct; an unknown fact is not filled from another series.
- `inventories` records membership within a declared scope, access path, evidence and
  completeness (`complete`, `incomplete`, or `unresolved`). Optional windows and acquisition
  facts bound the claim. An inventory is not a record of successful retrieval.
- `outcomes` records requested windows and `success`, `empty`, `failed`, `unsupported`,
  `unresolved`, or `no_match` results. A successful outcome identifies a concrete series
  and its physical facts. Other outcomes retain a reason; a requested selector can remain
  recorded without inventing a source identity.
- `issues` retains issue identity, severity and reason. `source_calls` retains source-call
  provenance, not publisher payload bytes or request headers.

Every physical row MUST reference a declared series and one of its fact segments.
Its station and partition product MUST agree with the series. Its source unit MUST
match that segment, and the segment MUST support the declared physical conversion.
Distinct published identities MUST remain distinct even when their physical facts match.

## Compatibility and refusal

A reader MUST validate the manifest before reading any partition. It MUST refuse an
unknown format version, missing or mistyped required field, noncanonical checksum or
fingerprint, duplicate or incomplete disposition, illegal disposition condition,
noncanonical partition key, path/key disagreement, row/count disagreement, illegal
value/state combination, extra partition, or missing partition. Refusal means no partial
interpretation, no in-place repair and no download. The error MUST identify the
store as incompatible or malformed and name the explicit rebuild operation. Compiler
version identifies the writer; it does not grant compatibility. Source vintage is
reported as a dated fact and MUST NOT be converted into stale/fresh status.

## Predicate-pushdown contract

A conforming reader expresses product, year, station, and conservative time restrictions
to the Parquet dataset scan rather than eagerly loading all partitions. Hive directory
filters eliminate unrelated products and years before file reads. The one-file partition
and `station_id` ordering permit Parquet row-group statistics to eliminate unrelated
station ranges; writers SHOULD emit row groups with `station_id` statistics. Time
pushdown may reduce the conservative candidate set, but the convert stage owns
exact requested-window clipping. Predicate pushdown changes I/O, never semantics.

## Analysis against source shapes

### Environment Canada HYDAT

HYDAT arrives as one national SQLite publisher artifact. Its `DLY_FLOWS` and
`DLY_LEVELS` tables are wide monthly rows keyed by `STATION_NUMBER`, `YEAR`, and `MONTH`,
with `NO_DAYS`, day-numbered native value columns, and paired day-numbered quality-symbol
columns. Compilation must unpivot each published day into a native daily row without
losing the value-state distinction or the quality cell. The table selects the canonical
product; `YEAR` selects the year partition; and sorting by `station_id` makes a national
partition prunable for a station query. A station/product/window read prunes the other
product and year directories first and then uses station statistics within the remaining
files. The single input artifact affects download and peak-space planning, not the store
shape. Source-column closure applies to every column in each HYDAT table, including
monthly fields and quality symbols; repeated or exactly reconstructible fields require
explicit disposition records rather than silent omission.

### Poland IMGW

IMGW arrives as yearly archives containing CSV source units, with monthly variants in
the published set. The `codz_YYYY` archive year is the Polish hydrological year, running
from November through October; it is not the calendar partition year. The partition year
is the row's calendar wall-clock year, derived per row from the archive's hydrological
year and the calendar-month column: November and December use hydrological year minus one,
and January through October use the hydrological year. One archive therefore contributes
rows to two adjacent `year=` partitions. Product identity maps to the
`product=<product_id>` partition. Blank CSV fields must be observed before typing and
stored as `published_blank`; source nulls, where the declared CSV schema distinguishes
them, use `published_null`; absent station-product-day records remain absent rows. Native
quality and otherwise unused CSV columns remain retained unless their disposition
explicitly proves reconstruction or argues a discard. Queries prune year and product
directories and then station ranges. Monthly archive boundaries do not change the annual physical partition
contract: their rows are compiled into the one file for that product/year partition.

## Compilation and accumulated storage

### IMGW partition finalisation

Revision `5` compilation of an ordered IMGW archive set uses two passes. The first pass establishes
every archive contribution and the final row count for each calendar `product`/`year` partition. The
second pass streams contributing rows into the single file for that partition. A compiler MUST NOT
finalise a partition file or its manifest count while an unread adjacent archive can still contribute.
The partition remains a calendar product/year partition.

### Accumulated-store format revision 7

Compiled stores use revision `5`. Accumulated live-provider parse output uses revision
`7`, described by `manifest.schema.json#accumulated`. Readers MUST check the revision
before opening any Parquet file. Unsupported revisions are refused with the store path
and an explicit operation: `download` for a compiled store or `clear_cache` for an
accumulated store.

The accumulated manifest contains exactly `format_version`, `provider_id`, `built_at`,
`coverage`, `partition_row_counts`, `series`, `inventories`, `outcomes`, `issues`, and
`source_calls`. `built_at` is the UTC write instant with six fractional digits and `Z`.
Coverage and partition counts MAY be empty: inventory and unsuccessful outcomes can be
stored even when no successful interval or observation row exists.

Each coverage record contains exactly `series_id`, `start`, `end`, `retrieved_at`,
`outcome_id`, and `facts_ids`. Endpoints are closed, naive native wall-clock timestamps;
the writer uses microsecond precision. `retrieved_at` is a UTC instant with six fractional
digits and `Z`, or null when not established. `facts_ids` is a nonempty, unique list.
Coverage MUST cite a `success` or `empty` outcome for the same series and retrieval
instant, whose window contains the covered interval and whose facts include the covered
facts. Coverage MUST NOT overlap for the same series and any shared fact segment.

Coverage records successful requested intervals, not fetch padding. Calendar-date
clipping expands daily intervals to the full native date axis used by convert. A
successful empty source answer still records coverage. Coverage makes no freshness,
expiry, or age claim.

Partitions use `product=<id>/year=<native-year>`, one Parquet file per partition,
station-id ordering, and the eight-column physical prefix specified above. No
provider-native columns follow that prefix. `published_value` denotes a non-null native
value and `published_null` a null value; `published_blank` is forbidden. Every row MUST
fall within coverage for its series and facts. Duplicate rows remain distinct.

Reuse checks both acquired inventory evidence and successful coverage for the requested
source identities and physical facts. Coverage checks use the microsecond axis. If the
requested scope is fully covered, held rows are served without source access. Otherwise
the driver reacquires the full requested scope and interval for that station and internal
product route, with fetch padding; it does not request only uncovered dates. Successful
replacements affect only their concrete
series, physical facts and requested interval. Padding cannot overwrite held rows.
Refresh replaces those rows and coverage with the successful current answer, including
an empty answer. Failed refreshes preserve held rows and successful coverage; their
outcomes and issues can still be recorded. Inventory evidence remains separate from
successful coverage. Matching facts never allow one source identity to cover another.

A provider store has one writer, guarded by a sibling write-lock directory. Writes stage
a complete candidate beside the store, validate it, then replace its directory. Partition
files are not modified in place. A failed stage leaves the previous store intact.
An interruption between renames can leave a sibling backup requiring manual recovery.
A subsequent reuse or refresh refuses before source access when a backup exists.
Explicit `clear_cache` deletes the canonical store and pending and backup namespaces;
it does not remove an active write lock. Concurrent reader/writer access and automatic
recovery are not guaranteed.

Publisher payload bytes are not stored. A held receipt is a store excerpt encoded from
selected physical rows, with served coverage and retrieval instants in provenance.
