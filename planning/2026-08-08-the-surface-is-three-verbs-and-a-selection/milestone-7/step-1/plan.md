# m7-s1 implementation plan: render selections with explicit coordinate-frame status

## 1. Objective

Add the public function `rivretrieve.map(selection)` as one merge-green slice. It renders one marker for every unique selected station at `(provider_id, station_id)` grain, even though the immutable input selection remains at `(provider_id, station_id, product_id)` series grain. Every marker must disclose the catalogue's exact `crs` string, and markers whose catalogue CRS is `unknown` must use a different colour from markers whose CRS is established.

Keep the legacy public `map_stations(*, providers=None, bbox=None)` API, its filtering behaviour, `StationMap`, and `_filter_stations` in place for milestone m9. The new `map` operation accepts only a RivRetrieve selection and offers no provider, bounding-box, or other narrowing capability.

The implementation starts from ref `1b903fa1b88522cbf2f441d080a414d17f5056cb`. At that ref, `find(provider="ch_foen")` materializes 738 selected series from packaged catalogue edges and those series project to exactly 246 unique `(provider_id, station_id)` stations. The packaged `ch_foen` station catalogue contains 246 rows, 246 unique `station_id` values, and only the exact CRS string `unknown`. These measured values are acceptance inputs, not values to regenerate or rewrite.

## 2. Semantics to implement

### Selection-to-station projection

In `src/rivretrieve/_internal/selection.py`, add the private `_station_frame(selection: _Selection) -> StationCatalog` projection, importing the existing `STATION_CATALOG_SCHEMA` and `StationCatalog` carriers from `rivretrieve._internal.catalogues.schemas`. Its denotation is:

```text
selection stations : Selection[Series] → StationCatalog unique at (ProviderId, StationId) grain
```

The projection must:

- call the existing selection type guard, so an object that is not the private frozen `_Selection` raises exactly `TypeError("selection must be a RivRetrieve selection")`;
- obtain the series frame through the existing `_as_frame(selection)` path, select `STATION_CATALOG_SCHEMA.polars_schema.names()`, and de-duplicate with `subset=["provider_id", "station_id"]`, `keep="first"`, and `maintain_order=True`;
- return these five columns, in this exact order and with these exact Polars dtypes:

  ```text
  provider_id: String
  station_id: String
  latitude: Float64
  longitude: Float64
  crs: String
  ```

- derive the rows only from `selection.series`; do not read a catalogue and do not call `stations()`, `find()`, `pick()`, or `_filter_stations`;
- collapse repeated product rows by the exact key `(provider_id, station_id)`, retaining one station row and preserving deterministic provider/station order;
- preserve `latitude`, `longitude`, and the exact catalogue `crs` string already frozen into the selected series; never replace `unknown` with `EPSG:4326` in `_Selection`, `_Series`, `as_frame(selection)`, the projected frame, or a packaged catalogue;
- return a zero-row frame with the same exact five-column schema for an empty selection, irrespective of its existing machine-readable empty reason;
- leave `_Selection`, `_Series`, `_EmptyReason`, `SELECTION_FRAME_SCHEMA`, `_find`, `_pick`, `_as_frame`, and `_from_frame` behaviour unchanged.

Update the module denotation docstring so it truthfully covers both catalogue query to series-grain selection and selection to unique station rows. Do not introduce a public selection class or methods on `_Selection`.

### Map rendering

In `src/rivretrieve/_internal/station_map.py`, retain `StationMap` as the renderer of the legacy raw five-column station frame and retain `_filter_stations` unchanged. Adapt rendering as follows:

- render exactly one Folium marker for every row passed to `StationMap`; do not drop rows based on CRS, provider, product, coordinates, or any other field;
- continue to pass marker locations as `[latitude, longitude]` and continue to compute an empty map's centre as exactly `[0.0, 0.0]`;
- for drawing only, treat a row whose exact `crs` is `unknown` as geographic latitude/longitude consumable by Folium. This is not a metadata conversion: the input row and its popup must still say `unknown`;
- create `folium.Icon(color="orange")` for a row whose exact `crs` is `unknown` and `folium.Icon(color="blue")` for every established CRS value. Pass that icon to `folium.Marker` through its `icon=` keyword. These exact colours are the implementation constants and test expectations for this step;
- append the catalogue value to every popup as the exact lowercase-labelled final line `crs: <value>`. Do not rewrite, normalize, infer, or otherwise interpret `<value>`;
- retain the existing tooltip format exactly as `<provider_id> (<station_id>)`;
- retain `_load_folium` and its failure contract. When `import_module("folium")` raises `ModuleNotFoundError`, raise `MissingOptionalDependencyError` containing `folium` and `pip install rivretrieve[map]`, chained from the import failure;
- do not install Folium. The gate environment intentionally lacks it, so real-backend tests continue to skip via their existing `pytest.importorskip("folium")` calls while the fake backend supplies complete acceptance evidence.

This shared renderer change means the legacy fake-backend popup gains the truthful final `crs` line and its marker gains an icon; all legacy selection/filtering, marker count, tooltip, location, missing-dependency, and real-backend behaviour remains in force. The existing legacy five-column frame already has `crs`, so it must remain renderable without adding a sixth input column.

### Public composition-root function and export

In `src/rivretrieve/_internal/discovery.py`, import `_station_frame` as the new private selection-to-station projection and add exactly:

```text
map : Selection[Series] → Folium Map
```

Operatively, `map(selection)` must accept one required positional-or-keyword `selection` parameter, project it to unique station rows, and render that frame with `StationMap`. It must not mutate the selection, read or mutate a packaged catalogue, or filter the projected rows. Its signature must contain exactly `("selection",)` and must not expose `provider`, `providers`, `bbox`, `bounding_box`, or any other narrowing parameter.

In `src/rivretrieve/__init__.py`, export `map` from discovery as `map`. Add no other public name. Keep every legacy export, including `map_stations`, unchanged for m9.

At the pinned ref the complete non-underscore public-name set after this step is exactly:

```python
{
    "ProviderHandle",
    "RawMode",
    "as_frame",
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

If another milestone's already-merged work has added a name to that assertion before execution, preserve that name and make only the set delta `+ {"map"}`. Do not add a name merely because another milestone plans to own it, and do not remove any name.

## 3. Write-set

The complete tracked implementation write-set is exactly:

1. `src/rivretrieve/_internal/selection.py`
   - Add the private, type-guarded, deterministic projection from series-grain `_Selection` to the exact five-column unique-station frame.
   - Update the module denotation docstring to include that projection.
2. `src/rivretrieve/_internal/station_map.py`
   - Render an orange icon for exact `crs == "unknown"`, a blue icon for established CRS, and append the exact source/catalogue CRS value to every popup.
   - Keep the legacy five-column `StationMap` input, legacy map filtering helpers, empty centre, and optional-dependency error path.
3. `src/rivretrieve/_internal/discovery.py`
   - Add the public composition-root `map(selection)` wrapper and import only the private projection it needs.
   - Leave `map_stations` and every other legacy/public function in place.
4. `src/rivretrieve/__init__.py`
   - Export only `map` as this step's new public name.
   - Do not change `__version__` (`0.1.49` at the pinned ref).
5. `tests/test_map_stations.py`
   - Extend the offline fake Folium backend with the exact icon shape below.
   - Add selection-map acceptance tests and update the one legacy popup literal to include `crs: unknown` plus its icon-colour assertion.
   - Keep all legacy tests, including both real-Folium `importorskip` tests.
6. `tests/test_package.py`
   - Add only `"map"` to the exact public-name set in `test_init_public_surface_exports_m2_provider_handle_surface`; preserve the rest of the set and all deferred-name assertions.

The executor must also create `pr-body.md` at the worktree root as the only untracked output. It should summarize the selection-to-station projection, explicit CRS popup/colour treatment, legacy compatibility, and the six gate results. It must remain untracked and must not be included in the commit.

There are no new fixture files. Do not modify or regenerate any `*.parquet`, `provider.json`, `uv.lock`, `pyproject.toml`, `CONTEXT.md`, `docs/adr/*.md`, `.pce/repository-contract.json`, or any planning/vision/review/graph artifact.

## 4. Existing assertions affected

### `tests/test_map_stations.py`

- `test_map_stations_signature_has_no_retired_parameters`: leave unchanged. The legacy signature remains `(*, providers=None, bbox=None)`, so `country` and `on_issue` remain absent.
- `test_map_stations_missing_backend_raises_fatal_contract`: leave unchanged. `StationMap` still calls `_load_folium`, and the same `MissingOptionalDependencyError` remains a `FatalContractError` with `folium` and `pip install rivretrieve[map]` in its text and no `IssuePolicyError` in its exception chain.
- `test_filter_stations_providers_uses_exact_provider_id`: leave unchanged. `_filter_stations` remains legacy-only and still returns exactly 246 `ch_foen` rows and zero `unknown_provider` rows.
- `test_filter_stations_bbox_uses_lon_lat_order_and_inclusive_bounds`: leave unchanged. The expected selected station remains exactly `2016`, the outside result remains empty, and the exact-boundary result remains `2016`.
- `test_filter_stations_combines_provider_and_bbox_filters`: leave unchanged. The expected station remains exactly `2016`, and the wrong-provider result remains empty.
- `test_filter_stations_rejects_invalid_inputs`: leave unchanged. The existing provider and bounding-box error matches remain valid.
- `test_map_stations_empty_result_returns_empty_map`: leave unchanged. The legacy unknown-provider filter still yields a `FakeMap` with exactly `[]` markers.
- `test_map_stations_fake_backend_receives_filtered_station_frame`: update the exact popup from

  ```text
  <strong>ch_foen</strong><br>Station: 2016<br>Latitude: 47.4825<br>Longitude: 8.1949
  ```

  to

  ```text
  <strong>ch_foen</strong><br>Station: 2016<br>Latitude: 47.4825<br>Longitude: 8.1949<br>crs: unknown
  ```

  Keep the exact tooltip `ch_foen (2016)`, location `[47.4825, 8.1949]`, and marker count `1`; add the exact icon-colour assertion `"orange"`.
- `test_map_stations_uses_packaged_station_catalogue_only`: keep its exact legacy marker count `246`; it remains evidence that the legacy operation reads the packaged station catalogue.
- `test_map_stations_reads_stations_not_products`: leave unchanged. Its exact counters remain `products == 0`, `station_products == 0`, and `stations >= 1`.
- `test_station_map_real_backend_returns_folium_map_for_selected_station`: retain unchanged, including `pytest.importorskip("folium")` and the exact HTML substrings `ch_foen` and `2016`. It remains one of the two expected skips when Folium is absent.
- `test_station_map_real_backend_renders_five_column_station_frame`: retain unchanged, including `pytest.importorskip("folium")` and the exact HTML substrings `stub_provider` and `nullable-1`. It proves the legacy exact five-column shape below remains renderable and remains the other expected skip when Folium is absent.
- `_five_column_station_frame`: leave its complete row and schema unchanged as quoted in section 5.

Add new tests with the following responsibilities and exact assertions:

- `test_map_signature_accepts_only_required_selection_without_narrowing`: `tuple(inspect.signature(rr.map).parameters) == ("selection",)`; the sole parameter is `POSITIONAL_OR_KEYWORD`; its default is `inspect.Parameter.empty`; and `{"provider", "providers", "bbox", "bounding_box"}` is disjoint from the parameters.
- `test_map_rejects_non_rivretrieve_selection`: `rr.map(object())` raises `TypeError` with exact text `selection must be a RivRetrieve selection`.
- `test_map_empty_selection_has_no_markers`: map `rr.find(provider="usgs_nwis", station="01646500", product="stage_daily_mean")`; assert its existing reason code is exactly `no_catalogue_edge`, the fake result has location `[0.0, 0.0]`, and its markers equal `[]`.
- `test_map_ch_foen_selection_renders_unique_unknown_crs_stations_without_mutation`: obtain exactly `selection = rr.find(provider="ch_foen")`; record `before = rr.as_frame(selection)` and a provider-filtered `rr.stations().data` frame before rendering; assert `before.height == 738`, `before.select("provider_id", "station_id").unique().height == 246`, and its CRS values are exactly `["unknown"]`; render through the fake backend; assert exactly 246 markers, every popup satisfies `marker.popup.endswith("<br>crs: unknown")`, and every icon colour is exactly `orange`; compare `rr.as_frame(selection)` to `before` with `polars.testing.assert_frame_equal(..., check_exact=True)`; read and provider-filter `rr.stations().data` again, compare it to the pre-render station frame with the same library assertion, and assert its exact CRS values remain `["unknown"]`. This test must not enumerate or author a replacement 738-row expected frame.
- `test_map_established_crs_uses_distinct_marker_colour_and_exact_popup`: use the exact one-series USGS selection and exact projected station values in section 5; assert one marker, exact blue colour, exact location, exact tooltip, and exact popup. Also assert `blue != orange` explicitly so the status distinction is visible in the fake backend.

Extend imports only as required for those assertions, including `polars.testing as pl_testing`. Do not create a new test file.

### `tests/test_package.py`

- `test_init_public_surface_exports_m2_provider_handle_surface`: update the exact full set by adding only `"map"`; the pinned-ref expected set after the update is quoted in full in sections 2 and 5. Keep the separate `__version__` presence assertion, `source_metadata` absence assertion, and `RawMode`/`to_utc` identity assertions unchanged.
- `test_deferred_public_names_remain_absent_after_provider_handle_promotion`: leave unchanged. In particular, `StationMap` remains absent from the public package surface, as do all other listed internal/deferred names.
- `test_version`: leave unchanged; there is no version bump.
- `test_all_packaged_catalogues_expose_exact_reduced_carriers`: leave unchanged. This step writes no catalogue file or schema and retains `published_record_start_date` and `published_record_end_date` exactly.

### `tests/test_selection.py`

No existing assertion is edited. Specifically:

- `test_selection_is_immutable_method_free_and_series_grained` remains valid because the projection is a module-private function, not a selection method, and `_Selection`/`_Series` remain frozen and series-grained.
- `test_as_frame_is_deterministic_and_from_frame_round_trips` remains valid because `_as_frame` and `SELECTION_FRAME_SCHEMA` are unchanged and map rendering never writes into either frame or selection.
- `test_selection_function_signatures_exclude_unshipped_capabilities` remains valid because `find`, `pick`, `as_frame`, and `from_frame` signatures do not change.

A ref-wide grep at `1b903fa1b88522cbf2f441d080a414d17f5056cb` finds no other tests referring to `map_stations`, `StationMap`, `_filter_stations`, `_station_popup`, or the exact package `module_defined_names` assertion. Therefore no other existing assertion requires an update.

## 5. Authored data

No binary, JSON, CSV, HTML, or other fixture is authored. The tests consume committed packaged catalogues. The following are all newly authored or changed in-test shapes and expected values; use them exactly.

### Fake Folium backend extension

The complete fake icon shape is:

```python
class FakeIcon:
    def __init__(self, *, color: str) -> None:
        self.color = color
```

The complete changed fake marker shape is:

```python
class FakeMarker:
    def __init__(
        self,
        *,
        location: list[float],
        tooltip: str,
        popup: str,
        icon: FakeIcon,
    ) -> None:
        self.location = location
        self.tooltip = tooltip
        self.popup = popup
        self.icon = icon

    def add_to(self, station_map: FakeMap) -> None:
        station_map.markers.append(self)
```

The complete changed fake Folium surface is:

```python
class FakeFolium:
    Map = FakeMap
    Marker = FakeMarker
    Icon = FakeIcon
```

`FakeMap` remains exactly a map with constructor inputs `location: list[float]`, `zoom_start: int`, and `control_scale: bool`, and an initially empty `markers: list[FakeMarker]`. No fake backend field beyond those shown is needed.

### Exact legacy five-column input fixture

Keep this existing fixture content and schema byte-for-byte in meaning:

```python
pl.DataFrame(
    [
        {
            "provider_id": "stub_provider",
            "station_id": "nullable-1",
            "latitude": 47.0,
            "longitude": 8.0,
            "crs": "unknown",
        }
    ],
    schema={
        "provider_id": pl.Utf8,
        "station_id": pl.Utf8,
        "latitude": pl.Float64,
        "longitude": pl.Float64,
        "crs": pl.Utf8,
    },
)
```

### Exact selection station-frame schema

The empty and non-empty private station projections both have exactly:

```python
pl.Schema(
    {
        "provider_id": pl.Utf8,
        "station_id": pl.Utf8,
        "latitude": pl.Float64,
        "longitude": pl.Float64,
        "crs": pl.Utf8,
    }
)
```

### Exact established-CRS expected station

The test input is exactly:

```python
rr.find(
    provider="usgs_nwis",
    station="01646500",
    product="discharge_daily_mean",
)
```

Its complete projected station row is:

```python
{
    "provider_id": "usgs_nwis",
    "station_id": "01646500",
    "latitude": 38.94977778,
    "longitude": -77.12763889,
    "crs": "EPSG:4269",
}
```

The complete expected marker observation is:

```python
{
    "location": [38.94977778, -77.12763889],
    "tooltip": "usgs_nwis (01646500)",
    "popup": (
        "<strong>usgs_nwis</strong><br>Station: 01646500"
        "<br>Latitude: 38.94977778<br>Longitude: -77.12763889"
        "<br>crs: EPSG:4269"
    ),
    "icon.color": "blue",
}
```

### Exact unknown-CRS expectations

For `rr.find(provider="ch_foen")`:

```text
selected series rows: 738
unique (provider_id, station_id) pairs: 246
rendered markers: 246
selection crs unique values: ["unknown"]
fresh packaged station crs unique values after rendering: ["unknown"]
required popup CRS line on every marker: crs: unknown
required icon colour on every marker: orange
```

For the existing Brugg legacy assertion, the complete expected marker is:

```python
{
    "location": [47.4825, 8.1949],
    "tooltip": "ch_foen (2016)",
    "popup": (
        "<strong>ch_foen</strong><br>Station: 2016"
        "<br>Latitude: 47.4825<br>Longitude: 8.1949"
        "<br>crs: unknown"
    ),
    "icon.color": "orange",
}
```

### Exact empty-selection and error expectations

The empty input is exactly:

```python
rr.find(
    provider="usgs_nwis",
    station="01646500",
    product="stage_daily_mean",
)
```

Its existing empty reason code is exactly `no_catalogue_edge`. Rendering produces a `FakeMap` whose location is exactly `[0.0, 0.0]` and whose markers are exactly `[]`.

For every non-selection object, including `object()`, the exact exception is:

```text
TypeError: selection must be a RivRetrieve selection
```

### Exact public-name expectation

The full pinned-ref public-name assertion after this step is:

```python
{
    "ProviderHandle",
    "RawMode",
    "as_frame",
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

## 6. Acceptance criteria

Run focused evidence before the full gates; these commands do not replace any gate in section 7.

1. Command:

   ```bash
   uv run pytest tests/test_map_stations.py -k 'map_signature_accepts_only_required_selection_without_narrowing or map_rejects_non_rivretrieve_selection'
   ```

   Expected observation: the new public function has exactly one required positional-or-keyword parameter named `selection`, exposes none of `provider`, `providers`, `bbox`, or `bounding_box`, and `object()` raises the exact `TypeError` text `selection must be a RivRetrieve selection`.

2. Command:

   ```bash
   uv run pytest tests/test_map_stations.py -k 'map_empty_selection_has_no_markers'
   ```

   Expected observation: the exact no-edge selection named in section 5 retains reason `no_catalogue_edge` and renders a fake map centred at `[0.0, 0.0]` with exactly `[]` markers.

3. Command:

   ```bash
   uv run pytest tests/test_map_stations.py -k 'map_ch_foen_selection_renders_unique_unknown_crs_stations_without_mutation'
   ```

   Expected observation: 738 selected series collapse to exactly 246 unique station markers; all 246 popups end with `<br>crs: unknown`; all 246 icons are `orange`; `as_frame(selection)` is frame-equal before and after rendering; and a fresh `rr.stations().data` provider slice remains frame-equal with exact CRS values `["unknown"]`.

4. Command:

   ```bash
   uv run pytest tests/test_map_stations.py -k 'map_established_crs_uses_distinct_marker_colour_and_exact_popup'
   ```

   Expected observation: the exact `usgs_nwis/01646500/discharge_daily_mean` selection produces one marker at `[38.94977778, -77.12763889]`, with tooltip `usgs_nwis (01646500)`, popup ending `crs: EPSG:4269`, icon colour `blue`, and an explicit assertion that `blue != orange`.

5. Command:

   ```bash
   uv run pytest tests/test_map_stations.py
   ```

   Expected observation: all fake-backend and legacy mapping tests pass. With Folium absent, exactly the two retained real-backend tests skip; no test requiring Folium is added.

6. Command:

   ```bash
   uv run pytest tests/test_package.py -k 'init_public_surface_exports_m2_provider_handle_surface or deferred_public_names_remain_absent_after_provider_handle_promotion or version'
   ```

   Expected observation: `map` is present in the exact full public set, every pre-existing public name remains, `StationMap` and all deferred/internal names remain absent, and the installed/package version remains unchanged.

7. Command:

   ```bash
   git diff --name-only
   ```

   Expected observation before the commit: tracked implementation changes are confined to the six paths in section 3. Pre-existing user changes outside those paths must remain untouched. `pr-body.md` is untracked and therefore is not listed by this command; verify it separately with `git status --short` and do not stage it.

## 7. Gate commands

After focused tests and after creating but not staging `pr-body.md`, run all gates verbatim in this exact order. Every command must exit zero:

```bash
uv sync
uv run ruff format
uv run ruff check --fix
uv run ty check src
uv run pytest
uv build
```

Expected observations:

- `uv sync` completes without changing `pyproject.toml` or `uv.lock`; neither dependency file is part of the write-set.
- `uv run ruff format` may rewrite implementation files in place and exits zero after formatting. It is intentionally not `--check`.
- `uv run ruff check --fix` exits zero with no remaining lint findings and introduces no change outside the six tracked paths.
- `uv run ty check src` exits zero. Its scope is exactly `src`.
- `uv run pytest` exits zero with exactly `1648 passed, 2 skipped` when starting from the pinned baseline and adding the five non-parameterized tests named in section 4. The two skips remain the same pre-existing real-Folium tests. No failure or extra skip is acceptable. If already-merged concurrent work has legitimately changed the total test count before execution, preserve that work and require its baseline pass count plus exactly five, still with only the same two Folium skips from this step's scope.
- `uv build` exits zero and creates valid distribution artifacts without a version change.

If any gate is red, treat it as caused by this change and fix it before committing. Do not accept or waive a failure against the green pinned baseline.

## 8. Constraints and prohibitions

### Repeatability and not-touched scope fence

This act is repeatable from the pinned ref: it is a pure source/test change over already committed catalogue artifacts. The implementation must not fetch, refresh, regenerate, edit, or write back any catalogue. Rendering may interpret exact `crs == "unknown"` as EPSG:4326 only at the instant it supplies `[latitude, longitude]` to Folium; persisted and returned metadata must remain exactly `unknown`.

Do not touch:

- `map_stations`, `StationMap`, or `_filter_stations` removal; m9 owns legacy deletion;
- any legacy public name: `ProviderHandle`, `RawMode`, `map_stations`, `observations`, `product_info`, `provider`, `provider_info`, or `stations`;
- any already-landed selection, products, or UTC semantics from m2, m3, or m6;
- `source_metadata`, which is deliberately absent;
- canonical `published_record_start_date` or `published_record_end_date` spelling; never restore bare canonical `start_date`/`end_date`;
- a bounding box, provider argument, click-to-select behaviour, or any capability that narrows a selection;
- `record_covers`, shipped `source="live"`, a coverage snapshot, harmonised station-name or river-name search, a chained query language, PyPI publication, documentation authoring, provider porting, or a decision about whether native tables ship in the wheel;
- any packaged catalogue (`provider.json`, `products.parquet`, `stations.parquet`, `station_products.parquet`, or `native.parquet`) or test-data fixture;
- `pyproject.toml` and `uv.lock`; Folium is optional, absent, and cannot be installed because the executor has no network;
- `CONTEXT.md` or `docs/adr/*.md`. The existing domain rule is that `unknown` remains a first-class source state; drawing-only interpretation does not change the recorded domain value and this step adds no new glossary decision;
- any planning, vision, milestone, step-graph, review, or approval artifact;
- any field under `stated` in `.pce/repository-contract.json`. Do not edit that file at all;
- the intentional negative fixture `tests/typecheck/nominal_window_misuse.py`. It is asserted by `tests/test_internal_engine_contracts.py`, must not be repaired or suppressed, and is intentionally outside the `uv run ty check src` gate;
- version `0.1.49`, tags, and release metadata.

Do not add a fallback for malformed data, catch and continue after rendering errors, mutate frozen selection objects, mutate frames in place, or infer an established CRS. Fail through the existing type/optional-dependency contracts.

`uv` opens `~/.cache/uv` for write on every invocation. The executor environment is expected to have `~/.config/uv/uv.toml` pointing `cache-dir` at a warm shared cache under `$TMPDIR`, which the sandbox permits. If a command fails with `Failed to initialize cache` or `Operation not permitted (os error 1)`, report/fix the missing executor cache configuration or purged temporary cache; do not work around it by changing repository dependency files or using `pip`, `poetry`, `conda`, or `pip-tools`.

After each formatting/fix command, inspect `git diff --name-only` and keep only the six tracked write-set paths. Preserve all pre-existing user changes, including changes outside the write-set; do not overwrite or clean them.

## 9. Executor policies

- Implement the entire step as exactly one squash-mergeable pull request into `pce/the-surface-is-three-verbs-and-a-selection/milestone-7`.
- Run all six gates in section 7 successfully before creating the commit.
- Create exactly one conventional commit after the gates, with commit subject:

  ```text
  feat: render selections with coordinate status
  ```

- Stage and commit only the six tracked write-set files. Leave `pr-body.md` at the worktree root untracked.
- Do not commit the plan, `pr-body.md`, build artifacts, cache content, or any unrelated/pre-existing change.
- Make no version change. Create no tag.
- Do not push the branch or commit.
- Add no attribution footer, `Co-authored-by`, `Signed-off-by`, or other commit-message footer.
- Do not edit any field under `stated` in `.pce/repository-contract.json`.
