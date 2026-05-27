# 01-foundations Plan

## 1. Goal and scope

This step ships the internal M1 foundation layer only:

- Add runtime dependency names to `[project].dependencies`: `polars`, `pandas`, `pydantic`, and `requests`, then refresh `uv.lock`.
- Introduce internal harness primitives: `CatalogSource`, `OnIssue`, `IssueSeverity`, `Issue`, `ProviderId`, and `ProductId`.
- Implement the shared `on_issue` policy helper for recoverable structured issues.
- Introduce internal catalogue result envelopes: `CatalogResult[T]` and `CatalogProvenance`.
- Add focused tests proving primitive construction, policy behavior, exception behavior, and envelope field roundtrips.

No public API is introduced in this step. `src/rivretrieve/__init__.py` remains unchanged and continues to export only `__version__ = "0.1.2"`. The tracker's broader M1 items for catalogue schemas, packaged artifacts, registry machinery, provider lookup, and `provider_info()` are intentionally split into later M1 steps.

Evidence:

- The tracker authorizes these primitives and dependencies in M1 (`docs/milestone-tracker.md:43-47`) while requiring imports and tests to remain green (`docs/milestone-tracker.md:9`, `docs/milestone-tracker.md:360`).
- Architecture defines the catalogue result shape and Polars canonical table contract (`architecture.md:221-240`).
- Architecture defines `Issue`, severities, `on_issue`, and fatal contract failures (`architecture.md:585-609`).
- The legacy code is an ABC returning pandas DataFrames, not a structured result/issue harness (`/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/base.py:9-23`, `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/base.py:51-77`).

## 2. API surface touched

Public surface:

- No public symbols added.
- No change to `src/rivretrieve/__init__.py`.

Internal surface:

- New package namespace: `src/rivretrieve/_internal/`.
- New module: `src/rivretrieve/_internal/primitives.py`.
- New module: `src/rivretrieve/_internal/issues.py`.
- New module: `src/rivretrieve/_internal/results.py`.
- New internal package marker: `src/rivretrieve/_internal/__init__.py`, with no broad re-exports.

Internal symbols:

- `CatalogSource = Literal["packaged", "live"]`.
- `OnIssue = Literal["warn", "raise", "ignore"]`.
- `IssueSeverity = Literal["info", "warning", "error"]`.
- `ProviderId = NewType("ProviderId", str)`.
- `ProductId = NewType("ProductId", str)`.
- `Issue`.
- `RivRetrieveError`.
- `IssuePolicyError`.
- `FatalContractError`.
- `apply_on_issue(issues: Sequence[Issue], on_issue: OnIssue) -> None`.
- `CatalogProvenance`.
- `CatalogResult[T]`.

## 3. Data structures and types

Use Pydantic v2 `BaseModel` for `Issue`, `CatalogProvenance`, and `CatalogResult[T]`. Configure each model explicitly:

- `Issue`: `ConfigDict(frozen=True)`.
- `CatalogProvenance`: `ConfigDict(frozen=True)`.
- `CatalogResult`: `ConfigDict(frozen=True)`.

Do not set `arbitrary_types_allowed=True` in this step. Step 01 has no Polars table value to validate yet; Step 02 should add that flag only if its catalogue table implementation proves it is required.

`Issue` fields:

- `severity: IssueSeverity`: required; one of `"info"`, `"warning"`, `"error"`.
- `code: str`: required machine-readable kind such as `"live_unsupported"` or `"partial_live_response"`.
- `message: str`: required human-readable diagnostic.
- `details: dict[str, object] | None = None`: optional structured context. This step does not sanitize secret-like keys; producers must not put secrets into issues, and a future security hardening task can add validation if needed.
- `provider_id: ProviderId | None = None`: optional provider context.

Do not add `Issue.is_fatal`. Fatal contract failures are exception-only paths, raised directly at the detection site. This avoids silent downgrade under `on_issue="ignore"` and matches architecture's wording that unknown providers, invalid catalogue source values, corrupt packaged artifacts, and provider implementation schema violations "raise immediately regardless of `on_issue`" (`architecture.md:607`).

Exception fields and behavior:

- `RivRetrieveError(Exception)`: root package exception for harness errors.
- `IssuePolicyError(RivRetrieveError)`: raised by `apply_on_issue` for recoverable warning/error issues under `on_issue="raise"`.
- `FatalContractError(RivRetrieveError)`: base exception for fatal contract failures raised directly by later detection code.
- `IssuePolicyError` instances carry `issues: tuple[Issue, ...]`, formed from the input `Sequence[Issue]`, so callers/tests can inspect structured diagnostics after a policy raise.
- `FatalContractError` may carry `issues: tuple[Issue, ...] = ()`, but fatal paths are not required to create issues. Step 02 should subclass it for corrupt packaged artifacts if useful; Step 03 should subclass it for unknown providers and invalid registry/provider IDs if useful.

Identifiers:

- `ProviderId = NewType("ProviderId", str)`.
- `ProductId = NewType("ProductId", str)`.

Use `NewType`, not bare aliases or Pydantic-validated strings. It gives static distinction with no runtime cost and avoids validating IDs before the owner exists. Provider ID `snake_case` enforcement is owned by Step 03 registry/provider lookup code, where IDs can be checked against provider package/module names. Step 02 may validate artifact-local IDs for artifact consistency, but Step 03 is the cross-harness owner.

`CatalogProvenance` fields:

- `source: CatalogSource`: required retrieval source, `"packaged"` or `"live"`.
- `provider_id: ProviderId | None = None`: optional because global aggregate catalogue calls may combine providers later; provider-level calls should fill it.
- `rivretrieve_version: str | None = None`: caller-filled package version. Step 03 should decide whether registry-produced provenance auto-populates from `rivretrieve.__version__`.
- `catalogue_version: str | None = None`: packaged or provider catalogue version when known.
- `artifact_id: str | None = None`: packaged artifact logical ID.
- `artifact_path: str | None = None`: packaged artifact path or resource name.
- `artifact_hash: str | None = None`: packaged artifact integrity hash.
- `generated_at: datetime | None = None`: packaged catalogue generation timestamp when known.
- `retrieved_at: datetime | None = None`: live retrieval timestamp when applicable.
- `endpoints: tuple[str, ...] = ()`: live endpoints/calls made.
- `query: dict[str, object] | None = None`: live query parameters or packaged selection context, without secrets.
- `response_version: str | None = None`: provider/API response version when available.

Use one optional-field model rather than a discriminated union. Architecture asks for sufficient provenance without over-specifying nested structures before provider evidence (`architecture.md:579-581`). Do not add cross-field validators yet, such as requiring live provenance to have `endpoints` or `retrieved_at`; Step 02/03 should add such validation only when concrete producers exist.

`CatalogResult[T]` fields:

- `data: T`: required catalogue table or typed catalogue object.
- `provenance: CatalogProvenance`: required.
- `issues: tuple[Issue, ...] = ()`: immutable issue collection, default empty.

Implement generics using Pydantic v2 generic models with `TypeVar("T")` and `class CatalogResult(BaseModel, Generic[T])`. This preserves tracker examples such as `CatalogResult[ProviderInfoCatalog]` (`docs/milestone-tracker.md:59`) and architecture examples (`architecture.md:223-228`).

## 4. Errors and failure modes

- Invalid literal values for `CatalogSource`, `OnIssue`, and `IssueSeverity` are rejected through Pydantic validation where those literals appear on models. Type aliases alone are static typing contracts.
- `apply_on_issue(..., "ignore")` returns without warnings for all issue severities.
- `apply_on_issue(..., "warn")` emits Python warnings for `"warning"` and `"error"` issues, and returns control.
- `apply_on_issue(..., "raise")` raises `IssuePolicyError` when any `"warning"` or `"error"` issue is present.
- `"info"` issues never warn or raise by default under any policy.
- Empty issue lists are no-ops under all policies.
- Fatal contract failures do not pass through `apply_on_issue`. They raise `FatalContractError` or a subclass directly, regardless of `on_issue`.

## 5. Tests

T01. `test_catalog_source_accepts_packaged_and_live`: `CatalogProvenance(source=...)` accepts both `CatalogSource` values.

T02. `test_catalog_source_rejects_unknown_value`: `CatalogProvenance(source="cached")` raises a Pydantic validation error.

T03. `test_issue_severity_accepts_all_values`: `Issue` accepts `"info"`, `"warning"`, and `"error"`.

T04. `test_issue_severity_rejects_unknown_value`: `Issue(severity="fatal", ...)` raises a Pydantic validation error.

T05. `test_issue_construction_roundtrip`: `Issue` preserves `severity`, `code`, `message`, `details`, and `provider_id`.

T06. `test_on_issue_empty_list_noops_for_all_policies`: empty issue lists return without warnings or exceptions for `"ignore"`, `"warn"`, and `"raise"`.

T07. `test_on_issue_ignore_ignores_all_severities`: info, warning, and error issues under `"ignore"` return without warnings.

T08. `test_on_issue_warn_ignores_info`: info issue under `"warn"` emits no warnings.

T09. `test_on_issue_warn_emits_for_warning_and_error`: warning and error issues under `"warn"` emit Python warnings and return.

T10. `test_on_issue_raise_ignores_info`: info issue under `"raise"` returns.

T11. `test_on_issue_raise_raises_for_warning_and_error`: warning and error issues under `"raise"` raise `IssuePolicyError`.

T12. `test_issue_policy_error_carries_issues`: raised `IssuePolicyError.issues` equals the warning/error issues that triggered the raise.

T13. `test_fatal_contract_error_is_separate_from_on_issue`: constructing or raising `FatalContractError` does not require an `Issue` and is not produced by `apply_on_issue`.

T14. `test_catalog_provenance_packaged_roundtrip`: packaged provenance preserves provider/version/artifact/hash/generated fields.

T15. `test_catalog_provenance_live_roundtrip`: live provenance preserves retrieved/endpoints/query/response fields.

T16. `test_catalog_result_roundtrip`: `CatalogResult[list[dict[str, object]]]` preserves `data`, `provenance`, and `issues`.

T17. `test_init_public_surface_still_only_version`: in `tests/test_package.py`, assert the package still exposes `__version__` and does not add planned M1 public names such as `providers`, `provider`, `provider_info`, `CatalogResult`, or `Issue`. The full offline-import negative-control remains Step 03.

## 6. Files

Implementation order that keeps `uv run pytest` green after each file-sized change:

1. Modify `pyproject.toml`: edit `[project].dependencies` only, replacing `dependencies = []` with runtime dependency names `polars`, `pandas`, `pydantic`, and `requests`. Do not edit `[dependency-groups].dev`.
2. Modify `uv.lock`: run `uv lock` or `uv sync` and commit the lockfile change with `pyproject.toml`. If resolution fails, stop per Section 9.
3. Add `src/rivretrieve/_internal/__init__.py`: package marker only.
4. Add `src/rivretrieve/_internal/primitives.py`: define `CatalogSource`, `OnIssue`, `IssueSeverity`, `ProviderId`, and `ProductId`.
5. Add `src/rivretrieve/_internal/issues.py`: define `Issue`, exception classes, and `apply_on_issue`.
6. Add `tests/test_internal_issues.py`: cover T03-T13. `uv run pytest` should pass.
7. Add `src/rivretrieve/_internal/results.py`: define `CatalogProvenance` and `CatalogResult[T]`.
8. Add `tests/test_internal_results.py`: cover T01-T02 and T14-T16. `uv run pytest` should pass.
9. Modify `tests/test_package.py`: add T17 without changing `src/rivretrieve/__init__.py`. `uv run pytest` should pass.
10. Run `uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`, and `uv run pytest`.

## 7. Open questions

Q1. Internal module layout.

Recommendation: use `src/rivretrieve/_internal/{primitives,issues,results}.py`. The underscore package makes non-public status explicit, keeps shared harness symbols away from future provider packages under `src/rivretrieve/providers/<provider_id>/` (`architecture.md:380-392`), and gives Step 03 registry internals stable import paths. Naming convention: modules under `rivretrieve._internal` are private harness implementation; top-level `rivretrieve.*` modules without underscore are not public unless exported from `rivretrieve.__init__` or documented.

Q2. Pydantic v1 vs v2.

Recommendation: choose Pydantic v2. Architecture already commits provider metadata models to Pydantic and extra-field preservation (`architecture.md:256-266`), and v2 uses `ConfigDict(extra="allow")` for those future models. This step's models do not need `extra="allow"` by default, but using v2 now prevents a v1-to-v2 migration later. The local environment already resolves and imports Pydantic v2 under Python 3.13.8.

Q3. Type modeling for Issue, CatalogResult, CatalogProvenance.

Recommendation: use Pydantic v2 `BaseModel` for all three. The objects cross internal module boundaries, need runtime validation for literals, and should stay consistent with provider metadata model policy. Frozen dataclasses are lighter, but they would not validate `Literal` values without custom code.

Q4. Issue field set.

Recommendation: `severity`, `code`, `message`, `details`, and `provider_id`. Do not include `is_fatal`. Architecture fixes the severity vocabulary to `info`, `warning`, and `error` (`architecture.md:587-593`) and lists fatal contract failures as immediate raises (`architecture.md:607`), so fatality belongs in exception control flow rather than the recoverable `Issue` data model.

Q5. `on_issue` policy helper signature and location.

Recommendation: put `apply_on_issue(issues: Sequence[Issue], on_issue: OnIssue) -> None` in `_internal/issues.py`. A plain helper is easier for Step 02/03 catalogue loaders and registry code to call than a context manager or `CatalogResult` method, and it keeps `CatalogResult` as a passive envelope. The helper accepts `Sequence[Issue]` and stores `tuple[Issue, ...]` on `IssuePolicyError`.

Q6. Distinguished exception type for fatal contract failures.

Recommendation: introduce `RivRetrieveError`, `IssuePolicyError`, and `FatalContractError` now. `FatalContractError` is raised directly at detection sites, not via `Issue` or `apply_on_issue`. Do not add `UnknownProviderError` or `CorruptCatalogArtifactError` in this step. Step 02 may subclass `FatalContractError` for corrupt packaged artifacts; Step 03 may subclass it for unknown providers and invalid provider IDs.

Q7. ProviderId / ProductId modeling.

Recommendation: use `NewType`. Enforce provider ID `snake_case` in Step 03 registry/provider lookup code, where IDs can be validated against package/module naming (`architecture.md:51-58`). Product IDs remain opaque and must not be parsed (`docs/milestone-tracker.md:20`), so runtime validation at the alias boundary would add constraints the architecture has not specified.

Q8. CatalogResult generic parameterization.

Recommendation: implement `CatalogResult[T]` with `TypeVar` plus `Generic[T]` on a Pydantic v2 model. The tracker explicitly writes public signatures using `CatalogResult[ProviderInfoCatalog]` (`docs/milestone-tracker.md:59`), and architecture's result shape leaves `data` as the requested table (`architecture.md:231`). Do not enable arbitrary-type validation until Step 02 has a concrete table type that needs it.

Q9. CatalogProvenance field set.

Recommendation: one model with optional fields for packaged and live provenance. A discriminated union would be stricter, but architecture warns not to over-specify nested provenance before provider evidence (`architecture.md:581`). Optional fields make Step 02 packaged artifact provenance and Step 03 empty-registry provider info provenance straightforward while preserving the packaged/live split via `source`.

Q10. Version pinning policy for runtime dependencies.

Recommendation: do not hard-code dependency version specifiers in this plan or in `[project].dependencies` for Step 01. Add the four runtime dependency names and let `uv` resolve Python-3.13-compatible versions into `uv.lock`. The existing `requires-python = ">=3.13"` constrains the resolver, and `uv.lock` is the repository's concrete pin for tests and development.

This avoids false precision in planner-chosen floors. If a later packaging policy requires lower bounds in `pyproject.toml`, that later change must verify the actual floor on Python 3.13, including wheel/source-install behavior. Do not copy legacy floors such as `pandas>=1.3.0` or `requests>=2.25.0` from `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/requirements.txt:1-2`; they belong to the old Python/package baseline.

## 8. Deferrals

- Catalogue schemas (`StationCatalog`, `ProductCatalog`, `StationProductCatalog`, `ProviderInfoCatalog`): Step 02.
- `PackagedCatalogArtifact` and corrupt artifact validation: Step 02. The fatal exception base is introduced here; artifact-specific detection belongs with artifact schema.
- Provider registry, deterministic `rr.providers()`, `rr.provider()`, and `rr.provider_info()`: Step 03.
- Provider ID `snake_case` enforcement: Step 03 registry/provider lookup code.
- Auto-populating `CatalogProvenance.rivretrieve_version`: Step 03, when registry-produced provenance first exists.
- Cross-field provenance validation, such as live provenance requiring an endpoint or retrieval timestamp: Step 02/03, when concrete producers exist.
- Secret-key validation for `Issue.details` or provenance `query`: later hardening task if needed. This step documents producer responsibility but does not implement sanitization.
- Offline-import negative-control test: Step 03, the first step that changes public imports and registry behavior.
- Provider subpackage layout and provider modules: Step 03 or later.
- Observation request/result contracts and annotation schemas: M2.
- Public `ProviderHandle` Protocol: M2.
- Real catalogue data and `ch_foen`: M3.
- Pandas export helpers: later M2 minimum export work. This step only adds pandas as a runtime dependency because the tracker requires it.

## 9. Stopping conditions for the executor

Stop and surface to the orchestrator if any of these happen:

- Implementing this step requires catalogue schemas, packaged artifact validators, registry code, provider modules, observation contracts, annotation schemas, public `ProviderHandle`, or real catalogue data.
- Architecture and tracker conflict on `on_issue`, fatal issue semantics, Polars canonical status, or public/private API exposure.
- Pydantic v2 fails to resolve or import under Python 3.13.
- `uv lock` resolves dependency versions that cannot install/import under Python 3.13.
- Runtime dependency resolution requires exact pins, lower bounds, or upper caps because of a concrete incompatibility.
- Fatal contract failures cannot be expressed cleanly as direct exceptions in Step 02/03 without adding fatality back to `Issue`.
- Provider ID `snake_case` validation cannot be deferred cleanly to Step 03 without making current tests meaningless.
- `src/rivretrieve/__init__.py` must change for reasons other than keeping the existing package metadata test green.
- Any intermediate implementation state would leave `uv run pytest` failing, package imports broken, or public symbols half-exported.
- The executor is tempted to recreate the legacy `RiverDataFetcher` inheritance shape, which tracker stopping conditions explicitly forbid (`docs/milestone-tracker.md:351`).
