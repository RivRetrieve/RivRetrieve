# 02-conformance-and-v1-closeout Execution

## Summary

Implemented the M5/V1 conformance closeout artifacts and the three §19 absence controls from the approved plan. No feature or runtime harness code was changed.

## Changed Files

- `tests/test_m5_exit_criteria.py` — added three V1 deferral/absence tests.
- `docs/v1-conformance.md` — added the §0-§18 checklist, §19 deferral table, structural/process notes, and verification-command record.
- `docs/provider_ports/ch_foen.md` — added the M5/V1 map/token closeout note.
- `docs/discoveries.md` — added a non-numbered V1 closeout note; no D11+ discovery was added.
- `README.md` — added minimal V1 usage docs for implemented APIs and the optional `map` extra.
- `docs/milestones/m5-map-and-v1-closeout/steps/02-conformance-and-v1-closeout/plan.md` — staged with the step.
- `docs/milestones/m5-map-and-v1-closeout/steps/02-conformance-and-v1-closeout/critique.md` — staged with the step.
- `docs/milestones/m5-map-and-v1-closeout/steps/02-conformance-and-v1-closeout/execution.md` — this execution record.
- `pyproject.toml` — patch version bump to `0.1.24`.
- `src/rivretrieve/__init__.py` — patch version bump to `0.1.24`.
- `uv.lock` — lockfile editable package version updated to `0.1.24` by the post-bump smoke check.

## Evidence Audit

Before writing `docs/v1-conformance.md`, I reran `rg` over `tests/` for the cited test names in the plan's §3 map. The cited tests resolve to current `def test_...` names in the test tree. I used current exact names in the artifact, including the strengthened §5 live-catalogue controls from the critique:

- `test_catalogue_reader_live_capable_products_raise_defensive_fatal_for_every_on_issue`
- `test_catalogue_reader_live_capable_stations_raise_defensive_fatal_for_every_on_issue`
- `test_catalogue_reader_live_capable_station_products_raise_defensive_fatal_for_every_on_issue`
- `test_catalogue_reader_live_products_raise_wraps_unsupported_issue`
- `test_catalogue_reader_live_products_ignore_returns_issue_without_warning`

I also verified that no equivalent direct controls already existed for the three §19 deferrals, so the gap-filler tests were added.

§0-§18 conformance blocker found: no.

## Gap-Filler Tests

Added all three planned gap-fillers:

- `test_v1_deferred_wide_form_helpers_remain_absent`
- `test_v1_products_are_not_rivretrieve_derived`
- `test_v1_observed_property_vocabulary_remains_river_gauge_scope`

Targeted verification:

```bash
uv run pytest tests/test_m5_exit_criteria.py
```

Result: 3 passed.

## Discoveries Closeout

Added a closeout note to `docs/discoveries.md` confirming no D11+ discovery was needed. The note records D5 as post-V1 hygiene, D6 as resolved by `_internal.providers`, and D7/D9 as future provider-code probes that did not fire in M4/M5 map work.

## Verification Sweep

```bash
uv run ruff format
uv run ruff check --fix
uv run ty check
uv run pytest
```

Results:

- `uv run ruff format` — 58 files left unchanged.
- `uv run ruff check --fix` — all checks passed.
- `uv run ty check` — all checks passed.
- `uv run pytest` — 442 collected, 440 passed, 2 skipped in 1.77s.
- Post-bump smoke check: `uv run pytest tests/test_package.py` — 3 passed.

Final test count and delta: baseline was 439 collected, 437 passed, 2 skipped offline; this step added 3 tests, so final collection is 442. The 2 skips are the expected folium-gated real-backend map tests: `test_station_map_real_backend_returns_folium_map_for_selected_station` and `test_station_map_real_backend_renders_all_null_nullable_columns`, skipped because `folium` is not installed locally.
