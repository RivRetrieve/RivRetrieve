# ANA inventory evidence

See [shared verification evidence](../../../docs/maintenance/evidence.md) for
archive access, exact input selection and verification prerequisites.

Retrieve the Brazil inputs outside the checkout in their repository-relative
layout. `tests/test_data/br_ana_inventory/capture.json` identifies the 20
digest-bound supporting files under `maintenance/catalogue/br_ana/inventory/`.
They retain acquisition attempts, retries, source-row accounting and original
capture scripts byte-for-byte. The archived `.py.txt` files are evidence, not
maintained generators.

Use [Brazil catalogue maintenance](../../../docs/provider_ports/br_ana.md) to
materialize the retained recordings and rebuild the catalogue offline.
Materialization checks every supporting file identity before reconstructing the
attested native table. Failed attempts remain distinct from successful retries.

Daily-source documentary and correspondence inputs use the archived
`tests/recordings/br_ana/` layout. The Markdown comparison report is a
digest-bound build input. It must remain byte-identical.

Set `RIVRETRIEVE_TEST_EVIDENCE_ROOT` to the same external root for the Brazil
tests. Missing inputs fail; tests do not download replacements or use archive
credentials. Keep test temporary files and full logs outside the checkout.

```sh
uv run pytest tests/test_br_ana*.py -q --tb=no -p no:cacheprovider \
  --basetemp "$PRIVATE_OUTPUT/pytest"
```
