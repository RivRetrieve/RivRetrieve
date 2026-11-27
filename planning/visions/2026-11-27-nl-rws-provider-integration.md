# Vision: Netherlands (`nl_rws`) Provider Integration (Step 5)

- **Effort:** [#1052](https://github.com/RivRetrieve/RivRetrieve/issues/1052)
- **Coordination:** [#355](https://github.com/RivRetrieve/RivRetrieve/issues/355) (tracker [#870](https://github.com/RivRetrieve/RivRetrieve/issues/870))
- **Target branch:** `port/nl-rws` (never merge to `main` until Step 8 [#1055](https://github.com/RivRetrieve/RivRetrieve/issues/1055))
- **Depends on:**
  - Step 1 ([#1048](https://github.com/RivRetrieve/RivRetrieve/issues/1048)): `planning/visions/2026-11-25-nl-rws-source-scope-and-access.md`
  - Step 2 ([#1049](https://github.com/RivRetrieve/RivRetrieve/issues/1049)): `planning/visions/2026-11-25-nl-rws-station-catalogue-and-metadata.md`
  - Step 3 ([#1050](https://github.com/RivRetrieve/RivRetrieve/issues/1050)): `planning/visions/2026-11-26-nl-rws-series-identity-and-physical-meaning.md`
  - Step 4 ([#1051](https://github.com/RivRetrieve/RivRetrieve/issues/1051)): `planning/visions/2026-11-26-nl-rws-retrieval-behavior.md`

## Goal

Connect the Netherlands Rijkswaterstaat (`nl_rws`) packaged catalogue, series
identity and annotation schema, and DDAPI 2.0 retrieval stages (`config.py`,
`fetch.py`, `parse.py`) into RivRetrieve's shared engine and built-in provider
manifest so that all 10 admitted `nl_rws` products work end-to-end through the
public discovery (`rr.providers()`, `rr.products()`, `rr.find()`,
`rr.metadata()`, `rr.describe()`) and retrieval (`rr.fetch()`) APIs, with full
shared contract compliance and focused source-independent integration tests.

## Scope and Design Decisions

### 1. Provider declaration (`src/rivretrieve/_internal/providers/nl_rws/declaration.py`)

Expose a `LiveStages` `ProviderDeclaration` following the `at_ehyd` pattern for
providers with `SharedAcquisitionProvider` and `SharedParseProvider`:

- `_Stages` class exposing:
  - `observation_source = "live"`
  - `config = config()`
  - `window_declarations = window_declarations()`
  - `shared_acquisition_products = SHARED_ACQUISITION_PRODUCTS` (the three
    `frozenset[ProductId]` `(NVT, GEM24H)` pairs)
  - `fetch = staticmethod(fetch)`
  - `parse = staticmethod(parse)`
  - `parse_group = staticmethod(parse_group)`
- `declaration = ProviderDeclaration(catalogue=Path(__file__).with_name("catalogue"), observations=LiveStages(stages=_Stages), required_credentials=())`
- No credentials (`required_credentials = ()`), no `credential_headers`, no
  `credential_exchange`, and no `public_archive_access` (DDAPI 2.0 is a live
  public API with no authentication).
- Observation annotations (`NL_RWS_OBSERVATION_SCHEMA` from `annotations.py`)
  are emitted directly via `AnnotationBundle` in `parse.py` and carried through
  the engine's assembly pipeline without extra manifest registration.

### 2. Built-in manifest and catalogue gate enrollment

Register `"nl_rws"` in:

1. `src/rivretrieve/_internal/provider_manifest.py`: add `"nl_rws"` to
   `BUILTIN_PROVIDER_IDS` (alphabetical order, between `"lt_lhmt"` and
   `"no_nve"`).
2. `src/rivretrieve/_internal/catalogue_origins.py`: add `ProviderId("nl_rws")`
   to `ORIGIN_GATE_ENROLLED_PROVIDERS` (required by
   `test_internal_catalogue_origins.py` and
   `test_catalogue_origin_certification.py` whenever a provider joins
   `BUILTIN_PROVIDER_IDS`).
3. `src/rivretrieve/_internal/catalogues/artifact.py`: add `"nl_rws"` to
   `ACQUISITION_PROVENANCE_ENROLLED_PROVIDERS` (matching the v3
   `provenance.json` packaged in Step 2).

Update the shared contract test lists that enumerate built-in/enrolled
providers (`tests/test_discovery.py`, `tests/test_internal_catalogue_origins.py`,
`tests/test_catalogue_origin_certification.py`, `tests/test_catalogue_evidence.py`,
`tests/test_packaging_carries_catalogues.py`, and any other
`BUILTIN_PROVIDER_IDS`-coupled contract tests) so the full shared `--logic-only`
test suite stays green on `port/nl-rws`.

### 3. Source-independent integration tests (`tests/test_nl_rws_integration.py`)

Verify `nl_rws` end-to-end through RivRetrieve's public APIs using an injected
fake `Transport` (zero network calls):

- **Public discovery:**
  - `rr.providers()` includes `"nl_rws"` with `credentials=[]` and
    `access="open"`.
  - `rr.products(provider="nl_rws")` returns all 10 admitted products.
  - `rr.find(provider="nl_rws", ...)` resolves the 1,706 packaged stations
    (including `lobith.bovenrijn.tolkamer`) and their products cleanly, and
    `rr.metadata(...)` returns packaged station metadata.
  - `rr.describe("nl_rws")` returns the packaged `croissant.json` descriptor
    (carrying `Rijkswaterstaat` / `CC0-1.0` metadata).
- **Public retrieval (`rr.fetch()` via `driver.drive`):**
  - **Canonical unit conversion:** `stage_nap_nvt` (`cm → m`),
    `discharge_m3d_nvt` (`m3/d → m3/s`), and `water_temperature_nvt`
    (`oC → degC`).
  - **Joint `NVT` + `GEM24H` co-acquisition:** requesting `discharge_m3s_nvt`
    and `discharge_m3s_gem24h` on a short window issues a single `POST` without
    `WaardeBewerkingsMethode` and decodes both products via `parse_group()`.
  - **Multi-station partial failure isolation:** an HTTP 400 failure on one
    station surfaces `OutcomeStatus.FAILED` while a healthy station in the same
    `rr.fetch()` succeeds and returns observations.
  - **Missing-value sentinels and annotations:** `Kwaliteitswaardecode = "99"`
    / `9.99999e+37` produces `value = None` alongside valid numeric values
    (including `0.0` and negative stage values), linked to the
    `nl_rws.observation` annotation table (`statuswaarde`,
    `kwaliteitswaardecode`).
  - **Parallel `WaardeBepalingsMethode` series:** distinct measurement methods
    (e.g. `other:F216` vs `other:F230`) remain separate series through engine
    assembly without collapsing.
  - **Empty window / HTTP 204:** returns an empty observation frame with
    `OutcomeStatus.NO_MATCH` (not a failure).

### 4. Ad-hoc live smoke check (not committed)

Before merging Step 5, run an ad-hoc live smoke check (outside committed tests)
using `rr.find(provider="nl_rws", ...)` and `rr.fetch(...)` against live
Rijkswaterstaat DDAPI 2.0 on `lobith.bovenrijn.tolkamer`:
- Joint `discharge_m3s_nvt` + `discharge_m3s_gem24h` over a short window
  (verifying live co-acquisition, parallel `WaardeBepalingsMethode` separation,
  and `nl_rws.observation` annotations).
- `stage_nap_nvt` over a short window (verifying live `cm → m` conversion).

All committed tests remain strictly offline (`--logic-only`).

### 5. Explicitly deferred to Step 6 ([#1053](https://github.com/RivRetrieve/RivRetrieve/issues/1053)) and Step 7 ([#1054](https://github.com/RivRetrieve/RivRetrieve/issues/1054))

- **Step 6 (`#1053` Verification):** Recorded-response observation verification
  against genuine retained DDAPI 2.0 responses, cache/store round-trip tests,
  wheel/sdist packaging checks, and the manual E-STREAMS external sanity
  comparison (never auto-download E-STREAMS).
- **Step 7 (`#1054` User documentation):** Author `docs/providers/nl_rws.md`
  (including explicit documentation of `Kwaliteitswaardecode = "99"` /
  `9.99999e+37` missing-value behavior and `statuswaarde` /
  `kwaliteitswaardecode` annotations).

## Evidence of Completion

1. `src/rivretrieve/_internal/providers/nl_rws/declaration.py` implemented and
   registered in `provider_manifest.py`, `catalogue_origins.py`, and
   `catalogues/artifact.py` on `port/nl-rws`.
2. `tests/test_nl_rws_integration.py` passes alongside all updated shared
   contract tests (`test_discovery.py`, `test_provider_declaration.py`,
   `test_catalogue_description.py`, `test_internal_catalogue_origins.py`,
   `test_provider_architecture_contracts.py`, and the `--logic-only` suite).
3. `ruff format --check`, `ruff check`, and `ty check src` pass with zero
   errors.
4. Ad-hoc live `rr.find()` + `rr.fetch()` smoke check against DDAPI 2.0
   succeeds and is recorded in the Step 5 PR / issue `#1052` summary.
