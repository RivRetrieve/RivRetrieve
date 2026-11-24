# Chile canonical series frequency alignment

Bring the Chile DGA provider branch (`port/cl-dga`) into conformance with the canonical ISO 8601 series frequency contract and bumped observation-store format merged to `main` via [PR #1032](https://github.com/RivRetrieve/RivRetrieve/pull/1032) (implementing [discussion #992](https://github.com/RivRetrieve/RivRetrieve/issues/992)) and [verification-evidence#162](https://github.com/RivRetrieve/verification-evidence/pull/162).

This work supports [Chile Step 8: Final review (#738)](https://github.com/RivRetrieve/RivRetrieve/issues/738) under [Program #734](https://github.com/RivRetrieve/RivRetrieve/issues/734). Completing this vision does **not** complete `#738` or merge `port/cl-dga` to `main`: it prepares `port/cl-dga` for final merge by opening a verified PR into `main` and posting the verification summary on `#738` for `@thiagovmdon`'s final review and merge decision. Publishing this vision does not authorize implementation.

## Context and repository facts

`port/cl-dga` (`94515453`) last merged `origin/main` at `6280716e`, immediately before PR `#1032` (`0a26499e`) and `verification-evidence#162` (`8114f99`) landed on `main`. As a result, `cl_dga` still carries the retired pre-`#992` contract:

- Legacy frequency strings (`"daily"`, `"monthly"`) instead of canonical ISO 8601 durations (`"P1D"`, `"P1M"`) in `src/rivretrieve/_internal/providers/cl_dga/series.py`, `src/rivretrieve/_internal/providers/cl_dga/generate_catalogue.py`, the packaged `cl_dga` catalogue (`products.parquet`, `source_series.json`, `croissant.json`, `provenance.json`), `docs/providers/cl_dga.md`, `tests/test_cl_dga_*.py`, `tests/test_missing_bulk_outcomes.py`, and `port/cl-dga`-added cases in `tests/test_calendar_windows.py`.
- Compiled observation store `format_version=10` instead of `12` in `src/rivretrieve/_internal/providers/cl_dga/config.py` and `tests/store/test_unknown_source_vintage.py`. PR `#1032` bumped compiled stores from `10` to `12` (accumulated `9` to `11`, export bundles `4` to `5`) because replacing `"daily"` / `"monthly"` with `"P1D"` / `"P1M"` changes content-derived `facts_id`.
- Shared files modified on both `port/cl-dga` and PR `#1032` that require clean reconciliation when merging `origin/main` into `port/cl-dga`—including the two 3-way merge-conflict sites (`src/rivretrieve/_internal/provider_series.py` and `tests/test_catalogue_origin_certification.py`) as well as overlapping docs, store, and test files (such as `docs/_generated/reference-tables.md`, `docs/usage.md`, `docs/design/observation-store-layout.md`, `src/rivretrieve/_internal/store/*`, `tests/test_calendar_windows.py`, and `tests/test_observation_store_validation.py`).
- In `RivRetrieve/verification-evidence`, `tests/source/test_cl_dga_catalogue.py` still asserts `daily_facts.frequency.value == "daily"`, `monthly_facts.frequency.value == "monthly"`, and queries `rr.find(..., frequency="daily" | "monthly")`. `declarations/cl_dga/catalogue.json` contains no frequency fields and needs no edits.
- `verification-evidence#162` added the missing `fi_syke` catalogue archive bindings, resolving the unrelated `verify.py --catalogue-inputs` blocker previously noted on `#738`.

## Settled scope and deliverables

### 1. Coordinate `RivRetrieve/verification-evidence`

- Open a small PR on `RivRetrieve/verification-evidence` aligning `tests/source/test_cl_dga_catalogue.py` to canonical ISO 8601 frequencies (`"P1D"` and `"P1M"`), following the pattern of `verification-evidence#162`.
- Leave `declarations/cl_dga/catalogue.json` unchanged.
- Wait for that `verification-evidence` PR to merge to `main` before finalizing `cl_dga`'s packaged catalogue provenance pin so that `provenance.json` pins a merged `verification-evidence` `main` commit rather than an unmerged branch commit.

### 2. Align `port/cl-dga` in `RivRetrieve/RivRetrieve`

- Merge current `origin/main` (including PR `#1032`) into `port/cl-dga` with a merge commit (no history rewrite) and resolve overlapping shared files consistently with `main`'s post-`#1032` contracts.
- Update `cl_dga` frequency declarations, catalogue generation, provider documentation (`docs/providers/cl_dga.md`), `cl_dga` tests, `tests/test_missing_bulk_outcomes.py`, and `port/cl-dga`-added calendar-window tests from `"daily"` / `"monthly"` to `"P1D"` / `"P1M"`. Match `docs/providers/cl_dga.md`'s retrieval table and examples to `main`'s post-`#1032` provider-doc conventions (e.g., `ca_eccc.md`, `pl_imgw.md`).
- Bump `cl_dga`'s compiled observation store `format_version` from `10` to `12` in `config.py` and `tests/store/test_unknown_source_vintage.py`.
- Rebuild `cl_dga`'s packaged catalogue against retained evidence in `verification-evidence` `main` so `products.parquet`, `source_series.json` (`facts_id`), `croissant.json`, and `provenance.json` reflect canonical frequencies and the merged evidence commit.
- Regenerate `docs/_generated/reference-tables.md` with `scripts/generate_reference.py`.
- Preserve all established `cl_dga` semantics, unknowns, limitations, and MOP terms/licensing notices unchanged (unknown daily statistic, `time_zone="unknown"`, `source_vintage=None`, preserved duplicate dates, `ALTITUD=0` as `source_null`, `license=None`, `citation=None`).

### 3. Landing boundary

- Push the verified alignment commits to `port/cl-dga`.
- Open a pull request from `port/cl-dga` into `main` ready for `@thiagovmdon`'s review and merge. Use a neutral reference to `#738` (no auto-closing keywords).
- Post a concise verification summary comment on `#738`.
- Do **not** merge `port/cl-dga` into `main`, and do **not** close or modify the state of `#738`.

## Verification bar

Before opening the `port/cl-dga -> main` PR and reporting on `#738`, confirm all of the following on the final commit of `port/cl-dga` against merged `verification-evidence` `main`:

- `ruff check`, `ruff format --check`, `ty check src`, and `scripts/generate_reference.py --check` pass.
- Full `pytest --logic-only` passes.
- `verify.py --catalogue-inputs` passes against merged `verification-evidence` `main` (including `cl_dga` catalogue rebuild certification).
- `verify.py` recorded certification passes for `cl_dga` (including `tests/source/test_cl_dga_catalogue.py` compiling the retained national ZIPs and querying `P1D`/`P1M` through `rr.find`/`rr.fetch`, `tests/test_cl_dga_boundary_probe.py`, and `tests/test_cl_dga_documentation.py`).

### Explicit exclusions

- Do **not** repeat the live DGA download or re-run the `docs/providers/cl_dga.md` example live against DGA; retained-archive compilation and `test_cl_dga_documentation.py` cover the updated `P1D`/`P1M` surface against the verified 2026-11-18 snapshot.
- Do **not** repeat the 10-basin CAMELS-CL comparison; DGA data parsing and numerical behavior are unchanged, and the `#742` result stands.
- Do **not** add a new `verification-evidence/acceptance/` entry for this alignment.

## Constraints and sequencing risk

- **Provenance pin ordering**: Finalizing `cl_dga`'s packaged catalogue `provenance.json` requires the `verification-evidence` PR to be merged to `main` first. If that PR is awaiting maintainer merge, pause before the final provenance re-pin and `port/cl-dga -> main` PR rather than pinning an unmerged commit.
- **No scope expansion**: Keep changes strictly within `#992` / PR `#1032` alignment and `origin/main` merge reconciliation; do not modify `cl_dga` retrieval logic, station selection, or metadata semantics.
