# Bosnia catalogue evidence

See [shared verification evidence](../../../docs/maintenance/evidence.md) for
archive access, exact input selection and verification prerequisites.

Verify the retained public evidence offline from the repository root:

```sh
uv run python maintenance/catalogue/ba_fhmzbih/scripts/verify_evidence.py
```

`inventory/baseline_workbook_access.json` accounts for all 180 station-product
pairs in the original 60-station native table. Its request identities, source
coordinates, response digests, and row accounting are checked against the native
table and the retained publisher routing metadata.

`inventory/workbook_cases.csv` is a derived four-row subset of the completed
station-product survey. Its original header and selected records are unchanged.
The survey context columns are historical metadata, not additional retained
inputs. The referenced evidence JSON files preserve their original bytes.
These cases check blank discharge, empty temperature and stage workbooks, and
an HTTP 404 response. They do not represent national survey coverage.

Public verification checks these source bodies and the baseline ledger structure.
It does **not** certify the private baseline workbook classifications. Complete
certification requires the existing controlled private corpus:

```sh
uv run python maintenance/catalogue/ba_fhmzbih/scripts/verify_evidence.py \
  --evidence-root /path/to/private/bosnia-corpus
```

The private corpus must contain `FILE_HASHES.json`,
`baseline-source-selection.json`, and every referenced response body. The verifier
checks the manifest identity and every file digest before comparing independently
read workbook facts with the ledger. Missing bodies fail. Nothing is acquired
from the network, and no private corpus is included here. `--certificate-out`
requires this complete private-body check.
