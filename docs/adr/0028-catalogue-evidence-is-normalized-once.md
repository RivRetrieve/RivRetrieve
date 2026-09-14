# ADR-0028: Catalogue evidence is normalized once and described by bounded Croissant

## Status

Accepted. This is an explicit public provenance-file, descriptor JSON/RDF, and nested
Python acquisition-provenance representation migration. Discovery and retrieval call
signatures and observation behavior do not change.

## Context

France's 33,139 evidenced station/product pairs generated 55,085,081 bytes of
provenance JSON and a second 102,402,010-byte Croissant projection. Ordinary USGS
selection loaded all 13 providers atomically and constructed France's national
Pydantic graph, even though only the requested provider's selection was returned.
The provenance carried 68,539 bindings and 35,397 acquisitions. Removing whitespace
or compressing and then expanding those same objects would not repair the runtime
representation.

## Decision

A catalogue publishes one schema-version-3 evidence header and five fixed-schema
Parquet relations: facts, acquisitions, bindings, binding membership, and exact
external inputs. Shared issuing-source statements, acquisition descriptions and
transformation declarations occur once. Source-local acquisition ordinals and
membership/input positions preserve the complete ordered evidence account.
Per-pair dependencies remain separate. No output is connected to an unrelated union
of acquisitions. Unknown availability stays selectable with its exact recorded reason.

The runtime `CatalogueEvidence` value carries the typed header and Polars relations,
not a per-row hierarchy. The nested `acquisition_provenance` members of selections
and results now expose that value. This is a documented breaking metadata-format
change; no lazy legacy facade, disguised tuple, or hidden graph expansion is retained.
Existing schema-v2 files remain deliberately readable through strict v2 validation
and normalization. Transitional builds may still construct the v2 input model;
new v3 runtime loading may not.

Croissant remains the standard catalogue descriptor. It describes the canonical and
evidence tables, hashes every packaged file, and declares extraction and relations.
Its size does not grow by emitting one node per acquisition or pair. An explicit
local resolver follows a selected fact's exact closure and can produce standard
JSON-LD for that closure. The bounded descriptor alone is not claimed to have the
old expanded transitive RDF graph. The only custom RDF predicate remains `rr:absence`.
The versioned [evidence profile](../catalogue-evidence.md#profile-3) fixes the new
schemas, offline resolution rules and Python inspection/serialization contract.

All whole-manifest corruption handling and vocabulary errors remain unchanged.
Every provider is fully validated before registration mutates the registry. Runtime
terms still follow their canonical provider-field bindings to the exact verified
source statements. Public RecordingReferences remain genuine and verified during
builds. Private bodies and committed native inputs are not wheel contents.

## Consequences

Users reading the former nested Pydantic tuples must migrate to typed header fields
and relation joins. `find`, `fetch`, the five observation columns, units, wall clocks,
receipts, issues, native input identity and each exact acquisition link are unchanged.
Full metadata JSON serialization is explicit and can cost memory proportional to
rows; ordinary discovery/retrieval does not serialize or expand that graph.

Resource acceptance measures the actual public paths in fresh processes, separately
from build and explicit full-value serialization costs. Red tests instrumented the
old public discovery and generator paths before this repair. Exact ordered v2/v3
round-trip and per-pair evidence tests supplement file-size and allocation-path
assertions. Historical Git blobs remain historical; no history rewrite is required.
