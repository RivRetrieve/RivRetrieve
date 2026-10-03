# Catalogue provenance and maintenance

This document owns the maintenance conventions for packaged provider catalogues. The
[domain glossary](../CONTEXT.md) defines origins, native tables and catalogue descriptors;
[`catalogue_origins.py`](../src/rivretrieve/_internal/catalogue_origins.py) enforces the
origin contract. Each certified canonical catalogue is a reproducible, network-free build
from a verified native table in the private source archive and its declarations.

## Evidence ownership

Catalogue evidence and its interpretation have complementary homes:

- `src/rivretrieve/_internal/providers/<provider>/catalogue/provenance.json` binds packaged facts to
  source records, the retained native table, and five digest-bound public evidence relations.
- Provider generators and library tests check catalogue transformations against
  explicitly selected, verified archive inputs.
- The private [source archive](https://github.com/RivRetrieve/verification-evidence#readme)
  owns retained native tables, recordings, reviewed evidence ledgers, provider-specific
  source limitations and source-certification tools. Its README locates maintained
  verification instructions and historical records.
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
evidence, and an exact semantic-frame comparison between the retained table and a fresh
materialization. The normal route is a live provider refresh. A complete response supplied by an
orchestrator outside a network-disabled executor is also acceptable with the same record.

A fixture may materialize a native table only when it is verified content-identical to a complete live
payload and the repository records the URL, retrieval instant, canonicalization, and digest. A
recovered historical import is permitted only when publisher routes cannot reproduce the complete
retained payload. Its record must bind the exact third-party materialization and commit, establish
raw-byte identity and a defensible provenance lower bound, cross-check identifiers against an
independent live source, and quantify coverage and agreement against every available publisher route.
A partial or coarser publisher route does not alone justify recovery; the provider notes must explain
why the complete retained payload cannot be reproduced.

## Retained catalogue inputs

The private [source archive](https://github.com/RivRetrieve/verification-evidence#readme)
owns retained source material, selected real source cases, native tables and
source-certification verifiers. RivRetrieve owns catalogue transformations and
library declarations. Code references identify the actual owning repository and
reviewed revision, including private evidence ledgers. Source evidence bytes retain
their original digests. Case indexes are derived claims, not publisher payloads.

Inputs stay outside source checkouts and distributions. Use the shared
[evidence workflow](maintenance/evidence.md) to select exact verified inputs.
Missing bodies fail rather than triggering network acquisition. Archive instructions
state each provider's prerequisites and original-body limitations.

## Row-level withholding

A retained native table and complete column origins do not by themselves establish every row-level
acquisition fact. Each structured `withheld_facts` group records a reason. When a group withholds
station or station-product rows, its explicit `catalogue_rows` locators identify the rows removed
during materialization. Packaged artefacts already contain that withholding and are loaded with
`withheld_rows_already_applied=True`; loading does not infer withholding from an absent fact binding.
The current affected providers are documented in their provider notes, and the executable result is
pinned by `tests/test_provider_row_withholding.py`.


## Current certification boundary

`ORIGIN_GATE_ENROLLED_PROVIDERS` in `catalogue_origins.py` is the executable certification boundary.
Every provider in `ORIGIN_GATE_ENROLLED_PROVIDERS` has complete audited catalogue origin declarations.
All fourteen providers are enrolled: eleven live providers, Canada and Poland with bulk
stores, and South Africa with catalogue-only access. Certification concerns catalogue
origins; it does not activate observation retrieval.

Brazil retains all acquired source rows in its native table. Its six internal access routes describe two telemetry quantities and two daily-mean
physical products. The daily routes retain separate source-series identities. Both
Bruto (raw) and Consistido (quality-checked by ANA) daily series are included without
preference. Each certified river gauge is a candidate; availability remains unknown
unless exact source-variant observations establish bounded positive evidence. Request
windows never become published record bounds. Build from the attested native table;
see [Brazil offline rebuild](#brazil-offline-rebuild) for build instructions and the
private archive for source acquisition evidence.

Commit `provider.json`, `products.parquet`, `stations.parquet`, `station_products.parquet`,
`provenance.json`, all five `provenance_*.parquet` relations, and the generated Croissant descriptor. Test fixtures must not republish
legacy uncertified catalogue values.

## Provider maintenance

After changing provider catalogue code or tests, run that provider's network-free build from its
verified archived native table and origins, then commit the resulting canonical artefacts with the change.
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

Run the reference `mlcroissant` validator through the test suite for all fourteen outputs,
including Brazil's inventory and separately identified source series. The validator is a development
dependency; reading a descriptor from an installed wheel must not import it. Catalogue
version and publication date come from the recorded catalogue date, and acquisition dates
remain source facts. No build clock enters the descriptor.

### Brazil offline rebuild

Use the reviewed archive coordinator's catalogue-input mode described in the
[evidence workflow](maintenance/evidence.md). It supplies verified inputs and
`br_ana.build-inputs.json` outside the checkout. Set `EVIDENCE_ROOT` to the supplied
input root, `BUILD_INPUTS` to that selection file and `PRIVATE_OUTPUT` to a separate
external output directory. The selection is not the coordinator receipt
`catalogue-input-provenance.json`.

The capture record binds the retained inventory recordings and supporting files.
Materialization checks their identities before reconstructing the attested native
table. Historical paths beneath `EVIDENCE_ROOT` retain their acquisition identities;
they do not refer to files in the public checkout.

```sh
uv run python src/rivretrieve/_internal/providers/br_ana/generate_catalogue.py \
  --materialize-record "$EVIDENCE_ROOT/tests/test_data/br_ana_inventory/capture.json" \
  --evidence-root "$EVIDENCE_ROOT" --native-out "$PRIVATE_OUTPUT/ana-native.parquet"

uv run python src/rivretrieve/_internal/providers/br_ana/generate_catalogue.py \
  --native "$PRIVATE_OUTPUT/ana-native.parquet" \
  --evidence-root "$EVIDENCE_ROOT" \
  --build-inputs "$BUILD_INPUTS" \
  --out "$PRIVATE_OUTPUT/ana-catalogue"
```

The build uses retained inventory, telemetry and daily-source inputs. Failed
acquisition attempts remain distinct from successful retries. Review generated
products for both source fidelity and disclosure before adopting them. Acquisition,
source certification and original-body limitations are maintained in the
[private archive](https://github.com/RivRetrieve/verification-evidence#readme).

## Observation evidence

Observation fixtures record real source interactions. The [recording implementation](../src/rivretrieve/_internal/recordings.py)
replays exact requests. Constructed payloads and retired implementations do not establish
source evidence. See [verification](architecture.md#evidence-and-verification) for the testing contracts.

## Public catalogue evidence

The [versioned evidence profile](catalogue-evidence.md#profile-3) describes the exact
relational files and offline traversal of individual facts. The descriptor does not
repeat the national acquisition graph as JSON-LD nodes.

The Python `acquisition_provenance` value carries `CatalogueEvidence`:

- A selection carries a tuple in selected-provider order.
- Observation/catalogue provenance carries one value, or genuine `None`.
- `evidence.header` holds provider/native identity, source statements and withholding.
- `evidence.facts`, `.acquisitions`, `.bindings`, `.binding_facts`, and
  `.external_inputs` are typed Polars tables.

Python model dumps retain Polars carriers. Explicit JSON dumps use the normalized
column-oriented representation. Discovery does not expand or serialize the full graph.
