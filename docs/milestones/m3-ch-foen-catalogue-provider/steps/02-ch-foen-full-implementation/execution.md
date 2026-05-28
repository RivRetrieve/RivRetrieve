# 02-ch-foen-full-implementation Execution

## 1. What was implemented

Implemented `ch_foen` end-to-end as a catalogue-only provider under `src/rivretrieve/_internal/providers/ch_foen/`. The step adds internal metadata models, an offline/livable maintainer generator, committed Existenz.ch fixture data, four packaged catalogue artifacts, an unregistered provider module with placeholder observations, lazy default registration, all-false capability declarations, and focused tests for metadata, generation, module behavior, registration, capabilities, offline import, and public-surface non-leakage.

## 2. Files changed

### 6A

- `src/rivretrieve/_internal/providers/ch_foen/__init__.py` -> internal provider package marker.
- `src/rivretrieve/_internal/providers/ch_foen/metadata.py` -> three internal Pydantic metadata models.
- `tests/test_ch_foen_metadata.py` -> model validation, nullable-field, and `extra="allow"` tests.

### 6B

- `tests/test_data/switzerland_metadata_locations.json` -> legacy Existenz.ch hydro locations fixture from `origin/switzerland`.
- `src/rivretrieve/_internal/providers/ch_foen/generate_catalogue.py` -> maintainer generator for provider, product, station, and station-product catalogues.
- `tests/test_ch_foen_generate_catalogue.py` -> fixture binding, generator validation, fatal-path, and artifact-write tests.

### 6C

- `src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json` -> generated provider info row.
- `src/rivretrieve/_internal/providers/ch_foen/catalogue/products.parquet` -> generated six-product catalogue.
- `src/rivretrieve/_internal/providers/ch_foen/catalogue/stations.parquet` -> generated 246-station catalogue.
- `src/rivretrieve/_internal/providers/ch_foen/catalogue/station_products.parquet` -> generated 1476-row availability matrix.

### 6D

- `src/rivretrieve/_internal/providers/ch_foen/module.py` -> ProviderModule-conformant catalogue functions, empty annotation schemas, and non-raising placeholder observations.
- `tests/test_ch_foen_module.py` -> module, catalogue, annotation, and placeholder observation tests.

### 6E

- `src/rivretrieve/_internal/discovery.py` -> lazy default-provider registration with `_DEFAULT_PROVIDER_REGISTRATION_ENABLED`.
- `tests/test_ch_foen_registration.py` -> public discovery, provider handle, metadata non-leak, and offline-import checks.
- `tests/test_discovery.py` -> singleton registry tests updated for default registration or private disable.
- `tests/test_m1_exit_criteria.py` -> isolated legacy registry expectation under private disable.
- `tests/test_m2_exit_criteria.py` -> isolated legacy registry expectation under private disable.
- `tests/test_offline_import.py` -> extended to forbid `_internal.providers` imports at `import rivretrieve` time.

### 6F

- `tests/test_ch_foen_capabilities.py` -> all-false capability and `source="live"` unsupported-routing tests.

### Docs

- `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md` -> amended in place for `_internal/providers/ch_foen/` path migration.
- `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/critique.md` -> critique of record staged with the step.
- `docs/discoveries.md` -> D6 through D9 added.

## 3. Tests run and results

- `uv run ruff format` -> passed (`44 files left unchanged`).
- `uv run ruff check --fix` -> passed (`All checks passed!`).
- `uv run ty check` -> passed (`All checks passed!`).
- `uv run pytest` -> passed (`369 passed in 1.15s`).
- Explicit T117/T119/T120 plus metadata-leak invocation -> passed (`4 passed`).
- Manual offline-import probe -> passed (`offline-import OK`).
- Manual fixture-binding probe -> passed (`246`, `Brugg`).
- Manual provider discovery/station-products probe -> passed (`['ch_foen']`, `1476`).
- Manual generator invocation -> passed and produced all four packaged artifacts.

## 4. Deviations from plan

None from the amended plan's scope or ordering. The implementation follows Amendment 1 by placing the provider under `src/rivretrieve/_internal/providers/ch_foen/`; this path change is the plan of record for execution.

## 5. Surprises

Python import mechanics made the original `rivretrieve.providers.ch_foen` path shadow the public `rr.providers()` callable, which triggered Amendment 1 and D6. During execution, type-checking also exposed two test/parser-shape issues: Pydantic `extra="allow"` extras should be asserted via `model_validate({...})`, and JSON parser shape checks should use concrete `dict` checks plus local casts where ty cannot preserve key/value types. The generator also surfaced the provider-info metadata serialization obligation from the M1/M2 catalogue contract.

## 6. Discoveries

- D6 -> provider subpackage path shadowed public callable `rr.providers`.
- D7 -> Pydantic `extra="allow"` constructor kwargs trip ty; use `model_validate(dict)` for extras assertions in tests.
- D8 -> catalogue contracts use asymmetric encodings; generator-side serialization obligations need round-trip review.
- D9 -> `isinstance(x, Mapping)` erases generics under ty; use `dict` for JSON-loaded data.

## 7. Hand-off notes for step 03

Step 03 should document the provider port at the amended `_internal/providers/ch_foen/` path and include the Q12 background: upstream still carries a literal `INFLUX_TOKEN` at `origin/switzerland:rivretrieve/switzerland.py:40` and uses it in the observation Authorization header, but M3 step 02 intentionally carries no token because it is catalogue-only. The provider info metadata is a deterministic JSON string in the packaged artifact, matching the current catalogue schema wire contract.
