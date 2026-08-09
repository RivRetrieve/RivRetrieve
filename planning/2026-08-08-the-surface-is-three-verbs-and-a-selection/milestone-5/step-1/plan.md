# m5-s1 implementation plan: expose boolean raw retention and issue policy on fetch

Pinned implementation base: `9725f16af881964903af9e556e96aa9e5c15a4ee`.

## 1. Objective

Expose the same two retrieval controls on both selection-based entry points:

```python
def fetch(
    selection: _Selection,
    *,
    start: object,
    end: object,
    raw: bool = False,
    on_issue: OnIssue = "warn",
) -> ObservationResult: ...

def fetch_by_provider(
    selection: _Selection,
    *,
    start: object,
    end: object,
    raw: bool = False,
    on_issue: OnIssue = "warn",
) -> dict[str, ObservationResult]: ...
```

`raw=False` returns no raw receipts. `raw=True` returns, for every selected series, the exact immutable `Payload.content` bytes handed to that provider's `parse` stage together with that payload's exact `SourceCallOrigin`. `on_issue` controls the completed, merged result for each provider and defaults to warning. Remove `RawMode` only from the package-root API while retaining it as the internal representation used by the legacy observation and provider-handle paths.

The human decision is settled and must not be reopened: public `raw` is a plain `bool`; public `on_issue` defaults to `"warn"`; `RawMode` and the `OnIssue = Literal["warn", "raise", "ignore"]` alias remain internal; and the vision's eventual ten-name public surface is exactly `as_frame`, `fetch`, `fetch_by_provider`, `find`, `from_frame`, `map`, `pick`, `products`, `providers`, and `to_utc`. This step removes only `RawMode`; milestone m9 owns the seven legacy removals needed to reach that final surface.

## 2. Semantics to implement

1. Add keyword-only `raw: bool = False` and then keyword-only `on_issue: OnIssue = "warn"` after the existing required `start` and `end` parameters on both `fetch` and `fetch_by_provider`. Preserve `selection` as required positional-or-keyword and `start`/`end` as required keyword-only arguments.
2. At each public discovery boundary, convert `raw` before calling internal observation plumbing:

   ```python
   raw_mode = RawMode.INCLUDE if raw else RawMode.OMIT
   ```

   Pass the resulting `RawMode` and the caller's `OnIssue` into `_fetch_provider_series`. Do not pass a bare bool to `ProviderHandle.observations` or `driver.drive`; `driver.drive` requires an actual `RawMode`.
3. Extend `_fetch_provider_series` with keyword-only `raw: RawMode` and `on_issue: OnIssue`. For every selected series, continue calling `handle.observations` separately with the exact singular station and product, always with `on_issue="ignore"`, and now with `raw=raw` rather than hard-coded `RawMode.OMIT`.
4. Fetch every selected series before applying the caller policy. This includes `on_issue="raise"`: it does not short-circuit at the first issue. Merge all per-series `ObservationResult` objects first. `_merge_provider_results` must continue concatenating `result.raw.entries` in selected-series/result order without decoding, copying, replacing, or reconstructing either `RawSourceCall.content` or `RawSourceCall.origin`; it must continue merging issues in result order.
5. After the provider result is complete, call `apply_on_issue(result.issues, on_issue)` exactly once and return that same result if the policy does not raise. Never apply the caller policy at the per-series handle calls and never apply it a second time. `apply_on_issue` leaves `result.issues` intact under every policy; it ignores `severity="info"`, emits one `RuntimeWarning` per `warning` or `error` issue for `"warn"`, raises one `IssuePolicyError` carrying the ordered actionable issues for `"raise"`, and emits/raises nothing for `"ignore"`.
6. Apply the preceding rules independently to every provider partition in `fetch_by_provider`. Both public functions terminate in `_fetch_provider_series` and return the same four-member `ObservationResult` (`data`, `provenance`, `issues`, `raw`); `fetch_by_provider` differs only by partitioning a selection and returning the results keyed by provider. The controls therefore must be mirrored rather than made dependent on selection cardinality.
7. Retain the raw invariant in operative terms: `Payload.content` is exactly the bytes handed to `parse`; when and only when internal mode is `RawMode.INCLUDE`, `driver.drive` creates a `RawSourceCall` with that exact `content` and that payload's exact `origin`; `RawMode.OMIT` creates no entries. Network bodies, deterministic local-query encodings, or extracted archive members are retained only when they are the bytes parse actually reads. Request headers are never added to origins.
8. Keep empty-selection and mixed-provider validation timing and exact existing errors unchanged. In particular, no provider lookup or fetch occurs before those errors, and `fetch_by_provider` of an empty selection remains `{}` under either default or explicit controls.
9. Delete only `from rivretrieve._internal.observations import RawMode as RawMode` from `src/rivretrieve/__init__.py`. Do not delete the enum or alter its members `OMIT = "omit"` and `INCLUDE = "include"`. `OnIssue` remains unexported. All source consumers continue importing these types from `_internal` modules.
10. Preserve the entire legacy `observations`/`ProviderHandle` plumbing for m9. Its public method signatures, defaults, runtime behavior, and internal `RawMode` usage do not change.

## 3. Write-set

The complete write-set is exactly these six repository-relative paths. Create or delete no file.

- `src/rivretrieve/_internal/discovery.py` — add both public parameters and annotations, convert each public bool to `RawMode`, thread the internal mode and issue policy through `_fetch_provider_series`, retain per-series `on_issue="ignore"`, replace the hard-coded raw omission with the passed mode, and replace the hard-coded final `"warn"` with the caller policy.
- `src/rivretrieve/__init__.py` — remove only the single package-root `RawMode` re-export. Keep `__version__ = "0.1.49"` and every other binding byte-for-byte except for formatter-imposed changes (none are expected).
- `tests/test_fetch.py` — extend the recording provider fixture with exact provider/series origins and opt-in per-series issues; update the signature assertion; add raw-retention tests for singular and multi-provider fetches; add merged multi-series warn/raise/ignore policy tests.
- `tests/test_package.py` — remove the package-root `RawMode` import, remove `"RawMode"` from the exact public-name set, assert the package root lacks it, and assert the same enum remains importable and usable internally.
- `tests/test_observations_wrapper.py` — change only the `RawMode` import to `from rivretrieve._internal.observations import RawMode`; preserve all legacy wrapper assertions.
- `tests/test_provider_handle.py` — change only the `RawMode` import to `from rivretrieve._internal.observations import RawMode`; preserve the public `ProviderHandle` import and every legacy signature assertion.

No gate or planned test requires any other write. In particular, do not modify `src/rivretrieve/_internal/observations.py`, `src/rivretrieve/_internal/driver.py`, `src/rivretrieve/_internal/issues.py`, `src/rivretrieve/_internal/primitives.py`, `src/rivretrieve/_internal/registry.py`, or any fixture file under `tests/test_data/`.

## 4. Existing assertions affected

### `tests/test_fetch.py`

- Update `test_fetch_functions_require_rivretrieve_selection_and_defer_request_controls` (renaming it to `test_fetch_functions_require_rivretrieve_selection_and_expose_request_controls` is permitted and preferred). Replace its exact three-parameter expectation and absence checks with the exact five-parameter expectations in section 5. Keep its invalid-selection error text `selection must be a RivRetrieve selection` and the assertion that no provider lookup occurs.
- `test_fetch_routes_only_selected_sparse_series` is deliberately untouched behaviorally: its default call proves `raw=False` gives `RawPayload(provider_id=ProviderId("usgs_nwis"), entries=())`; its exact frame, provenance, issue tuple, four-field result shape, and call order remain unchanged.
- `test_fetch_by_provider_returns_one_singular_result_per_provider` is deliberately untouched behaviorally: its default call proves every provider result has empty raw entries and retains its exact frames, provenance, result shape, column shape, partition order, and call order.
- `test_fetch_rejects_reason_carrying_empty_selection_before_lookup_or_fetch` is untouched: defaults do not change its exact `EmptySelectionError` text, no-I/O assertions, or empty `{}` partition result.
- `test_fetch_rejects_mixed_provider_selection_before_lookup_or_fetch` is untouched: defaults do not change its exact `MultiProviderSelectionError` text or no-I/O assertions.
- `test_fetch_refuses_zone_carrying_endpoint_before_stage_fetch` is untouched: new defaults do not change its exact `InvalidObservationRequestError` text or no-stage-fetch assertion.
- No existing frame assertion is changed. The new tests use the already authored `VALUES` mapping and recording parse frame unchanged; no new expected observation frame is introduced.

### `tests/test_package.py`

- Update `test_init_public_surface_exports_m2_provider_handle_surface`: the exact public-name set loses only `"RawMode"`; replace `rivretrieve.RawMode is RawMode` with `not hasattr(rivretrieve, "RawMode")`; add the internal identity/member assertions in section 5. Keep the `__version__`, `source_metadata`, and `to_utc` assertions.
- `test_version`, `test_deferred_public_names_remain_absent_after_provider_handle_promotion`, and `test_all_packaged_catalogues_expose_exact_reduced_carriers` are untouched. None refers to the removed root binding, and no catalogue, version, or deferred-name behavior changes.

### `tests/test_observations_wrapper.py`

- `test_observations_wrapper_delegates_to_provider_handle` and `test_observations_wrapper_forwards_default_on_issue` retain every assertion and expected call dictionary verbatim; only their test module's `RawMode` import moves to `_internal.observations`.
- Every parameterized case of `test_observations_wrapper_requires_core_keywords` is untouched. The legacy wrapper is not changed by this step.

### `tests/test_provider_handle.py`

- `test_provider_handle_protocol_method_signatures_match_tracker` retains the exact legacy observation method expectation, including `raw` default `RawMode.OMIT` and annotation string `"RawMode"`; only the enum's test import moves internal.
- All other functions in this file are untouched: `test_provider_handle_imported_from_package_root`, `test_provider_handle_is_runtime_checkable_protocol`, `test_private_provider_handle_structurally_conforms_to_public_protocol`, `test_public_provider_returns_provider_handle_protocol_instance`, `test_public_provider_return_annotation_is_provider_handle`, `test_public_provider_unknown_still_raises_unknown_provider_error`, `test_provider_handle_protocol_declares_exactly_five_public_methods`, and `test_private_provider_handle_has_no_removed_declaration_methods`. `ProviderHandle` remains a package-root name for m9.

### Internal RawMode assertions proven untouched

- `tests/test_ca_eccc_observations.py`, `tests/test_usgs_nwis_observations.py`, and `tests/test_internal_observations.py` already import `RawMode` from `rivretrieve._internal.observations`; do not modify them. Their assertions exercise the same retained internal enum and driver behavior.
- No test outside `tests/test_fetch.py` calls or introspects `fetch` or `fetch_by_provider` at the pinned ref, so there is no additional signature fallout.

## 5. Authored data

Use the following exact authored values. Do not substitute names, bytes, origins, issue text, error text, or expected ordering.

### Recording fixture changes

In `tests/test_fetch.py`, import `UTC` with `datetime`, import `Issue` and `IssuePolicyError` alongside `InvalidObservationRequestError`, and import `RawMode` from `rivretrieve._internal.observations` if needed for direct internal assertions. Add this field in `_RecordingStages.__init__`:

```python
self.issues_by_series: dict[tuple[str, str], tuple[Issue, ...]] = {}
```

For the single payload built by `_RecordingStages.fetch`, retain the exact content expression and use this exact origin:

```python
content=f"{self.provider_id}|{stations[0]}|{products[0]}".encode(),
origin=SourceCallOrigin(
    url=f"https://data.test/{self.provider_id}/{stations[0]}/{products[0]}",
    request_parameters={
        "station_id": stations[0],
        "product_id": str(products[0]),
    },
    status_code=200,
    retrieved_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    content_type="application/octet-stream",
    source_path=UnknownOriginFact(),
    query=UnknownOriginFact(),
),
```

Return the payload with the exact per-series issue lookup:

```python
return WithIssues(
    value=(payload,),
    issues=self.issues_by_series.get((stations[0], str(products[0])), ()),
)
```

The existing complete parse-value fixture remains:

```python
VALUES = {
    ("ca_eccc", "station-1", "level"): 10.0,
    ("ca_eccc", "station-2", "level_hourly"): 20.0,
    ("usgs_nwis", "station-1", "level"): 30.0,
    ("usgs_nwis", "station-2", "level_hourly"): 40.0,
}
```

### Exact public signatures

For each function in `(rr.fetch, rr.fetch_by_provider)`, assert this complete ordered parameter shape:

```python
assert tuple(signature.parameters) == ("selection", "start", "end", "raw", "on_issue")
assert signature.parameters["selection"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
assert signature.parameters["selection"].default is inspect.Parameter.empty
for name in ("start", "end"):
    assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters[name].default is inspect.Parameter.empty
assert signature.parameters["raw"].kind is inspect.Parameter.KEYWORD_ONLY
assert signature.parameters["raw"].default is False
assert signature.parameters["on_issue"].kind is inspect.Parameter.KEYWORD_ONLY
assert signature.parameters["on_issue"].default == "warn"
assert inspect.get_annotations(function, eval_str=False) == {
    "selection": "_Selection",
    "start": "object",
    "end": "object",
    "raw": "bool",
    "on_issue": "OnIssue",
    "return": (
        "ObservationResult"
        if function is rr.fetch
        else "dict[str, ObservationResult]"
    ),
}
```

Keep the exact invalid-selection assertion:

```python
with pytest.raises(TypeError, match="^selection must be a RivRetrieve selection$"):
    function(object(), start="2026-01-01", end="2026-01-01")
```

### Exact raw-retention evidence

The two existing default-path assertions remain exactly:

```python
assert result.raw == RawPayload(provider_id=ProviderId("usgs_nwis"), entries=())
```

and, within the provider loop:

```python
assert result.raw == RawPayload(provider_id=ProviderId(provider_id), entries=())
```

Add a singular-provider test named `test_fetch_raw_true_retains_every_selected_series_parse_input_and_origin`. Select the same sparse USGS series as `test_fetch_routes_only_selected_sparse_series`, call `rr.fetch(..., raw=True)`, and assert the complete ordered raw shape:

```python
assert result.raw.provider_id == ProviderId("usgs_nwis")
assert tuple(entry.content for entry in result.raw.entries) == (
    b"usgs_nwis|station-1|level",
    b"usgs_nwis|station-2|level_hourly",
)
assert tuple(entry.origin for entry in result.raw.entries) == (
    SourceCallOrigin(
        url="https://data.test/usgs_nwis/station-1/level",
        request_parameters={"station_id": "station-1", "product_id": "level"},
        status_code=200,
        retrieved_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        content_type="application/octet-stream",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    ),
    SourceCallOrigin(
        url="https://data.test/usgs_nwis/station-2/level_hourly",
        request_parameters={"station_id": "station-2", "product_id": "level_hourly"},
        status_code=200,
        retrieved_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        content_type="application/octet-stream",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    ),
)
```

Also assert the fixture recorded both exact calls:

```python
assert recording_stages.usgs_nwis.calls == [
    (("station-1",), ("level",)),
    (("station-2",), ("level_hourly",)),
]
```

Add a multi-provider test named `test_fetch_by_provider_raw_true_retains_provider_scoped_parse_inputs_and_origins`. Use `rr.find(product="level")`, call `rr.fetch_by_provider(..., raw=True)`, and assert the full result keys, bytes, and origins:

```python
assert tuple(results) == ("ca_eccc", "usgs_nwis")
assert {
    provider_id: tuple(entry.content for entry in result.raw.entries)
    for provider_id, result in results.items()
} == {
    "ca_eccc": (b"ca_eccc|station-1|level",),
    "usgs_nwis": (b"usgs_nwis|station-1|level",),
}
assert {
    provider_id: tuple(entry.origin for entry in result.raw.entries)
    for provider_id, result in results.items()
} == {
    "ca_eccc": (
        SourceCallOrigin(
            url="https://data.test/ca_eccc/station-1/level",
            request_parameters={"station_id": "station-1", "product_id": "level"},
            status_code=200,
            retrieved_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            content_type="application/octet-stream",
            source_path=UnknownOriginFact(),
            query=UnknownOriginFact(),
        ),
    ),
    "usgs_nwis": (
        SourceCallOrigin(
            url="https://data.test/usgs_nwis/station-1/level",
            request_parameters={"station_id": "station-1", "product_id": "level"},
            status_code=200,
            retrieved_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            content_type="application/octet-stream",
            source_path=UnknownOriginFact(),
            query=UnknownOriginFact(),
        ),
    ),
}
assert all(result.raw.provider_id == ProviderId(provider_id) for provider_id, result in results.items())
```

### Exact merged-issue evidence

For each issue-policy test, select exactly:

```python
sparse = rr.pick(
    rr.find(provider="usgs_nwis"),
    station=["station-1", "station-2"],
    product=["level", "level_hourly"],
)
```

Install these complete issue objects on the recording stage:

```python
first_issue = Issue(
    severity="warning",
    code="station_1_provisional",
    message="station-1 level is provisional",
    details={"station_id": "station-1", "product_id": "level"},
    provider_id=ProviderId("usgs_nwis"),
)
second_issue = Issue(
    severity="error",
    code="station_2_partial",
    message="station-2 level_hourly is partial",
    details={"station_id": "station-2", "product_id": "level_hourly"},
    provider_id=ProviderId("usgs_nwis"),
)
recording_stages.usgs_nwis.issues_by_series = {
    ("station-1", "level"): (first_issue,),
    ("station-2", "level_hourly"): (second_issue,),
}
```

Add `test_fetch_default_warns_once_per_actionable_merged_issue`. Do not pass `on_issue`, and assert exactly:

```python
with pytest.warns(RuntimeWarning) as captured_warnings:
    result = rr.fetch(sparse, start="2026-01-01", end="2026-01-01")

assert [str(warning.message) for warning in captured_warnings] == [
    "station-1 level is provisional",
    "station-2 level_hourly is partial",
]
assert result.issues == (first_issue, second_issue)
```

The exact length-two warning list proves the completed provider result receives one policy application, not one application per series plus another after merge.

Add `test_fetch_on_issue_ignore_returns_all_merged_issues_without_warnings` and assert exactly:

```python
with warnings.catch_warnings(record=True) as captured_warnings:
    result = rr.fetch(
        sparse,
        start="2026-01-01",
        end="2026-01-01",
        on_issue="ignore",
    )

assert captured_warnings == []
assert result.issues == (first_issue, second_issue)
```

Import `warnings` for this assertion.

Add `test_fetch_on_issue_raise_fetches_all_series_then_raises_for_merged_issues` and assert the exact error and completed call order:

```python
with pytest.raises(
    IssuePolicyError,
    match="^Recoverable issue policy requested an exception$",
) as raised:
    rr.fetch(
        sparse,
        start="2026-01-01",
        end="2026-01-01",
        on_issue="raise",
    )

assert raised.value.issues == (first_issue, second_issue)
assert recording_stages.usgs_nwis.calls == [
    (("station-1",), ("level",)),
    (("station-2",), ("level_hourly",)),
]
```

Add one mirrored policy test named `test_fetch_by_provider_applies_issue_policy_once_to_each_completed_provider_result`. Put `first_issue` on `ca_eccc` series `("station-1", "level")` and `second_issue` on `usgs_nwis` series `("station-1", "level")`, call `rr.fetch_by_provider(rr.find(product="level"), ..., on_issue="ignore")` under `warnings.catch_warnings(record=True)`, and assert this complete result:

```python
assert captured_warnings == []
assert tuple(results) == ("ca_eccc", "usgs_nwis")
assert results["ca_eccc"].issues == (first_issue,)
assert results["usgs_nwis"].issues == (second_issue,)
```

For this mirrored test only, use these provider-matching complete objects rather than the preceding USGS multi-series objects:

```python
first_issue = Issue(
    severity="warning",
    code="ca_eccc_provisional",
    message="ca_eccc station-1 level is provisional",
    details={"station_id": "station-1", "product_id": "level"},
    provider_id=ProviderId("ca_eccc"),
)
second_issue = Issue(
    severity="error",
    code="usgs_nwis_partial",
    message="usgs_nwis station-1 level is partial",
    details={"station_id": "station-1", "product_id": "level"},
    provider_id=ProviderId("usgs_nwis"),
)
```

### Exact package-root and internal enum expectations

The complete exact package public-name set after this step is 17 names:

```python
assert module_defined_names == {
    "ProviderHandle",
    "as_frame",
    "fetch",
    "fetch_by_provider",
    "find",
    "from_frame",
    "map",
    "map_stations",
    "observations",
    "pick",
    "product_info",
    "products",
    "provider",
    "provider_info",
    "providers",
    "stations",
    "to_utc",
}
```

Use this exact import and absence/internal-usability evidence:

```python
from rivretrieve import __version__, to_utc
from rivretrieve._internal.observations import RawMode

assert not hasattr(rivretrieve, "RawMode")
assert RawMode.OMIT.value == "omit"
assert RawMode.INCLUDE.value == "include"
assert rivretrieve.to_utc is to_utc
```

Do not add `OnIssue` to the package imports or expected names.

## 6. Acceptance criteria

1. `fetch` and `fetch_by_provider` expose the exact ordered signatures and defaults in section 5; annotations resolve to the exact authored strings under postponed annotations.
2. Existing calls that omit both controls behave as before: singular and partitioned results have the same observation frames/provenance/issues and `RawPayload.entries == ()`.
3. `raw=True` on a two-series singular-provider selection yields the two exact byte strings and origins in selection order. `raw=True` on a two-provider selection yields one exact provider-scoped receipt in each partition. The raw provider identifier matches its result partition.
4. Issues from two selected series are merged without filtering. Default `"warn"` emits exactly the two authored warnings once each and returns both issues; `"ignore"` emits nothing and returns both; `"raise"` fetches both series and raises exact text `Recoverable issue policy requested an exception` with both ordered actionable issues.
5. `fetch_by_provider(..., on_issue="ignore")` returns each provider's own ordered issues without warnings, demonstrating that policy is applied per completed provider result.
6. `RawMode` is absent from `rivretrieve`, remains importable from `rivretrieve._internal.observations`, and retains exact values `"omit"` and `"include"`. `OnIssue` remains internal and no new public name appears.
7. The package-root exact set has the 17 names listed in section 5. Every m9-owned legacy name remains present: `ProviderHandle`, `map_stations`, `observations`, `product_info`, `provider`, `provider_info`, and `stations`.
8. All pre-existing behavior/error assertions named in section 4 remain green. Six tests are added, so the full test observation is exactly `1660 passed, 2 skipped`; the only skips remain the pre-existing missing-folium skips at `tests/test_map_stations.py:179` and `tests/test_map_stations.py:190`, and that file is unmodified.
9. Formatting, lint, source-only typing, tests, and build each succeed independently. `uv.lock` and `pyproject.toml` remain byte-for-byte unchanged.

## 7. Gate commands

Run these commands from the repository root, verbatim and in this exact order, after all edits and before the commit:

```text
uv sync
uv run ruff format
uv run ruff check --fix
uv run ty check src
uv run pytest
uv build
```

Expected observations:

- `uv sync` succeeds without changing `pyproject.toml` or `uv.lock`.
- `uv run ruff format` succeeds; it rewrites files in place and exits 0 when it reformats. Do not replace it with `--check`.
- `uv run ruff check --fix` succeeds with no remaining lint violations.
- `uv run ty check src` succeeds. Its scope must remain exactly `src`.
- `uv run pytest` succeeds with exactly `1660 passed, 2 skipped`: the baseline 1,654 passing tests plus this step's six added tests, and the two unchanged missing-folium tests at `tests/test_map_stations.py:179` and `tests/test_map_stations.py:190`.
- `uv build` succeeds and produces the build artifacts expected by uv; do not commit generated build outputs.

If a uv command fails with `Failed to initialize cache` or `Operation not permitted (os error 1)`, inspect the execution environment rather than changing project files: `~/.config/uv/uv.toml` is expected to point `cache-dir` at a warm shared cache under `$TMPDIR`; the config may be missing, the temporary cache may have been purged, or another concurrent uv build may hold it. Concurrent uv build activity was the common measured cause. Rerun only after that external condition clears, preserving gate order for the final evidence run.

## 8. Constraints and prohibitions

- Work only from the tracked state at `9725f16af881964903af9e556e96aa9e5c15a4ee`; the executor has no vision/review files and needs none beyond this plan.
- Modify exactly the six paths in the write-set. Do not modify `CONTEXT.md`, any file in `docs/adr/`, any vision, graph, planning, review, provider, catalogue, or fixture artifact, or any field under `stated` in `.pce/repository-contract.json`.
- Do not delete or change internal `RawMode`, export `OnIssue`, change issue filtering, reconstruct raw bytes/origins, or alter the four-member `ObservationResult` shape.
- Remove only `RawMode` from the current package-root surface. Preserve all seven m9-owned legacy names and add/remove no other public name; m5/m9 union reconciliation is separate and must work regardless of landing order.
- Do not change legacy `observations`, `ProviderHandle`, `_ProviderHandle`, registry, provider modules, or their signatures. Do not perform any m9 deletion.
- Do not change `__version__ = "0.1.49"`, make any version bump, make a tag, or edit `pyproject.toml` or `uv.lock`.
- Do not install folium or any dependency. Keep `tests/test_map_stations.py` unmodified and its two missing-folium skips intact.
- `tests/typecheck/nominal_window_misuse.py` is an intentional negative type-check fixture asserted by `tests/test_internal_engine_contracts.py`. Never repair or suppress it and never widen the type-check command beyond `src`.
- Plan and implement only m5-s1. Do no Scope-Out work: no bounding box, `record_covers`, shipped `source="live"` capability, coverage snapshot, harmonised name/river search, chained query language, PyPI publication, documentation authoring, provider porting, or decision about native tables shipping in the wheel.
- Do not tolerate a red gate as historical: the pinned baseline is green (`1654 passed, 2 skipped`), so diagnose and fix any regression caused by this change within the stated write-set.
- Keep an explicit not-touched fence in the pull-request description naming all of the above exclusions. Do not include a pre-derived argument that the design is correct; report observable behavior and gate evidence only.

## 9. Executor policies

- Produce exactly one squash-mergeable conventional commit after all six gates pass. Use this exact commit subject: `feat: expose fetch retrieval controls`.
- Run every gate before creating the commit. If any edit is required after a gate, rerun the complete ordered gate sequence before committing.
- Create `pr-body.md` at the worktree root for the pull-request description and leave it untracked. It must summarize the observable API change, exact raw/issue evidence, gate results, and explicit not-touched scope fence. It is not part of the write-set or commit.
- Make no tag, no push, no branch operation, no attribution footer, no `Co-authored-by` footer, and no version change.
- Do not commit generated distributions, caches, `pr-body.md`, or any file outside the six-path write-set.
- The pull request is one squash merge into `pce/the-surface-is-three-verbs-and-a-selection/milestone-5`.
