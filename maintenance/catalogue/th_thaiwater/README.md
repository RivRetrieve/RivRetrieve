# ThaiWater catalogue evidence

See [shared verification evidence](../../../docs/maintenance/evidence.md) for
archive access, exact input selection and verification prerequisites.

`inventory/governing_station_product_evidence.csv` records the 825-station,
1,650-pair catalogue population. The archive retains the historical count and
source-limitations summary under
`maintenance/catalogue/th_thaiwater/inventory/governing_summary.json`. The supplying agencies and source requests remain
part of the evidence identity.

The external retained-input directory holds `recordings/` with two unchanged source bodies: a null graph and an HTTP-200
database error. Its `evidence/graph_receipts.csv` retains their exact original receipt
records. `evidence/recording_provenance.json` identifies the original Git commit,
ZIP path and digest, member names, and unchanged body digests. These cases protect body integrity, false availability refusal, and
source-failure parsing. They are not the complete governing corpus.

Set `RIVRETRIEVE_TEST_EVIDENCE_ROOT` to the external retained inputs in repository-relative
layout. Run consistency and source-case tests offline from the repository root:

```sh
uv run pytest tests/test_thaiwater_governing_evidence.py tests/test_thaiwater_source_outcomes.py
```

Full body verification requires the existing controlled private acquisitions.
Supply their directory explicitly; the verifier does not download missing bodies:

```sh
uv run python maintenance/catalogue/th_thaiwater/scripts/verify_governing_evidence.py \
  --ledger maintenance/catalogue/th_thaiwater/inventory/governing_station_product_evidence.csv \
  --native "$RIVRETRIEVE_TEST_EVIDENCE_ROOT/src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet" \
  --evidence-root /path/to/private/thaiwater-acquisitions
```

Run this complete private-body command before the negative provenance regressions.
It remains mandatory for full acceptance. Public ledger
agreement does not certify unavailable source bytes. Set
`THAIWATER_REVIEW_EVIDENCE_ROOT` to the same directory to run the private
cross-station receipt regression; missing configuration blocks that test.
The historical summary's mention of public CI describes its original record,
not a hosted workflow requirement.

## Catalogue build

The native table and source recordings are external build inputs. The reviewed
ledger stays in this repository. Build with explicit input and output locations:

```sh
uv run python -m rivretrieve._internal.providers.th_thaiwater.generate_catalogue \
  --native "$RIVRETRIEVE_TEST_EVIDENCE_ROOT/src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet" \
  --availability-evidence maintenance/catalogue/th_thaiwater/inventory/governing_station_product_evidence.csv \
  --evidence-root "$RIVRETRIEVE_TEST_EVIDENCE_ROOT" \
  --out /path/to/catalogue-output
```

Archive member paths preserve the existing provenance identities. Runtime discovery
and retrieval use packaged products and need no archive access. The retained native
table does not reconstruct the missing complete original metadata response.
