# 03-wrapper-capability-and-closeout Plan

## 1. Goal and scope

Ship the M4 package-root observation convenience wrapper and close the milestone without changing retrieval behavior.

This step lands:

- `rr.observations(...)`, a delegation-only free function that performs the existing package provider lookup and calls the returned handle's `.observations(...)`.
- The package-root public-surface expansion owned by T119/T120 for M4.
- A provider-info capability declaration update for `ch_foen.bulk_observations`, because step 02 made bulk observations behaviorally true.
- Generator-side and loader/runtime tests for the revised capability string.
- Observation-side population of `docs/provider_ports/ch_foen.md`.
- `docs/milestones/m4-ch-foen-observations/REPORT.md`, using the M1/M2/M3 report structure and ending with an M4 -> M5 handoff.

Out of scope:

- Any retrieval, parsing, transformation, windowing, preference, conversion, annotation-emission, provenance, issue-routing, or token-resolution behavior change.
- New annotation declarations or removal of the M4 step 01/02 declarations.
- New provider-internal or shared harness types.
- Promotion of any `_internal.providers.ch_foen` symbol to the package root.
- `rr.map_stations()`, V1 conformance closeout, a second provider, a shared backend-policy abstraction, wide-form pandas export, or product-vocabulary expansion.

The wrapper is sugar. The primary public observation path remains:

```python
rr.provider("ch_foen").observations(...)
```

## 2. API surface touched

This is the only M4 step that changes the package-root public surface.

New public symbol:

```python
def observations(
    *,
    provider: str,
    stations: str | Sequence[str],
    products: str | Sequence[str],
    start: object,
    end: object,
    on_issue: OnIssue = "warn",
) -> ObservationResult: ...
```

Signature decisions:

- Keyword-only, with the `*` marker immediately after `(`. This matches architecture.md §3 and the tracker call shape.
- Required keyword arguments: `provider`, `stations`, `products`, `start`, and `end`.
- Default: `on_issue="warn"`.
- Signature matches `ProviderHandle.observations(...)` modulo replacing `self` with `provider`.

Implementation location:

- Add the free function to `src/rivretrieve/_internal/discovery.py`, colocated with `providers`, `provider`, `provider_info`, `stations`, `products`, and `product_info`.
- Rationale: M1 step 03 put package-root free functions in `_internal.discovery`; this wrapper is the same public-discovery/delegation layer, not provider-specific code and not a new module.

`src/rivretrieve/__init__.py` re-export change:

- Add exactly:
  - `from rivretrieve._internal.discovery import observations as observations`
- Keep existing re-exports:
  - `ProviderHandle`
  - `product_info`
  - `products`
  - `provider`
  - `provider_info`
  - `providers`
  - `stations`
- No `ObservationResult`, `OnIssue`, `Sequence`, `Issue`, `AnnotationTable`, or `CatalogResult` package-root re-export.
- The patch version literal also changes at commit time per D1; that is not an API-shape decision.

T119/T120 expansion is owned by this step:

- T119 `module_defined_names` expected set becomes exactly:
  - `ProviderHandle`
  - `observations`
  - `product_info`
  - `products`
  - `provider`
  - `provider_info`
  - `providers`
  - `stations`
- T120 removes `"observations"` from the deferred/forbidden list.
- T120 explicitly keeps `ObservationResult`, `ObservationRequest`, `ObservationProvenance`, `AnnotationSchema`, `AnnotationTable`, `RawPayload`, `Issue`, `CatalogResult`, and all `ChFoen*` / schema / fatal-error internals absent from `rivretrieve`.

## 3. Data structures and types

Wrapper field-level contract:

| Parameter | Type annotation | Required | Forwarded as |
| --- | --- | --- | --- |
| `provider` | `str` | yes | argument to the existing package provider lookup |
| `stations` | `str | Sequence[str]` | yes | `stations=stations` |
| `products` | `str | Sequence[str]` | yes | `products=products` |
| `start` | `object` | yes | `start=start` |
| `end` | `object` | yes | `end=end` |
| `on_issue` | `OnIssue` | no, default `"warn"` | `on_issue=on_issue` |

Return:

- `ObservationResult`, imported only for annotations under `TYPE_CHECKING` or postponed annotations if needed.
- The return object is exactly whatever the provider handle returns; the wrapper must not construct, validate, copy, or normalize an `ObservationResult`.

No new internal type is required. If implementation seems to require a wrapper request model, wrapper result model, wrapper issue type, or wrapper-specific error type, stop: that is scope drift.

Delegation body:

```python
_provider_lookup = provider


def observations(
    *,
    provider: str,
    stations: str | Sequence[str],
    products: str | Sequence[str],
    start: object,
    end: object,
    on_issue: OnIssue = "warn",
) -> ObservationResult:
    provider_handle = _provider_lookup(provider)
    return provider_handle.observations(
        stations=stations,
        products=products,
        start=start,
        end=end,
        on_issue=on_issue,
    )
```

Pin this alias pattern exactly:

- Bind `_provider_lookup = provider` after `def provider(provider_id: str) -> ProviderHandle` is defined and before `def observations(...)` is defined.
- The public parameter remains named `provider` because architecture.md and the tracker require that keyword.
- The wrapper body calls `_provider_lookup(provider)`, not `provider(provider)`, because the keyword-only parameter shadows the module-level `provider()` callable inside the function body.
- `_provider_lookup` preserves the existing `provider()` implementation, including `_ensure_default_providers_registered()` lazy default registration. Do not call `_registry.get(...)` directly and do not reimplement lazy registration inside the wrapper.
- `_provider_lookup` is module-private and is not re-exported from `rivretrieve`.

The resulting executable delegation is:

```python
provider_handle = _provider_lookup(provider)
return provider_handle.observations(
    stations=stations,
    products=products,
    start=start,
    end=end,
    on_issue=on_issue,
)
```

Do not import `rivretrieve as rr` inside `_internal.discovery`.

D6 path-shadowing invariant:

- The public symbol name `observations` does not collide with any internal provider subpackage name.
- Do not create `src/rivretrieve/observations.py` or `src/rivretrieve/observations/`; the free function belongs in `_internal.discovery`.

Capability flag revision:

- Revise `bulk_observations` from `"false"` to this exact `pl.Utf8` string:

```text
true: 366-day window decomposition with stitched N x M station-product requests; partial failures reported as recoverable issues
```

Rationale:

- Step 02 made the behavior true for multi-station, multi-product provider-handle calls.
- A descriptive string is more informative than boolean `true` and matches the existing `ProviderInfoCatalog.bulk_observations` `pl.Utf8` column.
- The string stays a capability description, not a new schema column or architecture.md §9 change.

Regeneration expectations:

- `generate_catalogue.build_provider_info(...)` changes only the `bulk_observations` value.
- Regenerated `src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json` should change only `bulk_observations` unless the executor intentionally bumps a version-stamp column as part of the existing generator invocation.
- No changes to `products.parquet`, `stations.parquet`, or `station_products.parquet` are expected for this capability-only update. If regeneration modifies those artifacts, stop and inspect before proceeding.

D7/D9:

- D7 should not fire; no Pydantic model is added or changed.
- D9 should not fire; the wrapper has no JSON walk. Capability tests may `json.loads` `provider.json`; use concrete `dict` checks if inspecting loaded JSON.

## 4. Errors and failure modes

The wrapper introduces no new fatal or recoverable issue path.

Provider lookup failures that bubble from the existing `rr.provider(...)` implementation through `_provider_lookup(provider)`:

- `UnknownProviderError`, a `FatalContractError` subclass, for an unregistered provider ID.
- Any fatal packaged-artifact/provider-registration failure already reachable through lazy default registration, such as corrupt provider artifacts or provider ID mismatch. These remain direct fatal exceptions.

Provider-handle observation failures that bubble from `provider_handle.observations(...)`:

- `ObservationsUnavailableError` if a registered handle has no observation module.
- `InvalidObservationRequestError` for M2 request normalization failures, including empty or malformed station/product inputs and invalid temporal values.
- `InvalidObservationRequestError` or other existing `FatalContractError` subclasses for unsupported product IDs or provider-specific fatal request/policy drift from step 02.
- `ChFoenObservationParserError`, now a `FatalContractError` subclass, for malformed CSV or missing required Flux columns.
- `ObservationDataSchemaError` or `AnnotationSchemaViolationError` if the provider result violates the M2 result/annotation contracts.
- `IssuePolicyError` when the provider-handle path constructs recoverable issues and `on_issue="raise"` routes them.
- `RuntimeWarning` may be emitted by lower layers under `on_issue="warn"` for recoverable issues, exactly as today.

No two-channel routing decisions are made here:

- The wrapper does not catch exceptions.
- The wrapper does not call `apply_on_issue`.
- The wrapper does not transform fatal exceptions into `Issue` objects.
- The wrapper does not inspect or reroute `ObservationResult.issues`.
- The wrapper does not validate, normalize, or coerce `provider`, `stations`, `products`, `start`, `end`, or `on_issue`.

Call-time missing required keyword behavior:

- Omitting any of `provider`, `stations`, `products`, `start`, or `end` raises Python `TypeError` before any provider lookup. This is signature enforcement, not new runtime validation.

## 5. Tests

1. Delegation spy: monkeypatch `rivretrieve._internal.discovery._provider_lookup` or the backing registry to return a spy `_ProviderHandle`; call `rr.observations(...)`; assert spy `.observations(...)` is called once with exact forwarded kwargs and the wrapper returns the spy's sentinel result object.
2. Required-kwarg negative controls: omitting each of `provider`, `stations`, `products`, `start`, and `end` from `rr.observations(...)` raises `TypeError` or equivalent call-time signature failure.
3. Default `on_issue` forwarding: spy test omits `on_issue` and asserts the handle receives `on_issue="warn"`, unchanged.
4. Explicit `on_issue` forwarding: spy test passes `on_issue="ignore"` or `"raise"` and asserts that exact value is forwarded untouched.
5. Real ch_foen wrapper smoke: with step 02 transport injection installed on `ch_foen_module._observation_client_factory`, call `rr.observations(provider="ch_foen", stations=["2206"], products=["discharge_instantaneous"], start="2025-01-01", end="2025-01-01", on_issue="ignore")`; assert a real `ObservationResult` with the same station 2206 discharge facts from step 02: 144 rows, canonical value min `0.014`, max `0.015`, mean about `0.014944444444`, `fallback_source_used == "true"`, `native_unit == "L/s"`, and `converted_unit == "m3/s"`.
6. Public handle remains primary/callable: keep or add a small assertion that `rr.provider("ch_foen").observations(...)` still works with injected transport and returns equivalent fixture facts; do not replace existing provider-handle tests with wrapper-only tests.
7. T119 expansion: `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface` is renamed or adjusted so `module_defined_names` equals the M4 set including `observations`.
8. T120 expansion: `observations` is no longer forbidden; `ObservationResult`, `Issue`, `AnnotationTable`, `AnnotationSchema`, `RawPayload`, `ObservationRequest`, and other M2/M4 internal types remain forbidden at package root.
9. Offline-import test still passing: `import rivretrieve` in a subprocess still does not import `rivretrieve._internal.providers`, `rivretrieve._internal.providers.ch_foen`, or `generate_catalogue`.
10. Capability generator-side test: `generate_catalogue.generate_catalogue_from_fixture(...).provider_info["bulk_observations"]` equals the exact descriptive string in §3, and the value is a `str`.
11. Capability artifact/write test: `generate_catalogue.main([...])` writes `provider.json` with the exact descriptive `bulk_observations` string and does not require live network.
12. Capability loader/runtime test: `rr.provider("ch_foen").info().bulk_observations` equals the exact descriptive string after loading the packaged artifact.
13. Capability schema test: a one-row `ProviderInfoCatalog` frame with the descriptive string validates against `PROVIDER_INFO_CATALOG_SCHEMA`, preserving the `pl.Utf8` column contract.
14. No unintended artifact drift check: before regeneration, capture the current `provider.json` content from `HEAD`; after regeneration, parse both JSON objects and assert the only changed key is `bulk_observations` (or `bulk_observations` plus an explicitly agreed version-stamp key). Also inspect `git diff --stat` and the JSON/parquet artifact paths; if any catalogue artifact other than `provider.json` changes, stop unless the only additional change is an agreed version-stamp artifact.

Smoke fixture choice:

- Use station `2206` with `discharge_instantaneous`.
- Rationale: it exercises wrapper -> registered provider -> request normalization -> injected transport -> fallback native field -> `flow_ls` conversion -> annotations, without duplicating the broader bulk/windowing matrix from step 02. Station `2282` is simpler stage instant, and `2016` daily temperature exercises aggregation but not fallback/conversion.

## 6. Files

Implementation order must keep `uv run pytest` green without network at every checkpoint.

1. `src/rivretrieve/_internal/discovery.py`
   - Add `observations(...)` as a thin free function below the existing global discovery functions.
   - Add `Sequence`, `OnIssue`, and `ObservationResult` imports for annotations only as needed; with `from __future__ import annotations`, type-only imports may live under `TYPE_CHECKING` if that avoids runtime public-surface leakage.
   - Add `_provider_lookup = provider` after `def provider(...)` and use `_provider_lookup(provider)` inside `observations(...)` to avoid the required `provider` parameter shadowing the module-level function.
   - No package-root export yet; existing public-surface tests remain green because the function is still internal.

2. `src/rivretrieve/__init__.py` and `tests/test_package.py`
   - Atomically re-export `observations` and update T119/T120 in the same checkpoint.
   - Adding the import without T119/T120 changes fails the negative control, so these edits must not be split.

3. Wrapper tests
   - Add delegation spy tests, required-kwarg negative controls, default/explicit `on_issue` forwarding, real ch_foen wrapper smoke with injected transport, public-handle still-callable assertion, and offline-import re-verification if the existing test needs no change.
   - Prefer extending `tests/test_ch_foen_observations.py` for the smoke helper reuse and adding a focused `tests/test_observations_wrapper.py` or `tests/test_discovery.py` block for pure delegation tests.

4. Capability declaration revision
   - Change `build_provider_info(...)` in `src/rivretrieve/_internal/providers/ch_foen/generate_catalogue.py` from `"false"` to the exact descriptive string in §3.
   - Update/add generator-side tests in `tests/test_ch_foen_generate_catalogue.py`.
   - Update loader/runtime tests in `tests/test_ch_foen_capabilities.py`.
   - Regenerate `src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json` from the committed fixture:

```bash
uv run python -m rivretrieve._internal.providers.ch_foen.generate_catalogue \
  --fixture tests/test_data/switzerland_metadata_locations.json \
  --out src/rivretrieve/_internal/providers/ch_foen/catalogue \
  --catalogue-date 2026-05-28
```

   - Before regeneration, save or inspect `git show HEAD:src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json`.
   - After regeneration, compare the parsed old/new JSON objects key by key. The only changed key should be `bulk_observations` unless a version-stamp change is explicitly intended.
   - Inspect the artifact diff. Stop if regeneration touches product vocabulary, provider-info schema columns, station/station-product content, any other `provider.json` key, or anything outside `provider.json` and a deliberate version-stamp field.

5. `docs/provider_ports/ch_foen.md`
   - Populate these M4 observation-side sections:
     - `Observation Retrieval`
     - `Annotation Schema`
     - `Issues`
     - `Token Handling`
     - `Schema Divergence from Legacy Wide-Form Output`
     - `Pain Points`
   - Replace the stale M3 note that annotation schemas are empty.
   - Cite legacy evidence from `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python` at `cd9b030`.

6. `docs/milestones/m4-ch-foen-observations/REPORT.md`
   - Follow M1/M2/M3 structure:
     - status/range/tracker entry;
     - steps executed;
     - public API shipped vs tracker;
     - internal types introduced vs tracker;
     - runtime dependencies;
     - test count delta and negative controls;
     - discoveries logged;
     - surprises / M4 -> M5 handoff;
     - escalations;
     - ready for M5.
   - §7 must enumerate M4 outcomes affecting `rr.map_stations()`.
   - Manual report structure check: verify by comparison with M1/M2/M3 `REPORT.md`; no pytest test is required for report presence/structure.

7. Final verification and patch bump
   - Run:

```bash
uv run ruff format
uv run ruff check --fix
uv run ty check
uv run pytest
uv run bump-my-version bump patch
uv run pytest
```

   - Stage code, docs, regenerated artifact, `pyproject.toml`, and `src/rivretrieve/__init__.py`.
   - Commit and tag per project convention:

```bash
git tag v$(uv run bump-my-version show current_version)
```

## 7. Open questions

1. Where should `rr.observations` live?
   - Recommendation: `src/rivretrieve/_internal/discovery.py`, colocated with the M1/M2 free functions. M1 step 03 established `_internal.discovery` as the package-root free-function implementation module, and no new module is needed.

2. Wrapper signature shape?
   - Recommendation: keyword-only. Architecture.md §3 and tracker §3 M4 both show keyword observation calls, and M2 provider-handle observations are keyword-only.

3. Should the wrapper validate or normalize anything?
   - Recommendation: no. All request normalization and validation belongs to `ObservationRequest.from_inputs(...)` through `_ProviderHandle.observations(...)`. Duplicating checks in the wrapper creates divergence risk. The spy test must prove exact pass-through.

4. Should `bulk_observations` stay `"false"` or change?
   - Recommendation: change to the exact descriptive string in §3. Keeping `"false"` contradicts step 02 execution.md §9, which says bulk observations are behaviorally true. Boolean `true` would be honest, but a descriptive `pl.Utf8` string better captures the 366-day decomposition, N x M cross-product, stitching, transport-injected client, and recoverable partial-failure issues.

5. If `bulk_observations` changes, should regeneration touch other `provider.json` columns?
   - Recommendation: no, except for an explicit version-stamp field if the existing generator command updates `catalogue_version`. The current generator hardcodes all provider-info fields in `build_provider_info(...)`; the executor should inspect the diff and stop if any other capability flag or schema column changes.

6. Which smoke fixture should the wrapper use?
   - Recommendation: `2206` discharge instantaneous. It is the highest-signal single fixture because it proves fallback/conversion and annotation propagation through the real registration path.

7. How much legacy line-level reference should `docs/provider_ports/ch_foen.md` include?
   - Recommendation: cite line ranges for load-bearing translated behavior and keep harness-only behavior in prose. Useful citations:
     - Supported variables/native fields: `cd9b030:rivretrieve/switzerland.py:22-29` and `:44-81`.
     - 366-day windowing: `:43` and `:97-110`.
     - Flux query shape and exclusive stop: `:175-188`.
     - Per-gauge/per-variable download loop and headers: `:190-218`.
     - Parser shape and timezone conversion in legacy: `:220-241`.
     - Preference/fallback: `:251-261`.
     - `flow_ls` conversion: `:263-269`.
     - Daily aggregation: `:290-297`.
     - Instant filtering: `:348-352`.
     - Legacy example using gauge `2016` and daily discharge/temperature: `examples/test_switzerland_fetcher.py:9-20`.
     - `docs/fetchers/switzerland.rst:1-5` is only an automodule stub; cite it only to state that legacy docs delegated to module docs, not for behavior.

8. What must REPORT §7 hand off to M5?
   - Recommendation: include at least:
     - `ch_foen` station catalogue is packaged/offline, has 246 station rows, and carries required coordinates for map rendering.
     - M3/M4 confirmed `latitude` and `longitude` are canonical catalogue columns; `elevation_m` and `drainage_area_km2` remain nullable and should not block mapping.
     - Observation `resolved_timezone` annotations are now emitted as a pattern M5 may reference for time-aware popups, but station mapping itself should not infer time semantics from observation products.
     - Schema-divergence docs explain that M5 maps station catalogues, not legacy wide-form observation outputs.
     - Token handling is isolated to observation retrieval; `rr.map_stations()` must remain offline and must not touch the Influx token/client.
     - The D6 `_internal.providers` path-shadowing lesson continues to apply if map code imports provider assets lazily.
     - The final `bulk_observations` value is the descriptive string from §3, so M5 conformance closeout should no longer expect `"false"`.
     - The package-root public surface now includes `observations`, and T119/T120 were updated in M4; M5 public-surface tests build on that new baseline.
     - D7 and D9 did not fire across M4: step 02 execution.md §8 recorded no new Pydantic `extra="allow"` model and no JSON provider walk, and step 03 also adds neither.
     - D10 remains the legacy-citation method: use `git -C /Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python show cd9b030:<path>` for any M5 legacy Switzerland evidence.

9. Should T120 explicitly forbid `ObservationResult`, `Issue`, `AnnotationTable`, and other M2 types from leaking?
   - Recommendation: yes. The wrapper needs those names only for annotations or downstream return values; they are not promoted package-root symbols. T120 is exactly the guard against accidental type-hint imports leaking into `rivretrieve`.

## 8. Deferrals

- `rr.map_stations()`: M5 owns the station-map public surface and V1 closeout. M4 only documents observation facts that may inform M5.
- Retrieval behavior changes: step 02 owns the `ch_foen` observation pipeline. Any change here risks invalidating fixture facts and two-channel routing already pinned by 416 passing tests.
- Additional annotations: step 01/02 declared and emitted all M4 observation annotations. Adding more would require schema/test expansion and is not needed for the wrapper.
- Product vocabulary expansion: V1 vocabulary remains the six `ch_foen` products already in `products.parquet`; capability strings must not broaden it.
- Shared backend-policy abstraction: architecture.md §11 defers public backend policy; M4 evidence stays provider-internal.
- Wide-form pandas export: architecture.md §12 keeps long-form as the minimum contract; doc schema-divergence can describe legacy wide-form output without recreating it.
- Explicit `__all__`: D5 remains a post-M5 hygiene candidate. T119/T120 `module_defined_names` is sufficient for this step.
- Live catalogue flags: M4 observations do not add live catalogue support. `live_stations`, `live_products`, and `live_station_products` stay `False`.
- Secret/token reclassification: step 01/02 already classified the legacy token as a public service credential and isolated it in `observation_client._EMBEDDED_PUBLIC_TOKEN`. Step 03 documents the outcome; it does not revisit token architecture.

## 9. Stopping conditions for the executor

- Stop if implementing `rr.observations(...)` requires any validation, normalization, transformation, issue routing, or special case beyond delegation.
- Stop if the wrapper requires a new internal type.
- Stop if T119/T120 would need to make `ObservationResult`, `Issue`, `AnnotationTable`, or a `ChFoen*` symbol public to satisfy the wrapper.
- Stop if changing `bulk_observations` would require a new `ProviderInfoCatalog` column, product-vocabulary change, or architecture.md §9 amendment.
- Stop if regenerating catalogue artifacts changes anything outside `provider.json` and an explicit version-stamp field.
- Stop if the parsed regenerated `provider.json` differs from `HEAD` in any key other than `bulk_observations` and an explicitly agreed version-stamp key.
- Stop if any live network is needed for tests, docs, or report writing.
- Stop if `import rivretrieve` starts importing `rivretrieve._internal.providers` or `generate_catalogue`.
- Stop if a provider-port doc claim cannot be backed by `git -C /Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python show cd9b030:<path>` or by current target-repo tests/execution docs.
- Stop if REPORT §7 omits M4 facts relevant to `rr.map_stations()` and M5 closeout: station catalogue coordinates, nullable elevation/drainage, timezone annotation pattern, offline/token isolation, schema-divergence boundary, final `bulk_observations` value, the new `observations` public symbol plus T119/T120 baseline, D7/D9 cross-M4 firing status, or D10 legacy-citation outcome.
- Stop if the work requires a new architecture §14, §16, or §17 decision rather than documenting the behavior already landed in step 02.
