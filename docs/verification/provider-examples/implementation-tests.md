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
malformed and empty responses, held refresh and retries. Both implementation slices were subsequently repaired, independently approved and
merged. The final-head evidence below supersedes preliminary approval status.

Lithuania preservation and shared acquisition composition command:
`uv run --no-sync pytest -q tests/test_lt_lhmt_monthly_isolation.py tests/test_lt_lhmt_shared_acquisition.py tests/test_acquisition_composition.py`
reported 69 passes in 198.90 s. The worker used its own uv cache. This run preceded
the latest shared review fixes and must not be treated as final-head validation.

## Final reviewed integration

Implementation PRs #409, #410 and #411 are merged. The final example checkout is
`28d12fb70f75c89ee4ceac497fbbf80ddd768922`.

[Provider author validation](https://github.com/RivRetrieve/RivRetrieve/pull/411#issuecomment-5878610055)
retains the exact 22-file uv pytest command: **597 passed, one unchanged openpyxl
style warning, 136.01 s** at `dd61bcbe76168bdf9febe9b09370319df722f692`.
[Independent review](https://github.com/RivRetrieve/RivRetrieve/pull/411#issuecomment-5878598296)
passed a separate 21-file slice: **608 passed in 75.64 s**. These counts overlap.
Type checking of `src`, lint and formatting of `src tests`, and diff checks passed.

Review exposed and repaired MLIT month-end `24時` persistence, USGS UTC acquisition
versus native-offset cache boundaries, multi-span identity inventories,
cross-span physical-fact changes, stale broad inventory after narrow refresh,
and failed retry call linkage. The original independent probes passed after
repair. No source time zone or temporal support was inferred by these fixes.

[Shared independent approval](https://github.com/RivRetrieve/RivRetrieve/pull/410#issuecomment-5878618685)
covers returned/stored overlap agreement, unknown failed-request targets,
snapshot accepted-row keys and actual acquisition vintages, native/UTC coverage
validation, bounded inventory reuse and narrower identity changes. Accumulated
store revision 8 refuses obsolete revision 7 without modifying it. The shared
reviewer's final changed fixture test passed in 5.32 s. The author separately ran
`uv run pytest tests/test_fr_hydroportail_variants.py -q`: **83 passed in 43.40 s**.

[Final integration review](https://github.com/RivRetrieve/RivRetrieve/pull/411#issuecomment-5878658584)
approved `174e6b3e0cd6cb888ca6fca4264dcceb6232272b`: only 11 test lines differed
from the reviewed provider candidate; production code was identical. Independent
validation of that changed file passed **83 tests in 44.80 s**. The root agent
then merged it as `28d12fb`. Complete repository tests and live examples are
separate acceptance gates, not implied by these focused approvals.

## Complete repository suite

The root agent ran `uv run pytest` at baseline
`0b443049d50819978030e29e46011ca2101cb337`: **4,535 passed, three skipped,
78 warnings in 2,440.37 s (40:40)**. Its raw log remains at
`scratchpad/acquisition-validation/baseline-pytest.log`. Two skips require the
absent optional geopandas dependency; the third requires unavailable controlled
private Thai response fixtures. Those skips are limitations, not passes.
Baseline `uv run ty check src` passed. Inherited whole-tree formatting and lint
failures are recorded separately; exact historical execution scripts were not
silently reformatted. Final implementation full-suite results are pending.

At final target `28d12fb`, `uv run mkdocs build --strict` and `uv run ty check src`
passed. The root retained `scratchpad/acquisition-validation/final-mkdocs.log`.
The optional map follow-up
`uv run --with geopandas --with matplotlib pytest tests/test_coverage_map.py -q`
passed **four tests in 30.75 s**, with no dependency-file changes; its captured
log is `scratchpad/acquisition-validation/final-optional-maps-complete.log`.
An earlier retry with only geopandas still skipped two tests because matplotlib
was absent; it is not counted as completed optional coverage.

Final `uv run python scripts/generate_reference.py --check` passed with
`Reference is current.` The root retained
`scratchpad/acquisition-validation/final-reference.log`.
