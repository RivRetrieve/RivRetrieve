## What landed
- Files added/modified: `pyproject.toml`, `uv.lock`, `src/rivretrieve/_internal/__init__.py`, `src/rivretrieve/_internal/primitives.py`, `src/rivretrieve/_internal/issues.py`, `src/rivretrieve/_internal/results.py`, `tests/test_internal_issues.py`, `tests/test_internal_results.py`, `tests/test_package.py`, `docs/milestones/m1-harness-foundation/steps/01-foundations/execution.md`.
- Symbols added (internal): `CatalogSource`, `OnIssue`, `IssueSeverity`, `ProviderId`, `ProductId`, `Issue`, `RivRetrieveError`, `IssuePolicyError`, `FatalContractError`, `apply_on_issue`, `CatalogProvenance`, `CatalogResult`.
- Public surface delta: none; `src/rivretrieve/__init__.py` changed only for the required version-literal bump.

## Plan adherence
- Step 1: done as planned.
- Step 2: done as planned.
- Step 3: done as planned.
- Step 4: done as planned.
- Step 5: done as planned.
- Step 6: done as planned after correcting no-warning assertions in the tests.
- Step 7: done as planned.
- Step 8: done as planned.
- Step 9: done as planned after accounting for Python attaching `_internal` to the package object when private submodules are imported.
- Step 10: done as planned; `UP046` was suppressed narrowly on `CatalogResult` to preserve the approved `TypeVar` plus `Generic[T]` Pydantic pattern.
- T01: implemented.
- T02: implemented.
- T03: implemented.
- T04: implemented.
- T05: implemented.
- T06: implemented.
- T07: implemented.
- T08: implemented.
- T09: implemented.
- T10: implemented.
- T11: implemented.
- T12: implemented.
- T13: implemented with adjustment: sharpened parametrized form from the folded-in critique.
- T14: implemented.
- T15: implemented.
- T16: implemented.
- T17: implemented with adjustment: ignores underscore-private package attributes while asserting no public planned names are present.

## Architecture invariants verified
- `on_issue` is the sole policy knob: `apply_on_issue(issues, on_issue)` is the only policy helper and tests T06-T13 exercise only that axis.
- Fatal contract failures raise regardless of `on_issue`: `FatalContractError` is a direct exception class outside `apply_on_issue`; T13 asserts the helper only raises `IssuePolicyError`.
- `IssueSeverity` is exactly `{info, warning, error}`: the literal alias and `Issue` Pydantic validation enforce it; T03/T04 catch regressions.
- `info` severity never raises or warns: T08 and T10 cover `warn` and `raise`; T07 covers `ignore`.
- `Issue`, `CatalogProvenance`, `CatalogResult` are frozen: each model sets `ConfigDict(frozen=True)`.
- `arbitrary_types_allowed` is not set: no model config includes it.
- `ProviderId`/`ProductId` are `NewType`, not validated strings: `primitives.py` defines both with `NewType`; no validators are present.
- No public symbols added: `src/rivretrieve/__init__.py` was edited only for the required version-literal bump; T17 asserts planned public names are absent.
- Polars-canonical contract not weakened: `polars` was added as a runtime dependency; no table schema or pandas-first type was introduced.

## Negative-control evidence
- T13 assertion form: parametrized over empty, `info`, `warning`, `error`, and mixed `info+warning+error` issue lists crossed with `ignore`, `warn`, and `raise`. `raise` cells containing warning/error use `pytest.raises(IssuePolicyError)` and assert the exception is not `FatalContractError`; all no-raise cells use a blanket `try`/`except` and fail on any exception. It separately constructs `FatalContractError()` without an `Issue`.
- T17 assertion list: confirms `providers`, `provider`, `provider_info`, `CatalogResult`, and `Issue` are absent from `rivretrieve`; confirms `__version__` remains present.

## Resolver output
- `polars` 1.40.1.
- `pandas` 3.0.3.
- `pydantic` 2.12.5.
- `requests` 2.34.2.
- `uv run python -c "import polars, pandas, pydantic, requests"` runs cleanly under the project venv.

## Tool runs
- `uv run ruff format` - pass.
- `uv run ruff check --fix` - pass; one import-order autofix was applied, and `UP046` was locally suppressed to preserve the planned generic model syntax.
- `uv run ty check` - pass; no warnings suppressed.
- `uv run pytest` - pass, 38 tests.
- New test names: `test_issue_severity_accepts_all_values`, `test_issue_severity_rejects_unknown_value`, `test_issue_construction_roundtrip`, `test_on_issue_empty_list_noops_for_all_policies`, `test_on_issue_ignore_ignores_all_severities`, `test_on_issue_warn_ignores_info`, `test_on_issue_warn_emits_for_warning_and_error`, `test_on_issue_raise_ignores_info`, `test_on_issue_raise_raises_for_warning_and_error`, `test_issue_policy_error_carries_issues`, `test_fatal_contract_error_is_separate_from_on_issue`, `test_catalog_source_accepts_packaged_and_live`, `test_catalog_source_rejects_unknown_value`, `test_catalog_provenance_packaged_roundtrip`, `test_catalog_provenance_live_roundtrip`, `test_catalog_result_roundtrip`, `test_init_public_surface_still_only_version`.

## Discoveries
- `pytest.warns()` cannot be used to assert silence; tests use `warnings.catch_warnings(record=True)` for no-warning cells.
- Importing private submodules attaches `_internal` to the package object, so T17 must ignore underscore-private names rather than assert every non-dunder module attribute is absent.
- `ruff` on Python 3.13 prefers PEP 695 generic class syntax, but the approved plan requires `TypeVar` plus `Generic[T]`; `CatalogResult` keeps the planned syntax with a narrow `UP046` noqa.
- Later steps should use the same Pydantic v2 generic pattern if they need `CatalogResult[ConcreteSchema]`.

## Open items handed forward
- Step 02 owns: catalogue schemas, `PackagedCatalogArtifact`, corrupt artifact validation, artifact-local consistency checks if needed, and packaged/live provenance cross-field validation only when concrete producers exist.
- Step 03 owns: provider registry, deterministic `rr.providers()`, `rr.provider()`, `rr.provider_info()`, provider ID `snake_case` enforcement, `CatalogProvenance.rivretrieve_version` auto-population, provider imports, and offline-import negative-control testing.
- Later hardening: `Issue.details` and provenance `query` secret-key validation, provider subpackage layout, observation request/result contracts, annotation schemas, public `ProviderHandle` Protocol, real catalogue data, and pandas export helpers.

## Verification
- Commit hash: pending; commit resolution note below records the final hash after commit.
- Diff summary: 12 files changed, 729 insertions, 5 deletions.

## Commit resolution note
- The orchestrator logged D1 in `docs/discoveries.md`, exempting version-literal bumps in `src/rivretrieve/__init__.py` from the step's no-public-API-edit guard.
- `uv run bump-my-version bump --new-version 0.1.4 patch` was used because `v0.1.3` already existed on commit `6488f6e` while configured files still said `0.1.2`; using `0.1.3` would have collided with an existing tag.
- Final commit hash: recorded in the executor handoff response; embedding the final hash in this committed file would change the hash.
- Final tag: `v0.1.4`.
