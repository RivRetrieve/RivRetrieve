# Implementation regression evidence

These deterministic tests validate library behavior. They do not replace live
provider example execution. Commands ran through uv on 2026-09-28.

## Canada and complete-history stores

[PR #409](https://github.com/RivRetrieve/RivRetrieve/pull/409), implementation
commit `9c804f4`, was independently reviewed and merged. The author reported:

- `uv run pytest tests/store -q --durations=10`: 200 passed in 24.47 s.
- `uv run pytest tests/store/test_ca_eccc_download_safety.py -q --durations=10`:
  nine passed in 1.01 s; the slowest new test took 0.23 s.
- `uv run ruff check src/rivretrieve/_internal/providers/ca_eccc tests/store/test_ca_eccc_download_safety.py`: passed.
- `uv run ruff format --check src/rivretrieve/_internal/providers/ca_eccc tests/store/test_ca_eccc_download_safety.py`: passed.
- `uv run ty check src` and `git diff --check`: passed.

Tests use public download composition and real SQLite decode, compilation and
certification. An older fallback preserves the certified store and manifest.
Same-date and newer releases may legitimately contain fewer rows. Missing-release
404 fallback remains supported; 403, 302 and 500 retain status and URL and stop
after one HEAD. Transport exception identity survives. Existing and dangling
artifact symlinks fail before network access. The complete store suite preserves
Poland's atomic complete-history publication and recovery behavior. This checks
the witnessed local path-safety defect, not hostile concurrent filesystem mutation.
The independent reviewer separately reported 200 store tests in 26.08 s.

## Independent provider acquisitions

[PR #411](https://github.com/RivRetrieve/RivRetrieve/pull/411) retains its
[exact combined command and baseline comparison](https://github.com/RivRetrieve/RivRetrieve/pull/411#issuecomment-5878114885).
The author reported 454 passes in 131.44 s with one inherited openpyxl warning,
then 53 USGS passes in 0.80 s and 11 CHMI annual passes in 10.60 s. These runs
are separate, overlapping suites, not a sum of unique tests. The author reported
`uv run ty check src` and Ruff checks of source/tests passing.

Coverage includes CHMI annual DQ/HQ; Thailand capped 365-day requests; ANA
monthly daily and backward 30-day telemetry requests; MLIT HTML/DAT chunks;
Hub'Eau incomplete cursors; and USGS independent 1100-day spans. Tests exercise
first, middle, last and all failures, bounded evidence, receipts, shared failures,
malformed and empty responses, held refresh and retries. Provider review and
final shared-contract validation are still pending in this record.

Lithuania preservation and shared acquisition composition command:
`uv run --no-sync pytest -q tests/test_lt_lhmt_monthly_isolation.py tests/test_lt_lhmt_shared_acquisition.py tests/test_acquisition_composition.py`
reported 69 passes in 198.90 s. The worker used its own uv cache. This run preceded
the latest shared review fixes and must not be treated as final-head validation.
