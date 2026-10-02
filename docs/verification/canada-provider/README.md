# Canada provider verification

The private [source archive](https://github.com/RivRetrieve/verification-evidence)
retains the acquisition records, source index and execution logs for the September
2026 provider documentation review. Its inventory records exact collections,
member identities and known limits. These historical records do not establish
current service availability.

The retained national acquisition record describes a fresh HYDAT download and
certified compilation. The compact ZIP used by `test_ca_eccc_boundary_probe.py`
is a separate derived input, not that national publisher artifact. The test
preserves this distinction and compares compiled cells with a separate OGC
recording. Retained SQLite witnesses in the `NO_DAYS` tests are also distinct
from a complete publisher database.

## Run retained-input checks

Retrieve the reviewed archive selections outside source checkouts. Set
`RIVRETRIEVE_TEST_EVIDENCE_ROOT` to that external directory, keeping the
repository-relative paths recorded by the archive. The documentation source
index belongs under `docs/verification/canada-provider/sources/INDEX.json` in
that directory. Test recordings and native-table inputs keep their corresponding
`tests/test_data/` and `src/rivretrieve/_internal/providers/` relative paths.

```sh
uv run pytest tests/test_ca_eccc_boundary_probe.py tests/test_ca_eccc_no_days_evidence.py tests/test_ca_eccc_catalogue.py tests/test_ca_eccc_acquisition_provenance.py tests/test_canada_documentation.py -q --tb=no -p no:cacheprovider --basetemp "$PRIVATE_TEST_OUTPUT"
```

Use a fresh external `PRIVATE_TEST_OUTPUT` directory. Keep full output private.
The tests compare retained inputs; they do not reacquire the national archive or
verify missing historical publisher bodies. See [verification evidence](../../maintenance/evidence.md)
for archive selection, review and handling requirements.

## Maintained interpretation

[Source claims](source-claims.md) and [repository claims](repository-claims.md)
record the reviewed interpretation and its limits. References to source records
and execution logs on those pages identify privately retained historical
material. The Python scripts here preserve executable checks. They use the
explicit runtime cache location when run against a prepared national store;
`acquire.py` starts a new public download and is not an archive retrieval tool.
