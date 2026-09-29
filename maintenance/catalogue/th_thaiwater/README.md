# ThaiWater catalogue evidence

See [shared verification evidence](../../../docs/maintenance/evidence.md) for access,
collection selection and integrity checks. The [provider index](../../evidence/index.json)
records retained material, applicable commands and known gaps.

`inventory/governing_station_product_evidence.csv` records the 825-station,
1,650-pair catalogue population. `inventory/governing_summary.json` records its
counts and source limitations. The supplying agencies and source requests remain
part of the evidence identity.

`recordings/` holds two unchanged source bodies: a null graph and an HTTP-200
database error. `evidence/graph_receipts.csv` retains their exact original receipt
records. `evidence/recording_provenance.json` identifies the original Git commit,
ZIP path and digest, member names, and unchanged body digests. These cases protect body integrity, false availability refusal, and
source-failure parsing. They are not the complete governing corpus.

Run public consistency and source-case tests offline from the repository root:

```sh
uv run pytest tests/test_thaiwater_governing_evidence.py tests/test_thaiwater_source_outcomes.py
```

Full body verification requires the existing controlled private acquisitions.
Supply their directory explicitly; the verifier does not download missing bodies:

```sh
uv run python maintenance/catalogue/th_thaiwater/scripts/verify_governing_evidence.py \
  --ledger maintenance/catalogue/th_thaiwater/inventory/governing_station_product_evidence.csv \
  --native src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet \
  --evidence-root /path/to/private/thaiwater-acquisitions
```

This private-body command remains mandatory for full acceptance. Public ledger
agreement does not certify unavailable source bytes. Set
`THAIWATER_REVIEW_EVIDENCE_ROOT` to the same directory to run the private
cross-station receipt regression; otherwise that test reports an explicit skip.
The historical summary's mention of public CI describes its original record,
not a hosted workflow requirement.
