# France catalogue evidence

See [shared verification evidence](../../../docs/maintenance/evidence.md) for access,
collection selection and integrity checks. The [provider index](../../evidence/index.json)
records retained material, applicable commands and known gaps.

`inventory/governing_evidence.json.xz` binds the native station population to
recorded station-product acquisitions. `inventory/inventory_summary.json` retains
the corresponding source survey summary. `evidence/official_publication.json`
records publication statements, not measurement authorship or redistribution rights.
The two evidence bundles retain original receipts and available source bodies.

Run from the repository root:

```sh
uv run python maintenance/catalogue/fr_hubeau/scripts/verify_governing_evidence.py \
  --native maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet \
  --ledger maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz \
  --bundle maintenance/catalogue/fr_hubeau/evidence/hubeau_counts.tar.xz \
  --bundle maintenance/catalogue/fr_hubeau/evidence/hydroportail_history.tar.xz
uv run pytest tests/test_france_governing_evidence.py tests/test_france_source_evidence.py
```

The governing ledger binds the retained `inventory/native-2026-08-02.parquet`
snapshot. Use that historical input for this verifier. The current Hub’Eau catalogue
rebuild uses its current native table and separate publication-service scope.

Public verification checks ledger consistency and the retained bundle bytes.
It does not certify missing private bodies. Full body-backed verification requires
`--evidence-root /path/to/private/evidence` with every body and receipt named by
the ledger and publication index. Original acquisition-relative references remain
unchanged, including `reused-pr231-head46b2fde/evidence/` bundle identities.
Missing private material is an error, not permission to skip verification or to
reacquire or publish source bodies.
