# 02-catalogue-schemas Plan

## 1. Goal and scope

This step ships the internal catalogue-shape layer only:

- Define the four internal catalogue contracts: `StationCatalog`, `ProductCatalog`, `StationProductCatalog`, and `ProviderInfoCatalog`.
- Define field-level Polars dtypes and nullability for every catalogue column, with explicit nullable support for `StationCatalog.elevation_m` and `StationCatalog.drainage_area_km2`.
- Encode `metadata` as opaque JSON text in the Parquet-backed catalogue schemas so provider artifacts can be written and read under Polars 1.40.1.
- Define the packaged catalogue artifact contract for a provider catalogue directory containing `provider.json`, `products.parquet`, `stations.parquet`, and `station_products.parquet`.
- Add `CorruptCatalogArtifactError(FatalContractError)` and use it for corrupt artifact inputs, bypassing `apply_on_issue` for fatal contract failures.
- Add schema and artifact tests using synthetic data only.

No public API is introduced. `src/rivretrieve/__init__.py` must have no API-shape edits: no symbol additions, no re-exports, and no import changes. The required per-commit version-literal bump is exempt per `docs/discoveries.md:5-33`.

Evidence:

- M1 authorizes common catalogue schemas and `PackagedCatalogArtifact` (`docs/milestone-tracker.md:47-50`) and requires nullable elevation/drainage tests (`docs/milestone-tracker.md:87`).
- Catalogue tables must be Polars, not pandas (`architecture.md:231`, `docs/milestone-tracker.md:18`).
- Common schemas must stay small and keep provider metadata opaque (`architecture.md:244-266`).
- Packaged provider layout is fixed at `provider.json`, `products.parquet`, `stations.parquet`, and `station_products.parquet` under a provider package catalogue directory (`architecture.md:380-390`).
- Corrupt packaged catalogue artifacts are fatal contract failures regardless of `on_issue` (`architecture.md:607`).
- Legacy fetchers expose pandas class methods such as `RiverDataFetcher.get_cached_metadata()` and `get_available_variables()` rather than schema-validated Polars artifacts; this step intentionally diverges from that shape (`/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/base.py:9-23`, `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/base.py:51-77`).

## 2. API surface touched

Public surface:

- No public symbols added.
- No public imports changed.
- No API-shape edits to `src/rivretrieve/__init__.py`; only the mandatory version-literal bump is allowed before commit.

Internal modules:

- Add `src/rivretrieve/_internal/catalogues/__init__.py` as a private package marker with no broad re-exports.
- Add `src/rivretrieve/_internal/catalogues/schemas.py`.
- Add `src/rivretrieve/_internal/catalogues/artifact.py`.

Internal symbols introduced:

- `CatalogueColumn`.
- `CatalogueSchema`.
- `StationCatalog`.
- `ProductCatalog`.
- `StationProductCatalog`.
- `ProviderInfoCatalog`.
- `Availability` values: `"available"`, `"unavailable"`, `"unknown"`.
- `validate_catalogue(df: pl.DataFrame, schema: CatalogueSchema, *, on_issue: OnIssue = "warn") -> list[Issue]`, defined in `schemas.py`.
- `CorruptCatalogArtifactError`.
- `PackagedCatalogArtifact`.
- `load_packaged_catalogue_artifact(path: Path | str, *, on_issue: OnIssue = "warn") -> PackagedCatalogArtifact`.
- `packaged_catalogue_artifact_from_components(provider_info: Mapping[str, object], products: pl.DataFrame, stations: pl.DataFrame, station_products: pl.DataFrame, *, on_issue: OnIssue = "warn") -> PackagedCatalogArtifact`.

Step 03 should be able to import `PackagedCatalogArtifact` and `load_packaged_catalogue_artifact` from `rivretrieve._internal.catalogues.artifact` without importing provider packages or public registry code.

## 3. Data structures and types

Represent catalogue schemas with frozen dataclasses:

- `CatalogueColumn(name: str, dtype: pl.DataType | type[pl.DataType], nullable: bool = False)`.
- `CatalogueSchema(name: str, columns: tuple[CatalogueColumn, ...], unique_keys: tuple[tuple[str, ...], ...] = (), enum_values: dict[str, frozenset[str]] = {})`.

The schema object should expose a derived `polars_schema: pl.Schema` or equivalent mapping for construction/validation. The runtime checks against Polars 1.40.1 confirmed `pl.Schema` and `pl.Enum(["available", "unavailable", "unknown"])` are available, and the critique reproduced that `pl.Object` cannot be written to Parquet. Therefore `pl.Object` is not allowed in these catalogue schemas.

Use `pl.Utf8` for `metadata`, containing a JSON object string such as `"{}"`. The validator must check that non-null metadata strings parse as JSON objects, but it must not validate, normalize, or inspect provider-defined nested keys. This keeps the generic harness opaque with respect to metadata (`architecture.md:255-266`) while satisfying the Parquet artifact layout (`architecture.md:380-390`) and release-time artifact validation requirement (`architecture.md:450`). Later public/provider adapters may decode this field to plain dictionaries at public table boundaries; M1 does not introduce that public surface.

Use `pl.Date` for catalogue date columns. These fields are catalogue coverage/bookkeeping dates, not observation timestamps. The timestamp preservation rules in `architecture.md:622-626` apply to observation data and annotations; no timezone-aware catalogue datetime is needed in M1.

Catalogue contracts:

`StationCatalog`:

| Column | Polars dtype | Nullable | Rationale |
| --- | --- | --- | --- |
| `provider_id` | `pl.Utf8` | No | Provider scope and global key component (`architecture.md:71`, `architecture.md:273`). |
| `station_id` | `pl.Utf8` | No | Provider-native station key (`architecture.md:69-71`, `architecture.md:274`). |
| `name` | `pl.Utf8` | No | Small common display field; providers should use empty string only if source has no name. |
| `latitude` | `pl.Float64` | No | Required for discovery/map usefulness; decimal degrees. |
| `longitude` | `pl.Float64` | No | Required for discovery/map usefulness; decimal degrees. |
| `country` | `pl.Utf8` | No | Required normalized common field from `architecture.md:278`; do not enforce ISO vocabulary in this step. |
| `elevation_m` | `pl.Float64` | Yes | Field authorized by `architecture.md:279`; nullability is binding per tracker M1 exit criteria (`docs/milestone-tracker.md:48`, `docs/milestone-tracker.md:87`). |
| `drainage_area_km2` | `pl.Float64` | Yes | Field authorized by `architecture.md:280`; nullability is binding per tracker M1 exit criteria (`docs/milestone-tracker.md:48`, `docs/milestone-tracker.md:87`). |
| `start_date` | `pl.Date` | Yes | Catalogue coverage may be unknown. |
| `end_date` | `pl.Date` | Yes | Catalogue coverage may be open-ended or unknown. |
| `metadata` | `pl.Utf8` | No | Required opaque JSON object string; use `"{}"` when no provider metadata exists. |

Unique keys: `("provider_id", "station_id")`.

`ProductCatalog`:

| Column | Polars dtype | Nullable | Rationale |
| --- | --- | --- | --- |
| `provider_id` | `pl.Utf8` | No | Provider scope. |
| `product_id` | `pl.Utf8` | No | Opaque product key; do not parse (`architecture.md:315`, `architecture.md:369-374`). |
| `observed_property` | `pl.Utf8` | No | Required product dictionary dimension. |
| `frequency` | `pl.Utf8` | No | Required time semantics field (`architecture.md:616`). |
| `statistic` | `pl.Utf8` | No | Required semantics field; not computation instruction (`architecture.md:311`). |
| `period_type` | `pl.Utf8` | No | Required time semantics field (`architecture.md:618`). |
| `period_anchor` | `pl.Utf8` | No | Required time semantics field (`architecture.md:619`). |
| `unit` | `pl.Utf8` | No | Required common unit label; use `"unknown"` if source cannot determine it. |
| `native_id` | `pl.Utf8` | Yes | Provider parameter/measure identifier only when useful (`architecture.md:313`). |
| `derived` | `pl.Boolean` | No | Required; V1 products should normally be `False` (`architecture.md:374`). |
| `derivation_method` | `pl.Utf8` | Yes | Null for non-derived products. |
| `metadata` | `pl.Utf8` | No | Required opaque JSON object string. |

Unique keys: `("provider_id", "product_id")`.

`StationProductCatalog`:

| Column | Polars dtype | Nullable | Rationale |
| --- | --- | --- | --- |
| `provider_id` | `pl.Utf8` | No | Provider scope. |
| `station_id` | `pl.Utf8` | No | Station key component. |
| `product_id` | `pl.Utf8` | No | Product key component. |
| `availability` | `pl.Enum(["available", "unavailable", "unknown"])` | No | Fixed vocabulary from `architecture.md:335-341`. |
| `availability_reason` | `pl.Utf8` | Yes | Needed for `unknown`/`unavailable`; may be null for `available`. |
| `start_date` | `pl.Date` | Yes | Availability coverage may be unknown. |
| `end_date` | `pl.Date` | Yes | Open-ended or unknown coverage allowed. |
| `last_catalogue_check` | `pl.Date` | No | Required artifact bookkeeping date for known availability snapshot. |
| `metadata` | `pl.Utf8` | No | Required opaque JSON object string. |

Unique keys: `("provider_id", "station_id", "product_id")`.

`ProviderInfoCatalog`:

| Column | Polars dtype | Nullable | Rationale |
| --- | --- | --- | --- |
| `provider_id` | `pl.Utf8` | No | Required provider identity. |
| `name` | `pl.Utf8` | No | Human-readable provider/source name; inferred for M1 because architecture names capability fields but not a display label. |
| `live_stations` | `pl.Boolean` | No | Capability flag named by `architecture.md:432`. |
| `live_products` | `pl.Boolean` | No | Capability flag named by `architecture.md:432`. |
| `live_station_products` | `pl.Boolean` | No | Capability flag named by `architecture.md:432`. |
| `bulk_observations` | `pl.Utf8` | No | Descriptive capability named by `architecture.md:432`; keep as text until M2 observation contracts exist. |
| `catalogue_version` | `pl.Utf8` | Yes | Filled when a packaged artifact declares a version; duplicates `CatalogProvenance.catalogue_version` intentionally so the artifact is self-describing. M2/M3 should surface a fatal mismatch if separate producers ever disagree. |
| `metadata` | `pl.Utf8` | No | Required opaque JSON object string for provider-level extras, excluding M2 observation method signatures. |

Unique keys: `("provider_id",)`.

`provider.json` is parsed in M1 as a row-shaped mapping that validates against exactly one `ProviderInfoCatalog` row. To keep `provider.json` ergonomic, its `metadata` member may be a JSON object; the loader should canonicalize it to a sorted-key JSON string before constructing the one-row `ProviderInfoCatalog` DataFrame. M2 may introduce a singular `ProviderInfo` typed row view that is isomorphic to these columns, but M1 must not add that type.

`PackagedCatalogArtifact` should be a frozen dataclass:

- `provider_info: dict[str, object]` or `Mapping[str, object]` containing the validated provider info row.
- `products: pl.DataFrame`.
- `stations: pl.DataFrame`.
- `station_products: pl.DataFrame`.

The constructor path should not perform I/O implicitly. Use separate constructors/functions for loading from path and validating already-loaded components.

## 4. Errors and failure modes

Fatal failures raise immediately and do not pass through `apply_on_issue`:

- Missing artifact directory: `CorruptCatalogArtifactError`.
- Path exists but is not a directory: `CorruptCatalogArtifactError`.
- Missing `provider.json`, `products.parquet`, `stations.parquet`, or `station_products.parquet`: `CorruptCatalogArtifactError`.
- Unparseable `provider.json`: `CorruptCatalogArtifactError`.
- `provider.json` does not contain a JSON object: `CorruptCatalogArtifactError`.
- Parquet file unreadable by Polars: `CorruptCatalogArtifactError`.
- DataFrame missing required column: fatal. In direct schema tests this may be `FatalContractError`; through the artifact loader it must be wrapped as `CorruptCatalogArtifactError`.
- DataFrame column has wrong dtype: fatal; artifact path raises `CorruptCatalogArtifactError`.
- Non-nullable column contains nulls: fatal; artifact path raises `CorruptCatalogArtifactError`.
- Metadata column contains a non-JSON string or a JSON non-object such as `[]`: fatal; artifact path raises `CorruptCatalogArtifactError`.
- `availability` contains a value outside `"available"`, `"unavailable"`, or `"unknown"`: fatal; artifact loader should cast `pl.Utf8` to the enum when needed and wrap cast failures in `CorruptCatalogArtifactError`.
- Duplicate `("provider_id", "station_id")` in stations: fatal; artifact path raises `CorruptCatalogArtifactError`.
- Duplicate `("provider_id", "product_id")` in products: fatal; artifact path raises `CorruptCatalogArtifactError`.
- Duplicate `("provider_id", "station_id", "product_id")` in station products: fatal; artifact path raises `CorruptCatalogArtifactError`.
- Duplicate `("provider_id",)` in provider info row/table: fatal; artifact path raises `CorruptCatalogArtifactError`.
- Artifact-local provider ID mismatch across `provider.json` and the three DataFrames: fatal; artifact path raises `CorruptCatalogArtifactError`.
- `station_products` references station/product IDs absent from the artifact's station/product tables: fatal; artifact path raises `CorruptCatalogArtifactError`.

Recoverable issues:

- Extra columns in catalogue DataFrames should produce warning `Issue` objects and pass through `apply_on_issue`. Extra columns are not part of the contract consumed by generic code, but they do not corrupt the required common schema. The artifact loader may preserve them in the DataFrame; Step 03 can decide whether aggregation selects only common columns.

`CorruptCatalogArtifactError` should be one subclass, not a hierarchy. Step 03 can catch one fatal artifact type at the registry boundary and inspect the message or chained exception if needed. Use exception chaining (`raise CorruptCatalogArtifactError(...) from exc`) for JSON decode errors, Polars read/cast errors, and lower-level validation failures. A fine-grained hierarchy would be premature before registry behavior exists.

## 5. Tests

T01. `test_catalogue_schema_objects_define_expected_columns`: each schema exposes exactly the authorized common columns in order.

T02. `test_catalogue_schema_objects_define_polars_dtypes`: each schema maps every column to the planned Polars dtype, including metadata as `pl.Utf8`, date fields as `pl.Date`, and availability as `pl.Enum`.

T03. `test_station_catalog_nullable_fields_accept_non_null_values`: station schema validates non-null `elevation_m` and `drainage_area_km2`.

T04. `test_station_catalog_nullable_fields_accept_null_values`: station schema validates null `elevation_m` and `drainage_area_km2`.

T05. `test_non_nullable_station_column_rejects_null`: a null in a required station column raises a fatal contract error.

T06. `test_missing_required_column_rejected`: omitting a required schema column raises a fatal contract error.

T07. `test_wrong_dtype_rejected`: a wrong dtype, such as string latitude, raises a fatal contract error.

T08. `test_extra_column_returns_warning_issue`: an extra column returns a warning `Issue` and does not corrupt the required shape under `on_issue="ignore"`.

T09. `test_availability_accepts_allowed_enum_values`: all three availability values validate.

T10. `test_availability_rejects_invalid_value`: an invalid availability value raises a fatal contract error.

T11. `test_metadata_column_is_opaque_json_object_string`: JSON object string metadata validates and the validator does not inspect nested provider fields.

T12. `test_metadata_column_rejects_non_object_json`: a metadata value such as `"[]"` raises a fatal contract error.

T13. `test_provider_info_catalog_validates_row_shape`: a one-row provider info DataFrame constructed in memory, with the same shape `provider.json` will produce, validates against `ProviderInfoCatalog`.

T14. `test_packaged_artifact_from_components_happy_path`: already-loaded provider info plus three DataFrames returns a `PackagedCatalogArtifact`.

T15. `test_packaged_artifact_from_path_happy_path`: a synthetic temporary directory with JSON and Parquet files loads and validates.

T16. `test_packaged_artifact_missing_directory_raises_corrupt`: a nonexistent artifact directory raises `CorruptCatalogArtifactError`.

T17. `test_packaged_artifact_path_not_directory_raises_corrupt`: passing a file path instead of a directory raises `CorruptCatalogArtifactError`.

T18. `test_packaged_artifact_missing_file_raises_corrupt`: deleting one required file raises `CorruptCatalogArtifactError`.

T19. `test_packaged_artifact_unparseable_json_raises_corrupt`: invalid `provider.json` raises `CorruptCatalogArtifactError`.

T20. `test_packaged_artifact_provider_json_not_object_raises_corrupt`: a JSON array or scalar in `provider.json` raises `CorruptCatalogArtifactError`.

T21. `test_packaged_artifact_unreadable_parquet_raises_corrupt`: invalid parquet bytes raise `CorruptCatalogArtifactError`.

T22. `test_packaged_artifact_schema_missing_column_raises_corrupt`: missing required column in an artifact table raises `CorruptCatalogArtifactError`.

T23. `test_packaged_artifact_schema_wrong_dtype_raises_corrupt`: wrong dtype in an artifact table raises `CorruptCatalogArtifactError`.

T24. `test_packaged_artifact_non_nullable_null_raises_corrupt`: null in a non-nullable artifact table column raises `CorruptCatalogArtifactError`.

T25. `test_packaged_artifact_metadata_non_object_json_raises_corrupt`: metadata JSON that is not an object raises `CorruptCatalogArtifactError`.

T26. `test_packaged_artifact_invalid_availability_raises_corrupt`: invalid availability value in artifact data raises `CorruptCatalogArtifactError`.

T27. `test_packaged_artifact_duplicate_station_key_raises_corrupt`: duplicate `(provider_id, station_id)` in stations raises `CorruptCatalogArtifactError`.

T28. `test_packaged_artifact_duplicate_product_key_raises_corrupt`: duplicate `(provider_id, product_id)` in products raises `CorruptCatalogArtifactError`.

T29. `test_packaged_artifact_duplicate_station_product_key_raises_corrupt`: duplicate `(provider_id, station_id, product_id)` raises `CorruptCatalogArtifactError`.

T30. `test_packaged_artifact_duplicate_provider_info_key_raises_corrupt`: duplicate provider info rows or duplicate provider identity after row conversion raises `CorruptCatalogArtifactError`.

T31. `test_packaged_artifact_provider_id_mismatch_raises_corrupt`: mismatched provider IDs across components raise `CorruptCatalogArtifactError`.

T32. `test_packaged_artifact_dangling_station_product_station_fk_raises_corrupt`: a station-product row referencing a missing station raises `CorruptCatalogArtifactError`.

T33. `test_packaged_artifact_dangling_station_product_product_fk_raises_corrupt`: a station-product row referencing a missing product raises `CorruptCatalogArtifactError`.

T34. `test_corrupt_artifact_still_raises_under_ignore`: under `on_issue="ignore"`, any corrupt artifact path still raises `CorruptCatalogArtifactError` and does not call `apply_on_issue`.

T35. `test_init_public_surface_still_has_no_new_symbols`: `rivretrieve` still exposes `__version__` and does not expose `providers`, `provider`, `provider_info`, catalogue schemas, `PackagedCatalogArtifact`, or `CorruptCatalogArtifactError`.

## 6. Files

Implementation order that keeps `uv run pytest` green at every file-sized boundary:

1. Add `src/rivretrieve/_internal/catalogues/__init__.py` as an empty private package marker. Run `uv run pytest`.
2. Add `src/rivretrieve/_internal/catalogues/schemas.py` with dataclass schema specs, `validate_catalogue`, and no artifact loader. Run `uv run pytest`.
3. Add `tests/test_internal_catalogue_schemas.py` covering T01-T13. Run `uv run pytest`.
4. Add `src/rivretrieve/_internal/catalogues/artifact.py` with `CorruptCatalogArtifactError`, `PackagedCatalogArtifact`, component validation, and path loading. Run `uv run pytest`.
5. Add `tests/test_internal_packaged_catalogue_artifact.py` covering T14-T34. Prefer `tmp_path` generated artifacts over committed fixtures; use `DataFrame.write_parquet()` in tests to exercise path loading without storing real provider data. Run `uv run pytest`.
6. Modify `tests/test_package.py` only if T35 needs to extend the existing public-surface negative control from Step 01. Run `uv run pytest`.
7. Run `uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`, and `uv run pytest`.
8. Run `uv run bump-my-version bump patch`, stage the version changes with the code changes, commit, and tag per `docs/discoveries.md:21-33`.

No on-disk `tests/test_data/` fixtures are required unless the executor finds Polars path-loading behavior cannot be exercised cleanly with `tmp_path`. If fixtures become necessary, place only skeletal synthetic artifacts under `tests/test_data/catalogues/valid_synthetic/` and deliberately corrupt variants under `tests/test_data/catalogues/corrupt_*`; do not commit real provider data.

## 7. Open questions

Q1. Module layout under `src/rivretrieve/_internal/`.

Recommendation: use `catalogues/schemas.py` and `catalogues/artifact.py`. This groups catalogue-specific contracts without crowding the already-existing `_internal/{primitives,issues,results}.py` files from Step 01. It leaves Step 03 free to add registry code as `src/rivretrieve/_internal/registry.py` or `src/rivretrieve/_internal/providers.py` without a naming collision. It also does not conflict with provider package layout under `src/rivretrieve/providers/<provider_id>/catalogue/` because `_internal.catalogues` is private harness code while `providers/.../catalogue/` is artifact data (`architecture.md:380-390`).

Q2. Schema-spec representation.

Recommendation: choose a custom frozen dataclass holding column names, Polars dtypes, and nullable flags, with a derived `pl.Schema` mapping. `pl.Schema` alone does not encode nullability, while row-by-row Pydantic models would fight the Polars-canonical contract and force table-to-record conversion. A dataclass is explicit, low ceremony, and lets validation operate directly on `pl.DataFrame`.

Q3. Validator signature and fatal/recoverable split.

Recommendation: implement `validate_catalogue(df, schema, *, on_issue="warn") -> list[Issue]`. It should return recoverable issues only for extra columns and should call `apply_on_issue` for those issues. Missing columns, dtype mismatch, non-nullable nulls, invalid enum values, invalid metadata JSON-object shape, and duplicate unique keys are fatal schema violations. Direct schema validation can raise `FatalContractError`; the artifact loader must catch fatal schema failures and raise `CorruptCatalogArtifactError` so corrupt packaged artifacts always use the step-specific fatal subclass. This preserves Step 01's two-channel design (`docs/milestones/m1-harness-foundation/steps/01-foundations/plan.md:70-78`).

Q4. Required vs nullable per column.

Recommendation: use the field table in Section 3. Required means the column must exist and contain no nulls. Nullable means the column must exist but may contain null values. The two mandatory nullable station fields are `elevation_m` and `drainage_area_km2`; tests must prove both null and non-null values pass. For architecture-silent fields, require identifiers, names, coordinates, core product semantics, capability booleans, and metadata; allow nulls only where source coverage or optional native IDs are legitimately unknown.

Q5. ProviderInfoCatalog column set.

Recommendation: `provider_id`, `name`, `live_stations`, `live_products`, `live_station_products`, `bulk_observations`, `catalogue_version`, and `metadata`. This includes all capability fields explicitly named by `architecture.md:432`, provides a human-readable name, and keeps artifact versioning available for packaged provenance. It deliberately excludes observation request signatures, annotation schemas, endpoint details, credentials, and per-provider method contracts, all of which belong to M2 `ProviderInfo`, provider handles, observation contracts, or provider modules.

Q6. Encoding of `metadata`.

Recommendation: use `pl.Utf8` containing a JSON object string in all four catalogue schemas. This is a correction from the initial `pl.Object` idea: Polars 1.40.1 can construct `pl.Object` columns, but cannot write them to Parquet, so `pl.Object` is incompatible with the packaged artifact contract (`architecture.md:380-390`). `pl.Struct` would require a shared field schema for provider-specific metadata and would weaken opacity/extra-field preservation. Moving metadata out of Parquet would change the artifact contract and should not be done in this step. JSON text keeps the Parquet files writable, keeps generic validation limited to "is this an object-shaped metadata payload?", and lets later public adapters decode to plain dictionaries at public table boundaries (`architecture.md:256-266`). Use canonical JSON encoding for generated fixtures/artifacts so diffs and tests are deterministic.

Q7. Encoding of date columns.

Recommendation: `pl.Date` for station/product availability coverage and catalogue check dates. Catalogue dates are release artifact metadata, not provider-native observation timestamps. If a future provider has sub-day catalogue validity evidence, that is a provider-port pain point to record rather than an M1 reason to widen all catalogue fields to timezone-aware datetimes.

Q8. Encoding of availability.

Recommendation: `pl.Enum(["available", "unavailable", "unknown"])` plus explicit loader normalization. The loader should accept Parquet files whose `availability` column is either already that exact enum dtype or `pl.Utf8`; for `pl.Utf8`, it must cast to the enum before validation. If the cast raises a Polars exception because a value is out of vocabulary, wrap it in `CorruptCatalogArtifactError`. Any other dtype is a schema mismatch and raises `CorruptCatalogArtifactError`. This allows simple fixture/generator code while still returning a validated enum-typed `StationProductCatalog`.

Q9. PackagedCatalogArtifact API shape.

Recommendation: a frozen dataclass plus separate loader/factory functions. `PackagedCatalogArtifact` should be a passive typed bundle that Step 03's registry can consume naturally, while `load_packaged_catalogue_artifact(path, *, on_issue="warn")` owns I/O and validation. Avoid `__init__(path)` because implicit filesystem work in construction makes tests and registry error handling less clear.

Q10. Corrupt-artifact failure modes and exception type.

Recommendation: classify every corruption mode listed in Section 4 as fatal except extra columns, which are recoverable warnings. Use one `CorruptCatalogArtifactError` subclass. Registry code in Step 03 can catch one type and either surface it or wrap it in registry context; a small hierarchy can be added only if real registry handling needs it.

Q11. Test fixture strategy.

Recommendation: hybrid in spirit, but implemented with in-memory DataFrames plus `tmp_path` on-disk artifacts. Schema unit tests should build Polars frames in memory. Artifact path tests should write tiny synthetic JSON/parquet files to `tmp_path` to exercise real loading without committed fixture files. This depends on the Q6 JSON-string metadata decision; with `pl.Utf8` metadata, temporary Parquet fixtures are writable under Polars 1.40.1. Commit files under `tests/test_data/` only if a concrete Polars path-loading issue makes generated temporary artifacts insufficient.

Q12. ProviderInfoCatalog handoff to M2.

Recommendation: M1 treats `provider.json` as a provider-info row dict validated against `ProviderInfoCatalog`. M2 can introduce singular `ProviderInfo` as a typed row view isomorphic to this schema, or as a richer object that can be losslessly constructed from this row plus provider module capabilities. M1 must not introduce `ProviderInfo` now because the tracker assigns it to M2 (`docs/milestone-tracker.md:129-135`).

## 8. Deferrals

- Provider registry, deterministic `rr.providers()`, `rr.provider()`, `rr.provider_info()`, and empty/stub registry tests: Step 03. Hard rationale: this step only creates schema and artifact contracts; registry consumption is the next vertical slice.
- UnknownProviderError and registry/provider ID `snake_case` enforcement: Step 03. Hard rationale: provider ID validation at the registry boundary was explicitly handed forward by Step 01 (`docs/milestones/m1-harness-foundation/steps/01-foundations/execution.md:70-72`).
- Offline-import negative-control test: Step 03. Hard rationale: that step first touches public imports/registry behavior; Step 02 keeps public imports unchanged.
- Public discovery APIs and public `ProviderHandle` Protocol: Step 03/M2 as tracked. Hard rationale: no half-wired public API or empty Protocol (`docs/milestone-tracker.md:22`, `docs/milestone-tracker.md:150`).
- Singular `ProviderInfo`: M2. Hard rationale: the tracker lists it under M2 internal types, while M1 ships only the aggregate provider-info catalogue schema.
- Observation request/result, annotation schemas, and provider observation behavior: M2. Hard rationale: outside catalogue artifact shape.
- Real `ch_foen` artifacts, provider package data, and `generate_catalogue.py`: M3. Hard rationale: M1 must not commit real provider data or import maintainer-only generation code.
- Provider-owned Pydantic metadata models such as `ChFoenStationMetadata`: M3. Hard rationale: generic harness code treats metadata as opaque until provider-specific evidence exists.
- Pandas export helpers and pandas-based schema validation: deferred beyond this step. Hard rationale: Polars is canonical and pandas is export convenience only (`architecture.md:231`).

## 9. Stopping conditions for the executor

Stop and surface to the orchestrator if any of these happen:

- Implementing this step requires registry symbols, provider modules, public discovery functions, a singular `ProviderInfo`, observation contracts, annotation schemas, or real provider data.
- Architecture and tracker disagree on any schema column or nullability rule.
- `pl.Enum(["available", "unavailable", "unknown"])`, `pl.Utf8` JSON metadata, or `pl.Schema` cannot be used reliably under Polars 1.40.1.
- The executor is tempted to use `pl.Object` for any Parquet-backed catalogue column.
- The executor cannot keep `elevation_m` and `drainage_area_km2` nullable while enforcing all other required fields.
- Corrupt packaged artifacts cannot raise a `FatalContractError` subclass directly without passing through `apply_on_issue`.
- Any fatal contract failure listed in Section 4 is being modeled as a recoverable `Issue(severity="error")` rather than a direct exception.
- The executor needs to parse or validate nested provider `metadata` contents in generic harness code.
- The executor wants to add a Polars schema metaclass, abstract validator hierarchy, future-extension hook, or shared provider base class.
- `src/rivretrieve/__init__.py` needs any edit other than the mandatory version-literal bump.
- Any intermediate state leaves `uv run pytest` failing or package imports broken.
- The implementation would need committed real provider data, a `ch_foen` provider, or a maintainer `generate_catalogue.py`.
