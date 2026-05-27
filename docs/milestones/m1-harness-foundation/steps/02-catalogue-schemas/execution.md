## What landed
- Files added/modified: `pyproject.toml`, `uv.lock`, `src/rivretrieve/__init__.py`, `src/rivretrieve/_internal/catalogues/__init__.py`, `src/rivretrieve/_internal/catalogues/schemas.py`, `src/rivretrieve/_internal/catalogues/artifact.py`, `tests/test_internal_catalogue_schemas.py`, `tests/test_internal_packaged_catalogue_artifact.py`, `tests/test_package.py`, `docs/milestones/m1-harness-foundation/steps/02-catalogue-schemas/execution.md`.
- Symbols added (internal): `CatalogueColumn`, `CatalogueSchema`, `StationCatalog`, `ProductCatalog`, `StationProductCatalog`, `ProviderInfoCatalog`, `AvailabilityDtype`, `AVAILABILITY_VALUES`, `CatalogueDtype`, `validate_catalogue`, `CorruptCatalogArtifactError`, `PackagedCatalogArtifact`, `load_packaged_catalogue_artifact`, `packaged_catalogue_artifact_from_components`.
- Public surface delta: none beyond the required version literal bump from `0.1.5` to `0.1.6`.

## Plan adherence
- Step 1: done as planned; added empty private package marker and `uv run pytest` passed.
- Step 2: done as planned; added schemas and validator only, then `uv run pytest` passed.
- Step 3: done as planned; added T01-T13, then `uv run pytest` passed after correcting T10 to avoid Polars construction-time failure before validator entry.
- Step 4: done as planned; added artifact loader/factory, then `uv run pytest` passed.
- Step 5: done as planned; added T14-T34 using `tmp_path`, then `uv run pytest` passed after fixing test-helper DataFrame truthiness.
- Step 6: done as planned; extended `tests/test_package.py` for T35, then `uv run pytest` passed.
- Step 7: done as planned; `ruff format`, `ruff check --fix`, `ty check`, and `pytest` passed.
- Step 8: done as planned with D1 tag-state adjustment; `v0.1.5` already existed and configured files were at `0.1.5`, so `uv run bump-my-version bump patch` produced `0.1.6`; post-bump `uv run pytest` passed.
- T01: implemented.
- T02: implemented.
- T03: implemented.
- T04: implemented.
- T05: implemented.
- T06: implemented.
- T07: implemented.
- T08: implemented.
- T09: implemented.
- T10: implemented with adjustment: uses a wider `pl.Enum` containing `retired` so the DataFrame can be constructed and validator rejects it fatally.
- T11: implemented.
- T12: implemented.
- T13: implemented.
- T14: implemented.
- T15: implemented.
- T16: implemented.
- T17: implemented.
- T18: implemented.
- T19: implemented.
- T20: implemented.
- T21: implemented.
- T22: implemented.
- T23: implemented.
- T24: implemented.
- T25: implemented.
- T26: implemented.
- T27: implemented.
- T28: implemented.
- T29: implemented.
- T30: implemented with adjustment: component factory accepts row-sequence provider-info mappings to exercise duplicate provider identities without non-object JSON.
- T31: implemented.
- T32: implemented.
- T33: implemented.
- T34: implemented.
- T35: implemented by extending the existing public-surface negative control.

## Architecture invariants verified
- Polars-canonical: schemas use Polars dtypes and `validate_catalogue` accepts `pl.DataFrame`; no pandas import exists in the catalogue code. T01, T02, and T14-T15 catch drift.
- metadata is `pl.Utf8` JSON object strings: schema dtypes pin `metadata` to `pl.Utf8`; validator parses only object shape and does not inspect nested keys. T11, T12, and T25 catch regressions.
- Fatal raises regardless of `on_issue`: missing required file in T34 raises `CorruptCatalogArtifactError` with explicit `on_issue="ignore"`.
- Two-channel: extra columns produce warning `Issue` objects through `apply_on_issue`, while missing columns, dtype mismatch, nulls, metadata shape, duplicate keys, ID mismatch, and dangling references raise fatal exceptions. T08 covers recoverable path; T05-T07, T12, and T22-T33 cover fatal paths.
- elevation_m nullable: `StationCatalog` marks it nullable, and T03 plus T04 cover non-null and explicit null values.
- drainage_area_km2 nullable: `StationCatalog` marks it nullable, and T03 plus T04 cover non-null and explicit null values.
- availability is `pl.Enum` with the three fixed levels: `AvailabilityDtype = pl.Enum(("available", "unavailable", "unknown"))`; T09, T10, and T26 catch regressions.
- Date columns are `pl.Date`: T02 asserts date dtypes for the catalogue schemas.
- on_issue is the sole policy knob: public validator/loader/factory signatures expose only `on_issue`; no strict or raise-on-extra switch exists.
- No public symbols added beyond version bump: T35 asserts planned public M1 names remain absent from `rivretrieve`.
- No speculative abstractions: implementation uses frozen dataclasses and functions only; no Protocol, ABC, registry symbol, provider base class, or loader hierarchy was introduced.

## Negative-control evidence
- T04 construction snippet: `df = pl.DataFrame({"elevation_m": [None, 12.3], "drainage_area_km2": [45.6, None], ...}, schema=StationCatalog.polars_schema)`. Assertion form: call `validate_catalogue(..., on_issue="raise")`, assert no raise, assert no returned `Issue` has `severity == "error"`, and assert both columns are `pl.Float64`.
- T34 corruption mode: missing required `stations.parquet` after writing a valid tmp_path artifact. Assertion form: `pytest.raises(CorruptCatalogArtifactError)` around `load_packaged_catalogue_artifact(artifact_path, on_issue="ignore")`.
- T35 assertion list: confirms absence of `providers`, `provider`, `provider_info`, `StationCatalog`, `ProductCatalog`, `StationProductCatalog`, `ProviderInfoCatalog`, `PackagedCatalogArtifact`, `CorruptCatalogArtifactError`, `CatalogResult`, and `Issue`; confirms `__version__` remains present.

## Polars 1.40.1 behavior notes
- `pl.Schema` usage shape adopted: each `CatalogueSchema.polars_schema` returns `pl.Schema({column.name: column.dtype for column in columns})`.
- `pl.Enum` cast behavior observed: casting `pl.Utf8` value `"retired"` to `pl.Enum(["available", "unavailable", "unknown"])` raises `polars.exceptions.InvalidOperationError`; artifact loader wraps it into `CorruptCatalogArtifactError`.
- Parquet round-trip of `pl.Utf8` metadata column: confirmed working with schema `Schema({'metadata': String})` and value `"{}"` preserved.
- `pl.Object` was not used anywhere in this step's code.

## Fixture strategy used
- Used in-memory DataFrames for schema and component-factory tests.
- Used `tmp_path` for on-disk artifact tests, writing synthetic `provider.json` and Parquet files during the test run.
- No committed `tests/test_data/` fixtures were added.

## Tool runs
- `uv run ruff format` - pass; reformatted four files before type cleanup and no files on the final rerun.
- `uv run ruff check --fix` - pass; auto-fixed import ordering, then required manual `type CatalogueDtype = ...` alias syntax.
- `uv run ty check` - pass; no warnings suppressed.
- `uv run pytest` - pass, 72 tests.
- New test names: `test_catalogue_schema_objects_define_expected_columns`, `test_catalogue_schema_objects_define_polars_dtypes`, `test_station_catalog_nullable_fields_accept_non_null_values`, `test_station_catalog_nullable_fields_accept_null_values`, `test_non_nullable_station_column_rejects_null`, `test_missing_required_column_rejected`, `test_wrong_dtype_rejected`, `test_extra_column_returns_warning_issue`, `test_availability_accepts_allowed_enum_values`, `test_availability_rejects_invalid_value`, `test_metadata_column_is_opaque_json_object_string`, `test_metadata_column_rejects_non_object_json`, `test_provider_info_catalog_validates_row_shape`, `test_packaged_artifact_from_components_happy_path`, `test_packaged_artifact_from_path_happy_path`, `test_packaged_artifact_missing_directory_raises_corrupt`, `test_packaged_artifact_path_not_directory_raises_corrupt`, `test_packaged_artifact_missing_file_raises_corrupt`, `test_packaged_artifact_unparseable_json_raises_corrupt`, `test_packaged_artifact_provider_json_not_object_raises_corrupt`, `test_packaged_artifact_unreadable_parquet_raises_corrupt`, `test_packaged_artifact_schema_missing_column_raises_corrupt`, `test_packaged_artifact_schema_wrong_dtype_raises_corrupt`, `test_packaged_artifact_non_nullable_null_raises_corrupt`, `test_packaged_artifact_metadata_non_object_json_raises_corrupt`, `test_packaged_artifact_invalid_availability_raises_corrupt`, `test_packaged_artifact_duplicate_station_key_raises_corrupt`, `test_packaged_artifact_duplicate_product_key_raises_corrupt`, `test_packaged_artifact_duplicate_station_product_key_raises_corrupt`, `test_packaged_artifact_duplicate_provider_info_key_raises_corrupt`, `test_packaged_artifact_provider_id_mismatch_raises_corrupt`, `test_packaged_artifact_dangling_station_product_station_fk_raises_corrupt`, `test_packaged_artifact_dangling_station_product_product_fk_raises_corrupt`, `test_corrupt_artifact_still_raises_under_ignore`; extended `test_init_public_surface_still_only_version`.

## Discoveries
- `pl.Series(..., dtype=expected_enum)` with an out-of-vocabulary value raises during Series construction, before `validate_catalogue` can run. Direct T10 therefore uses a wider enum dtype and lets the validator reject the mismatch; artifact T26 covers the real loader path where Utf8 is cast to the fixed enum and invalid values raise `InvalidOperationError`.
- `v0.1.5` already existed before this step and configured files were already at `0.1.5`; this step correctly bumped to `0.1.6` per D1's instruction to inspect tag state.
- No contradiction with architecture.md or the tracker was found.
- No discovery rose above step-local execution notes, so `docs/discoveries.md` was not amended.

## Open items handed forward
- Step 03 imports from `rivretrieve._internal.catalogues.artifact`: `PackagedCatalogArtifact`, `load_packaged_catalogue_artifact`. Signatures match plan section 2: `load_packaged_catalogue_artifact(path: Path | str, *, on_issue: OnIssue = "warn") -> PackagedCatalogArtifact`.
- Step 03 owns: provider registry, deterministic `rr.providers()`, `rr.provider()`, `rr.provider_info()`, `UnknownProviderError`, registry/provider ID snake_case enforcement, public imports, and offline-import negative-control testing.
- M2 owns: singular `ProviderInfo`, observation request/result, annotation schemas, public `ProviderHandle` Protocol, and provider observation contracts.
- M3 owns: real `ch_foen` artifacts, provider package data, `generate_catalogue.py`, and provider-specific metadata models.

## Verification
- Commit hash: pending; final hash is recorded in the executor handoff response because embedding the final hash in this committed file would change the hash.
- Tag created: pending; expected final tag is `v0.1.6` because `v0.1.5` already existed.
- Diff summary before commit: 10 files changed, 1213 insertions, 5 deletions.
