# Catalogue evidence

## Profile 3

Profile URI: `https://github.com/RivRetrieve/RivRetrieve/blob/main/docs/catalogue-evidence.md#profile-3`.

`describe(provider)` reads the packaged Croissant 1.0 JSON-LD offline. Its
`schemaVersion` identifies this profile. `version` and `datePublished` still name
the source catalogue date, when established. The descriptor describes relational files without expanding the national acquisition
graph. Individual fact lineage can be resolved offline when needed.

### Packaged files and trust boundary

The descriptor declares ten exact file identities: `provider.json`,
`products.parquet`, `stations.parquet`, `station_products.parquet`,
`provenance.json`, and the five evidence Parquets below. Each distribution includes
its relative `contentUrl`, SHA-256, byte count (`contentSize`) and media type.
`native.parquet` is not packaged. Its external revision-pinned identity remains
`isBasedOn` on the descriptor when established.

Validate the descriptor distributions and the schema-version-3 header against the
actual supplied bytes before reading relations. The header's `files` key set is
exactly the five evidence basenames. Each value's `path` equals its key. Absolute
paths, URL authority, directories, parent traversal and symlinks are not permitted.
The composition root reads those exact local files; no resolver discovers files or
fetches an agency. Header identities also carry exact row counts and schema version.

The header preserves ordered source records, descriptions, transformation
declarations, withholding and row-locator requirements. Source records preserve
issuer, operator, evidence recording identities, source statements and private
verification states. They do not inline acquisitions. Private verification remains
redacted. This profile does not publish private source bodies or interpret licences.

### Fixed physical relations

All integer keys are `UInt32`. Strings use Parquet string columns. Material byte
counts are `Int64`. `?` means nullable. Every other column and every list member is
non-null. The physical column order below is normative.

| Relation and basename | Columns in physical order |
| --- | --- |
| facts: `provenance_facts.parquet` | fact_id:UInt32, name:String, carrier:String?, station_id:String?, product_id:String?, locator_role:String? |
| acquisitions: `provenance_acquisitions.parquet` | acquisition_key:UInt32, source_ordinal:UInt32, acquisition_ordinal:UInt32, acquisition_id:String, method:String, instant_type:String, description_id:UInt32, requested_from:List(String), retrieved_at_start:String?, retrieved_at_end:String?, recording_ids:List(String), material_filename:String?, material_sha256:String?, material_byte_count:Int64? |
| bindings: `provenance_bindings.parquet` | binding_id:UInt32, fact_group:String, source_ordinal:UInt32?, acquisition_key:UInt32?, transformation_id:UInt32? |
| binding_facts: `provenance_binding_facts.parquet` | binding_id:UInt32, position:UInt32, fact_id:UInt32 |
| external_inputs: `provenance_external_inputs.parquet` | binding_id:UInt32, position:UInt32, source_ordinal:UInt32?, fact_id:UInt32 |

Croissant RecordSets are named `provenance_` plus the relation name. Every column
has its exact extraction source and scalar `dataType`. List columns declare
`isArray: true`, `arrayShape: "-1"`. RecordSet keys are `fact_id`,
`acquisition_key`, `binding_id`, and `(binding_id, position)` for each edge table.
Croissant `references` connects foreign `fact_id`, `binding_id`, and
`acquisition_key` to the exact owning file and column, using standard
`fileObject` and `extract.column`. This is the same key exposed by its owning
RecordSet Field. Physical-column references support the reference loader's actual
extraction; its cross-RecordSet `references.field` path currently fails when a join
receives a record generator rather than a DataFrame. No loader patch or bypass is
required. A reference is a foreign-key relation, not an instruction to interpret
a Parquet file as an RDF graph.

The physical widths, nullable shapes, header-array indices, ownership constraints
and tuple order are profile rules enforced by the evidence validator. Croissant
alone does not certify them. Empty tables carry the same complete schema.

IDs are unique contiguous zero-based original positions. Source-local acquisition
ordinals preserve acquisition order. Descriptions and transformation declarations
are deduplicated only by exact value in first-occurrence order. Binding membership
and external input positions preserve original tuple order and repeated inputs.
Names and fact groups are unique. Every fact has exactly one producer or withholding
account. Bindings are either an exact source/acquisition pair or a transformation,
never both. All references, source ownership and statement acquisition links must
close. Runtime observation acquisitions cannot ground packaged catalogue facts,
directly or transitively. Cycles and incompatible absence markers are rejected.

`source_ordinal` indexes `header.source_records`. `description_id` indexes
`header.descriptions`. `transformation_id` indexes `header.transformations`.
Acquisitions preserve each exact ordered request location, retrieval instant or
interval, recording ID and optional material identity. They are not campaign summaries.
A material identity is all three material columns present or all three null.

### Exact fact and row location

Every canonical Croissant Field has `subjectOf` containing a standard CreativeWork
locator. Its `identifier` is the exact `facts.name` key. Its `url` names the fact
relation, and `conformsTo` names this profile. This locator is not an inline RDF
ancestor. RecordSets reference the locator schema, not a national list of row nodes.

A non-row fact has all four locator columns null. A station locator has carrier
`station`, exact station ID and role, with null product ID. A station-product
locator has carrier `station_product`, exact station ID, exact product ID and role.
Non-null locator keys are unique. Availability uses role `availability`. Required
roles cover every exact canonical key, including unknown availability. Fact names
are checked against literal established key productions. Never split or truncate
an ID, generate a station × product cross-product or replace a source fact with a
derived name. Unlocated facts remain individually selectable by exact name.

Availability and its precise reason belong to the canonical station-product row.
They are not duplicated in the evidence tables or inferred from acquisition text.

### Offline Python and Polars inspection

Selections carry catalogue evidence in `acquisition_provenance`, in selected-provider
order. Each value is a `CatalogueEvidence`. Access source words through
`evidence.header.source_records`; inspect acquisition records through Polars relations.

```python
import polars as pl
import rivretrieve as rr

selection = rr.find(provider="ba_fhmzbih", station="2101-B", quantity="temperature")
evidence = selection.acquisition_provenance[0]
row = rr.series(selection).row(0, named=True)
fact = evidence.facts.filter(
    (pl.col("station_id") == row["station_id"])
    & (pl.col("product_id") == row["product_id"])
    & (pl.col("locator_role") == "availability")
)
producer = fact.join(evidence.binding_facts, on="fact_id").join(
    evidence.bindings, on="binding_id"
)
# This availability fact is transformed from an acquired workbook fact.
inputs = producer.select("binding_id").join(evidence.external_inputs, on="binding_id")
input_facts = inputs.select("fact_id").join(evidence.facts, on="fact_id")
input_producers = input_facts.join(evidence.binding_facts, on="fact_id").join(
    evidence.bindings, on="binding_id"
)
direct = input_producers.join(evidence.acquisitions, on="acquisition_key")
# For other transformed facts, follow their exact dependencies in the same way.
# source_ordinal identifies the issuing source, not an inferred measurement producer.
```

For catalogue-maintenance work, the internal pure resolver supplies standard
JSON-LD for exact fact names. It takes validated evidence and performs no network
requests. This internal interface is not a public observation API. The optional
`CanonicalPair` input requires a canonical availability row, not a series-inspection
row: `rr.series` describes source identities and does not certify availability.
Install `rdflib` separately to run the RDF consumer portion below, for example
with `uv run --with rdflib python your_script.py`.

```python
from rivretrieve._internal.catalogues.evidence_graph import (
    FactSelection, resolve_evidence,
)

graph_document = resolve_evidence(
    evidence, FactSelection(names=(fact["name"].item(),))
)
# Optional consumer dependency, not imported by RivRetrieve:
import json
from rdflib import Graph
graph = Graph().parse(data=json.dumps(graph_document), format="json-ld")
```

The result's `about` selects exact fact nodes. Follow `isBasedOn` from those nodes
through binding nodes and their exact external inputs to acquired materials.
`hasPart` on each binding retains its ordered multi-output membership. Acquisition
`about` explicitly links the issuing source. `license`, `citation` and `usageInfo`
explicitly reference that source's statement nodes; each exact quotation appears
once. Recording nodes retain exact URLs, instants, digests and source-local IDs.
Corroborating material is separately labelled under `citation`, outside historical
`isBasedOn` ancestry. Deliberate withholding uses `rr:absence`. No other extension
predicate is introduced. Private locations are not promoted to download URLs.

Full metadata JSON serialization is explicit and proportional to relation size:
`model_dump(mode="python")` carries DataFrames, while `model_dump(mode="json")`
and `model_dump_json()` carry the header plus five column-oriented dictionaries.
The strict JSON parser accepts that normalized shape. A JSON value round-trip is
not a certificate of possession of the original digest-bound Parquet bytes.
Discovery, fetch and describe do not call full serialization or expand this graph.


### Unacquired station-product facts

An explicitly unknown candidate availability is not a claim of source silence.
A row-scoped `station_product:<station_id>:<product_id>.availability` fact can be
an `absence_marker` with `marker_value=unknown` and a withheld external input whose
reason is `no_acquisition_record_established`. The exact station/product must exist
in the emitted catalogue and its availability must be `unknown`. Row-locator
completeness still covers every candidate. Nonexistent pairs, misspelled roles,
other row-scoped fields and mismatched marker values are rejected.

The two nullable `station_product.published_record_start_date` and
`station_product.published_record_end_date` column facts also admit an explicit
`null` absence marker when their acquisition is unestablished. Probed windows and
station operating periods do not become published product record bounds.
Nested input validation, normalized evidence validation and final carrier-value
validation enforce the same narrow vocabulary. This extends supported absence
carriers without weakening source attribution or treating an unknown as unavailable.
