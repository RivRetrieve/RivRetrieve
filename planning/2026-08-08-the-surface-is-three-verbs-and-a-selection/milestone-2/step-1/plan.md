# m2-s1 implementation plan — immutable catalogue selections and discovery

Pinned implementation baseline: `4b16c5749817787b56f3ac54233c78529fb2a0ab`.

This plan is self-contained for a network-disabled, zero-context executor. Read implementation inputs from the pinned baseline with `git show 4b16c5749817787b56f3ac54233c78529fb2a0ab:<path>` before editing. The implementation worktree will not contain this planning directory. At the pinned ref, `docs/adr/0019-the-public-surface-is-functions-over-a-selection.md` and `docs/adr/0020-a-capability-that-evaporates-by-country-does-not-ship.md` are not tracked; do not depend on either file. The operative rules are stated below.

## 1. Objective

Add an immutable, method-free catalogue selection at `(provider_id, station_id, product_id)` series grain and expose `find()`, `pick()`, `as_frame()`, and `from_frame()` beside the existing `providers()`. Discovery must distinguish unknown vocabulary (raise atomically) from a valid but absent station-product edge (return an ordinary empty selection with a machine-readable reason), must treat `availability == "unknown"` as an edge and `availability == "unavailable"` as no edge, and must render and frame selections deterministically. Preserve every legacy public name for the later m9 deletion step and update the package's exact-name assertion in the same change.

## 2. Semantics to implement

### 2.1 Denotation and values

Put this denotation line verbatim in the new module docstring:

```text
selection discovery : PackagedCatalogue × Query → Selection[Series]
```

Use private, frozen, slotted dataclasses in `rivretrieve._internal.selection`:

```python
@dataclass(frozen=True, slots=True)
class _EmptyReason:
    code: Literal["no_catalogue_edge", "not_in_selection", "empty_frame"]
    provider_ids: tuple[str, ...]
    station_ids: tuple[str, ...]
    product_ids: tuple[str, ...]
    published_products: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Series:
    provider_id: str
    station_id: str
    product_id: str
    latitude: float
    longitude: float
    crs: str
    observed_property: str
    frequency: str
    statistic: str
    period_type: str
    period_anchor: str
    unit: str
    native_id: str | None
    availability: Literal["available", "unknown"]
    availability_reason: str | None
    start_date: date | None
    end_date: date | None
    last_catalogue_check: date


@dataclass(frozen=True, slots=True)
class _Selection:
    series: tuple[_Series, ...]
    empty_reason: _EmptyReason | None = None
```

`_Series` is the immutable carrier for one catalogue edge. `_Selection.series` is always sorted lexicographically by `(provider_id, station_id, product_id)` and contains no duplicate key. A non-empty selection must have `empty_reason is None`. An empty selection must have a non-`None` `_EmptyReason`. Tuples, frozen dataclasses, and frozen nested values make both the outer selection and every series row immutable. Do not add public methods or a chained query API. Dunder-only `__str__`/`__repr__` rendering is permitted and required below; callable names not beginning with `_` on an instance must be the empty set.

Do not export `_Selection`, `_Series`, `_EmptyReason`, `UnknownStationError`, or `UnknownProductError` from `rivretrieve.__init__`. The public values are constructed only by the four public functions.

### 2.2 Catalogue materialization and edge rule

Build the selectable series table only from already-registered packaged catalogue artifacts. Ensure default providers are registered using the existing composition-root registration path before reading `_registry.iter_records()`. Do not read environment variables, resolve new literal catalogue paths, open live sources, or add network access.

For each provider, inner-join:

- `artifact.station_products` to `artifact.stations` on `("provider_id", "station_id")`;
- that result to `artifact.products` on `("provider_id", "product_id")`.

Select the exact frame columns, types, and order in section 5.1, then sort by `provider_id`, `station_id`, `product_id`.

The load-bearing edge rule is:

```text
A catalogue edge exists for a station_products row if and only if availability is not "unavailable".
"available" is an edge.
"unknown" is an edge.
"unavailable" is not an edge and therefore cannot occur in _Series or as_frame() output.
```

Do not rewrite `unknown` to `available`, fill an availability reason, or otherwise interpret source judgement. `STATION_PRODUCT_CATALOG_SCHEMA` defines the three-valued enum `("available", "unavailable", "unknown")` and its unique key is `("provider_id", "station_id", "product_id")`. The measured packaged totals are exactly 326,574 station-product rows: 72,769 `available`, 128,780 `unavailable`, and 125,025 `unknown`.

### 2.3 Public signatures

Implement these signatures. `SelectionInput` below means `str | Sequence[str]`; normalize a string as one identifier, not as a sequence of characters, preserve request order while validating, and store/sort resulting identifiers deterministically.

```python
def find(
    *,
    provider: str | None = None,
    station: str | None = None,
    product: str | None = None,
) -> _Selection: ...


def pick(
    selection: _Selection,
    *,
    provider: str | Sequence[str] | None = None,
    station: str | Sequence[str] | None = None,
    product: str | Sequence[str] | None = None,
) -> _Selection: ...


def as_frame(selection: _Selection) -> pl.DataFrame: ...


def from_frame(frame: pl.DataFrame) -> _Selection: ...
```

No signature may accept `source`, `live`, `bbox`, a bounding box under another spelling, `record_covers`, start/end or any record-window argument, a predicate/callback, or a chained-query object. Do not change the existing `providers() -> list[str]` signature or behavior.

### 2.4 Vocabulary and error classification

Vocabulary is read from the complete registered packaged catalogue, never inferred from the current selection rows:

- Provider vocabulary is the exact set returned by the existing `_registry.list_provider_ids()` after default registration.
- Canonical product vocabulary is the union of every `artifact.products["product_id"]`, independent of provider. At the pinned ref it is exactly:

```python
(
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
)
```

- Station identity is `(provider_id, station_id)`. If a provider filter is present, each requested station is valid if it exists for at least one requested provider. If there is exactly one requested provider, this is ordinary provider-scoped validation. If no provider filter is present, a station is valid if it exists under at least one provider. Never collapse two provider-station identities merely because their bare station strings match.

Use the existing `UnknownProviderError` for an unknown provider. Add private exception classes derived from `FatalContractError` for unknown canonical products and provider-scoped stations. Their exact messages are:

```text
Provider is not registered: missing_provider
Canonical product is not registered: 'stage_daily_mea'
Station is not registered for provider 'usgs_nwis': '0164650'
Station is not registered: 'does-not-exist'
```

For multiple requested providers, an invalid station message must list the normalized providers in sorted order:

```text
Station is not registered for providers ('fr_hubeau', 'usgs_nwis'): 'does-not-exist'
```

Validate in deterministic category order: providers, products, stations. Within a category, validate in caller order and raise for the first invalid identifier. Validate the complete request before filtering or constructing a result. Therefore any invalid identifier in a list fails the whole `pick()` call and no partial selection is returned.

Do not perform fuzzy correction, case folding, whitespace stripping, identifier normalization, or automatic substitution. A near miss such as `0164650` raises the exact station error above and never returns the `01646500` selection. A raised error may eventually contain a suggestion, but this step does not add one.

`find()` is total over valid vocabulary and uses the same validation pipeline regardless of whether one, two, or three filters are supplied. In particular, the invalid canonical product `stage_daily_mea` raises `UnknownProductError` with the exact same text for all three calls:

```python
find(product="stage_daily_mea")
find(provider="usgs_nwis", product="stage_daily_mea")
find(provider="usgs_nwis", station="01646500", product="stage_daily_mea")
```

A canonical product that a named provider does not publish is still valid vocabulary and yields an empty selection; it is not an unknown-product error. Likewise, valid provider, station, and product identifiers whose intersection has no non-`unavailable` edge yield an empty selection.

### 2.5 `find()` behavior

After atomic vocabulary validation, conjunctively filter the complete edge table by each supplied scalar. `find()` with no filters returns all non-`unavailable` edges. Provider-only, product-only, station-only, provider/product, provider/station, and the full triple all use the same table and classification rules.

For a non-empty result, return sorted `_Series` rows with `empty_reason=None`. For an empty result return:

```python
_EmptyReason(
    code="no_catalogue_edge",
    provider_ids=(provider,) if provider is not None else (),
    station_ids=(station,) if station is not None else (),
    product_ids=(product,) if product is not None else (),
    published_products=<value below>,
)
```

If both provider and station were supplied, `published_products` is the sorted tuple of product IDs for that provider-station whose availability is not `unavailable`, even when the requested product is absent. Otherwise it is `()`.

The catalogue-true required case is exactly:

```python
find(provider="usgs_nwis", station="01646500", product="stage_daily_mean")
```

It returns `series == ()` and:

```python
_EmptyReason(
    code="no_catalogue_edge",
    provider_ids=("usgs_nwis",),
    station_ids=("01646500",),
    product_ids=("stage_daily_mean",),
    published_products=(
        "discharge_daily_mean",
        "discharge_instantaneous",
        "stage_instantaneous",
    ),
)
```

At the pinned ref the station's `stage_daily_mean` row exists but is exactly `availability == "unavailable"` with `availability_reason == "No matching USGS source series was published for this station-product"`; it is therefore an absent edge. The same station has exactly the three non-`unavailable` products enumerated above.

Nationality-blind edge behavior is required:

- `find(provider="cz_chmi", product="discharge_daily_mean")` returns exactly 831 rows; every row has `availability == "unknown"` and none is `available`.
- `find(provider="usgs_nwis", product="discharge_daily_mean")` returns exactly 24,447 rows; these are the available rows. The 1,811 `unavailable` USGS rows are excluded.

Bare station ID `01010000` exists under both `fr_hubeau` and `usgs_nwis`. `find(station="01010000")` must retain rows for both provider identities. `find(provider="fr_hubeau", station="01010000")` must retain only `fr_hubeau`; `find(provider="usgs_nwis", station="01010000")` must retain only `usgs_nwis`. The exact non-`unavailable` keys are:

```python
(
    ("fr_hubeau", "01010000", "water_temperature_instantaneous"),
    ("usgs_nwis", "01010000", "discharge_daily_mean"),
    ("usgs_nwis", "01010000", "discharge_instantaneous"),
    ("usgs_nwis", "01010000", "stage_instantaneous"),
)
```

### 2.6 `pick()` behavior

First require `selection` to be `_Selection`; raise `TypeError("selection must be a RivRetrieve selection")` for any other object. Validate every supplied name against the complete catalogue vocabulary rules in section 2.4, not against `selection.series`. Only after all vocabulary is valid, conjunctively filter the input rows.

For a non-empty result, return sorted rows and `empty_reason=None`. If the input selection is already empty, all requested vocabulary is valid, and filtering cannot add rows, return an empty selection carrying the input's existing `_EmptyReason` unchanged. If the input is non-empty but valid filters remove every row, return:

```python
_EmptyReason(
    code="not_in_selection",
    provider_ids=<sorted normalized provider filter or ()>,
    station_ids=<sorted normalized station filter or ()>,
    product_ids=<sorted normalized product filter or ()>,
    published_products=(),
)
```

Required real-but-absent behavior:

```python
base = find(provider="usgs_nwis", product="stage_daily_mean")
result = pick(base, station="01646500")
```

Station `01646500` is real in the full USGS station catalogue, so this must not raise `UnknownStationError`. It returns `series == ()` and exactly:

```python
_EmptyReason(
    code="not_in_selection",
    provider_ids=(),
    station_ids=("01646500",),
    product_ids=(),
    published_products=(),
)
```

Atomic list rejection must be tested with these complete inputs and exact errors; in every case no selection is returned and `base` remains byte-for-byte/equality unchanged:

```python
base = find(provider="usgs_nwis")

pick(base, provider=["usgs_nwis", "missing_provider"])
# UnknownProviderError: Provider is not registered: missing_provider

pick(base, product=["discharge_daily_mean", "stage_daily_mea"])
# UnknownProductError: Canonical product is not registered: 'stage_daily_mea'

pick(base, provider="usgs_nwis", station=["01646500", "0164650"])
# UnknownStationError: Station is not registered for provider 'usgs_nwis': '0164650'
```

### 2.7 `as_frame()` and `from_frame()`

`as_frame()` requires `_Selection`, otherwise raises `TypeError("selection must be a RivRetrieve selection")`. It creates a new Polars `DataFrame` on every call, with the exact schema in section 5.1, row order `(provider_id, station_id, product_id)`, and values copied from the immutable rows. Mutating the returned frame must not mutate the selection. An empty selection returns a zero-row frame with that full schema; the machine-readable reason remains on the selection and is not represented by a sentinel row.

`from_frame()` requires a Polars `DataFrame`, otherwise raises `TypeError("frame must be a polars.DataFrame")`. It requires at least these three columns in this order and with exact `pl.Utf8` dtypes:

```python
("provider_id", "station_id", "product_id")
```

Extra columns are permitted and ignored when selecting identity, which allows a caller to filter `as_frame(selection)` in Polars without manually dropping metadata. Missing key columns raise exactly:

```text
Selection frame is missing required columns: provider_id, station_id, product_id
```

List only the actually missing names, in the canonical order above. A null key raises exactly:

```text
Selection frame contains null identity values
```

A duplicate triple raises exactly:

```text
Selection frame contains duplicate series keys: provider_id, station_id, product_id
```

Validate every key atomically against the full catalogue using the same provider/product/provider-scoped-station vocabulary rules. Then require each triple to be a real non-`unavailable` edge. A valid triple with no edge raises exactly:

```text
Selection frame contains no catalogue edge: ('usgs_nwis', '01646500', 'stage_daily_mean')
```

Do not trust or preserve caller-supplied metadata columns; rebuild the full `_Series` rows from the packaged catalogue by key. Thus `from_frame(as_frame(selection)) == selection` for every non-empty selection. A zero-row input returns:

```python
_Selection(
    series=(),
    empty_reason=_EmptyReason(
        code="empty_frame",
        provider_ids=(),
        station_ids=(),
        product_ids=(),
        published_products=(),
    ),
)
```

### 2.8 Deterministic text rendering

`str(selection)` and `repr(selection)` must be identical. Render only the immutable series keys, not Polars' terminal-width-dependent formatting. For a non-empty selection the exact shape is a header followed by sorted rows, separated by ` | `, with no trailing blank line. For the required one-row selection:

```text
provider_id | station_id | product_id
usgs_nwis | 01646500 | discharge_daily_mean
```

For the required empty USGS selection in section 2.5, the exact output is:

```text
provider_id | station_id | product_id
<empty>
empty_reason.code=no_catalogue_edge
empty_reason.provider_ids=usgs_nwis
empty_reason.station_ids=01646500
empty_reason.product_ids=stage_daily_mean
empty_reason.published_products=discharge_daily_mean,discharge_instantaneous,stage_instantaneous
```

For an empty tuple-valued reason field, render the value after `=` as the empty string. This keeps the reason machine-readable on `.empty_reason` and human-visible in deterministic printing.

## 3. Write-set

This is the complete write-set. Do not create or modify any other file.

1. `src/rivretrieve/_internal/selection.py` — create. Define the denotation docstring, private immutable carriers, private errors, catalogue materialization, vocabulary validation, edge filtering, public function implementations, exact frame schema, and deterministic rendering described above.
2. `src/rivretrieve/_internal/discovery.py` — modify. Add thin public composition-root wrappers or imports for `find`, `pick`, `as_frame`, and `from_frame` that use the existing `_ensure_default_providers_registered()` and `_registry`; keep every existing function, signature, registration branch, and result unchanged. The selection module may receive the tuple of already-registered records as a narrow argument to avoid importing the composition root and creating a circular import.
3. `src/rivretrieve/__init__.py` — modify. Re-export exactly `find`, `pick`, `as_frame`, and `from_frame` using the repository's explicit `from ... import name as name` pattern. Preserve all ten existing non-private names and keep `__version__ = "0.1.49"` unchanged.
4. `tests/test_selection.py` — create. Add all tests named in section 5.3 using only committed packaged catalogues and inline expected values quoted in this plan. Do not create a fixture file and do not perform network access.
5. `tests/test_package.py` — modify only `test_init_public_surface_exports_m2_provider_handle_surface`, extending its exact expected set by `"as_frame"`, `"find"`, `"from_frame"`, and `"pick"`. Do not change the version test, deferred-name test, or catalogue-artifact assertions.
6. `pr-body.md` — create at the worktree root only after all gates pass. Use the exact contents in section 9. Keep it untracked and do not include it in the commit.

No dependency, generated catalogue, Parquet artifact, external fixture, snapshot, lockfile, version file, glossary, ADR, README, user documentation, vision artifact, graph, or review artifact belongs in this write-set.

## 4. Existing assertions affected

### Updated

- `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface` is the only existing exact-public-name assertion. Replace its expected set with exactly:

```python
{
    "ProviderHandle",
    "RawMode",
    "as_frame",
    "find",
    "from_frame",
    "map_stations",
    "observations",
    "pick",
    "product_info",
    "products",
    "provider",
    "provider_info",
    "providers",
    "stations",
}
```

### Explicitly proven untouched

At the pinned ref, `git grep` finds no existing `find`, `pick`, `as_frame`, `from_frame`, `UnknownStationError`, or selection assertion in `src` or `tests`. The only `vars(rivretrieve)`/`dir(rivretrieve)` exact public-name equality is the test above. Preserve these named assertions without editing them:

- `tests/test_package.py::test_version`: no version bump; both package version declarations remain `0.1.49`.
- `tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion`: `_Selection`, `_Series`, `_EmptyReason`, `UnknownStationError`, and `UnknownProductError` remain private and all names already listed as deferred/removed remain absent.
- `tests/test_discovery.py::test_providers_empty_registry_returns_default_providers` and `tests/test_discovery.py::test_providers_sorted_independent_of_registration_order`: `providers()` is already implemented and exported and must not change.
- `tests/test_m1_exit_criteria.py::test_m1_exit_criteria_smoke_sweep` and `tests/test_m2_exit_criteria.py::test_m2_exit_criteria_public_surface_sweep`: the existing provider registry, `provider()`, `ProviderHandle`, catalogue accessors, and their results remain available and unchanged until m9.
- `tests/test_ba_fhmzbih_module.py::test_ba_fhmzbih_in_providers_list`, `tests/test_ca_eccc_module.py::test_ca_eccc_in_providers_list`, `tests/test_pl_imgw_module.py::test_pl_imgw_registered_with_packaged_stations`, `tests/test_usgs_nwis_module.py::test_usgs_nwis_in_providers_list`, and `tests/test_za_dws_module.py::test_za_dws_in_providers_list`: default registration is reused, not replaced.
- `tests/test_catalogue_only_br_ana_jp_mlit_no_nve_th_thaiwater.py::test_catalogue_only_provider_remains_discoverable_and_readable` and `tests/test_catalogue_only_ch_foen_cz_chmi_fr_hubeau_lt_lhmt.py::test_catalogue_only_provider_remains_discoverable_and_readable`: legacy handle discovery remains intact.
- `tests/test_internal_catalogue_origins.py::test_origin_gate_enrols_exactly_the_eleven_in_scope_providers` and `tests/test_provider_architecture_contracts.py::test_registry_uses_engine_stages_or_catalogue_only_registration`: do not change the registered provider population or provider architecture.
- `tests/test_discovery.py::test_global_discovery_uses_reader_for_table_selection_and_validation`: existing `stations()`, `products()`, and `product_info()` continue using `CatalogueReader` exactly as before. The new selection path may read already-validated packaged artifact frames but must not alter this test's expected call count `{"stations": 1, "products": 2}`.

No existing assertion requires a catalogue artifact or fixture update because this step reads the current artifacts without changing their schema or contents.

## 5. Authored data

### 5.1 Exact selection frame shape

Define the exact `pl.Schema` below. This is the complete authored frame shape at the pinned ref; do not add an empty-reason column or sentinel row.

```python
pl.Schema(
    {
        "provider_id": pl.Utf8,
        "station_id": pl.Utf8,
        "product_id": pl.Utf8,
        "latitude": pl.Float64,
        "longitude": pl.Float64,
        "crs": pl.Utf8,
        "observed_property": pl.Utf8,
        "frequency": pl.Utf8,
        "statistic": pl.Utf8,
        "period_type": pl.Utf8,
        "period_anchor": pl.Utf8,
        "unit": pl.Utf8,
        "native_id": pl.Utf8,
        "availability": pl.Enum(["available", "unknown"]),
        "availability_reason": pl.Utf8,
        "start_date": pl.Date,
        "end_date": pl.Date,
        "last_catalogue_check": pl.Date,
    }
)
```

Nullable values are represented by Polars nulls; the schema's dtype remains the declared dtype. Do not rename `start_date` or `end_date` in this step.

### 5.2 Exact one-row frame used for frame/rendering acceptance

The complete expected frame for `find(provider="usgs_nwis", station="01646500", product="discharge_daily_mean")` is:

```python
pl.DataFrame(
    [
        {
            "provider_id": "usgs_nwis",
            "station_id": "01646500",
            "product_id": "discharge_daily_mean",
            "latitude": 38.94977778,
            "longitude": -77.12763889,
            "crs": "EPSG:4269",
            "observed_property": "discharge",
            "frequency": "daily",
            "statistic": "mean",
            "period_type": "interval",
            "period_anchor": "start",
            "unit": "m3/s",
            "native_id": "00060:00003",
            "availability": "available",
            "availability_reason": None,
            "start_date": date(1930, 3, 1),
            "end_date": date(2026, 7, 31),
            "last_catalogue_check": date(2026, 8, 2),
        }
    ],
    schema=SELECTION_FRAME_SCHEMA,
)
```

Use `polars.testing.assert_frame_equal(actual, expected, check_exact=True)`.

### 5.3 Required tests and exact assertions

Create `tests/test_selection.py` with these tests. Names and expected values are part of the plan; do not substitute generic fixtures or approximate counts.

1. `test_selection_is_immutable_method_free_and_series_grained`
   - Construct `selection = rr.find(provider="usgs_nwis", station="01646500")`.
   - Assert exact keys:

```python
(
    ("usgs_nwis", "01646500", "discharge_daily_mean"),
    ("usgs_nwis", "01646500", "discharge_instantaneous"),
    ("usgs_nwis", "01646500", "stage_instantaneous"),
)
```

   - Assert attempting to assign `selection.series = ()` and attempting to assign `selection.series[0].product_id = "stage_daily_mean"` each raises `dataclasses.FrozenInstanceError`.
   - Assert `{name for name in dir(selection) if not name.startswith("_") and callable(getattr(selection, name))} == set()`.

2. `test_find_validates_unknown_vocabulary_independent_of_argument_count`
   - Call each of the three `stage_daily_mea` examples in section 2.4.
   - Each raises `UnknownProductError` and `str(exc) == "Canonical product is not registered: 'stage_daily_mea'"`.

3. `test_find_near_miss_station_raises_without_correction`
   - `rr.find(provider="usgs_nwis", station="0164650")` raises `UnknownStationError` with exact text `"Station is not registered for provider 'usgs_nwis': '0164650'"`.
   - Do not call `find` with `01646500` inside the exception branch and do not accept a returned selection.

4. `test_find_unavailable_edge_returns_reason_listing_published_products`
   - Use the exact `stage_daily_mean` call and exact `_EmptyReason` field values from section 2.5.
   - Assert `rr.as_frame(selection).height == 0`, `rr.as_frame(selection).schema == SELECTION_FRAME_SCHEMA`, and exact empty text from section 2.8.

5. `test_find_includes_unknown_edges_for_czech_and_excludes_unavailable_usgs_rows`
   - Czech expected height is `831`; availability values are exactly `["unknown"]` after unique/sort/cast-to-string.
   - USGS expected height is `24_447`; availability values are exactly `["available"]`.
   - Assert both are non-empty.

6. `test_find_scopes_duplicate_bare_station_ids_by_provider`
   - Assert the unscoped exact four-key tuple and the two provider-scoped subsets from section 2.5.
   - French subset is exactly `(("fr_hubeau", "01010000", "water_temperature_instantaneous"),)`.
   - USGS subset is exactly:

```python
(
    ("usgs_nwis", "01010000", "discharge_daily_mean"),
    ("usgs_nwis", "01010000", "discharge_instantaneous"),
    ("usgs_nwis", "01010000", "stage_instantaneous"),
)
```

7. `test_pick_validates_catalogue_scope_not_input_rows`
   - Use the exact `base` and `result` from section 2.6.
   - Assert the base is non-empty, result is empty, result's exact `_EmptyReason` fields match section 2.6, and no exception is raised.

8. `test_pick_preserves_an_existing_empty_reason`
   - Build the empty `find()` result from section 2.5, call `pick(selection, provider="usgs_nwis")`, and assert `picked.empty_reason is selection.empty_reason` and `str(picked) == str(selection)`.

9. `test_pick_rejects_vocabulary_lists_atomically`
   - Parameterize the three complete calls and exact exception texts from section 2.6.
   - Save `before = base`; after each raise assert `base == before` and its key tuple is unchanged.

10. `test_as_frame_is_deterministic_and_from_frame_round_trips`
    - Use the exact one-row selection and exact frame in section 5.2.
    - Assert two `as_frame()` calls are exact-frame-equal, each equals the expected frame, their Python identities differ, `rr.from_frame(actual) == selection`, and `str(selection)` is the exact non-empty text in section 2.8.
    - Mutate/drop a column from the returned frame into a new Polars value and assert a fresh `rr.as_frame(selection)` still equals the exact expected frame.

11. `test_from_frame_parses_identity_and_rebuilds_catalogue_metadata`
    - Pass a one-row frame containing exactly `provider_id="usgs_nwis"`, `station_id="01646500"`, `product_id="discharge_daily_mean"`, plus a caller-supplied extra column `ignored="caller value"`.
    - Assert `rr.as_frame(rr.from_frame(frame))` equals the exact frame in section 5.2 and has no `ignored` column.

12. `test_from_frame_rejects_malformed_or_absent_edges`
    - Missing all identity columns raises `FatalContractError` with exact text `"Selection frame is missing required columns: provider_id, station_id, product_id"`.
    - A duplicate of the valid one-row identity raises exact text `"Selection frame contains duplicate series keys: provider_id, station_id, product_id"`.
    - The identity `("usgs_nwis", "01646500", "stage_daily_mean")` raises exact text `"Selection frame contains no catalogue edge: ('usgs_nwis', '01646500', 'stage_daily_mean')"`.
    - A zero-row frame with the three exact UTF-8 identity columns yields the exact `empty_frame` reason from section 2.7.

13. `test_selection_function_signatures_exclude_unshipped_capabilities`
    - `inspect.signature(rr.find).parameters` is exactly `("provider", "station", "product")`, and all three are keyword-only with default `None`.
    - `inspect.signature(rr.pick).parameters` is exactly `("selection", "provider", "station", "product")`; `selection` is positional-or-keyword with no default and the other three are keyword-only with default `None`.
    - `inspect.signature(rr.as_frame).parameters` is exactly `("selection",)`.
    - `inspect.signature(rr.from_frame).parameters` is exactly `("frame",)`.
    - Across all four parameter sets, assert these names are absent exactly: `{"source", "live", "bbox", "bounding_box", "record_covers", "start", "end", "window", "query", "predicate"}`.

### 5.4 No fixtures

No test fixture file is authored. All acceptance rows above come from committed packaged Parquet catalogues at the pinned ref, and all constructed frames are quoted in full in sections 5.1–5.3. Do not add or regenerate any file under `tests/test_data/` or `src/rivretrieve/_internal/providers/*/catalogue/`.

## 6. Acceptance criteria

Run these focused checks while implementing, before the ordered gates. They are not substitutes for the full gates.

1. Command:

```bash
uv run pytest tests/test_selection.py -q
```

Expected observation: exits 0. The thirteen named tests in section 5.3 pass, including all three cases of the atomic-list parameterization. There is no network access.

2. Command:

```bash
uv run pytest tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion -q
```

Expected observation: exits 0. The public set is exactly the fourteen names in section 4; the legacy names remain present and internal selection/error classes remain absent.

3. Command:

```bash
uv run python - <<'PY'
import rivretrieve as rr

empty = rr.find(provider="usgs_nwis", station="01646500", product="stage_daily_mean")
print(len(empty.series))
print(empty.empty_reason.code)
print(empty.empty_reason.published_products)
print(rr.find(provider="cz_chmi", product="discharge_daily_mean").series.__len__())
print(rr.find(provider="usgs_nwis", product="discharge_daily_mean").series.__len__())
PY
```

Expected stdout exactly:

```text
0
no_catalogue_edge
('discharge_daily_mean', 'discharge_instantaneous', 'stage_instantaneous')
831
24447
```

4. Command:

```bash
git diff --check
```

Expected observation: exits 0 with no output.

5. Command after the commit:

```bash
git status --short
```

Expected observation: exactly `?? pr-body.md`; all implementation and test files are committed, and no other tracked or untracked file was created by this step.

## 7. Gate commands

Run the following commands verbatim, in this exact order, before creating the commit. Do not skip, reorder, combine, or substitute a whole-project typecheck:

```bash
uv sync
uv run ruff format
uv run ruff check --fix
uv run ty check src
uv run pytest
uv build
```

Expected observations:

- `uv sync` exits 0 and reports no `pyproject.toml`/`uv.lock` synchronization change.
- `uv run ruff format` exits 0; inspect `git diff` afterwards because this command rewrites files.
- `uv run ruff check --fix` exits 0 with no unresolved lint findings; inspect fixes before continuing.
- `uv run ty check src` exits 0 with no type errors.
- `uv run pytest` exits 0 with the baseline's 1,622 passing and 2 skipped tests plus every newly authored test/parameter case; no pre-existing failure is tolerated.
- `uv build` exits 0 and produces both source and wheel distributions. Build artifacts are not committed.

## 8. Constraints and prohibitions

### Established repository facts

- `providers()` already exists at `src/rivretrieve/_internal/discovery.py:32` at the pinned ref and is already exported. Preserve its implementation and return shape.
- None of `find`, `pick`, `as_frame`, `from_frame`, or `UnknownStationError` exists at the pinned ref. There is no legacy collision.
- Preserve every legacy public name for m9: `ProviderHandle`, `RawMode`, `map_stations`, `observations`, `product_info`, `products`, `provider`, `provider_info`, `providers`, and `stations`.
- `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface` is an exact-set assertion and must be updated in this commit.
- The default-branch baseline is fully green: 1,622 passed, 2 skipped.

### Not-touched scope fence

Do not touch or implement any of the following:

- no deletion or behavior change to `ProviderHandle`, `provider()`, `observations()`, `stations()`, `products()`, `provider_info()`, `product_info()`, `map_stations()`, or `RawMode`;
- no bounding-box or coordinate filter;
- no `record_covers`, start/end coverage, or other record-window filter;
- no public or shipped `source="live"` capability and no live catalogue request;
- no coverage snapshot;
- no harmonized station-name or river-name search;
- no chained query language, selection methods, query objects, callbacks, or fuzzy correction;
- no `fetch`, `fetch_by_provider`, `source_metadata`, `map`, or `to_utc`; those belong to other milestones;
- no observation schema/result/provenance change;
- no provider porting;
- no catalogue schema rename and no decision about whether native tables ship in wheels;
- no catalogue regeneration or packaged Parquet/JSON edits;
- no PyPI publication;
- no README, user-documentation, glossary, ADR, vision, milestone graph, step graph, or review-artifact edits;
- no dependency change, `pyproject.toml` edit, or `uv.lock` edit;
- no version bump and no tag;
- do not edit any field under `stated` in `.pce/repository-contract.json`.

### Binding environment hazards — quote and follow verbatim

1. "uv opens ~/.cache/uv/sdists-v9/.git for write on EVERY invocation, so no uv command can run under a sandbox that denies writes there. pce measures stated gates under a Seatbelt profile whose only writable roots are the repository root and the platform temporary directory, and the codex sandbox allows workdir, /tmp and $TMPDIR; neither allows ~/.cache. The machine therefore carries ~/.config/uv/uv.toml setting cache-dir to a warm shared cache under $TMPDIR, which both sandboxes permit. Measured: all five stated gates green in a cold fresh worktree with network denied. If a gate fails with 'Failed to initialize cache' / 'Operation not permitted (os error 1)', that config is missing or the temp cache was purged; recreate it and re-warm with uv sync --reinstall outside any sandbox. Do not point cache-dir inside the repository: uv warns it may be included in distributions and every fresh worktree starts cold with no network."
2. "Mutation testing must set PYTHONDONTWRITEBYTECODE=1 and pytest -p no:cacheprovider: same-size edits written within one mtime second collide under CPython (mtime, size) pyc invalidation and produce a false killed result."
3. "A full-suite run inside a git archive extraction shows a spurious extra failure in tests/test_ch_foen_generate_catalogue.py because that test shells out to git show HEAD: and an extraction is not a repository."
4. "The default-branch gate baseline is fully green as of the commit that introduced this file, and pce contract check aborts on the first red gate. Any red gate an executor observes is therefore caused by its own change and must be fixed, not tolerated against a historical baseline. The previous run's red baseline (a B905 at br_ana/generate_catalogue.py:507, an invalid-argument-type at br_ana/generate_catalogue.py:623, and an unresolved-import of tqdm at jp_mlit/generate_catalogue.py:202) was closed in that same commit; tqdm is now a declared dev dependency, so the deliberately-optional import at jp_mlit/generate_catalogue.py:202 resolves for ty while its try/except ImportError still governs runtime."
5. "tests/typecheck/nominal_window_misuse.py is an INTENTIONAL negative type-check fixture asserted by tests/test_internal_engine_contracts.py. It is excluded from the stated typecheck gate because that gate is scoped to src. Whole-project uv run ty check therefore reports it and must never be used as the gate. Never repair or suppress that fixture."
6. "uv run ruff format is the stated format gate and rewrites files in place rather than reporting; it exits 0 even when it reformats. Use uv run ruff format --check to observe drift without mutating the tree."

Binding gate ordering:

1. "uv sync before format before lint before typecheck before test; uv build last"

Binding lockfile rule:

1. "uv.lock is tracked and must stay synchronized with pyproject.toml; uv sync reports 0 changes at this baseline"

## 9. Executor policies

1. Work on the step branch targeting `pce/the-surface-is-three-verbs-and-a-selection/milestone-2` and produce exactly one squash-mergeable conventional commit.
2. Run every gate in section 7 before committing. If any gate is red, fix the change and rerun from the first gate; do not commit a red result.
3. Use exactly this conventional commit subject and add no body/footer unless the repository tooling requires a body:

```text
feat: add immutable catalogue selections
```

4. After the gates pass, create `pr-body.md` at the worktree root with exactly:

```markdown
## Summary

- add immutable catalogue selections at provider/station/product series grain
- add total `find` and catalogue-scoped `pick` discovery with reason-carrying empty results
- add deterministic Polars conversion through `as_frame` and `from_frame`
- preserve the legacy public surface while exporting the four new functions

## Validation

- `uv sync`
- `uv run ruff format`
- `uv run ruff check --fix`
- `uv run ty check src`
- `uv run pytest`
- `uv build`
```

5. Leave `pr-body.md` untracked. Do not stage or commit it.
6. Create no tag. Do not push. Add no attribution, `Co-authored-by`, `Signed-off-by`, or other footer.
7. Do not edit any field under `stated` in `.pce/repository-contract.json`.
8. Version policy is `NONE`: keep version `0.1.49`, make no version commit, and create no tag.
9. Before handoff, verify the commit contains only the five tracked paths in section 3 and that `git status --short` contains only `?? pr-body.md`.
