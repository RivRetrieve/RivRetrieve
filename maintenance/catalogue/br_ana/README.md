# ANA inventory evidence

See [shared verification evidence](../../../docs/maintenance/evidence.md) for
archive access, exact input selection and verification prerequisites.

`inventory/` contains the 20 digest-bound supporting files named by
[`capture.json`](../../../tests/test_data/br_ana_inventory/capture.json).
They retain the acquisition attempts, retries, source-row accounting and original
capture scripts byte-for-byte. The `.py.txt` files are evidence, not maintained generators.

Use [Brazil catalogue maintenance](../../../docs/provider_ports/br_ana.md) to
materialize the retained recordings and rebuild the catalogue offline.
Materialization checks every supporting file identity before reconstructing the
attested native table. Failed attempts remain distinct from successful retries.

Daily-source documentary and correspondence evidence remains in
[`tests/recordings/br_ana/`](../../../tests/recordings/br_ana/).
The Markdown comparison report is a digest-bound build input, not disposable prose.
