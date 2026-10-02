# Raw-only compatibility artifacts

The artifacts described below are retained in the private
[source archive](../../../docs/maintenance/evidence.md). They are external test
inputs, not files installed with RivRetrieve. Retrieve them in repository-relative
layout and set `RIVRETRIEVE_TEST_EVIDENCE_ROOT` to the external root. The
[compatibility tests](../../test_fr_hydroportail_variants.py) read that root and
leave the retained originals unchanged.

Generated through the public API before selector support, from repository commit
`910d6ee73e4fdfb30993ec51060e2c4ac11e09a8` (base implementation).
The source is `fr_hydroportail_station_Q_padded.recording.json`: station
1232000101, discharge, requested 2026-06-01 through 2026-06-02, cache reuse,
receipts included. `selection.zip` and `result.zip` are public `to_bundle`
exports. `cache/` is the unmodified public accumulated store. The old variant
is null; its published raw identity must not be relabelled during loading.
These are library-generated compatibility artifacts, not additional source captures.
