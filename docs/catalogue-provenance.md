# Catalogue provenance and maintenance

This document owns the maintenance conventions for packaged provider catalogues. The
[domain glossary](../CONTEXT.md) defines origins, native tables and catalogue descriptors;
[`catalogue_origins.py`](../src/rivretrieve/_internal/catalogue_origins.py) enforces the
origin contract. Each certified canonical catalogue is a reproducible, network-free build
from a committed native table and its declarations.

## Evidence ownership

Catalogue evidence has four complementary homes:

- `src/rivretrieve/_internal/providers/<provider>/catalogue/provenance.json` binds packaged facts to
  source records, the committed native table, and five digest-bound public evidence relations.
- Provider generators, acquisition manifests, receipts, and tests hold machine-verifiable request,
  digest, schema, count, and semantic-frame checks.
- [`provider_ports/`](provider_ports/) holds provider-specific rationale, source limitations, and
  capture evidence that is needed for human audit but is not represented by the structured records.
- The generated Croissant descriptor beside each catalogue exposes its tables, issuing bodies,
  verbatim terms, file identities and [deliberate absences](catalogue-absence.md#absence) to machines.
  `rivretrieve.describe(provider)` reads this packaged document without network access.

The pure construction is in
[`catalogues/descriptor.py`](../src/rivretrieve/_internal/catalogues/descriptor.py).
Each provider's existing writer emits schema-v3 evidence and `croissant.json` from the exact packaged file bytes
and the verified build provenance. Extraction points to packaged columns, while standard
provenance relationships retain acquisition inputs and separate corroborating evidence.

A native-table acquisition record must identify every exact non-secret request, its UTC retrieval
instant, accepted row and station counts, deterministic canonicalization and ordering, SHA-256
evidence, and an exact semantic-frame comparison between the committed table and a fresh
materialization. The normal route is a live provider refresh. A complete response supplied by an
orchestrator outside a network-disabled executor is also acceptable with the same record.

A fixture may materialize a native table only when it is verified content-identical to a complete live
payload and the repository records the URL, retrieval instant, canonicalization, and digest. A
recovered historical import is permitted only when publisher routes cannot reproduce the complete
committed payload. Its record must bind the exact third-party materialization and commit, establish
raw-byte identity and a defensible provenance lower bound, cross-check identifiers against an
independent live source, and quantify coverage and agreement against every available publisher route.
A partial or coarser publisher route does not alone justify recovery; the provider notes must explain
why the complete committed payload cannot be reproduced.

## Row-level withholding

A committed native table and complete column origins do not by themselves establish every row-level
acquisition fact. Each structured `withheld_facts` group records a reason. When a group withholds
station or station-product rows, its explicit `catalogue_rows` locators identify the rows removed
during materialization. Packaged artefacts already contain that withholding and are loaded with
`withheld_rows_already_applied=True`; loading does not infer withholding from an absent fact binding.
The current affected providers are documented in their provider notes, and the executable result is
pinned by `tests/test_provider_row_withholding.py`.


## Current certification boundary

`ORIGIN_GATE_ENROLLED_PROVIDERS` in `catalogue_origins.py` is the executable certification boundary.
[ADR 0012](adr/0012-a-catalogue-column-declares-its-origin.md) records the original deferral boundary.
`no_nve` is enrolled after gaining a committed attested native table and complete origin declarations.
`br_ana` is enrolled after an attested inventory union and explicit Fluviometrica projection.
All acquired source rows remain in its native table. Its products and station-product facts
remain withheld pending source semantics and observation-stage certification. This intermediate
catalogue certification is not end-to-end Brazil observation delivery.

Brazil's former `--fixture`, `--live`, and `--withhold-uncertified` catalogue routes refuse
with a migration message. Materialize retained credential-free recordings first, then build
from the attested native table. See [Brazil maintenance](provider_ports/br_ana.md).

Commit `provider.json`, `products.parquet`, `stations.parquet`, `station_products.parquet`,
`provenance.json`, all five `provenance_*.parquet` relations, and the generated Croissant descriptor. Test fixtures must not republish
legacy uncertified catalogue values.

## Provider maintenance

After changing provider catalogue code or tests, run that provider's network-free build from its
committed native table and origins, then commit the resulting canonical artefacts with the change.
Never substitute a live or fixture-backed canonical build.

The descriptor is a build output; do not edit it by hand. Rebuild it whenever its tables,
origins or acquisition provenance change. Packaged file digests identify the emitted bytes;
native-table identities retain the recorded commit, digest and byte size. Private evidence
is identified by digest and is never copied into a distribution. Each issuing body's terms
stay on that body's material. A dataset with several issuing bodies does not acquire a
single combined licence or citation.

Runtime `license` and `citation` scalars follow their canonical provider-field bindings
to verified source statements. Explicit withholding and absence markers remain in force;
the runtime does not select an unrelated contributor's words to fill a scalar. Full
per-source statements remain available in acquisition provenance and in the descriptor.

Run the reference `mlcroissant` validator through the test suite for all thirteen outputs,
including Brazil's inventory-only descriptor. The validator is a development
dependency; reading a descriptor from an installed wheel must not import it. Catalogue
version and publication date come from the recorded catalogue date, and acquisition dates
remain source facts. No build clock enters the descriptor.

## Observation evidence

Observation fixtures follow [ADR 0024](adr/0024-an-observation-fixture-is-a-recording.md). That ADR,
not this catalogue procedure, owns exact request replay and the rule against treating constructed
payloads or retired implementations as source evidence.

## Public metadata migration: schema version 3

[ADR 0028](adr/0028-catalogue-evidence-is-normalized-once.md) and the
[versioned evidence profile](catalogue-evidence.md#profile-3) document the explicit
metadata migration. The descriptor is now bounded: it describes exact relational
files rather than repeating the national acquisition graph as JSON-LD nodes.
Resolving an individual fact or pair is an explicit offline relation traversal.

The nested Python `acquisition_provenance` value is now `CatalogueEvidence`:

- A selection carries a tuple in selected-provider order.
- An observation/catalogue provenance carries one value, or genuine `None`.
- `evidence.header` holds provider/native identity, source statements and withholding.
- `evidence.facts`, `.acquisitions`, `.bindings`, `.binding_facts`, and
  `.external_inputs` are typed Polars tables.

Old `.fact_bindings` and `.source_records[*].acquisitions` tuple access is not an
alias or an implicit full-graph projection. Use the profile's exact keys and joins.
Python model dumps retain Polars carriers; explicitly requested JSON dumps use the
normalized column-oriented representation. This changes metadata representation,
not the discovery/fetch signatures, returned observations or evidence conclusions.

The reader explicitly supports old schema-v2 catalogue files by validating and
normalizing them. The returned metadata type is the same for both file versions.
Unknown versions fail rather than falling back. V2 parsing and transitional generator
builds still pay the old object cost; v3 runtime reading does not reconstruct v2.
