# France catalogue evidence

See [shared verification evidence](../../../docs/maintenance/evidence.md) for
archive access, exact input selection and verification prerequisites.

The authored `inventory/governing_evidence.json.xz` remains in this repository.
It binds the native station population to recorded station-product acquisitions.
The local declaration `evidence/official_publication.json` records publication
statements, not measurement authorship or redistribution rights. In the external
archive inputs, `inventory/inventory_summary.json` retains the corresponding source
survey summary. The two evidence bundles retain original receipts and available
source bodies.

Retrieve the selected inputs outside source checkouts in their repository-relative
layout. Set `EVIDENCE_ROOT` to that directory. Run from the code repository root:

```sh
export EVIDENCE_ROOT=/path/to/verified-inputs
export RIVRETRIEVE_TEST_EVIDENCE_ROOT="$EVIDENCE_ROOT"
```

Use the reviewed catalogue build through the [archive coordinator](../../../docs/maintenance/evidence.md)
to export `fr_hubeau.build-inputs.json` outside the checkout. Set
`BUILD_INPUTS` to that adopted `CatalogueBuildInputs` selection. The coordinator
receipt `catalogue-input-provenance.json` has a different schema. Keep these
files and generated outputs in the private output directory.

```sh
uv run python maintenance/catalogue/fr_hubeau/scripts/verify_governing_evidence.py \
  --native "$EVIDENCE_ROOT/maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet" \
  --ledger maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz \
  --official-index maintenance/catalogue/fr_hubeau/evidence/official_publication.json \
  --bundle "$EVIDENCE_ROOT/maintenance/catalogue/fr_hubeau/evidence/hubeau_counts.tar.xz" \
  --bundle "$EVIDENCE_ROOT/maintenance/catalogue/fr_hubeau/evidence/hydroportail_history.tar.xz"
uv run pytest tests/test_france_governing_evidence.py tests/test_france_source_evidence.py
```

The governing ledger binds the retained `inventory/native-2026-08-02.parquet`
snapshot. Use that historical input for this verifier. The current Hub’Eau catalogue
rebuild uses its current native table and separate publication-service scope.

Public verification checks ledger consistency and the retained bundle bytes.
It does not certify missing private bodies. Full body-backed verification requires
`--evidence-root /path/to/acquisition-bodies` with every body and receipt named by
the ledger and publication index. Original acquisition-relative references remain
unchanged, including `reused-pr231-head46b2fde/evidence/` bundle identities.
Missing private material is an error, not permission to skip verification or to
reacquire or publish source bodies.

That full-body root uses the acquisition-relative paths in the ledger. It is distinct
from the repository-relative `EVIDENCE_ROOT` used for retained build and test inputs.
Keep verifier output and full failure details private.

## Current Hub’Eau rebuild

```sh
uv run python maintenance/catalogue/fr_hubeau/inventory/build_catalogue.py \
  --evidence-root "$EVIDENCE_ROOT" \
  --build-inputs "$BUILD_INPUTS" \
  --revision RETAINED_NATIVE_REVISION \
  --out /path/to/private-output/hubeau-catalogue \
  --capture-output /path/to/private-output/native_capture.json
```

Use the retained native input's recorded revision. The build reads station responses
and receipts from the external root. `--availability-ledger` can select an explicit
authored ledger; its default is this repository's `inventory/governing_evidence.json.xz`.
Generated native and catalogue files go to `--out`. The generated acquisition record
goes to `--capture-output`. Both destinations must be outside source checkouts and
separate from retained inputs. Source identities keep their original repository paths,
regardless of the output location. Review generated products before publishing them.
