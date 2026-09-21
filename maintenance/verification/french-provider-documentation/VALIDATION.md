# Validation commands

All commands run in the implementation worktree with uv on 2026-09-21.

- `uv sync`: passed.
- `uv run python maintenance/verification/french-provider-documentation/verify_live_examples.py --out maintenance/verification/french-provider-documentation/2026-09-21`: passed; both live retrievals, four exact output comparisons, final page SHA-256 hashes in `2026-09-21/results.json`.
- `uv run pytest -q tests/test_fr_hubeau_documentation.py`: 4 passed in 5.41s after final live capture.
- `uv run python maintenance/verification/french-provider-documentation/inspect_provider_counts.py`: passed; `provider-counts.txt`.
- `uv run python scripts/generate_reference.py --check`: Reference is current.
- `uv run ty check src`: All checks passed.
- `uv run ruff check tests/test_fr_hubeau_documentation.py maintenance/verification/french-provider-documentation/*.py`: All checks passed.
- `git diff --check`: passed.

The first broad regression invocation started before the final recordings existed.
It produced 137 passes and two `UnmatchedRequestError` failures in the new page replay
cases because the recording file glob was still empty. Running the page tests after
the live capture completed produced 4 passes. No production code changed to address
this orchestration error. The initial full log is retained at
`.worktrees/evidence/effort-313-initial-regression.log`.

Archive audit: all 23 authoritative response bodies match the three manifests
and have recorded HTTP 200 status. Includes the explicitly identified mispunctuated
URL redirect; corrected licence URL evidence is recorded separately.

## Final aggregate regression run

```sh
uv run pytest -q tests/test_fr_hubeau_documentation.py tests/test_documentation.py tests/test_supporting_documentation.py tests/test_reference_contracts.py tests/test_fr_hydroportail_variants.py tests/test_fr_hydroportail_station.py tests/test_fr_hydroportail_unit_definition.py tests/test_fr_hydroportail_contracts.py
```

139 passed, 1 warning in 223.67s (0:03:43)

`regression-verification.log` retains complete output. The sole warning is the
existing rdflib `ConjunctiveGraph` deprecation in catalogue documentation tests.
