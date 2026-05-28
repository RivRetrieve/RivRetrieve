# Critique — 02-ch-foen-full-implementation

## Verdict

**DISPATCH WITH MINORS FOLDED.**

The plan is substantively correct on the load-bearing axes: product vocabulary, ProviderModule Protocol conformance, observations placeholder shape, capability flags (all-False), lazy registration, fixture binding (246 / Brugg), artifact-driven universe, no ch_foen-specific reader, and no token-bearing code in runtime source. Legacy citations were spot-checked against `thirdparty/RivRetrieve-Python @ origin/switzerland` and resolve to the claimed content with a handful of off-by-tens-of-lines errors (Minor). Two test-naming/coverage gaps and one mishandled interaction with the autouse `clear_provider_registry` fixture need fold-in tightenings before dispatch. None of the findings rise to ESCALATE or SEND BACK.

---

## Major findings

None.

The most likely Major candidates were checked and cleared:

- **Vocabulary broadening.** The user-orchestrator prompt mentioned "precipitation, snow, lake-level, glacier" as products the legacy exposes. The legacy `SwitzerlandFetcher` does NOT expose any of those — `VARIABLE_MAP` at `thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:44-80` lists exactly six entries: `DISCHARGE_{DAILY_MEAN,INSTANT}`, `STAGE_{DAILY_MEAN,INSTANT}`, `WATER_TEMPERATURE_{DAILY_MEAN,INSTANT}`. The Existenz.ch *API* offers other endpoints (precipitation, snow, etc.) but the legacy fetcher's catalogue surface is restricted to these six. The plan §3.4 classifies all six as canonical V1 with no silent broadening. Confirmed against `docs/product_dictionary.md` — every classification (`discharge_instantaneous`, `discharge_daily_mean`, `stage_instantaneous`, `stage_daily_mean`, `water_temperature_instantaneous`, `water_temperature_daily_mean`) matches the dictionary entry semantics (observed_property / frequency / statistic / period_type / period_anchor / unit) exactly.
- **Protocol conformance.** Read `src/rivretrieve/_internal/provider_module.py:14-55`. All seven `@staticmethod` functions are listed in plan §6D with matching names, and §2 / §6D acknowledges the keyword-only `*` separators, the `observations(request, *, on_issue)` shape, and the absence of `on_issue`/`source` on `info()`. No deviation.
- **Observations placeholder shape.** Plan §4.2 / §4.3 / §5.5 pin: Issue-routed (`observations_not_yet_implemented`, severity error), empty `data` against `ObservationDataSchema`, empty annotation tables against `RowAnnotationTableSchema`/`SeriesAnnotationTableSchema`, provenance present, `raw is None`, never raises under any `on_issue`. The deliberate decision NOT to pass `on_issue` to `apply_on_issue` is called out explicitly with the load-bearing rationale. The plan even includes a stop-condition (§9) if a reviewer insists on literal `apply_on_issue(on_issue)` semantics. Aligned with the orchestrator's stated requirement.
- **Capability routing under all-False.** Verified by reading `src/rivretrieve/_internal/catalogue_reader.py:48-62, 85-99, 115-131`: each `source="live"` branch checks `provider_info.live_*` and, when False, emits a `LiveCatalogueUnsupportedIssue` and returns an empty typed frame with `apply_on_issue((issue,), on_issue)`. Plan §3.5 / Q8 are correct without M2 code change.
- **Offline-import invariant.** `tests/test_offline_import.py:7-30` already forbids `rivretrieve.providers`, anything under `rivretrieve.providers.*`, and any module ending in `generate_catalogue` after `import rivretrieve`. Plan §6E mandates local imports inside the registration helper and forbids touching `generate_catalogue` from runtime code. The invariant survives.
- **Fixture binding.** Verified: `git show origin/switzerland:tests/test_data/switzerland_metadata_locations.json` decodes to `len(payload) == 246` and station `"2016"` has `details = {id:'2016', name:'Brugg', water-body-name:'Aare', water-body-type:'river', chx:657000, chy:259360, lat:47.4825, lon:8.1949}`. Both tracker-pinned facts are assertable as written.
- **M2 dispatch & module-check-first.** Plan §4.3 explicitly relies on the M2 step 05/06 module-check-first ordering at `src/rivretrieve/_internal/registry.py:89-113`. The handle passes `on_issue` straight to `self._module.observations(request, on_issue=on_issue)` and validates annotation names afterward; empty schemas vs empty annotation tables passes (`validate_annotation_names` at observations.py:223-228 returns silently when `emitted` is empty).
- **Token handling (Q10 + Q12).** Verified upstream by reading `switzerland.py:40` and `:197-203` directly. Token is still a hardcoded class attribute in the legacy `origin/switzerland` branch and is used in the Authorization header. Plan correctly does not relax M3 step 02 (no token in target runtime source) and limits the upstream-token statement to "background for step 03 docs."
- **Premature abstraction / hardcoded IDs.** Plan §6D explicitly says "Do not create a `ch_foen` reader" and "must be artifact-driven, not hardcoded station/product IDs." Stop conditions §9 also pin this.

---

## Minor findings

### Minor-1. Plan §5.4 names a `test_global_station_products_include_ch_foen_rows` test, but no `rr.station_products()` global function exists or is planned.

- **Where:** plan.md §5.4, line `- test_global_station_products_include_ch_foen_rows.`
- **Contract:** Read `src/rivretrieve/__init__.py:1-9` — package root exports `product_info`, `products`, `provider`, `provider_info`, `providers`, `stations`, plus `ProviderHandle` and `__version__`. No `station_products`. Tracker §M2 line 102 lists "Global `rr.stations()`, `rr.products()`, and `rr.product_info()` over packaged catalogues" — `station_products` is intentionally absent from global discovery. T119 enforces this set exactly (`tests/test_package.py:11-23`).
- **Fix:** Either delete the test, or rename and rescope it to `test_provider_handle_station_products_returns_ch_foen_rows` and have it call `rr.provider("ch_foen").station_products()`. (The `1476 = 246 × 6` count from §3.3 is the natural body of that test.)

### Minor-2. Plan does not address the autouse `clear_provider_registry` fixture interaction with lazy registration.

- **Where:** plan.md §6E ("It must be idempotent and must not clobber test registries. Tests that clear `_registry` may need a supported way to disable default registration for isolated registry tests, or they should use fresh `ProviderRegistry` instances where possible.")
- **Contract:** `tests/conftest.py:320-324` defines `clear_provider_registry` as `autouse=True` — it clears `_registry` BEFORE and AFTER every test. After plan §6E lands, `tests/test_discovery.py:41-42 (test_providers_empty_registry_returns_empty_list)` will call `rr.providers()` after a fresh `_registry.clear()` and expect `[]`, but the lazy helper will re-populate `["ch_foen"]` first. Same break risk for any other test that hits the live `_registry` after clear and asserts an exact provider list, e.g. `tests/test_discovery.py:48-51` which expects `["a_provider", "z_provider"]` after registering two stubs (lazy registration will turn that into `["a_provider", "ch_foen", "z_provider"]`).
- **Fix:** Plan §2 / §6E should explicitly enumerate (a) the tests in `tests/test_discovery.py` that will need updates and (b) the contract for "disable default registration" (e.g., an environment variable, a sentinel, or relying on the conftest autouse to swap out registration before tests run). The hand-wave "may need a supported way" is not enough.

### Minor-3. Several legacy citation line ranges are off by tens of lines.

- **Where:** plan.md §3.1 table.
- **Concrete misalignments verified against `git show origin/switzerland:rivretrieve/switzerland.py` with explicit line numbering:
  - `elevation_m` row cites `:120`. Actual `ALTITUDE: np.nan` is at line 161. Line 120 is in `_split_windows` (`return windows`).
  - `drainage_area_km2` row cites `:121`. Actual `AREA: np.nan` is at line 162. Line 121 is the `_empty_metadata_frame` definition start area.
  - `country` row cites `:42`. `COUNTRY = "Switzerland"` is at line 42 ✓ (but the `163` end of the cited range is the row construction; the citation pair `:42, :163` is fine).
  - `INFLUX_TOKEN` (Q12) cites `:37-40`. Token is on line 40 only; lines 37-39 are `BASE_URL`, `METADATA_URL`, `INFLUX_URL`. Narrow the range.
- **Contract:** L_legacy_citation_fidelity — citations must say what the plan claims at the cited lines. These are off but defensibly close; none point at content that contradicts the plan.
- **Fix:** Re-number with the actual lines (161, 162, 40). Optional, since the cited tokens are still resolvable in the file — but the lens flags these as Minor at least.

### Minor-4. T120 extension with `ChFoen*` names is redundant.

- **Where:** plan.md §2 ("if the test adds them to the absence list, that is an additive negative-control update, not a public-surface change.") and §5.8 ("optionally extended to include `ChFoenStationMetadata`...").
- **Contract:** Read `tests/test_package.py:26-59` — the test checks `hasattr(rivretrieve, name)` for each name. The Pydantic models live in `rivretrieve.providers.ch_foen.metadata`, not at the package root, so they cannot leak via `hasattr(rivretrieve, "ChFoenStationMetadata")` unless someone re-exports them in `src/rivretrieve/__init__.py`. The proposed extension does not test a real leak vector.
- **Fix:** Drop the extension proposal or recast it as a separate test that imports `rivretrieve.providers.ch_foen.metadata` and asserts that NO `Ch*` symbol is also accessible from `rivretrieve` after a discovery call.

### Minor-5. Q6 ("module.py vs functions in `__init__.py`") slightly mischaracterizes the architecture example.

- **Where:** plan.md §6D ("`module.py` keeps `__init__.py` as an empty package marker and avoids registration side effects.") and Q6.
- **Contract:** `architecture.md:386-394` shows the provider package layout with `__init__.py` and `metadata.py` and no `module.py`. The natural reading is that the seven provider functions live in `__init__.py`. The plan's choice of `module.py` is defensible (separation of concerns; keeps the package marker empty) but the rationale "avoids registration side effects" is weak — registration side effects only happen if registration code is at module top-level, regardless of which file holds the Protocol functions.
- **Fix:** Strengthen the rationale to "keeps `from rivretrieve.providers.ch_foen import module` as the single explicit binding point and avoids accidentally executing module-body code via `import rivretrieve.providers.ch_foen`," or accept the architecture example and put functions in `__init__.py`. Either works; the plan should commit cleanly to one with the actual reason.

---

## Nits

### Nit-1. §3.5 `metadata` JSON example string ends with a trailing colon.

`"legacy_source":"thirdparty/RivRetrieve-Python @ origin/switzerland::"` — the doubled trailing `::` looks like a leftover placeholder. Cosmetic only; the actual JSON content for the artifact will be generated at runtime.

### Nit-2. §3.3 wording.

`"M3 materializes known provider station-product universe as unknown"` — "as unknown" is slightly garbled. Read as "with availability=unknown" which is what §3.3's row template makes clear, so no contract risk.

### Nit-3. §2 T117/T119/T120 expectations refer to "T117 / T119 / T120" but `tests/test_provider_handle.py:92` is the only canonical T117 anchor and the plan doesn't pin the corresponding M2-step-06 numbering elsewhere. Cosmetic.

---

## Lens-by-lens summary

- **L1 (scope completeness):** ✅ — scaffolding, generator, artifacts, module, lazy registration, placeholder observations, capability declaration, fixture, schema validation, generator fatal paths, observation non-raise contract are all covered.
- **L2 (scope over-reach):** ✅ — real observations, top-level `rr.observations`, `rr.map_stations`, product dictionary edits, architecture edits, provider port doc beyond stub, and M3 closeout REPORT are explicitly deferred in §1 and §8.
- **L3 (citation verification):** ⚠️ Minor — some line ranges off (see Minor-3) but every spot-checked citation resolves to claimed content. No hallucinations.
- **L4 (test coverage adequacy):** ⚠️ Minor — §5.5 covers the placeholder shape exhaustively including parametrized `on_issue`; §5 covers fixture bindings (246, Brugg) but §5.4 misnames one test (Minor-1) and §6E hand-waves on autouse fixture interaction (Minor-2).
- **L5 (error handling completeness):** ✅ — §4.1 enumerates fatal paths (generator + runtime); §4.2 splits Issue-carrying from fatal; §4.3 pins the placeholder non-raise rule.
- **L6 (open question rigor):** ✅ — Q1 is the hardest and it's right: all six map to canonical V1 with explicit defense (`docs/product_dictionary.md` matches every classification); Q12 is verified by actually reading `switzerland.py:40, :197-203` rather than restating commit text.
- **L7 (deferral hygiene):** ✅ — observations, top-level wrapper, `map_stations`, full provider-port doc, REPORT, vocabulary expansion, token handling all explicitly tagged with target milestone.
- **L8 (implementation order):** ✅ — §6A→§6F walk: at end of 6A no registration path exists (`git grep ch_foen` checkpoint); end of 6B generator and tests exist but `generate_catalogue` is only imported by tests, satisfying offline-import; end of 6C artifacts exist on disk but no runtime change; end of 6D module exists but is unregistered (provider handle dispatch only reaches it via the registry, so importing alone has no side effects); end of 6E lazy registration in place and tests adjusted. Gap-free.
- **L9 (stopping conditions):** ✅ — covers vocabulary conflict, fixture/common-schema conflict, lazy registration vs offline import, M2 register-keyword changes, `_ProviderHandle.observations` change pressure, placeholder cannot avoid raise, hardcoded IDs, live routing change pressure, T117/T119/T120 invariant violation, network requirement in suite, citation un-verifiability.
- **L10 (architecture commitment compliance):** ✅ — function-based provider Protocol, packaged-only normal discovery, `metadata` as JSON-encoded provider-owned Pydantic, nullable elevation/area, `last_catalogue_check` as date, `bulk_observations` as descriptive string.
- **L11 (speculative abstraction check):** ✅ — no ch_foen reader, no abstract base, no observation result subclass, no "for-later" hooks, no helper interfaces.
- **L_two_channel:** ✅ — placeholder is Issue-routed (severity error) and explicitly does NOT raise under any `on_issue`; fatal generator paths and corrupt artifact paths remain raises and stay fatal under all `on_issue` settings.
- **L_inherited_patterns:** ✅ — pattern 1 (`_module=None` default + keyword registration in §6E), pattern 5 (T117/T119/T120 SHAPE invariants pinned in §2 and §5.8), pattern 7 (artifact-driven universe explicit in §6D — "must be artifact-driven, not hardcoded station/product IDs"), pattern 8 (two-channel observed). Patterns 2-4, 6 (always-on annotation validation; CatalogueReader as single site; no inheritance; structural Protocol) all respected.
- **L_legacy_citation_fidelity:** ⚠️ Minor — most citations use the `thirdparty/RivRetrieve-Python @ origin/switzerland:<file>:<line>` form. A few line numbers misalign (Minor-3). No hallucinations.
- **L_vocabulary_boundary:** ✅ — every §3.4 classification semantic-matches `docs/product_dictionary.md`. No ch_foen-specific IDs proposed. No drops. No silent broadening into precipitation/snow/lake-level/glacier (which the legacy `SwitzerlandFetcher` does not expose anyway — the user-prompt's mention of those products is not represented in `VARIABLE_MAP`).
- **L_offline_invariant:** ✅ — §6E mandates local imports inside the registration helper; the existing `tests/test_offline_import.py` enforces the rule; no path in §6 requires importing `rivretrieve.providers.ch_foen.*` at `import rivretrieve` time.
- **L_rename_atomicity:** N/A — no renames in this step.
- **L_protocol_conformance:** ✅ — verified against `src/rivretrieve/_internal/provider_module.py:14-55`. All seven functions present, keyword-only `*` boundaries match, `info()` lacks `on_issue` (matches Protocol), `observations(request, *, on_issue)` first arg positional (matches Protocol), `station_products(stations: Sequence[str] | None = None, *, ...)` positional-then-keyword (matches Protocol). The M2 step 06 dispatch site at `registry.py:89-113` calls `self._module.observations(request, on_issue=on_issue)` and `self._module.row_annotation_schema()` / `series_annotation_schema()` — plan's module signatures match.
- **L_fixture_binding:** ✅ — 246 and Brugg both directly assertable per verified `jq` lookup. §5.2 binds both as test exit criteria.

---

## Adversarial probes attempted

1. Ran `cd /Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python && git show origin/switzerland:tests/test_data/switzerland_metadata_locations.json | python3 -c "import sys, json; d=json.load(sys.stdin); p=d.get('payload',{}); print(len(p)); print(p.get('2016'))"` → `246` and station 2016 `{name:'Brugg', water-body-name:'Aare', lat:47.4825, lon:8.1949}`. **Confirms** plan §5.2 fixture bindings.
2. Ran `cd /Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python && git show origin/switzerland:rivretrieve/switzerland.py | awk 'NR>=35 && NR<=85 {printf "%d: %s\n", NR, $0}'` → confirmed `INFLUX_TOKEN` on line 40 only, `VARIABLE_MAP` on lines 44-80 with exactly six entries (`DISCHARGE_DAILY_MEAN`, `DISCHARGE_INSTANT`, `STAGE_DAILY_MEAN`, `STAGE_INSTANT`, `WATER_TEMPERATURE_DAILY_MEAN`, `WATER_TEMPERATURE_INSTANT`). **Confirms** no precipitation/snow/lake-level/glacier products in legacy; vocabulary classification is non-broadening. **Contradicts** Minor-3 citation `:37-40`.
3. Ran `awk 'NR>=140 && NR<=210 {printf "%d: %s\n", NR, $0}'` on the same file → confirmed `ALTITUDE: np.nan` at line 161, `AREA: np.nan` at line 162, `Authorization: f"Token {self.INFLUX_TOKEN}"` at line 200. **Contradicts** plan §3.1 `:120` and `:121` citations (off by ~40 lines); **confirms** Q12's `:197-203` token usage citation.
4. Read `src/rivretrieve/_internal/provider_module.py:14-55` → verified all seven Protocol functions and signatures. **Confirms** §6D and §2 protocol claim.
5. Read `src/rivretrieve/_internal/registry.py:32-113` → verified `_module: ProviderModule | None = None` default, module-check-first dispatch in `observations`, keyword `provider_module=` in `register()`. **Confirms** plan §6E ("M2 keyword parameter") and §4.3 ("module-presence check") inheritance.
6. Read `src/rivretrieve/_internal/catalogue_reader.py:48-138` → verified that all-False `live_*` flags route to `LiveCatalogueUnsupportedIssue` + `apply_on_issue` with no code change. **Confirms** §3.5, Q4, Q8.
7. Read `src/rivretrieve/_internal/issues.py:76-88` (`apply_on_issue`) → verified that `severity="error" + on_issue="raise"` raises `IssuePolicyError`. **Confirms** plan §4.2's "load-bearing compatibility decision" — the non-raising placeholder genuinely cannot route through literal `apply_on_issue(on_issue)`.
8. Read `src/rivretrieve/__init__.py:1-9` and `tests/test_package.py:11-23` → confirmed package root is exactly `{ProviderHandle, product_info, products, provider, provider_info, providers, stations}` plus `__version__`, and `station_products` is NOT a global function. **Triggers** Minor-1 (test name is misleading).
9. Read `tests/conftest.py:320-329` → confirmed `clear_provider_registry` is `autouse=True` and `fresh_registry` is an opt-in fixture. **Triggers** Minor-2 (plan §6E hand-waves on this interaction).
10. Read `tests/test_offline_import.py` → confirmed the subprocess script forbids `rivretrieve.providers` and any `generate_catalogue` after `import rivretrieve`. **Confirms** §6E's local-import discipline is the right approach.
11. Read `docs/product_dictionary.md` → confirmed every plan §3.4 classification (`discharge_instantaneous`, `discharge_daily_mean`, `stage_instantaneous`, `stage_daily_mean`, `water_temperature_instantaneous`, `water_temperature_daily_mean`) matches dictionary semantics exactly. **Confirms** L_vocabulary_boundary clean.
12. Read `docs/milestones/m2-discovery-and-observation-contracts/REPORT.md:118-128` → confirmed the six pinned inherited patterns (module=None default, module-check-first, always-on annotation validation, stub hardcoded universe NOT to be copied, structural Protocol, CatalogueReader sole site). **Confirms** plan §6D and §6E adhere to all six.
13. Read `tests/test_discovery.py:41-51` → confirmed `test_providers_empty_registry_returns_empty_list` and the two-stub-registration test will both break under lazy registration unless updated. **Concretizes** Minor-2.
14. Read `architecture.md:380-434` (Provider Module Contract + Provider info section) → confirmed `bulk_observations` is descriptive (not boolean), `catalogue_version` is per-snapshot, and the example layout shows no `module.py`. **Confirms** plan's `bulk_observations="false"` string is schema-valid; **triggers** Minor-5 (plan's `module.py` rationale could be stronger).
