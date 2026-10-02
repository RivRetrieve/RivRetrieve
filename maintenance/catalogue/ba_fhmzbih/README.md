# Bosnia catalogue evidence

See [shared verification evidence](../../../docs/maintenance/evidence.md) for
archive access, exact input selection and verification prerequisites.

Retrieve the retained inputs outside the checkout following the private archive
instructions. Supply their repository-relative tree and the retained native table
explicitly. Verify the selected workbook cases offline from the repository root:

```sh
uv run python maintenance/catalogue/ba_fhmzbih/scripts/verify_evidence.py \
  --retained-evidence-root /path/to/retained-inputs \
  --baseline-native /path/to/retained-inputs/src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet
```

`inventory/baseline_workbook_access.json` accounts for all 180 station-product
pairs in the original 60-station native table. Its request identities, source
coordinates, response digests, and row accounting are checked against the native
table and the retained publisher routing metadata.

`maintenance/catalogue/ba_fhmzbih/inventory/workbook_cases.csv` under the retained
input root is a derived four-row subset of the completed
station-product survey. Its original header and selected records are unchanged.
The survey context columns are historical metadata, not additional retained
inputs. The referenced evidence JSON files preserve their original bytes.
These cases check blank discharge, empty temperature and stage workbooks, and
an HTTP 404 response. They do not represent national survey coverage.

Selected-case verification checks these source bodies and the baseline ledger structure.
It does **not** certify the private baseline workbook classifications. Complete
certification requires the existing controlled private corpus:

```sh
uv run python maintenance/catalogue/ba_fhmzbih/scripts/verify_evidence.py \
  --retained-evidence-root /path/to/retained-inputs \
  --baseline-native /path/to/retained-inputs/src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet \
  --evidence-root /path/to/private/bosnia-corpus
```

The private corpus must contain `FILE_HASHES.json`,
`baseline-source-selection.json`, and every referenced response body. The verifier
checks the manifest identity and every file digest before comparing independently
read workbook facts with the ledger. Missing bodies fail. Nothing is acquired
from the network, and no private corpus is included here. `--certificate-out`
requires this complete private-body check.

The reviewed `inventory/baseline_workbook_access.json` stays with the verifier
code. `--workbook-access-ledger` can select another reviewed ledger explicitly.
Commands using `--catalogue-root` or its `--research-root` alias must instead
pass `--retained-evidence-root` for the repository-relative input tree and
`--baseline-native` for the native table. Use `--workbook-access-ledger` when
selecting a ledger outside its default code location.
The retained input root supplies the selected cases, routing recording and source
bodies under `maintenance/catalogue/ba_fhmzbih/`. The controlled baseline corpus
has its own existing layout and remains a separate `--evidence-root` input.

For a catalogue build, pass `--native`, `--workbook-access-ledger`,
`--series-recording`, `--evidence-root` and `--out` to
`uv run python -m rivretrieve._internal.providers.ba_fhmzbih.generate_catalogue`.
The retained root supplies the provenance recordings in their repository-relative
layout. Their historical path identities and digest checks stay unchanged.

Set `RIVRETRIEVE_TEST_EVIDENCE_ROOT` to the retained input root for the
Bosnia tests. Missing required inputs fail rather than using checkout copies.
Run tests with `--tb=no -p no:cacheprovider` and keep detailed failures private.
