# French provider-page regression checks

[The documentation tests](../test_fr_hubeau_documentation.py) replay retained
source interactions and compare the provider examples with their documented
output. They also check the displayed catalogue populations against the packaged
runtime catalogues.

Retrieve the exact recordings from the private
[source archive](../../docs/maintenance/evidence.md) outside source checkouts.
Set `RIVRETRIEVE_TEST_EVIDENCE_ROOT` to their repository-relative input root.
Replay checks the saved interactions; it does not establish current service
availability. Historical acquisition and page-validation reports remain in the
archive.
