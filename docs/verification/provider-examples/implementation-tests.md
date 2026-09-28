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

## First integrated full-suite failure

The root's full `uv run pytest` at `28d12fb` returned **41 failed, 4,631 passed,
five skipped, 78 warnings and seven errors in 2,448.63 s (40:48)**. This is not a
passing final suite. The skip set included absent optional geopandas/folium and
the unavailable controlled private Thai bodies. Packaging setup also lacked a
fresh-cache build prerequisite; a subsequent warmed packaging subset passed
four tests in 14.17 s. Neither explanation dismisses the remaining contract
failures. The root assigned repairs and will rerun the complete suite with
optional dependencies and warmed build prerequisites.

The provider-page runs retained here still identify the exact `28d12fb` code.
They do not verify any later repair. Final acceptance remains incomplete for
both the repository suite and the HydroPortail source blocker.

The root then reran the environment-affected subset at unchanged `28d12fb`:

```bash
uv run --extra map pytest tests/test_documentation_examples.py tests/test_distribution_isolation.py tests/test_drainage_area_packaging.py tests/test_packaging_carries_catalogues.py tests/test_packaging_excludes_catalogue_build_inputs.py -q
```

With a warmed external `UV_CACHE_DIR`, **33 tests passed in 138.81 s**. The
optional map extra and an online build preflight supplied missing environment
prerequisites; source and dependency files did not change. The root retained
`scratchpad/acquisition-validation/final-environment-regressions.log`. A full
rerun with these prerequisites remains required.

## Reference generation check

The root later found that `mkdocs build` regenerates `docs/reference.md`. Its
initial post-build `--check` therefore did not establish that the committed
reference was current. The evidence checkout ran the check **before** any build:

```text
$ uv run python scripts/generate_reference.py --check
Reference drift: run uv run python scripts/generate_reference.py
```

It exited 1 in 5.21 s. After correcting `CoverageInterval.interval` from
"Covered wall-clock interval" to "Covered interval on its declared time axis",
`uv run python scripts/generate_reference.py` regenerated the reference. An
immediate pre-build `--check` exited 0 in 0.41 s with `Reference is current.`
The regenerated page documents format 8, native/UTC interval axes and explicit
outcome coverage/key evidence. The docstring correction changes documentation,
not executable behavior. Independent AST comparison is required before carrying
forward the unchanged-behavior live examples.

The root owns publication of this reference/docstring correction in a separate
PR. The evidence branch briefly contained the same correction during validation,
then removed those two file deltas to avoid duplicate ownership. The recorded
pre-build checks above are historical execution evidence, not a claim that this
evidence-only PR publishes the generated reference.

## Evidence-branch checks

After merging target `8da58e4` into the evidence branch, the reference check passed
before any build in 0.41 s. Scoped lint for the runner and five mechanically
cleaned historical ancillary scripts passed. Whole-tree Ruff now reports only
one inherited import-spacing error in `canada-provider/final_snippets.py` and two
formatting failures: that file and `brazil-provider/examples.py`. The other 503
Python files are formatted. Both retained files explicitly preserve exact
historical executed snippets; their bytes were intentionally not changed. This
is a disclosed whole-tree check limitation, not a clean full-lint claim.

## Completed full-suite rerun

At target `8da58e4d30e06b65c86fbbfd9c4cccb461e9e460`, the root ran:

```bash
UV_CACHE_DIR=<external-warmed-cache> uv run --extra map --with geopandas --with matplotlib pytest
```

Captured result, exit 0:

```text
SKIPPED [1] tests/test_thaiwater_governing_evidence.py:72: controlled private bodies are required; mandatory acceptance check
4683 passed, 1 skipped, 78 warnings in 2424.45s (0:40:24)
```

The raw log is `scratchpad/acquisition-validation/final-pytest-8da58e4.log`.
The private Thai fixture acceptance check remains unverified. The warnings remain
reported; this is not a claim that every test passed. Baseline was 4,535 passed,
three skipped in 2,440.37 s. Different optional prerequisites and concurrent
workloads mean these durations are observations, not a performance comparison.
The reference check passed on the final target before the documentation build.

The completed evidence tree passed its pre-build reference check (0.55 s),
runner lint/format and `git diff --check`. Its own
`uv run mkdocs build --strict` exited 0 in 2.02 s. The build
left the tracked reference unchanged; this pass did not hide a regenerated diff.

Evidence-branch focused documentation validation:
`uv run --extra map pytest tests/test_documentation.py tests/test_supporting_documentation.py -q`
completed with the captured result:

```text
Installed 3 packages in 4ms
.......                                                                  [100%]
=============================== warnings summary ===============================
tests/test_supporting_documentation.py::test_catalogue_evidence_markdown
  /Users/nicolaslazaro/Desktop/work/RivRetrieve/.worktrees/visions/provider-example-evidence/.venv/lib/python3.13/site-packages/rdflib/plugins/parsers/jsonld.py:159: DeprecationWarning: ConjunctiveGraph is deprecated, use Dataset instead.
    conj_sink = ConjunctiveGraph(store=sink.store, identifier=sink.identifier)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
7 passed, 1 warning in 7.41s
```
