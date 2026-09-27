# Public selector regression validation

Before production edits, `uv run pytest tests/test_fr_hydroportail_variants.py -q`
failed both discovery checks: public variant was `{None}` rather than the four
published selectors (2 failed, 4.50 seconds).

The next fail-first run, `uv run pytest tests/test_fr_hydroportail_variants.py -q
--maxfail=3`, additionally reached the real fetch transport path. An explicit
`most_valid` selection issued `statusData=raw` (3 failed, 6.75 seconds).

Before production edits, the old public `find` / `fetch(cache="reuse",
receipts=True)` / `to_bundle` path generated the retained raw-only fixtures in
`tests/test_data/fr_hydroportail_legacy_raw`. The request replayed genuine saved
1232000101 discharge bytes for June 1–2, 2026 and produced 282 rows. The old
selection and result retain a null variant; the accumulated inventory declares
`incomplete`, not a fabricated complete inventory.

`uv run pytest tests/test_fr_hydroportail_variants.py -q -k pre_variant`
then failed on the unchanged implementation: the expanded scope issued only raw
rather than four selectors (1 failed, 3.38 seconds). The test loads the old
exports, copies the old cache, enters the real public acquisition path, and
checks that retained fixture files are unchanged. Its response variants are
explicitly synthetic protocol controls, not historical captures.

Green results are recorded in the delivery validation after implementation.

Confirmed post-change commands:

- `uv run pytest tests/test_fr_hydroportail_variants.py -q -k pre_variant`: 1 passed, 78 deselected (3.63 s). This extended check also fetches the loaded old selection export and verifies all four requests.
- `uv run pytest tests/test_fr_hydroportail_variants.py -q -k recorded`: 18 passed, 63 deselected (44.34 s). Includes Q/H, each named selector, both station/windows, and unrestricted overlapping histories.

Adjacent `.red.txt` and `.green.txt` files contain actual command stdout.

`uv run pytest tests/test_fr_hydroportail_station.py tests/test_fr_hydroportail_unit_definition.py tests/test_ba_fr_public.py tests/test_french_publication_services.py tests/test_ba_fr_live.py -q --maxfail=3`: 31 passed, 2 warnings in 45.70s

The initial combined post-change process passed the 63 synthetic/discovery/cache variant cases before stopping at five recorded-test assertions loaded before their correction. Those assertions incorrectly disallowed existing provenance licence/citation notices; the corrected 18 recorded cases then passed separately. No production change was needed for that test correction.
