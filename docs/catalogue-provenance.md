# Catalogue provenance and maintenance

This document owns the maintenance conventions for packaged provider catalogues. The architecture is
owned by [ADR 0012](adr/0012-a-catalogue-column-declares-its-origin.md) and
[ADR 0013](adr/0013-the-catalogue-is-built-from-a-committed-native-table.md): each canonical column
declares its origin, and each certified canonical catalogue is a pure, network-free build from a
committed native table and those declarations. This document does not restate those decisions.

## Evidence ownership

Catalogue evidence has three complementary homes:

- `src/rivretrieve/_internal/providers/<provider>/catalogue/provenance.json` binds packaged facts to
  source records and the committed native table.
- Provider generators, acquisition manifests, receipts, and tests hold machine-verifiable request,
  digest, schema, count, and semantic-frame checks.
- [`provider_ports/`](provider_ports/) holds provider-specific rationale, source limitations, and
  capture evidence that is needed for human audit but is not represented by the structured records.

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
[ADR 0012](adr/0012-a-catalogue-column-declares-its-origin.md) records why `br_ana` and `no_nve` remain
outside it pending the credentialed native acquisition in
[issue 90](https://github.com/RivRetrieve/RivRetrieve/issues/90). Until each gains a committed attested
native table and origin declarations, generate its deterministic empty catalogue with:

```bash
uv run python src/rivretrieve/_internal/providers/<provider>/generate_catalogue.py \
  --withhold-uncertified \
  --catalogue-date <existing-version> \
  --out src/rivretrieve/_internal/providers/<provider>/catalogue/
```

Commit `provider.json`, `products.parquet`, `stations.parquet`, `station_products.parquet`, and
`provenance.json`. Test fixtures must not republish legacy uncertified catalogue values.

## Provider maintenance

After changing provider catalogue code or tests, run that provider's network-free build from its
committed native table and origins, then commit the resulting canonical artefacts with the change.
Never substitute a live or fixture-backed canonical build.

## Observation evidence

Observation fixtures follow [ADR 0024](adr/0024-an-observation-fixture-is-a-recording.md). That ADR,
not this catalogue procedure, owns exact request replay and the rule against treating constructed
payloads or retired implementations as source evidence.
