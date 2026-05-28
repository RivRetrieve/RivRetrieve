# 03-live-source-capability-routing Plan

## 1. Goal and scope

Ship capability-aware provider-level `source="live"` routing for the three catalogue reader methods in one commit:

- Add internal `LiveCatalogueUnsupportedIssue`, the structured recoverable `Issue` used when a caller asks for live catalogue data but the provider declares that live catalogue capability as unsupported.
- Add internal `LiveCatalogueRoutingNotImplementedError(FatalContractError)`, the defensive direct fatal for the currently unreachable state `source="live"` with the relevant capability flag set to `True`.
- Replace the three fatal `source != "packaged"` guards in `CatalogueReader` at `src/rivretrieve/_internal/catalogue_reader.py:34`, `:59`, and `:73` with routing that distinguishes invalid source values from unsupported live source values.
- Preserve packaged catalogue behavior, product filters, station-product filters, schema validation, provenance shape, and global discovery behavior unchanged.
- Extend reader tests to cover packaged, live unsupported, invalid source, and defensive live-supported behavior for `read_products`, `read_stations`, and `read_station_products`.

This step must not call provider module catalogue functions for `source="live"`. The legacy analogue is `UKEAFetcher.get_metadata()`, which calls the EA hydrology stations endpoint in `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/uk_ea.py:53-79`. Step 03 deliberately does not replicate that live API pattern; M2 routes unsupported live catalogue requests through `Issue` policy and returns empty catalogue tables.

## 2. API surface touched (public + internal)

Public surface:

- No new public symbols.
- No changes to `src/rivretrieve/__init__.py` API shape except the mandatory version literal bump before commit.
- Keep the present public names exactly `{"providers", "provider", "provider_info", "stations", "products", "product_info"}` plus `__version__`.
- Extend the public-surface absence test to explicitly include `LiveCatalogueUnsupportedIssue` and `LiveCatalogueRoutingNotImplementedError`.

Internal surface:

- Modify `src/rivretrieve/_internal/issues.py`:
  - Add `class LiveCatalogueUnsupportedIssue(Issue)`.
  - Add `class LiveCatalogueRoutingNotImplementedError(FatalContractError)`.
  - Keep `InvalidCatalogueSourceError` in this file and leave its shape unchanged.
- Modify `src/rivretrieve/_internal/catalogue_reader.py`:
  - Validate `source` as one of `{"packaged", "live"}`.
  - Keep invalid source values as direct `InvalidCatalogueSourceError`.
  - Route unsupported live catalogue requests through `apply_on_issue`.
  - Keep packaged source behavior unchanged.

Test-only surface:

- Extend `tests/conftest.py` to build a live-capable stub artifact for packaged-capability invariance tests and defensive fatal tests. The existing default fixture already sets all three live flags to `False`.
- Extend `tests/test_internal_catalogue_reader.py` for the step 03 matrix.
- Extend `tests/test_package.py` absence list only; do not relax the present public set.

## 3. Data structures and types (issue, routing, capability lookup, empty results)

`Issue` is a frozen Pydantic model with fields `severity`, `code`, `message`, `details`, and `provider_id` in `src/rivretrieve/_internal/issues.py:9-17`. Because the tracker names `LiveCatalogueUnsupportedIssue` as the internal type for this path, implement it as a typed `Issue` subclass, not a PascalCase factory function. This preserves the bound name, avoids a nonstandard function name, and keeps the issue code/message defaults co-located with the issue type. A module-level constant is invalid because method, capability, provider ID, and message vary.

Recommended subclass contract:

```python
class LiveCatalogueUnsupportedIssue(Issue):
    def __init__(self, *, provider_id: ProviderId | None, method: str, capability: str) -> None:
        super().__init__(
            severity="warning",
            code="live_catalogue_unsupported",
            message=f"Provider {provider_id or '<global>'} does not support live catalogue method {method}",
            details={"method": method, "capability": capability, "source": "live"},
            provider_id=provider_id,
        )
```

The exact message may be executor-polished, but tests should assert stable structured fields: severity, code, provider ID, and details. The code string is `live_catalogue_unsupported`. It is a stable internal label for M2 tests and diagnostics, not a documented public compatibility contract yet.

Capability mapping:

- `read_stations` reads `ProviderInfo.from_row(self.artifact.provider_info).live_stations`.
- `read_products` reads `.live_products`.
- `read_station_products` reads `.live_station_products`.

Use `ProviderInfo.from_row(...)` per call rather than direct dict access. This preserves the typed row view from step 01 and avoids changing the frozen `CatalogueReader(artifact, provider_id)` constructor. The per-call dataclass construction cost is irrelevant for small catalogue entry points and keeps capability interpretation in one place.

Source routing per method:

- Source validity happens first. `source not in {"packaged", "live"}` raises `InvalidCatalogueSourceError(source)` directly.
- Method input validation happens next for existing fatal contracts. In particular, `read_products(source="live", observed_property=123)` still raises `FatalContractError`; live unsupported routing must not silence malformed product filter inputs.
- `source == "packaged"`: run the current packaged path unchanged.
- `source == "live"` and capability is `False`: construct the method-specific `LiveCatalogueUnsupportedIssue`, call `apply_on_issue((issue,), on_issue)`, and return `CatalogResult(data=<empty typed frame>, provenance=<live provenance>, issues=(issue,))`.
- `source == "live"` and capability is `True`: raise `LiveCatalogueRoutingNotImplementedError(...)` directly.

Empty data frames for unsupported live results:

- Stations: `pl.DataFrame(schema=StationCatalog.polars_schema)`.
- Products: `pl.DataFrame(schema=ProductCatalog.polars_schema)`.
- Station-products: `pl.DataFrame(schema=StationProductCatalog.polars_schema)`.

These empty frames validate cleanly through `validate_catalogue(..., on_issue="raise")`; verified locally with all three schemas returning `[]`.

Provenance for unsupported live:

- `source="live"` because provenance should describe the requested catalogue source branch, not the packaged artifact used only for capability metadata.
- `provider_id=self.provider_id`.
- `rivretrieve_version=__version__`.
- `catalogue_version` copied from `artifact.provider_info["catalogue_version"]` when it is a string, matching the existing packaged reader shape.
- `artifact_id=None`, `artifact_path=None`, `artifact_hash=None`, `generated_at=None`, `retrieved_at=None`, `endpoints=()`, `query=None`, `response_version=None`.

This keeps the current `CatalogProvenance` shape from `src/rivretrieve/_internal/results.py:9-26` and leaves M3 real-live provenance room to populate `retrieved_at`, `endpoints`, `query`, and `response_version`.

## 4. Errors and failure modes (separate fatal-raise from Issue-routed paths)

Fatal direct raises, never routed through `apply_on_issue`:

- Invalid source values, including `"archive"`, `""`, `None`, or arbitrary objects cast past typing, raise `InvalidCatalogueSourceError`.
- `source="live"` with the relevant live capability flag `True` raises `LiveCatalogueRoutingNotImplementedError`.
- Non-string, non-`None` product filter values still raise `FatalContractError` directly on the packaged path.
- Catalogue schema violations on packaged final frames still raise direct `FatalContractError` through `validate_catalogue`.
- Malformed provider info rows encountered while reading capability flags raise the existing direct `ProviderInfoValidationError`.

Issue-routed paths:

- `source="live"` with the relevant capability flag `False` is the only new issue-routed path in this step.
- `on_issue="warn"` calls `warnings.warn(..., RuntimeWarning, stacklevel=2)` through `apply_on_issue`, then returns a `CatalogResult` with the issue in `issues`.
- `on_issue="raise"` raises `IssuePolicyError` containing the issue and returns no result.
- `on_issue="ignore"` emits no warning, raises nothing, and returns a `CatalogResult` with the issue in `issues`.
- Existing extra-column catalogue warnings remain routed by `validate_catalogue` only on packaged paths.

Two-channel guardrail:

- `LiveCatalogueUnsupportedIssue` must have severity `"warning"` and must be passed to `apply_on_issue`.
- `InvalidCatalogueSourceError` and `LiveCatalogueRoutingNotImplementedError` must never be converted into `Issue` objects.
- Fatal failures stay direct in line with M1 report §7.6, where the two-channel exception hierarchy is the load-bearing pattern.
- Existing fatal input validation keeps priority over live unsupported routing after source validity. The concrete step-03 case is malformed product filters: `read_products(source="live", observed_property=123)` raises `FatalContractError` directly rather than returning a live-unsupported issue.

## 5. Tests (enumerated, one-line each; include negative controls)

Step 02 ended at T27. Step 03 starts at T28 and should add 18 tests:

T28. `test_catalogue_reader_packaged_products_unchanged_by_live_capability`: packaged `read_products` returns the artifact products and packaged provenance when capability is either false or true.

T29. `test_catalogue_reader_packaged_stations_unchanged_by_live_capability`: packaged `read_stations` ignores capability and preserves the existing result.

T30. `test_catalogue_reader_packaged_station_products_unchanged_by_live_capability`: packaged `read_station_products` ignores capability and preserves the existing result.

T31. `test_catalogue_reader_live_products_warn_returns_empty_result_with_issue`: capability false plus `on_issue="warn"` emits `RuntimeWarning`, returns empty `ProductCatalog` data, live provenance, and one issue.

T32. `test_catalogue_reader_live_stations_warn_returns_empty_result_with_issue`: capability false plus `on_issue="warn"` emits `RuntimeWarning`, returns empty `StationCatalog` data, live provenance, and one issue.

T33. `test_catalogue_reader_live_station_products_warn_returns_empty_result_with_issue`: capability false plus `on_issue="warn"` emits `RuntimeWarning`, returns empty `StationProductCatalog` data, live provenance, and one issue.

T34. `test_catalogue_reader_live_products_raise_wraps_unsupported_issue`: capability false plus `on_issue="raise"` raises `IssuePolicyError` whose first issue has code `live_catalogue_unsupported`.

T35. `test_catalogue_reader_live_stations_raise_wraps_unsupported_issue`: same raise-policy assertion for stations.

T36. `test_catalogue_reader_live_station_products_raise_wraps_unsupported_issue`: same raise-policy assertion for station-products.

T37. `test_catalogue_reader_live_products_ignore_returns_issue_without_warning`: capability false plus `on_issue="ignore"` returns an issue and emits no warnings.

T38. `test_catalogue_reader_live_stations_ignore_returns_issue_without_warning`: same ignore-policy assertion for stations.

T39. `test_catalogue_reader_live_station_products_ignore_returns_issue_without_warning`: same ignore-policy assertion for station-products.

T40. `test_catalogue_reader_invalid_source_remains_direct_fatal_for_all_methods`: parametrized over the three reader methods and an invalid source string; each raises `InvalidCatalogueSourceError` with no `IssuePolicyError` chain.

T41. `test_catalogue_reader_invalid_source_ignores_capability_and_on_issue`: invalid source remains fatal when capability is true or false and `on_issue` is warn, raise, or ignore.

T42. `test_catalogue_reader_live_capable_products_raise_defensive_fatal_for_every_on_issue`: capability true plus `source="live"` raises `LiveCatalogueRoutingNotImplementedError` for `on_issue in ("warn", "raise", "ignore")`, with no `IssuePolicyError` chain.

T43. `test_catalogue_reader_live_capable_stations_raise_defensive_fatal_for_every_on_issue`: same defensive fatal policy matrix for stations.

T44. `test_catalogue_reader_live_capable_station_products_raise_defensive_fatal_for_every_on_issue`: same defensive fatal policy matrix for station-products.

T45. `test_catalogue_reader_live_products_invalid_filter_remains_direct_fatal`: `source="live"` with capability false and a non-string product filter raises `FatalContractError` directly, with no `IssuePolicyError` chain and no live-unsupported result.

Extend existing public-surface T23 rather than adding a new public test:

- Add `LiveCatalogueUnsupportedIssue` and `LiveCatalogueRoutingNotImplementedError` to the deferred absence list in `tests/test_package.py`.

The full Cartesian matrix degenerates into these tests: packaged source is behaviorally identical across capability and `on_issue`, invalid source ignores both capability and `on_issue`, live unsupported has the three meaningful policy outcomes, and live capability-true fatals are explicitly proven non-silenceable across every `on_issue` value.

## 6. Files (new + modified, in implementation order keeping pytest green at each)

1. Modify `src/rivretrieve/_internal/issues.py` to add `LiveCatalogueUnsupportedIssue(Issue)` and `LiveCatalogueRoutingNotImplementedError(FatalContractError)`. Run `uv run pytest`.
2. Extend `tests/test_internal_issues.py` with focused assertions for `LiveCatalogueUnsupportedIssue`: severity, code, provider ID, message, and details. Run `uv run pytest`.
3. Extend `tests/conftest.py` with required live capability overrides in `_provider_info(...)` and the two artifact factory fixtures, or add a narrow helper fixture that post-builds a valid artifact with selected `live_*` flags set to `True`. Keep default flags false. This fixture support is required for T28-T30 and T42-T44. Run `uv run pytest`.
4. Update the existing invalid-source tests in `tests/test_internal_catalogue_reader.py` before changing reader behavior: remove `source="live"` from the `InvalidCatalogueSourceError` cases and keep only values that remain invalid, such as `"archive"`. This preserves T10/T11 intent until T40/T41 supersede it. Run `uv run pytest`.
5. Modify `src/rivretrieve/_internal/catalogue_reader.py` to import `ProviderInfo`, `LiveCatalogueUnsupportedIssue`, `LiveCatalogueRoutingNotImplementedError`, and `apply_on_issue`; replace the three `source != "packaged"` guards with capability-aware branching. Prefer small explicit per-method branches plus shared private helpers such as `_empty_frame(schema)` and `_live_provenance()`; do not change `CatalogueReader.__init__`. Run `uv run pytest`.
6. Extend `tests/test_internal_catalogue_reader.py` for T28-T45. Reuse `_issue_policy_error_chain`, `polars.testing.assert_frame_equal`, and schema assertions from the existing file. T42-T44 must parametrize over `on_issue in ("warn", "raise", "ignore")`; T40/T41 must be a strict superset of the old T10/T11 invalid-source intent. Run `uv run pytest`.
7. Modify `tests/test_package.py` T23 absence list to include `LiveCatalogueUnsupportedIssue` and `LiveCatalogueRoutingNotImplementedError`. Run `uv run pytest`.
8. Run `uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`, and `uv run pytest`.
9. Run `uv run bump-my-version bump patch`, stage the plan plus code/test/version changes, commit, and tag `v$(uv run bump-my-version show current_version)` per project instructions.

## 7. Open questions (with recommendation per question)

Q1. `LiveCatalogueUnsupportedIssue` shape.

Recommendation: typed subclass of `Issue`. The initial factory option has the right construction semantics, but the required name is PascalCase and therefore reads as a type; making it a real `Issue` subclass preserves the tracker-bound name and avoids a nonstandard factory function. A constant is invalid because method, capability, provider ID, and message vary.

Q2. Issue code string.

Recommendation: `live_catalogue_unsupported`. It is short, stable, and specific to catalogue source capability. Treat it as an internal stable test label in M2, not a documented public issue-code contract.

Q3. Defensive fatal exception name.

Recommendation: `LiveCatalogueRoutingNotImplementedError`. It describes the real failure: a provider advertises live catalogue capability, but the harness has no route to execute it in M2. `LiveCatalogueNotYetImplementedError` is too broad, and `LiveCatalogueSupportedButUnroutedError` is accurate but awkward.

Q4. Source-branching logic.

Recommendation: mostly duplicate the explicit branch sequence in the three methods, with tiny shared helpers only for provenance and empty-frame construction. Avoid a decorator. Avoid a single `_route_live_source(...) -> CatalogResult | None` because the multiple return modes would be less clear than three small branches at the method entry points.

Q5. Capability lookup.

Recommendation: `ProviderInfo.from_row(self.artifact.provider_info)` per call, then read the relevant dataclass attribute. This respects the typed view and avoids changing the frozen reader constructor. This re-validates a row already validated at artifact-build time, but the duplication is defensive and small; direct dict access is simpler but bypasses the row contract, while caching in `__init__` changes construction shape and risks step 02 tests.

Q6. Empty data frame schema.

Recommendation: construct `pl.DataFrame(schema=<Schema>.polars_schema)` for each method. Verified locally that `validate_catalogue` accepts empty typed `StationCatalog`, `ProductCatalog`, and `StationProductCatalog` frames with no issues.

Q7. Provenance for unsupported live.

Recommendation: `source="live"`, same provider/version/catalogue fields as packaged where available, and all actual-live retrieval fields empty. This records the requested source while avoiding false claims that a live endpoint was called.

Q8. Python warning under `on_issue="warn"`.

Recommendation: yes. `apply_on_issue` emits `warnings.warn(issue.message, RuntimeWarning, stacklevel=2)` for warning/error severity issues under `"warn"`, raises `IssuePolicyError` under `"raise"`, and returns silently under `"ignore"`.

Q9. Stub fixture capability flags.

Confirmed: `tests/conftest.py:_provider_info(...)` sets `live_stations=False`, `live_products=False`, and `live_station_products=False`; `tests/_stubs/stub_provider.py` mirrors all three as `False`. Existing fixtures suffice for unsupported-live tests. Add a live-capable artifact variant or fixture override for T28-T30 packaged-capability invariance and T42-T44 defensive fatal tests.

Q10. Test inventory and numbering.

Recommendation: T28-T45, 18 tests. This is enough to cover the meaningful matrix without expanding every degenerate cell into separate tests. Existing T10/T11 invalid-source tests must be updated before the reader behavior changes because `source="live"` is no longer invalid.

## 8. Deferrals (with hard rationale: which later step or milestone handles each)

- Public `ProviderHandle` Protocol promotion: later M2 step. Hard rationale: step 03 changes no public symbols.
- Observation contracts: M2 steps 04-05. Hard rationale: live catalogue unsupported issues are catalogue-only; observations have separate request/result/provenance concerns.
- `observations()`, `row_annotation_schema()`, and `series_annotation_schema()` on `_ProviderHandle`: M2 steps 04-05. Hard rationale: this step touches only catalogue reader source routing.
- Actual provider live catalogue calls: M3 or later provider-specific implementation. Hard rationale: tracker §2 keeps normal discovery offline, and M2 step 03 only routes unsupported live as an issue.
- Global `rr.stations()`, `rr.products()`, and `rr.product_info()` source parameters: deferred indefinitely unless architecture changes. Hard rationale: tracker §2 line 16 makes source provider-level only.
- New `CatalogProvenance` fields for unsupported live: deferred. Hard rationale: the existing shape is sufficient and M3 real-live calls can populate existing live-related fields.
- Restructuring `InvalidCatalogueSourceError`: deferred/not planned. Hard rationale: step 02 settled placement in `issues.py`, and this step only narrows when it is raised.
- Real provider modules and `ch_foen`: M3. Hard rationale: tests remain stub-only and offline.
- D2 queued architecture §7/§9 addenda: coordinator work before M3 unless a contradiction appears. Hard rationale: step 03 can execute within the current tracker invariants.

## 9. Stopping conditions for the executor

Stop and surface if any of these happen:

- Implementing `source="live"` requires importing or calling provider module functions.
- Any live catalogue branch performs network I/O or reaches for legacy `get_metadata()` behavior.
- `LiveCatalogueUnsupportedIssue` is implemented as `FatalContractError`, raised directly, or made silenceable by bypassing `apply_on_issue`.
- `InvalidCatalogueSourceError` is routed through `apply_on_issue` for any source value.
- `source="live"` with capability true is routed as a recoverable issue instead of raising direct `LiveCatalogueRoutingNotImplementedError`.
- The design requires changing `CatalogueReader(artifact, provider_id)` constructor shape.
- Global discovery gains a `source` parameter, capability check, or live branch.
- Stub provider catalogue functions stop raising `NotImplementedError` or become part of the live path.
- Public surface tests need to permit new public exports.
- Unsupported-live provenance requires adding a new `CatalogProvenance` field.
- Empty unsupported-live data cannot be represented as typed empty Polars frames accepted by the existing schemas.
- D2 queued architecture addenda become necessary for correctness rather than documentation cleanup.
- Any intermediate file order leaves `uv run pytest` failing or `import rivretrieve` broken.
