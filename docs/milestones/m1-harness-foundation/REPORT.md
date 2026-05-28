# M1 — Harness Foundation — Milestone Report

**Status:** closed.
**Range:** `1b4d15a` (M1 step 01) … `c9181da` (M1 step 03), branch `docs/provider-redesign-proposal`, not pushed.
**Tracker entry:** [docs/milestone-tracker.md §3 "M1 — Harness foundation"](../../milestone-tracker.md).

M1 establishes the dependency layer, the issue/policy primitives, the catalogue artifact contracts, the provider registry, and the public discovery surface required by architecture.md §0, §2, §4, §6, §7, §8, §10, §14, §15.

## 1. Steps executed

| Step | Commit | Tag | Tests after | Net new |
|------|--------|-----|-------------|---------|
| 01-foundations | `1b4d15a` | `v0.1.4` | 38 | +38 |
| (housekeep) | `3cb85eb` | `v0.1.7` | 72 | 0 |
| 02-catalogue-schemas | `549752d` | `v0.1.6` | 72 | +34 |
| 03-registry-and-surface | `c9181da` | `v0.1.8` | 91 | +19 |

The housekeeping commit `3cb85eb` between step 02 and step 03 landed three things outside step scope: tracking the previously-orphaned `plan.md` / `critique.md` for each step (step 01's were already tracked; step 02's were not), bumping the `uv_build` constraint to `>=0.11.16,<0.12`, and the mandatory patch bump. Tag inventory at M1 close: `v0.1.2` through `v0.1.8` sequentially, no gaps.

## 2. Public API shipped — vs. tracker

| Tracker entry (line 56–59) | Shipped | Location | Divergence |
|---|---|---|---|
| `def providers() -> list[str]` | ✓ | `rivretrieve/__init__.py` re-export of `_internal.discovery.providers` | none |
| `def provider(provider_id: str) -> object` | ✓ | re-export of `_internal.discovery.provider` | none — return type stays `object` per tracker pin; M2 narrows to `ProviderHandle` Protocol |
| `def provider_info() -> CatalogResult[ProviderInfoCatalog]` | ✓ | re-export of `_internal.discovery.provider_info` | none |

No public symbols beyond those three plus `__version__`. The public-surface negative control (`tests/test_package.py::test_init_public_surface_exports_m1_discovery_only`) asserts module_defined_names equals exactly `{"providers", "provider", "provider_info"}` and a 16-name deferred list is absent.

## 3. Internal types introduced — vs. tracker

All 14 tracker-named internal types landed:

| Type | Tracker line | Step |
|---|---|---|
| `CatalogSource` | 62 | 01 |
| `OnIssue` | 63 | 01 |
| `Issue` | 64 | 01 |
| `IssueSeverity` | 65 | 01 |
| `ProviderId` | 66 | 01 |
| `ProductId` | 67 | 01 |
| `CatalogResult` | 68 | 01 |
| `CatalogProvenance` | 69 | 01 |
| `StationCatalog` | 70 | 02 |
| `ProductCatalog` | 71 | 02 |
| `StationProductCatalog` | 72 | 02 |
| `ProviderInfoCatalog` | 73 | 02 |
| `PackagedCatalogArtifact` | 74 | 02 |
| `ProviderRegistry` | 75 | 03 |

**Implementation-required additions not enumerated by the tracker (all internal):**

- Step 01: `RivRetrieveError`, `IssuePolicyError`, `FatalContractError`, `apply_on_issue` helper. The two-channel exception hierarchy was the design that made architecture.md §15 "fatal contract failures raise regardless of `on_issue`" structurally enforceable.
- Step 02: `CatalogueColumn`, `CatalogueSchema` (frozen-dataclass schema spec, defended in step 02 Q2 against pydantic-row alternatives); `validate_catalogue` free function; `CorruptCatalogArtifactError` (FatalContractError subclass); `load_packaged_catalogue_artifact` and `packaged_catalogue_artifact_from_components` loader/factory functions.
- Step 03: `UnknownProviderError` (FatalContractError subclass); `_ProviderHandle`, `_ProviderRecord`, module-level `_registry`; `_internal.discovery.{providers, provider, provider_info}` implementations.

None of these contradicts the tracker — all are derived primitives the tracker entry implies but does not name. The two-channel exception design and the `CatalogueColumn`/`CatalogueSchema` representation are the load-bearing architectural choices that should be carried forward unmodified into M2.

## 4. Runtime dependencies added

| Package | Resolved version | Tracker authorization |
|---|---|---|
| polars | 1.40.1 | line 44 |
| pandas | 3.0.3 | line 44 |
| pydantic | 2.12.5 | line 44 |
| requests | 2.34.2 | line 44 |

Version floors were intentionally not pinned in `pyproject.toml`; `uv.lock` is the concrete resolution per step 01 Q10. All four resolve under `requires-python = ">=3.13"`.

## 5. Test count delta and negative-control inventory

**Total: 91 passing.** Net +91 from the pyplate scaffold's placeholder.

**Negative-control tests, each enforcing one M1 exit criterion:**

| Test | Enforces | Location |
|---|---|---|
| `test_station_catalog_nullable_fields_accept_null_values` | `elevation_m` and `drainage_area_km2` accept explicit null values (tracker line 87) | `tests/test_internal_catalogue_schemas.py` |
| `test_corrupt_artifact_still_raises_under_ignore` | corrupt packaged artifacts raise regardless of `on_issue` (tracker line 86, architecture.md §15) | `tests/test_internal_packaged_catalogue_artifact.py` |
| `test_provider_unknown_raises_unknown_provider_error` | `rr.provider("missing")` is a direct fatal raise; `IssuePolicyError` is absent from the exception's cause/context graph (tracker line 84) | `tests/test_discovery.py` |
| `test_import_rivretrieve_does_not_import_providers_or_generators` | `import rivretrieve` does not import any provider module or `generate_catalogue.py` (tracker line 88) | `tests/test_offline_import.py` |
| `test_init_public_surface_exports_m1_discovery_only` | only the three tracker-authorized public symbols leak; 16-name deferred list confirmed absent | `tests/test_package.py` |
| `test_fatal_contract_error_is_separate_from_on_issue` | `apply_on_issue` only ever raises `IssuePolicyError`; never `FatalContractError` (parametrized matrix across severities × policies) | `tests/test_internal_issues.py` |

The offline-import test uses a subprocess with `sys.modules` inspection AND an affirmative sentinel assertion (`rivretrieve._internal.catalogues.artifact in sys.modules`) so the gate remains meaningful before any provider package exists.

## 6. Discoveries logged

One project-level discovery landed during M1:

- **D1** — Per-commit version bump touches `src/rivretrieve/__init__.py` ([docs/discoveries.md](../../discoveries.md)). The `bump-my-version` configuration updates both `pyproject.toml` and `src/rivretrieve/__init__.py` version literals. This collided with step 01's "no `__init__.py` edits" scope guard. Resolution: scope guards must phrase the restriction as "no API-shape edits," with the version-literal bump exempt. The discovery also documented a pre-existing `v0.1.3` tag on commit `6488f6e` that forced step 01 to land at `v0.1.4` rather than `v0.1.3`, and the negative-control test pattern of asserting *symbol absence* (not file-content equality).

No architecture.md or tracker contradictions were discovered. The two-channel fatal/recoverable design, the Polars-canonical commitment, the offline-import invariant, and the `on_issue`-sole-policy-knob design all held without amendment across all three steps.

## 7. Surprises and candidate updates for the coordinator's M2 prep

Items the project coordinator should review before M2 dispatch:

1. **Step audit-trail policy formalized mid-milestone.** Steps 01 and 02 initially committed only `execution.md`; `plan.md` and `critique.md` were orphaned. The housekeeping commit (`3cb85eb`) tracked the M1 orphans, and the policy "stage plan/critique/execution together" was baked into the step 03 executor brief. The tracker §3 milestone entries should be amended to make this the explicit per-step convention.

2. **`pl.Utf8` JSON-string `metadata` encoding** is now the load-bearing architectural choice for the four catalogue schemas. Step 02's round-1 plan proposed `pl.Object`; the reviewer caught the Parquet-round-trip blocker, and the revised plan switched to JSON strings (defended in step 02 Q6). Architecture.md §7 mentions "plain dictionaries at public table boundaries" but does not specify the wire encoding inside packaged Parquet artifacts. Recommend a brief architecture.md addendum to §7 codifying the JSON-string-in-Parquet convention so M3's `ch_foen` catalogue generation cannot accidentally diverge.

3. **`ProviderInfoCatalog` column set is now pinned by implementation.** Step 02 Q5 selected `{provider_id, name, live_stations, live_products, live_station_products, bulk_observations, catalogue_version, metadata}`. The architecture.md §9 capability mention (lines 432–433) names the three `live_*` flags and `bulk_observations` but is silent on `name` and `catalogue_version`. M2's singular `ProviderInfo` must be isomorphic to these columns — recommend the M2 planner reference step 02 §3 lines 124–139 as the row contract.

4. **Build-backend bump (`uv_build` 0.9 → 0.11)** was landed in the housekeeping commit, not as part of any milestone step. Future milestone planners may want to call out build-system updates as an explicit infra category in step §8 deferrals (presently they fall through the cracks).

5. **Tracker line 58's `rr.provider(provider_id: str) -> object`** is the only public M1 API signature that intentionally uses a weak return type. M2's narrowing must extend the existing private `_ProviderHandle` dataclass — the M2 step 01 planner should be told that the `_ProviderHandle` already exists, has no methods yet, and that the seven Protocol methods (`info`, `products`, `stations`, `station_products`, `row_annotation_schema`, `series_annotation_schema`, `observations`) attach to it. Renaming `_ProviderHandle` → `ProviderHandle` in M2 is a clean promotion path.

6. **The two-channel exception design held perfectly.** Across all three steps, the regression vector "fatal contract failure encoded as `Issue(severity="error")` and silenceable under `on_issue="ignore"`" surfaced as a reviewer L15/L14/R1 concern AND was caught by a structural test in every case (`test_fatal_contract_error_is_separate_from_on_issue`, `test_corrupt_artifact_still_raises_under_ignore`, `test_provider_unknown_raises_unknown_provider_error`). M2's `ObservationResult` fatal-contract paths should follow the same pattern: subclass `FatalContractError`, raise directly, never route through `apply_on_issue`.

## 8. Escalations

One step-internal conflict required orchestrator-level resolution (logged as D1, summarized in §6 above). No escalation to the human was needed beyond the housekeeping question. The reviewer/planner loop converged within 2 rounds on every step.

## 9. Ready for M2

The harness foundation is shippable. Steps 01–03 are committed, tagged, tested, and verified. The deferral list at the end of each step's `plan.md` §8 enumerates exactly what M2 owns; nothing M2-bound leaked into M1 commits.

The M2 planner can begin from a clean tree at `c9181da` / `v0.1.8`. The first M2 step's brief should reference this report's §3 (implementation-required additions), §7.5 (the `_ProviderHandle` promotion path), and §7.6 (the two-channel pattern to follow for observation-result fatal contracts).
