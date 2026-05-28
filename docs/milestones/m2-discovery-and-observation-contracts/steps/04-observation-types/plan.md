# 04-observation-types Plan

## 1. Goal and scope

Ship the internal observation and annotation contracts in one commit, without retrieval logic or public surface changes:

- Add `ObservationRequest`, a frozen validated record of provider ID, requested station IDs, product IDs, and required typed `start` / `end` temporal values.
- Add `ObservationProvenance`, a retrieval-bookkeeping record that mirrors the `CatalogProvenance` pattern while carrying observation-specific call/window/decomposition fields and never secrets.
- Add `AnnotationSchema`, using the existing `CatalogueColumn` / `CatalogueSchema` pattern for its declaration-table schema while representing architecture §13's per-annotation declaration shape.
- Add `AnnotationTable`, the runtime validated long-form annotation table wrapper.
- Add `RawPayload`, the minimal provider-native raw response slot.
- Add `ObservationResult`, with the exact field set required by tracker §2: `data`, `row_annotations`, `series_annotations`, `provenance`, `issues`, and `raw`.
- Add an annotation-name validator that raises a fatal exception when emitted annotation IDs are not declared by provider schemas.
- Pin the canonical observation long-table schema and validate `ObservationResult.data` against it.
- Extend tests for construction, direct fatal validation, export behavior, annotation validation, public-surface negative control, and offline-import preservation.

This step must not add `_ProviderHandle.observations()`, provider annotation-schema methods, `ProviderModule` observation/annotation members, real retrieval, real provider modules, top-level `rr.observations(...)`, public exports, or wide-form pandas helpers.

Legacy divergence: the legacy base contract allows missing dates and returns a single-variable pandas frame indexed by time (`/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/base.py:17-23`, `:39-42`). `USAFetcher` also defaults missing dates and returns a variable-named column after provider-specific parsing (`/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/usa.py:126-166`). Step 04 deliberately diverges from legacy: `start` and `end` are required fatal contract inputs, Polars is canonical, and the result data is provider-scoped long form with `{time, station_id, product_id, value}`.

## 2. API surface touched (public + internal)

Public surface:

- No new public symbols.
- No `src/rivretrieve/__init__.py` API-shape edit. Only the mandatory version-literal bump is allowed before commit.
- Keep the public names exactly `{"providers", "provider", "provider_info", "stations", "products", "product_info"}` plus `__version__`.
- Extend T23's absence list to include every new internal name and fatal exception name from this step.

Internal surface:

- Add one new file: `src/rivretrieve/_internal/observations.py`.
- Modify `src/rivretrieve/_internal/issues.py` to add fatal exception classes:
  - `InvalidObservationRequestError(FatalContractError)`.
  - `ObservationDataSchemaError(FatalContractError)`.
  - `AnnotationSchemaViolationError(FatalContractError)`.
- Import and reuse `CatalogueColumn`, `CatalogueSchema`, and `validate_catalogue` from `src/rivretrieve/_internal/catalogues/schemas.py`.
- Do not modify `ProviderModule` in this step. Its observation and annotation members remain deferred.
- Do not modify `_ProviderHandle` in this step.

Test-only surface:

- Add focused tests under `tests/test_internal_observations.py`.
- Extend `tests/test_package.py` deferred absence list.
- Extend offline-import tests only if the new imports change the existing sentinel expectations.

## 3. Data structures and types

### ObservationRequest

Recommendation: frozen dataclass.

Fields:

- `provider_id: ProviderId`.
- `stations: tuple[str, ...]`.
- `products: tuple[str, ...]`.
- `start: datetime`.
- `end: datetime`.

Construction:

- Provide `ObservationRequest.from_inputs(*, provider_id: ProviderId | str, stations: str | Sequence[str], products: str | Sequence[str], start: datetime | date | str, end: datetime | date | str) -> ObservationRequest`.
- Validate `provider_id is not None` before any string coercion, then normalize with `ProviderId(str(provider_id))` after validating it is a non-empty string.
- Normalize a single station/product string to a one-element tuple.
- Normalize a non-string station/product sequence to `tuple(value)`.
- Preserve sequence order and duplicates in step 04. Deduplication and product/station availability checks belong to retrieval.
- Coerce `start` and `end` to typed temporal values in the internal request. Use `datetime.datetime` as the stored type: `datetime` values pass through, `date` values become midnight datetimes, and ISO-like strings are parsed with the standard library. Do not use pandas as a new request dependency surface even though pandas is installed for export convenience.
- Do not infer product frequency, period anchoring, timezone meaning, or hydrological time semantics during request construction. Those facts remain product metadata, annotations, provenance, and issues.
- Do not include `on_issue`. It is a downstream recoverable-issue policy knob, not part of what was requested. Step 05 can pass it beside the request when routing provider execution.

Fatal validation:

- `provider_id is None`, non-string-like, or empty after string conversion: `InvalidObservationRequestError`.
- `start is None`: `InvalidObservationRequestError`.
- `end is None`: `InvalidObservationRequestError`.
- `start` or `end` cannot be coerced to `datetime`: `InvalidObservationRequestError`.
- `stations is None`: `InvalidObservationRequestError`.
- `products is None`: `InvalidObservationRequestError`.
- `stations` is not `str` and not a `Sequence`: `InvalidObservationRequestError`.
- `products` is not `str` and not a `Sequence`: `InvalidObservationRequestError`.
- Empty station sequence after normalization: `InvalidObservationRequestError`.
- Empty product sequence after normalization: `InvalidObservationRequestError`.
- Any normalized station/product element is not `str`: `InvalidObservationRequestError`.
- Empty-string station/product IDs after stripping whitespace: `InvalidObservationRequestError`.

Use one exception class for these request cases because the caller response is identical: fix the request before provider execution. Tests can assert message fragments for diagnosis without multiplying fatal types.

### ObservationProvenance

Recommendation: frozen Pydantic `BaseModel`, mirroring `CatalogProvenance` in `src/rivretrieve/_internal/results.py`.

Fields:

- `source: str` or a narrower future literal if a retrieval-source vocabulary is later pinned.
- `provider_id: ProviderId`.
- `rivretrieve_version: str | None = None`.
- `catalogue_version: str | None = None`.
- `requested_at: datetime | None = None`.
- `retrieved_at: datetime | None = None`.
- `request: dict[str, object] | None = None`.
- `calls_made: tuple[dict[str, object], ...] = ()`.
- `time_windows: tuple[dict[str, object], ...] = ()`.
- `decomposition: tuple[str, ...] = ()`.
- `endpoints: tuple[str, ...] = ()`.
- `query: dict[str, object] | None = None`.
- `response_version: str | None = None`.
- `metadata: str | None = None`.

`metadata`, if used, is a JSON object string by the M1 opaque-metadata convention. Provenance records retrieval/build bookkeeping only: URLs, call summaries, request parameters, request decomposition, returned windows, status/query metadata, and response versions. `time_windows` and `decomposition` are step-04 plan-of-record additions justified by architecture §17's split/stitch provenance needs, not direct field-name quotes from §14. Scientific metadata such as units, timezone facts, quality flags, period anchoring, native datum, and provider QC fields belong in product metadata or annotations.

### AnnotationSchema

Recommendation: frozen dataclass representing one provider-declared annotation, as architecture §13 intends.

Fields:

- `annotation_id: str`.
- `description: str`.
- `value_type: str`.
- `allowed_values: tuple[str, ...] | None = None`.
- `source_field: str | None = None`.

Validation:

- `annotation_id` is a non-empty string.
- `description` is a string.
- `value_type` is a non-empty string. Step 04 should use a small allowed vocabulary such as `{"string", "integer", "float", "boolean", "datetime", "json"}` unless existing docs already pin a different vocabulary.
- `allowed_values`, when present, is a tuple of strings.
- `source_field`, when present, is a non-empty string.

Schema-representation tie to M1 step 02:

- Define `AnnotationSchemaDeclaration = CatalogueSchema(...)` with columns `annotation_id`, `description`, `value_type`, `allowed_values`, and `source_field`.
- Use `CatalogueColumn` for those declaration columns. Store `allowed_values` as a JSON object/array string column if a table view is needed; the dataclass exposes it as `tuple[str, ...] | None`.
- Provide `AnnotationSchema.to_row() -> dict[str, object]` and optional `AnnotationSchema.from_row(row: Mapping[str, object]) -> AnnotationSchema` through `AnnotationSchemaDeclaration` if needed for tests.
- Do not define `AnnotationColumn`. Reuse `CatalogueColumn` directly for declaration-schema columns and for annotation table schemas.

This keeps the provider-returned `list[AnnotationSchema]` as a list of per-annotation declarations. It does not invert the architecture into a whole-table declaration with an allowed-name set.

### AnnotationTable

Recommendation: frozen dataclass wrapper, not a type alias.

Fields:

- `data: pl.DataFrame`.
- `schema: CatalogueSchema`.

Construction should validate `data` against the supplied table schema with `on_issue="raise"` and raise `AnnotationSchemaViolationError` for malformed tables. The wrapper binds a runtime frame to the table shape it satisfies while keeping provider declarations as `list[AnnotationSchema]`.

Recommended fixed table-schema constants:

- `RowAnnotationTableSchema = CatalogueSchema(...)`.
- `SeriesAnnotationTableSchema = CatalogueSchema(...)`.

Row annotation columns:

- `time: pl.Datetime`, non-null. Do not force a fixed timezone. Providers preserve native timestamps by default and record timezone facts in series annotations.
- `station_id: pl.Utf8`, non-null.
- `product_id: pl.Utf8`, non-null.
- `annotation: pl.Utf8`, non-null. Values are provider-declared `AnnotationSchema.annotation_id`.
- `value: pl.Utf8`, nullable.

Series annotation columns:

- `station_id: pl.Utf8`, non-null.
- `product_id: pl.Utf8`, non-null.
- `annotation: pl.Utf8`, non-null. Values are provider-declared `AnnotationSchema.annotation_id`.
- `value: pl.Utf8`, nullable.

The table column names deliberately match architecture §12: `annotation` and `value`, not `annotation_name` and `annotation_value`. Step 04 validates table shape and declaration membership. Rich `value_type` / `allowed_values` enforcement is explicitly deferred to a later validation layer because the tracker exit criterion for this step is undeclared-name failure.

The wrapper asymmetry is intentional: `ObservationResult.data` remains a bare `pl.DataFrame` because tracker §2 and the public result shape require `data` directly, and `ObservationResult` validates it against `ObservationDataSchema` at construction. An `ObservationTable` wrapper would add indirection without changing behavior in this step.

### RawPayload

Recommendation: frozen dataclass with minimal payload metadata.

Fields:

- `provider_id: ProviderId`.
- `content_type: str | None = None`.
- `content: bytes | str | None = None`.
- `metadata: str | None = None`.

`metadata`, if present, is a JSON object string. `content` is provider-native bytes for binary payloads and text for JSON/text responses; `content_type` distinguishes them. `RawPayload` is optional at the result level; `ObservationResult.raw` should be `RawPayload | None`. This supports the M2 stub case with `raw=None` and lets M3/M4 preserve small native payloads without committing to provider-specific subclasses or arbitrary mappings.

### ObservationResult

Recommendation: frozen Pydantic `BaseModel`.

Model config:

- `ConfigDict(frozen=True, arbitrary_types_allowed=True)`, because `pl.DataFrame` is an arbitrary runtime type.

Fields exactly:

- `data: pl.DataFrame`.
- `row_annotations: AnnotationTable`.
- `series_annotations: AnnotationTable`.
- `provenance: ObservationProvenance`.
- `issues: tuple[Issue, ...] = ()`.
- `raw: RawPayload | None = None`.

Validation:

- `data` must be a `pl.DataFrame`.
- `data` must satisfy the canonical observation schema.
- `row_annotations` and `series_annotations` are already validated wrappers.
- Schema violations raise `ObservationDataSchemaError` directly.

Methods:

- `to_polars() -> pl.DataFrame`: return `self.data`.
- `to_pandas() -> pandas.DataFrame`: return `self.data.to_pandas()` and do no reshaping, widening, renaming, unit conversion, or annotation merge.

### Canonical observation long-table schema

Recommendation: define a free constant using the existing schema infrastructure:

- `ObservationDataSchema = CatalogueSchema(...)`.

Columns:

- `time: pl.Datetime`, non-null.
- `station_id: pl.Utf8`, non-null.
- `product_id: pl.Utf8`, non-null.
- `value: pl.Float64`, nullable.

No `provider_id`: provider-scope observation rows do not require it under tracker §2 L25. No quality flag, unit, timezone-original, endpoint, native code, or status columns: those belong in annotations/provenance/product metadata. `value` is nullable so providers can represent explicit missing observations without inventing a quality column; absence of rows remains the natural representation for no returned observations.

Do not force UTC in step 04. The schema should accept Polars datetime values without mandating a fixed timezone. Providers preserve native timestamps by default; timezone facts and any conversion belong in series annotations and issues under architecture §16. If Polars equality against `pl.Datetime` proves too strict for mixed timezone-aware/naive frames, implement `validate_observation_data` with a deliberate datetime-kind check for the `time` column rather than pretending all providers emit UTC.

`validate_observation_data` must keep fatal schema failures out of the recoverable issue channel. In particular, detect extra columns directly before calling `validate_catalogue` and raise `ObservationDataSchemaError` without exception chaining. Do not let `validate_catalogue(..., on_issue="raise")` turn extra columns into `IssuePolicyError` in the cause/context chain.

### Annotation-name validator

Recommendation: free function:

`validate_annotation_names(table: AnnotationTable, schemas: Sequence[AnnotationSchema]) -> None`.

Behavior:

- Union `annotation_id` values from the supplied schemas.
- Read unique values from `table.data["annotation"]`.
- Raise `AnnotationSchemaViolationError` if any emitted annotation ID is absent from the declared set.
- Raise directly regardless of `on_issue`; undeclared names are a provider-side contract violation.
- Scope is name/declaration membership only in step 04. Validation of table values against each schema's `value_type` and `allowed_values` is deferred to a later debug/provider validation layer unless the executor can add it without broadening scope.

Step 05's handle call site can validate row annotations against `provider.row_annotation_schema()` and series annotations against `provider.series_annotation_schema()` with the same function. A method on `AnnotationTable` would force table instances to know provider declarations, and a method on one `AnnotationSchema` would be awkward because providers return a sequence of per-annotation declarations.

## 4. Errors and failure modes

Fatal direct raises, never routed through `apply_on_issue`:

- Missing or malformed `provider_id`, `start`, or `end`: `InvalidObservationRequestError`.
- Missing, wrong-type, empty, or malformed `stations` / `products`: `InvalidObservationRequestError`.
- Invalid `AnnotationSchema` construction, malformed `AnnotationTable`, or undeclared emitted annotations: `AnnotationSchemaViolationError`.
- Malformed `ObservationResult.data`: `ObservationDataSchemaError`.
- Wrong `ObservationResult.data` type: `ObservationDataSchemaError`.
- Any `validate_catalogue(..., on_issue="raise")` failure used inside observation/annotation validation should be wrapped in the relevant fatal subclass with exception chaining.

Issue-routed paths:

- None are introduced in step 04.
- `ObservationRequest` does not accept `on_issue`.
- Tests should still parametrize fatal cases over `on_issue in ("warn", "raise", "ignore")` by calling helper functions or wrapper paths that ignore the policy, proving `_issue_policy_error_chain(exc) == []`.

Two-channel guardrail:

- Do not create `Issue` objects for request validation, annotation declaration failures, undeclared emitted annotations, or observation-data schema failures.
- Do not call `apply_on_issue` for these fatal contracts.
- Downstream recoverable observation issues such as gaps, conflicts, fallback sources, and partial data are deferred to step 05/M4.

## 5. Tests (enumerated, one-line each; include negative controls)

Step 03 ended at T45. Step 04 starts at T46 and should add about 34-38 test functions, depending on how much the executor collapses policy matrices with parametrization:

T46. `test_observation_request_from_single_station_product_normalizes_to_tuples`: single strings become one-element tuples and provider ID is preserved.

T47. `test_observation_request_from_sequences_preserves_order`: multiple station/product IDs normalize to tuples in caller order.

T48. `test_observation_request_coerces_typed_temporal_inputs`: datetime, date, and ISO-like strings become stored `datetime` values.

T49. `test_observation_request_rejects_missing_provider_id_for_every_on_issue`: missing provider ID raises `InvalidObservationRequestError` across warn/raise/ignore policy values with no `IssuePolicyError` chain.

T50. `test_observation_request_rejects_missing_start_for_every_on_issue`: `start=None` raises direct fatal across policy values.

T51. `test_observation_request_rejects_missing_end_for_every_on_issue`: `end=None` raises direct fatal across policy values.

T52. `test_observation_request_rejects_unparseable_temporal_values`: unparseable start/end inputs raise direct fatal.

T53. `test_observation_request_rejects_missing_stations_for_every_on_issue`: `stations=None` raises direct fatal across policy values.

T54. `test_observation_request_rejects_missing_products_for_every_on_issue`: `products=None` raises direct fatal across policy values.

T55. `test_observation_request_rejects_empty_station_sequence_for_every_on_issue`: empty station sequence raises direct fatal.

T56. `test_observation_request_rejects_empty_product_sequence_for_every_on_issue`: empty product sequence raises direct fatal.

T57. `test_observation_request_rejects_non_string_and_empty_ids`: representative non-string IDs and empty-string station/product IDs raise direct fatal.

T58. `test_observation_provenance_constructs_without_scientific_metadata`: bookkeeping fields freeze and do not require units/timezone/QC fields.

T59. `test_observation_provenance_metadata_may_be_json_string`: optional opaque metadata string is preserved.

T60. `test_annotation_schema_constructs_per_annotation_declaration`: one declaration stores `annotation_id`, `description`, `value_type`, `allowed_values`, and `source_field`.

T61. `test_annotation_schema_declaration_reuses_catalogue_schema_pattern`: declaration rows validate through `AnnotationSchemaDeclaration` built from `CatalogueColumn`.

T62. `test_annotation_schema_rejects_invalid_annotation_id`: empty/non-string annotation IDs raise `AnnotationSchemaViolationError`.

T63. `test_annotation_schema_rejects_invalid_value_type`: unsupported or empty value types raise direct fatal.

T64. `test_annotation_table_validates_row_annotation_shape`: valid row annotation data with `time, station_id, product_id, annotation, value` constructs an `AnnotationTable`.

T65. `test_annotation_table_validates_series_annotation_shape`: valid series annotation data with `station_id, product_id, annotation, value` constructs an `AnnotationTable`.

T66. `test_annotation_table_rejects_missing_required_column`: malformed annotation data raises `AnnotationSchemaViolationError`.

T67. `test_annotation_table_rejects_wrong_dtype`: dtype mismatch raises `AnnotationSchemaViolationError`.

T68. `test_validate_annotation_names_accepts_declared_annotation_ids`: emitted annotations declared by the supplied schemas pass.

T69. `test_validate_annotation_names_rejects_undeclared_annotations_for_every_on_issue`: undeclared emitted annotations raise `AnnotationSchemaViolationError` across warn/raise/ignore with no `IssuePolicyError` chain.

T70. `test_validate_annotation_names_accepts_multiple_provider_schemas`: declarations are unioned across schemas.

T71. `test_raw_payload_constructs_minimal_payload`: minimal provider ID plus optional content fields freeze.

T72. `test_observation_data_schema_accepts_canonical_long_table`: valid `{time, station_id, product_id, value}` Polars frame validates.

T73. `test_observation_data_schema_accepts_native_datetime_without_utc_mandate`: the validator accepts the planned non-UTC/non-forced datetime dtype for `time`.

T74. `test_observation_data_schema_rejects_provider_id_column_as_extra_under_raise`: extra `provider_id` is not part of canonical provider-scope observations and raises through the schema-validation wrapper as `ObservationDataSchemaError`.

T75. `test_observation_data_schema_rejects_missing_column`: missing canonical column raises `ObservationDataSchemaError`.

T76. `test_observation_data_schema_rejects_wrong_dtype`: time/value/string dtype violations raise `ObservationDataSchemaError`.

T77. `test_observation_data_schema_rejects_null_identity_columns`: null time/station/product raises `ObservationDataSchemaError`.

T78. `test_observation_data_schema_allows_null_value`: nullable values are accepted.

T79. `test_observation_result_constructs_with_exact_field_set`: valid result preserves data, annotations, provenance, issues, and raw.

T80. `test_observation_result_to_polars_returns_data_identity`: `result.to_polars() is result.data`.

T81. `test_observation_result_to_pandas_matches_polars_boundary_conversion`: use `pandas.testing.assert_frame_equal(result.to_pandas(), result.data.to_pandas())`.

T82. `test_observation_result_rejects_schema_violation_for_every_on_issue`: malformed data raises direct fatal across policy values with no `IssuePolicyError` chain.

T83. `test_init_public_surface_still_excludes_observation_internal_names`: extend T23 for all new names.

If test count pressure is high, combine T49-T57 and T74-T77 with parametrization while preserving the T-number intent in comments or test names.

## 6. Files (new + modified, in implementation order keeping pytest green at each)

1. Modify `src/rivretrieve/_internal/issues.py` to add `InvalidObservationRequestError`, `ObservationDataSchemaError`, and `AnnotationSchemaViolationError`. Run `uv run pytest`.
2. Add `src/rivretrieve/_internal/observations.py` with `ObservationDataSchema`, `ObservationRequest`, and request normalization/coercion helpers only. Run `uv run pytest`.
3. Add `tests/test_internal_observations.py` request tests T46-T57, using the existing `_issue_policy_error_chain` helper pattern from discovery/catalogue tests. Run `uv run pytest`.
4. Extend `observations.py` with `ObservationProvenance` and `RawPayload`. Run `uv run pytest`.
5. Add T58-T59 and T71. Run `uv run pytest`.
6. Extend `observations.py` with `AnnotationSchema`, `AnnotationSchemaDeclaration`, `RowAnnotationTableSchema`, `SeriesAnnotationTableSchema`, `AnnotationTable`, and `validate_annotation_names`. Run `uv run pytest`.
7. Add T60-T70. Run `uv run pytest`.
8. Extend `observations.py` with required `validate_observation_data`, plus `ObservationResult.to_polars()` and `.to_pandas()`. `ObservationResult` must call `validate_observation_data` during construction. Run `uv run pytest`.
9. Add T72-T82, using `polars.testing.assert_frame_equal` and `pandas.testing.assert_frame_equal` rather than manual element-wise checks. Run `uv run pytest`.
10. Modify `tests/test_package.py` T23 absence list to include `ObservationDataSchema`, `RowAnnotationTableSchema`, `SeriesAnnotationTableSchema`, `AnnotationSchemaDeclaration`, `ObservationRequest`, `ObservationProvenance`, `AnnotationSchema`, `AnnotationTable`, `RawPayload`, `ObservationResult`, `InvalidObservationRequestError`, `ObservationDataSchemaError`, and `AnnotationSchemaViolationError`. Run `uv run pytest`.
11. Extend `tests/test_offline_import.py` only if the new internal module changes sentinel imports; otherwise leave it unchanged and run `uv run pytest`.
12. Run `uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`, and `uv run pytest`.
13. Run `uv run bump-my-version bump patch`, stage the revised plan plus code/test/version changes, commit, and tag `v$(uv run bump-my-version show current_version)` per project instructions.

## 7. Open questions (with recommendation per question)

Q1. ObservationRequest representation: Pydantic model or frozen dataclass?

Recommendation: frozen dataclass with a validating `from_inputs` constructor. Project precedent uses frozen dataclasses for row/result/schema contracts (`ProviderInfo`, catalogue schemas) and Pydantic for diagnostic/result envelopes. `ObservationRequest` is a normalized internal value object, not a user-facing validation model. Explicit validation also makes direct fatal errors clear and keeps `on_issue` out of the object.

Q2. ObservationRequest field types and `on_issue`.

Recommendation: include `provider_id: ProviderId`, normalize `stations` and `products` to `tuple[str, ...]`, store `start` and `end` as typed `datetime` values, and keep `on_issue` separate. The public handle may accept `str | Sequence[str]` and timestamp-like values; the internal request should be immutable, provider-aware, and typed. Timezone/period semantics are not inferred here.

Q3. ObservationRequest fatal validation paths and exception names.

Recommendation: one fatal class, `InvalidObservationRequestError(FatalContractError)`, for missing/malformed provider ID, missing/unparseable dates, missing/empty station/product collections, wrong collection types, non-string IDs, and empty-string IDs. Multiple subclasses would add test and API surface without changing caller behavior.

Q4. AnnotationSchema shape.

Recommendation: `AnnotationSchema(annotation_id, description, value_type, allowed_values=None, source_field=None)`, a per-annotation declaration matching architecture §13. Reuse the M1 step 02 pattern by defining `AnnotationSchemaDeclaration = CatalogueSchema(...)` with `CatalogueColumn` objects for the declaration table, not by making `AnnotationSchema` a whole-table allowed-name set. Do not define `AnnotationColumn`.

Q5. AnnotationTable shape.

Recommendation: frozen dataclass wrapping `pl.DataFrame` plus the `CatalogueSchema` table shape it satisfies. A typed alias is too weak because validation needs the bound row/series table schema; a wrapper keeps step 05 result construction straightforward and preserves Polars as the underlying table.

Q6. RawPayload shape.

Recommendation: minimal frozen dataclass with `provider_id`, `content_type`, `content`, and optional JSON-string `metadata`, while `ObservationResult.raw` is nullable. `content` is bytes for binary payloads and text for JSON/text responses. Avoid `Mapping[str, object]` because it has no contract, and avoid provider subclassing until `ch_foen` supplies concrete needs.

Q7. Annotation-name validator location.

Recommendation: free function `validate_annotation_names(table, schemas) -> None` in `observations.py`. Step 05 can call it for row and series annotations using provider-declared schemas. It avoids making `AnnotationTable` provider-aware and avoids forcing callers to pick one schema when declarations are a sequence of per-annotation declarations.

Q8. Fatal exception for undeclared annotation names.

Recommendation: `AnnotationSchemaViolationError(FatalContractError)` in `issues.py`. It covers undeclared names and malformed annotation tables without introducing a separate exception per schema failure. `UndeclaredAnnotationError` is narrower but would still need a table-schema companion; one contract-violation class is cleaner.

Q9. Canonical observation long-table schema.

Recommendation: `ObservationDataSchema = CatalogueSchema(...)` in `observations.py` with exactly `time`, `station_id`, `product_id`, and `value`. Use a Polars datetime dtype for `time` without a fixed UTC mandate, and allow null `value` only. Do not add provider ID, quality flags, units, native codes, timezone columns, or `timestamp`; those belong elsewhere by tracker and architecture invariants.

Q10. File layout.

Recommendation: single file `src/rivretrieve/_internal/observations.py`. The six types are tightly coupled and should land together. Split only if the implementation grows beyond roughly 300-400 lines or imports become cyclic; step 04 should not create a package hierarchy prematurely.

Q11. Test inventory.

Recommendation: T46-T83, about 34 test functions after parametrization. The inventory covers request construction/fatals, provenance/raw construction, schema declaration/table validation, annotation-name validation, canonical data schema validation, result exports, public-surface absence, and direct-fatal negative controls.

Q12. `on_issue` interactions.

Recommendation: every step-04 fatal path raises directly regardless of `on_issue`. Because `ObservationRequest` does not carry `on_issue`, tests should parametrize a local policy variable or helper wrapper over `"warn"`, `"raise"`, and `"ignore"` and assert the same fatal exception with `_issue_policy_error_chain(exc) == []`. Do the same for undeclared annotations and observation-data schema violations.

## 8. Deferrals (with hard rationale: which later step or milestone handles each)

- `_ProviderHandle.observations()` method body: M2 step 05. Hard rationale: step 04 creates the request/result contracts only.
- `_ProviderHandle.row_annotation_schema()` and `.series_annotation_schema()`: M2 step 05. Hard rationale: provider declaration methods wire to `AnnotationSchema` after this type exists.
- `ProviderModule` observation/annotation members: M2 step 05. Hard rationale: this step must not alter provider-module protocol shape.
- Public `ProviderHandle` Protocol promotion and `rr.provider()` return narrowing: M2 step 05 or 06. Hard rationale: public handle must expose the full behavior coherently.
- Promoting `ObservationResult`, `ObservationRequest`, or annotation types to `rivretrieve.__init__`: later M2/M4 public surface decision. Hard rationale: step 04 has no public surface change.
- Real observation retrieval and provider dispatch: M4. Hard rationale: this step is contract-only and no provider execution exists.
- Real provider modules and `ch_foen`: M3+. Hard rationale: tests remain stub/internal only.
- Top-level `rr.observations(...)`: M4. Hard rationale: it must delegate to provider observations after that method exists.
- Wide-form pandas helpers: permanently deferred per tracker §19. Hard rationale: `to_pandas()` is long-form boundary conversion only.
- Full annotation value validation against `value_type` and `allowed_values`: later debug/provider validation, unless an executor can add it narrowly inside step 04. Hard rationale: the tracker exit criterion for this step is undeclared annotation-name failure.
- Observation schema fields beyond `{time, station_id, product_id, value}`: deferred unless tracker/architecture changes. Hard rationale: quality, unit, timezone, endpoint, and native-source facts belong in annotations/provenance/product metadata.
- D2 queued architecture §7/§9 addenda: coordinator work before M3 unless a contradiction appears. Hard rationale: step 04 can execute within current tracker invariants after the critique fixes above.

## 9. Stopping conditions for the executor

Stop and surface if any of these happen:

- Implementing this step requires adding `_ProviderHandle.observations()` or any handle method body.
- Implementing this step requires adding `row_annotation_schema`, `series_annotation_schema`, or `observations` to `ProviderModule`.
- Any observation or annotation contract is exported from `src/rivretrieve/__init__.py`.
- Annotation schemas require an `AnnotationColumn` or any parallel replacement for `CatalogueColumn` / `CatalogueSchema`.
- `AnnotationSchema` starts representing a whole table plus a set of names instead of one per-annotation provider declaration.
- The canonical observation table needs `provider_id` at provider-scope row level.
- The canonical observation table uses `timestamp` instead of `time`.
- Annotation tables use `annotation_name` / `annotation_value` instead of `annotation` / `value`.
- Internal `ObservationRequest` cannot carry `provider_id` or typed temporal values.
- Observation validation forces UTC conversion or rejects provider-native datetime values solely because they are not UTC.
- Any fatal validation path is routed through `apply_on_issue`, encoded as an `Issue`, or silenceable under `on_issue="ignore"`.
- `to_pandas()` needs reshaping, widening, joining annotations, unit conversion, or any transformation beyond `self.data.to_pandas()`.
- `RawPayload` needs secrets, credentials, auth headers, or unbounded provider objects.
- Observation provenance starts carrying scientific metadata such as units, timezone facts, QC flags, or datum semantics.
- Real provider modules, network I/O, or legacy `_download_data` / `_parse_data` behavior enter the implementation.
- T25's stub catalogue functions stop raising `NotImplementedError`.
- D2's queued architecture addenda become necessary for step-04 correctness rather than documentation cleanup.
- Any intermediate implementation order leaves `uv run pytest` failing or `import rivretrieve` broken.
