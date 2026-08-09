# m9-s1 implementation plan — retire the legacy public surface and catalogue-source switch

## 1. Objective

Deliver one green breaking-surface PR that removes the object/table-shaped legacy API and the catalogue source selector. After this change, catalogue discovery is packaged-only; observation fetching reaches the registered provider runtime internally; and the shipped package surface is exactly the surviving function API plus `RawMode` (whose publicness belongs to m5 and is not changed here).

The observable result at this step is:

```python
[name for name in dir(rivretrieve) if not name.startswith("_")]
== [
    "RawMode",
    "as_frame",
    "fetch",
    "fetch_by_provider",
    "find",
    "from_frame",
    "map",
    "pick",
    "products",
    "providers",
    "to_utc",
]
```

The following names must be unreachable from the package root:

```python
(
    "ProviderHandle",
    "CatalogSource",
    "map_stations",
    "observations",
    "product_info",
    "provider",
    "provider_info",
    "stations",
)
```

`CatalogSource` was not exported at the pinned ref, so its absence from `dir(rivretrieve)` is only a public smoke assertion. Its load-bearing removal evidence is that it no longer exists in active `src/` or `tests/`, and no active catalogue API accepts `source=`.

## 2. Semantics to implement

### 2.1 Public surface removal

- Delete the public `ProviderHandle` protocol module and its package-root export.
- Delete `provider(provider_id)`, the top-level `observations(...)` wrapper, global `stations()`, global `provider_info()`, `product_info()`, its private `_global_products()` implementation, global-catalogue helper `_concat_or_empty()`, and `map_stations(...)`.
- Remove all corresponding imports from `rivretrieve/__init__.py`. Do not provide aliases, deprecation shims, `__getattr__` fallbacks, or alternate import paths.
- Keep `providers`, `find`, `pick`, `fetch`, `fetch_by_provider`, `products`, `as_frame`, `from_frame`, `map`, and `to_utc` behavior and signatures unchanged.
- Keep `RawMode` exported exactly as it is at the pinned ref. Do not add or remove `raw=` or `on_issue=` on `fetch` or `fetch_by_provider`; m5 owns those decisions.
- Bind discovery’s internal `_provider_lookup` directly to `_registry.get`. `fetch()` and `fetch_by_provider()` continue partitioning selected series and calling the registered internal `_ProviderHandle.observations(...)`; they must not route through a public `provider()` function.

### 2.2 Surviving discovery behavior

`products(provider=None)` remains the list-shaped public product discovery API:

- It reads only packaged product catalogues through `CatalogueReader.read_products()`.
- With `provider is None`, return the sorted, deduplicated union of canonical product IDs across every registered provider.
- With a registered provider ID, return that provider’s sorted canonical product-ID list.
- With an unknown provider ID, raise `UnknownProviderError` with exact text `Provider is not registered: missing_provider` for the test input `missing_provider`.
- Return a plain `list[str]`, never a `CatalogResult` or `polars.DataFrame`.

`map(selection)` remains the sole mapping API. It renders the unique station frame carried by a RivRetrieve selection. It accepts only the required `selection` argument; it does not regain provider or bounding-box arguments.

### 2.3 Packaged-only catalogue reader

Remove `CatalogSource = Literal["packaged", "live"]` from `_internal/primitives.py`. Narrow every active catalogue call to packaged data. The final callable shapes are exactly:

```python
class CatalogueReader:
    def read_products(
        self,
        *,
        observed_property: str | None = None,
        frequency: str | None = None,
        statistic: str | None = None,
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]: ...

    def read_stations(
        self,
        *,
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]: ...

    def read_station_products(
        self,
        stations: Sequence[str] | None = None,
        *,
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]: ...
```

The `ProviderModule` protocol, internal registry `_ProviderHandle`, all thirteen provider `module.py` files, and `tests/_stubs/stub_provider.py` use these exact catalogue method shapes:

```python
def products(
    *,
    observed_property: str | None = None,
    frequency: str | None = None,
    statistic: str | None = None,
    on_issue: OnIssue = "warn",
) -> CatalogResult[pl.DataFrame]: ...

def stations(
    *,
    on_issue: OnIssue = "warn",
) -> CatalogResult[pl.DataFrame]: ...

def station_products(
    stations: Sequence[str] | None = None,
    *,
    on_issue: OnIssue = "warn",
) -> CatalogResult[pl.DataFrame]: ...
```

For those methods:

- Always read the committed `PackagedCatalogArtifact` frames.
- Preserve exact product filters, station-product station filtering, schema validation, `on_issue` handling for catalogue validation, and packaged provenance.
- Delete source validation, every `source == "live"` branch, live empty-frame returns, unsupported-live issues, and defensive live-routing failures.
- Delete `_live_provenance()` and the now-unused `_empty_frame()` from `catalogue_reader.py`.
- Delete `LiveCatalogueUnsupportedIssue`, `InvalidCatalogueSourceError`, and `LiveCatalogueRoutingNotImplementedError` from `_internal/issues.py`; no active caller remains.
- `CatalogProvenance.source` survives but narrows to `Literal["packaged"]`. It remains required and every catalogue result continues to set it to exactly `"packaged"`. Observation provenance is a different model and continues accepting such values as `"live"`, `"local"`, and provider engine source strings.

### 2.4 Internal data retained and live behavior fenced

Retain `live_stations`, `live_products`, and `live_station_products` in `ProviderInfo`, `PROVIDER_INFO_CATALOG_SCHEMA`, all committed `provider.json` files, parsing, round-trip tests, and packaged artefacts. These are internal committed catalogue-schema data. Once `provider()` and `provider_info()` disappear, there is no surviving public reader for them; do not regenerate or edit catalogue artifacts.

Retain all USGS behavior independent of the withdrawn catalogue selector:

- `src/rivretrieve/_internal/providers/usgs_nwis/module.py` keeps `observation_source: str = "live"`.
- `src/rivretrieve/_internal/providers/usgs_nwis/generate_catalogue.py` keeps `read_live_native_rows()`, `refresh_native_table_from_live()`, and the `--live` native-table maintenance route unchanged.
- `tests/test_usgs_nwis_generate_catalogue.py` remains unchanged, including `test_live_transport_uses_exact_102_in_scope_urls`, `test_cli_rejects_cross_mode_combinations`, and `test_native_build_is_network_free_and_byte_deterministic`.
- The observation-engine tests continue asserting `ObservationProvenance.source == "live"`; catalogue provenance alone is narrowed.

The inert `reference/legacy_observations/` tree is excluded by repository configuration and remains byte-for-byte untouched even though its historical files mention `CatalogSource` and `rr.provider`. This step does not port or clean the reference providers.

## 3. Write-set

No path outside this list may be created, modified, or deleted by the implementation. Packaged Parquet/JSON catalogues are not in the write-set.

### Source files to modify

- `src/rivretrieve/__init__.py` — remove the seven withdrawn public function imports and the `ProviderHandle` import; retain the eleven-name surface and `__version__ = "0.1.49"`.
- `src/rivretrieve/_internal/discovery.py` — delete the legacy functions and dead imports/helpers; bind `_provider_lookup = _registry.get`; preserve all selection, fetch, merge, registration, and `products()` behavior.
- `src/rivretrieve/_internal/catalogue_reader.py` — remove `source` parameters and all invalid/live branches; keep only packaged reads, filters, validation, and packaged provenance.
- `src/rivretrieve/_internal/issues.py` — delete the three catalogue-selector-only issue/error classes named above; leave all observation and general issue behavior unchanged.
- `src/rivretrieve/_internal/primitives.py` — delete only `CatalogSource`; retain `OnIssue`, `IssueSeverity`, and nominal IDs.
- `src/rivretrieve/_internal/provider_module.py` — remove `CatalogSource` and `source` from the three protocol methods.
- `src/rivretrieve/_internal/registry.py` — remove `CatalogSource` and `source` from internal catalogue methods and their reader calls; preserve `_ProviderHandle`, observation dispatch, provider extras, registration, and lookup.
- `src/rivretrieve/_internal/results.py` — replace the `CatalogSource` import/type with `Literal["packaged"]` for `CatalogProvenance.source`; change no other result fields.
- `src/rivretrieve/_internal/providers/ba_fhmzbih/module.py`
- `src/rivretrieve/_internal/providers/br_ana/module.py`
- `src/rivretrieve/_internal/providers/ca_eccc/module.py`
- `src/rivretrieve/_internal/providers/ch_foen/module.py`
- `src/rivretrieve/_internal/providers/cz_chmi/module.py`
- `src/rivretrieve/_internal/providers/fr_hubeau/module.py`
- `src/rivretrieve/_internal/providers/jp_mlit/module.py`
- `src/rivretrieve/_internal/providers/lt_lhmt/module.py`
- `src/rivretrieve/_internal/providers/no_nve/module.py`
- `src/rivretrieve/_internal/providers/pl_imgw/module.py`
- `src/rivretrieve/_internal/providers/th_thaiwater/module.py`
- `src/rivretrieve/_internal/providers/usgs_nwis/module.py`
- `src/rivretrieve/_internal/providers/za_dws/module.py`

For each of the thirteen provider modules, remove the `CatalogSource` import, remove and stop forwarding `source`, and otherwise preserve the module. In `ca_eccc/module.py`, also remove the two stale docstring examples that tell users to call `rr.provider(...)`; do not replace them with a new public cache API. Keep `cache_status()` and `refresh_cache()` as internal module functions. In `usgs_nwis/module.py`, do not alter observation-stage exports or `observation_source`.

### Source file to delete

- `src/rivretrieve/_internal/handle.py` — delete the public protocol completely.

### Test support and test files to modify

- `tests/_stubs/stub_provider.py` — remove `CatalogSource` and the three `source` parameters; preserve all stub data and behavior.
- `tests/test_ba_fhmzbih_module.py`
- `tests/test_ca_eccc_module.py`
- `tests/test_ca_eccc_observations.py`
- `tests/test_catalogue_only_br_ana_jp_mlit_no_nve_th_thaiwater.py`
- `tests/test_catalogue_only_ch_foen_cz_chmi_fr_hubeau_lt_lhmt.py`
- `tests/test_ch_foen_capabilities.py`
- `tests/test_discovery.py`
- `tests/test_internal_catalogue_reader.py`
- `tests/test_internal_issues.py`
- `tests/test_internal_registry.py`
- `tests/test_internal_results.py`
- `tests/test_m1_exit_criteria.py`
- `tests/test_map_stations.py`
- `tests/test_package.py`
- `tests/test_pl_imgw_module.py`
- `tests/test_provider_architecture_contracts.py`
- `tests/test_usgs_nwis_module.py`
- `tests/test_usgs_nwis_observations.py`
- `tests/test_za_dws_module.py`

### Test files to delete

- `tests/test_m2_exit_criteria.py` — its single exit-criteria test specifies the withdrawn handle, global tables, selector errors, and live catalogue routing.
- `tests/test_observations_wrapper.py` — all tests specify the deleted wrapper.
- `tests/test_provider_handle.py` — all tests specify the deleted public protocol and `provider()`.

### Untracked operational file

- `pr-body.md` at the worktree root — create it, leave it untracked, and never add it to the commit. Its complete content is in section 5.

## 4. Existing assertions affected

The executor must use the pinned tracked tests as the source for assertions not reproduced below. “Keep assertions unchanged” means change only the access path/setup needed after surface removal; retain every expected value and exact error string already present in that named function.

### Provider/module suites

- `tests/test_ba_fhmzbih_module.py`: in `test_ba_fhmzbih_stations_offline`, `test_ba_fhmzbih_products_offline`, `test_ba_fhmzbih_station_products_offline`, `test_ba_fhmzbih_info`, and `test_ba_fhmzbih_station_fields`, call `ba_fhmzbih_module.stations/products/station_products/info` directly and keep every assertion unchanged. In `test_ba_fhmzbih_observations_unavailable`, initialize defaults with `rr.providers()` and call `_registry.get("ba_fhmzbih").observations(...)`; keep the existing exact exception match. `test_ba_fhmzbih_in_providers_list`, `test_ba_fhmzbih_module_has_no_observations`, and `test_ba_fhmzbih_module_catalogue_path_exists` are untouched.
- `tests/test_ca_eccc_module.py`: delete `test_ca_eccc_provider_handle_returns`, `test_ca_eccc_global_stations_includes_provider`, and `test_ca_eccc_live_catalogue_returns_warning_issue`. Route `test_ca_eccc_info_name`, `test_ca_eccc_catalogue_version`, `test_ca_eccc_live_stations_capability`, all `stations/products/station_products` tests, and station/schema tests directly through `ca_eccc_module`; keep their assertions unchanged. In `test_ca_eccc_cache_lifecycle_remains_reachable`, call `ca_eccc_module.cache_status()` and `ca_eccc_module.refresh_cache()` and retain exact expected values `"cache-status"` and `["cache-refresh"]`. The providers-list and engine-stage-contract tests are untouched.
- `tests/test_ca_eccc_observations.py`: in all three functions—`test_ca_eccc_registry_dispatch_uses_engine_driver`, `test_ca_eccc_include_retains_exact_ordered_parse_inputs_and_query_origins`, and `test_ca_eccc_all_missing_preserves_issue_policy`—initialize default registration with `rr.providers()` and replace only `rr.provider("ca_eccc")` with `_registry.get("ca_eccc")`; retain every frame, provenance, raw payload, issue, request, and exception assertion unchanged.
- `tests/test_catalogue_only_br_ana_jp_mlit_no_nve_th_thaiwater.py`: in `test_catalogue_only_provider_remains_discoverable_and_readable`, obtain the provider module via the existing dynamic import, use its `info/stations/products/station_products`, keep provider registration and module catalogue assertions, use `rr.products(provider=provider_id)` for the public product list, and remove only the assertions over deleted global `rr.stations()` and `rr.provider_info()`. `test_catalogue_only_module_retains_only_catalogue_surface` stays unchanged. In `test_catalogue_only_provider_rejects_observation_retrieval`, initialize defaults and call `_registry.get(provider_id).observations(...)`, retaining the existing `ObservationsUnavailableError` text. Delete `test_catalogue_only_live_catalogue_behaviour_is_retained`. Route `test_no_nve_packaged_availability_examples_are_retained` and `test_jp_mlit_packaged_source_coordinates_are_adopted` through their provider modules and keep assertions unchanged. Reference-tree and fixture tests are untouched.
- `tests/test_catalogue_only_ch_foen_cz_chmi_fr_hubeau_lt_lhmt.py`: apply the same direct-module/public-`products()` rewrite in `test_catalogue_only_provider_remains_discoverable_and_readable`, removing only global station/provider-info assertions; leave `test_catalogue_only_module_retains_only_catalogue_surface` unchanged. Route `test_catalogue_only_provider_rejects_observation_retrieval` through the initialized `_registry.get(provider_id)` runtime and keep the exception assertion. Every README, reference-tree, origin, generator, and fixture assertion is untouched.
- `tests/test_ch_foen_capabilities.py`: keep `test_ch_foen_provider_info_capabilities_are_declared`, but call `ch_foen_module.info()` and retain exact field assertions (`False`, `False`, `False`, and `BULK_OBSERVATIONS_DESCRIPTION`). Delete the three `test_ch_foen_live_*_unsupported_uses_m2_routing` functions.
- `tests/test_pl_imgw_module.py`: call `pl_imgw_module.stations/products/station_products/info` in the catalogue/info tests and keep all expected counts, product IDs, artefact names, and bulk-observation text unchanged. Route `test_pl_imgw_observations_unavailable` through initialized `_registry.get("pl_imgw")` with its existing exception assertion. Delete `test_pl_imgw_handle_has_no_cache_controls`; `test_pl_imgw_module_has_no_observation_or_cache_surface` already proves the surviving internal module boundary and remains unchanged.
- `tests/test_usgs_nwis_module.py`: route catalogue/info calls through `usgs_nwis_module` and keep every expected count, product set, CRS, coordinate, path, provider info, and `observation_source == "live"` assertion unchanged. Providers-list, stage-contract, and catalogue-path tests remain otherwise untouched.
- `tests/test_usgs_nwis_observations.py`: in all five test functions, initialize defaults with `rr.providers()` and use `_registry.get("usgs_nwis").observations(...)`; preserve every request, frame, issue-policy, raw receipt, credential-redaction, provenance, and exact URL/parameter assertion unchanged.
- `tests/test_za_dws_module.py`: route catalogue/info calls through `za_dws_module`, keeping all counts, product IDs, station coordinates/ranges, CRS, and metadata assertions unchanged. Route `test_za_dws_observations_unavailable` through initialized `_registry.get("za_dws")`, retaining its exception assertion. Providers-list, no-observations, and catalogue-path tests are untouched.
- `tests/test_provider_architecture_contracts.py`: rename/adapt `test_cache_carve_out_handle_contracts_are_explicit` to test the internal modules directly: `ca_eccc_module.cache_status` and `.refresh_cache` are callable, while `pl_imgw_module` has neither attribute. Keep all other functions and assertions unchanged, especially `test_registry_uses_engine_stages_or_catalogue_only_registration`.

### Discovery, registry, reader, result, and package suites

- `tests/test_discovery.py`: delete `test_provider_returns_registered_placeholder_object`, `test_provider_unknown_raises_unknown_provider_error`, both `test_provider_info_*` functions, `test_provider_lookup_malformed_id_is_membership_miss`, both global-stations functions, `test_global_product_info_retains_independent_table_contract`, and `test_global_discovery_provenance_is_global_packaged`. Narrow `test_global_discovery_disabled_defaults_empty_registry_distinguishes_result_kinds` to exact assertions `products() == []` and `type(products()) is list`. Narrow `test_global_discovery_uses_reader_for_table_selection_and_validation` to `products()` only and exact calls `{"products": 1}`. Keep `test_providers_empty_registry_returns_default_providers`, `test_providers_sorted_independent_of_registration_order`, `test_global_products_returns_sorted_deduplicated_vocabulary`, `test_products_returns_exact_global_vocabulary_and_every_provider_subset`, `test_products_result_is_not_a_catalogue_or_dataframe`, and `test_products_unknown_provider_raises_loudly`; these are the explicit `products()` survival regressions, and all their existing expected values remain unchanged.
- `tests/test_internal_catalogue_reader.py`: keep `test_catalogue_reader_products_returns_packaged_catalog_result`, `test_catalogue_reader_stations_returns_packaged_catalog_result`, `test_catalogue_reader_station_products_returns_packaged_catalog_result`, all product-filter tests, all station-product filter tests, `test_catalogue_reader_non_string_filter_raises_direct_fatal`, and `test_reader_preserves_polars_schema_after_empty_filter` unchanged apart from signature fallout. In the three `test_catalogue_reader_packaged_*_unchanged_by_live_capability` functions, remove `source="packaged"`, rename them to say provider-info capability fields do not change packaged reads, and retain provenance/data/issues assertions. Delete `_expected_live_provenance`, the live-issue helper, all four invalid-source test functions, all nine unsupported-live warn/raise/ignore functions, all three live-capable routing-fatal functions, `test_catalogue_reader_invalid_source_ignores_capability_and_on_issue`, and `test_catalogue_reader_live_products_invalid_filter_remains_direct_fatal`. Remove their now-unused imports/fixtures.
- `tests/test_internal_issues.py`: delete `test_live_catalogue_unsupported_issue_constructs_provider_issue`, `test_live_catalogue_unsupported_issue_constructs_global_issue`, and `test_live_catalogue_routing_not_implemented_error_is_fatal_contract_error`; remove their imports. Every general issue, issue-policy, and fatal-contract assertion remains untouched.
- `tests/test_internal_registry.py`: remove the wrapper-only tail of `test_registry_passes_widened_fetch_window_and_preserves_requested_provenance` beginning with its `_provider_lookup` monkeypatch and `rr.observations(...)`; retain all direct runtime assertions. Rename the three `test_public_observations_*` functions to `test_registry_observations_*` and replace `rr.provider(...).observations` with `_registry.get(...).observations`; preserve their exact frames, issue lists, and error text. Rename the four `test_provider_handle_info/catalogue_*` functions to `test_registered_runtime_*`; the private `_ProviderHandle` survives, so retain their assertions and packaged provenance exactly. All registration, engine, validation, and unknown-registry lookup tests remain untouched.
- `tests/test_internal_results.py`: replace `test_catalog_source_accepts_packaged_and_live` with `test_catalog_provenance_accepts_packaged_source` asserting `CatalogProvenance(source="packaged").source == "packaged"`; change the rejection test to parameterize exact inputs `("live", "cached")` and assert both raise `pydantic.ValidationError` without matching unstable Pydantic prose; delete `test_catalog_provenance_live_roundtrip`; keep packaged provenance and `CatalogResult` round trips unchanged.
- `tests/test_m1_exit_criteria.py`: retain the single smoke function but replace the removed provider lookup/global provider-info assertions with `rr.products(provider="missing")` raising `UnknownProviderError` and exact `rr.products() == ["level"]`; retain exact `rr.providers() == ["a_provider", "z_provider"]`. Remove dead imports.
- `tests/test_package.py`: rename the public-surface test for m9 and assert the exact sorted `dir()` list in section 1, plus absence of the exact eight-name tuple in section 1. Keep identity assertions for `RawMode` and `to_utc`. In `test_deferred_public_names_remain_absent_after_provider_handle_promotion`, remove `import_module("rivretrieve._internal.handle")` from `affected_modules`; retain the remaining absence assertions. `test_version` and all packaged-catalogue carrier assertions—including `live_*` provider-info fields—remain untouched.
- Delete all assertions in the three test files listed under “Test files to delete”; they assert only withdrawn contracts.

### Mapping suite

- `tests/test_map_stations.py`: keep the first five `rr.map` tests and their exact assertions. Rename `test_map_signature_accepts_only_required_selection_without_narrowing` to `test_map_survives_map_stations_removal_with_only_required_selection`; this is the explicit survival regression. Delete the legacy `map_stations` signature/backend/filtering/catalogue-reader tests, the `_filter_stations` tests, and the `packaged_stations` fixture; remove imports used only by them.
- Preserve both real-folium tests and their `pytest.importorskip("folium")` guards so the network-disabled, no-folium baseline still reports exactly two skips. To remove the stale withdrawn call in `test_station_map_real_backend_returns_folium_map_for_selected_station`, replace only its setup/call with the exact selection in section 5 and retain all four existing assertions. `test_station_map_real_backend_renders_five_column_station_frame` and `_five_column_station_frame()` remain byte-for-byte unchanged. Do not install folium.

### Explicitly proven untouched

- `tests/test_fetch.py` is not in the write-set. All six tests remain unchanged; `_record_provider_lookups` continues proving that `fetch`/`fetch_by_provider` use the internal lookup seam, and the source binding changes from public `provider` to `_registry.get` beneath that seam.
- `tests/test_internal_provider_module.py` is not in the write-set. Its protocol-member and stub-conformance assertions remain valid because only method parameters narrow.
- `tests/test_internal_provider_info.py` is not in the write-set. All five functions remain unchanged and continue proving `live_stations`, `live_products`, and `live_station_products` parse and round-trip.
- `tests/test_internal_catalogue_schemas.py` is not in the write-set. `test_catalogue_schema_objects_define_expected_columns`, `test_catalogue_schema_objects_define_polars_dtypes`, and `test_provider_info_catalog_validates_row_shape` remain unchanged and continue proving the live capability fields remain in the committed schema.
- `tests/test_usgs_nwis_generate_catalogue.py` and `src/rivretrieve/_internal/providers/usgs_nwis/generate_catalogue.py` are not in the write-set, as detailed in section 2.4.
- `tests/test_pl_imgw_cache.py::test_refresh_cache_reports_parse_issues` (the existing assertion that issue messages do not contain `"rr.provider"`) is untouched: it is content validation, not a call to the deleted API.
- `tests/typecheck/nominal_window_misuse.py` is an intentional negative fixture asserted by `tests/test_internal_engine_contracts.py`; do not edit, repair, or suppress it.

## 5. Authored data

No data fixture is added or changed. No expected Parquet/JSON frame is authored. Existing provider frame assertions retain the exact tracked data at the pinned ref.

The complete newly authored expected public surface and removed-name tuple are exactly those in section 1. The complete canonical product expectations used by the explicit survival regression are:

```python
EXPECTED_PRODUCT_IDS = [
    "discharge_daily_max",
    "discharge_daily_mean",
    "discharge_hourly_mean",
    "discharge_instantaneous",
    "stage_daily_max",
    "stage_daily_mean",
    "stage_daily_min",
    "stage_hourly_mean",
    "stage_instantaneous",
    "water_temperature_daily_mean",
    "water_temperature_hourly_mean",
    "water_temperature_instantaneous",
]

EXPECTED_PRODUCTS_BY_PROVIDER = {
    "ba_fhmzbih": ["discharge_instantaneous", "stage_instantaneous", "water_temperature_instantaneous"],
    "br_ana": ["discharge_daily_mean", "discharge_instantaneous", "stage_daily_mean", "stage_instantaneous", "water_temperature_instantaneous"],
    "ca_eccc": ["discharge_daily_mean", "stage_daily_mean"],
    "ch_foen": ["discharge_instantaneous", "stage_instantaneous", "water_temperature_instantaneous"],
    "cz_chmi": ["discharge_daily_mean", "discharge_instantaneous", "stage_daily_mean", "stage_instantaneous", "water_temperature_daily_mean"],
    "fr_hubeau": ["discharge_daily_max", "discharge_daily_mean", "discharge_instantaneous", "stage_daily_max", "stage_instantaneous", "water_temperature_instantaneous"],
    "jp_mlit": ["discharge_daily_mean", "discharge_hourly_mean", "stage_daily_mean", "stage_hourly_mean"],
    "lt_lhmt": ["discharge_daily_mean", "stage_daily_mean"],
    "no_nve": ["discharge_daily_mean", "discharge_hourly_mean", "discharge_instantaneous", "stage_daily_mean", "stage_hourly_mean", "stage_instantaneous", "water_temperature_daily_mean", "water_temperature_hourly_mean", "water_temperature_instantaneous"],
    "pl_imgw": ["discharge_daily_mean", "stage_daily_mean", "water_temperature_daily_mean"],
    "th_thaiwater": ["discharge_instantaneous", "stage_instantaneous"],
    "usgs_nwis": ["discharge_daily_mean", "discharge_instantaneous", "stage_daily_max", "stage_daily_mean", "stage_daily_min", "stage_instantaneous"],
    "za_dws": ["discharge_daily_mean", "discharge_instantaneous", "stage_instantaneous"],
}
```

The adapted real-folium map test uses exactly:

```python
selection = rr.find(provider="ch_foen", station="2016")
station_map = rr.map(selection)

assert isinstance(station_map, folium.Map)
html = station_map.get_root().render()
assert "ch_foen" in html
assert "2016" in html
```

The packaged catalogue provenance source tests use exactly `"packaged"`. The rejected catalogue provenance source inputs are exactly `("live", "cached")`. No new exact error-message assertion is authored; existing exact exception messages retained by the rewritten tests must remain byte-for-byte as tracked.

The complete `pr-body.md` content is:

```markdown
## Summary

- retire ProviderHandle and the legacy provider, observation, global table, product-info, and map-stations surface
- make catalogue reads packaged-only and remove CatalogSource routing
- keep products, selection mapping, internal fetch dispatch, and independent USGS live maintenance behavior intact

## Validation

- uv sync
- uv run ruff format
- uv run ruff check --fix
- uv run ty check src
- uv run pytest
- uv build
- installed-wheel public-surface smoke check
```

## 6. Acceptance criteria

1. Active-source removal scan:

   ```bash
   git grep -n -E 'ProviderHandle|CatalogSource|def provider\(|def observations\(|def provider_info\(|def stations\(|def product_info\(|def map_stations\(' -- src tests
   ```

   Expected observation: no matches for `ProviderHandle`, `CatalogSource`, or the deleted top-level definitions. Provider-module/internal `stations()` definitions are intentionally still present, so inspect any `def stations(` matches and confirm they are only the packaged-only methods listed in section 2.3. There must be no active `source=` catalogue argument or branch. Historical matches under `reference/legacy_observations/` are outside this scoped command and intentionally retained.

2. Public source-tree test:

   ```bash
   uv run pytest tests/test_package.py tests/test_discovery.py tests/test_fetch.py tests/test_internal_registry.py tests/test_internal_catalogue_reader.py tests/test_map_stations.py
   ```

   Expected observation: all selected tests pass except the same two `pytest.importorskip("folium")` tests, which remain skipped because folium is not installed. The exact package list, removed-name absence, packaged-only reader, products survival, map survival, and internal fetch lookup are proven.

3. Provider/USGS focus:

   ```bash
   uv run pytest tests/test_ba_fhmzbih_module.py tests/test_ca_eccc_module.py tests/test_ca_eccc_observations.py tests/test_catalogue_only_br_ana_jp_mlit_no_nve_th_thaiwater.py tests/test_catalogue_only_ch_foen_cz_chmi_fr_hubeau_lt_lhmt.py tests/test_ch_foen_capabilities.py tests/test_pl_imgw_module.py tests/test_provider_architecture_contracts.py tests/test_usgs_nwis_module.py tests/test_usgs_nwis_observations.py tests/test_usgs_nwis_generate_catalogue.py tests/test_za_dws_module.py
   ```

   Expected observation: all pass; USGS observation provenance is still `"live"`, its generator live transport/CLI tests remain present, and provider catalogue tests read committed packaged artefacts without a selector.

4. Full suite gate expectation: `uv run pytest` passes with exactly `1654 + additions - deletions` collected outcomes as produced by the implemented test rewrite and exactly `2 skipped`; do not hard-code a new pass count before implementation. Any failure is introduced by this change because the pinned baseline is `1654 passed, 2 skipped`.

5. Build the wheel with the required final gate, then smoke the actual installed wheel without dependency resolution:

   ```bash
   uv pip install --python .venv/bin/python --reinstall --no-deps dist/rivretrieve-0.1.49-py3-none-any.whl
   .venv/bin/python -c 'import rivretrieve; expected=["RawMode","as_frame","fetch","fetch_by_provider","find","from_frame","map","pick","products","providers","to_utc"]; actual=[n for n in dir(rivretrieve) if not n.startswith("_")]; assert actual == expected, (actual, expected); removed=("ProviderHandle","CatalogSource","map_stations","observations","product_info","provider","provider_info","stations"); assert all(not hasattr(rivretrieve, n) for n in removed), removed'
   ```

   Expected observation: both commands exit 0 using the already-built exact-version wheel; no network resolution occurs. This reinstall happens only after all gates and does not change tracked files. If the wheel filename differs despite the required no-version-change policy, stop and diagnose rather than globbing an unrelated wheel.

6. Repository-state check:

   ```bash
   git status --short
   ```

   Expected observation before commit: only the tracked write-set above plus `?? pr-body.md`; no catalogue artifacts, `pyproject.toml`, `uv.lock`, ADRs, context, reference files, or contract `stated` fields changed. Expected observation after the one commit: only `?? pr-body.md` remains.

## 7. Gate commands

Run these verbatim, in this exact order, after implementation and before the commit:

```bash
uv sync
uv run ruff format
uv run ruff check --fix
uv run ty check src
uv run pytest
uv build
```

`uv run ruff format` rewrites files in place and exits 0 when it reformats; inspect the resulting diff. Do not substitute `ruff format --check`. The typecheck gate is deliberately scoped to `src`; never widen it to the intentional negative fixture under `tests/typecheck/`.

If a uv command fails with `Failed to initialize cache` or `Operation not permitted (os error 1)`, check that `~/.config/uv/uv.toml` still points `cache-dir` at the warm shared cache under `$TMPDIR`, that the cache was not purged, and that another `uv build` is not running concurrently. Concurrent uv builds were the common measured cause. Do not switch package managers.

## 8. Constraints and prohibitions

- Base every implementation read on commit `9725f16af881964903af9e556e96aa9e5c15a4ee`; the executor can read tracked files but cannot rely on this planning/vision directory at runtime.
- Do not edit anything under `reference/legacy_observations/`.
- Do not edit `CONTEXT.md` or add/edit an ADR: this step implements the already-ratified breaking surface and adds no new domain decision.
- Do not edit any field under `stated` in `.pce/repository-contract.json`.
- Do not edit `pyproject.toml` or `uv.lock`; they are tracked, synchronized, and no dependency changes are required.
- Do not change `__version__` (`0.1.49` at the pinned ref), schedule a version bump, or create a tag.
- Do not change RawMode publicness or add/remove `fetch`/`fetch_by_provider` `raw=` or `on_issue=` arguments.
- Do not remove or change the internal `_ProviderHandle`; only the public `ProviderHandle` protocol is deleted.
- Do not remove provider-info `live_stations`, `live_products`, or `live_station_products`, and do not edit or regenerate any of the thirteen packaged catalogue directories.
- Do not alter USGS `observation_source="live"`, `read_live_native_rows()`, `refresh_native_table_from_live()`, its `--live` maintenance route, or their tests.
- Do not install folium. Preserve the two pre-existing missing-folium skips and their `pytest.importorskip("folium")` guards; adapt only the stale withdrawn API call required for collection/runtime correctness.
- Do not add a bounding box API, `record_covers`, shipped `source="live"`, a coverage snapshot, harmonized name/river search, a chained query language, PyPI publication, documentation work, provider porting, or a decision about whether native tables ship in the wheel.
- Do not run network-backed catalogue refreshes. Catalogue reads and tests are packaged-only.
- Do not tolerate a red gate as historical: the pinned baseline is green, so diagnose and fix every regression caused by this change.

## 9. Executor policies

- Implement the complete step as one squash-ready change and make exactly one conventional commit, after every gate in section 7 succeeds.
- Use exact commit message:

  ```text
  refactor!: retire the legacy catalogue surface
  ```

- Create `pr-body.md` with the exact content in section 5 at the worktree root and leave it untracked. Never stage or commit it.
- After gates and the installed-wheel smoke check, inspect the diff and status, then commit the tracked write-set once. Do not make preparatory, fixup, or gate-result commits.
- Do not tag, push, publish, or create remote state.
- Do not add attribution, co-author, sign-off, generated-by, or other footers.
- The PR targets `pce/the-surface-is-three-verbs-and-a-selection/milestone-9` and is intended to be squash-merged as this single conventional commit.
