# Milestone Tracker — Adversarial Critique

Critique target: `docs/milestone-tracker.md` (planned 11-milestone V1 plan).

## Verdict

**SEND BACK TO PLANNER.**

The tracker is broadly sound — architecture coverage is complete, §19 deferrals are honored, `ch_foen` is correctly positioned as translation-with-redesign, and exit criteria mostly admit negative controls. But three substantive gaps require planner judgment, not mechanical fold-in:

1. **No milestone introduces an HTTP client dependency**, even though M6's catalogue generation hits `https://api.existenz.ch/apiv1/hydro/locations` live and M8's `ch_foen` observations call the existenz.ch InfluxDB endpoint. The package can't actually do either job at the declared milestone boundary.
2. **M7 silently lands `ch_foen.observations` in a half-state.** After M7, `ch_foen` satisfies a `ProviderHandle` Protocol that (since M5) requires `observations()`, but the real implementation is M8. The tracker never says what M7-era `ch_foen.observations(...)` does — NotImplementedError, stub returning an Issue-wrapped result, or absent. That decision belongs to the planner; it shapes M7 vs M8 and the one-commit-shippability invariant.
3. **M2 lands a public `ProviderHandle` Protocol that has zero methods.** Architecture.md §9 commits the Protocol to "expose the same public catalogue and observation behavior." A method-less Protocol in M2 → M3 contradicts that contract until M4/M5 backfill the methods. Either delay the Protocol's public exposure or split its introduction across M2–M5 explicitly.

The rest is fold-in territory.

## Architecture coverage table (L1)

Walked architecture.md §0–§18 against tracker milestone coverage. Every commitment maps to at least one milestone; no orphans.

| arch.md section | Tracker milestone(s) | OK? |
|---|---|---|
| §0 Document Roles and Change Process | M1 (invariants), M11 (closeout) | ✅ |
| §1 Architectural Goals | M1, M6–M8, M11 | ✅ |
| §2 Provider Identity | M2, M7 | ✅ |
| §3 Public API Surface | M2, M3, M4, M5, M9, M10 | ✅ |
| §4 Packaged Catalogue Architecture | M3, M4, M7 | ✅ |
| §5 Live Catalogue Queries | M4, M7 | ✅ |
| §6 Catalogue Result Shape | M3, M4 | ✅ |
| §7 Catalogue Record Model | M3, M6, M7 | ✅ |
| §8 Product Dictionary | M1 (ProductId), M3 (ProductCatalog), M6 (provider→canonical mapping) | ✅ |
| §9 Provider Module Contract | M2, M4, M5, M7, M8 | ⚠️ (Protocol empty at M2; see Major #3) |
| §10 Maintainer Catalogue Generation | M3 (schema), M6 (`generate_catalogue.py`) | ✅ |
| §11 Observation Request | M5, M8, M9 | ✅ |
| §12 Observation Result | M5, M8 | ✅ |
| §13 Annotation Schemas | M5 (contract), M8 (`ch_foen` schemas) | ✅ |
| §14 Provenance | M3 (catalogue), M5 (observation), M8 (real recording) | ✅ |
| §15 Issues and Error Policy | M1, M3, M4, M5, M8 | ✅ |
| §16 Time and Units | M5, M6, M8 | ✅ |
| §17 Multi-API Providers and Stitching | M5 (contract), M8 (`ch_foen` stitching) | ✅ |
| §18 Reference Provider and Feedback Loop | M6, M7, M8, M11 | ✅ |

§19 is deferrals; checked separately under L2 — clean.

## Major findings

### Major 1 — No milestone introduces an HTTP client; M6 generation and M8 observations cannot actually run

Tracker §3 / M1 — *Shared primitives and dependencies* — In scope:
> "Add required runtime dependencies for the committed architecture, including Polars and any validation library selected by implementation."

Polars and a validation library are named. **No HTTP client is named in any milestone.**

Concrete violations:

- **M6** ("Translate `SwitzerlandFetcher.get_metadata()` and cached Switzerland site data into `ch_foen` catalogue generation"). M6 exit criterion explicitly requires:
  > "`docs/provider_ports/ch_foen.md` records the translated source endpoints/artifacts from `SwitzerlandFetcher`, including `https://api.existenz.ch/apiv1/hydro/locations`."
  Reaching that endpoint from `generate_catalogue.py` (the only place it's allowed; §10) requires an HTTP library. The legacy `SwitzerlandFetcher.get_metadata()` uses `requests` via `rivretrieve.utils.requests_retry_session()` (verified at `RivRetrieve-Python/rivretrieve/switzerland.py:128–148`). M6 cannot honor its own exit criterion without an HTTP dep declared.
- **M8** ("`ch_foen.observations(request, ...)`"). Legacy `SwitzerlandFetcher._download_data` posts to `https://influx.konzept.space/api/v2/query?org=api.existenz.ch` (verified at `switzerland.py:190–215`) using `requests`. M8 is a runtime path inside the installed package; the HTTP dep must be a real runtime dependency, not a maintainer-only one. M8's dependency list — "M1, M2, M5, M6, M7" — doesn't include any HTTP-introducing milestone because none exists.

Contract violated: architecture.md §0/§9 require provider runtime code to deliver `observations()`; tracker §2 cross-cutting invariant: "Keep the package installable/importable and `uv run pytest` green at every milestone boundary; no milestone may leave half-wired public imports or failing placeholder behavior."

Concrete fix: pick one approach and commit to it:
- (a) Add `httpx` (or `requests`) to M1 dependencies alongside Polars, even though M1's tests don't use it.
- (b) Defer HTTP dep declaration to M6 (for `generate_catalogue.py`) and again to M8 (declared as a runtime dep before observation code lands), and say so in both milestone scopes.

Either is fine, but the tracker must name the milestone.

### Major 2 — M7 leaves `ch_foen.observations` half-wired between M7 and M8

Tracker M5 — *Observation contracts with stub execution* — adds to the Protocol:
> "`def ProviderHandle.observations(*, stations: ..., start: ..., end: ..., on_issue: ... ) -> ObservationResult: ...`"

Tracker M7 — *`ch_foen` packaged catalogue provider* — in-scope is catalogue methods only:
> "Runtime `ch_foen.info()`, `products()`, `stations()`, and `station_products()`."

But `ch_foen` is registered as a Protocol-conformant provider in M7 (`rr.providers()` returns `["ch_foen"]`). The Protocol since M5 requires `observations()`. The tracker is silent on what happens when a user — between commit M7 and commit M8 — runs:

```python
rr.provider("ch_foen").observations(stations="2206", products="discharge_daily_mean",
                                     start="2025-01-01", end="2025-01-31")
```

Possible answers, each with different consequences:

- `AttributeError` / `NotImplementedError`: violates Protocol conformance and the §2 invariant "no milestone may leave half-wired public imports or failing placeholder behavior."
- Returns `ObservationResult` with a structured "not yet implemented" `Issue`: contract-compliant, but the tracker doesn't say so.
- The module simply doesn't expose `observations`: violates the Protocol and the M7 exit criterion that `ch_foen` is a real provider.

This is the single most likely source of a broken intermediate commit. The planner must pick a stance and codify it. Suggested fix in M7's exit criteria:

> "`rr.provider('ch_foen').observations(...)` returns an `ObservationResult` whose `issues` contains a single `error`-severity `Issue` with code `observations_not_yet_implemented` and no `data` rows. This makes M7 Protocol-conformant; full observation retrieval lands in M8."

Or, alternatively, defer `ch_foen` registration until M8 and have M7 ship the artifacts in `src/rivretrieve/providers/ch_foen/catalogue/` without `__init__.py` exposure — but that contradicts M7's stated public observable behavior (`rr.providers()` includes `"ch_foen"`).

### Major 3 — M2 introduces an empty `ProviderHandle` Protocol; architecture.md §9 commits it to a non-empty contract

Tracker M2 — *Provider registry and handle skeleton* — In scope:
> "Public provider handle typed by a protocol."

Public surface introduced:
> "`class ProviderHandle(Protocol): ...`"

Risk section says:
> "The provider protocol must avoid promising catalogue or observation behavior that M3-M5 have not introduced yet."

Architecture.md §9 disagrees:
> "The public provider handle is typed by a `typing.Protocol` that exposes the same public catalogue and observation behavior. `source` and `on_issue` are part of the public catalogue method contract."

A literally empty `Protocol` at M2 is at best meaningless (every object satisfies it), at worst misleading to users browsing autocomplete in M2/M3. M3 doesn't widen the Protocol (M3 introduces only `provider_info()` as a free function, not on the handle). M4 widens the Protocol with catalogue methods. M5 widens it again with `observations`. The Protocol grows in three commits without being declared a growing artifact.

Fix options the planner should pick from:

- Keep the Protocol empty in M2 but rename it `_ProviderHandle` (private) or omit it from `rr` namespace; promote it to public in M4 once it has real methods.
- Land the full Protocol in M2 with `NotImplementedError`-raising default methods, accepting that the Protocol is a forward declaration. (Awkward but legitimate.)
- Split M2 into "registry only, no Protocol" + the Protocol lands incrementally as a documented growing surface in M4 and M5. Cross-cutting invariants should then state "the public `ProviderHandle` Protocol grows monotonically across M2→M5."

Either way, the tracker should not pretend a method-less Protocol is the architecture.md §9 contract.

## Minor findings

### Minor 1 — M4 legacy citation overstates which files contain `get_metadata()`

Tracker M4 — "Legacy Python analogues consulted" cites `usa.py` and `canada.py`, and the analogue note says:
> "Legacy analogue: `get_cached_metadata()`, `get_metadata()`, and `get_available_variables()`."

`usa.py` and `canada.py` do **not** define `get_metadata()` (verified via `grep -n "def get_metadata" rivretrieve/*.py`); only `uk_ea.py` and `uk_nrfa.py` do among the cited files. The list-of-files / list-of-methods rendering implies all-cited-files-have-all-three-methods, which is false.

Fix: tighten the note. Either drop `get_metadata()` from the analogue text in M4 (since the bulk of M4's structure derives from cached-metadata aggregation, not live `get_metadata`), or keep it but make explicit "live `get_metadata` exists in `uk_ea.py` and `uk_nrfa.py` only; not in `usa.py` / `canada.py`." The latter is more honest given M4 introduces `source="live"`.

### Minor 2 — Test fixture reuse from `origin/switzerland` is cited but not exit-criterion-enforced

L14: the legacy Switzerland branch ships pre-validated fixtures (`switzerland_metadata_locations.json`, `switzerland_2206_discharge_20250101.csv`, `switzerland_2282_stage_20250101.csv`, `switzerland_2016_temperature_20200101.csv`). The legacy test suite at `tests/test_switzerland.py` already pins specific expected values (e.g., 246 stations, station "2016" → name "Brugg", lat 47.4825, lon 8.1949 — verified in the branch).

M6 cites `switzerland_metadata_locations.json`; M8 cites the three observation CSVs. But the exit criteria say only:
- M6: "`ch_foen` catalogue generation can produce schema-valid station, product, and station-product artifacts in a maintainer workflow."
- M8: "A recorded or otherwise deterministic test fixture proves a `ch_foen` observation call returns valid `ObservationResult` tables and declared annotations."

Neither commits the executor to use the validated legacy fixtures as ground-truth. An executor reading M6/M8 in isolation could legitimately decide to recapture Swiss responses, drifting from the legacy baseline that has already been validated by Switzerland-branch maintainers.

Fix: add to M6 exit:
> "`tests/test_data/switzerland_metadata_locations.json` (from `origin/switzerland`) is committed under the new repo's `tests/test_data/` and used as the recorded response for the catalogue-generator test. The generator's station-count and at-least one named station (e.g., `2016 → Brugg`) match the legacy fixture."

And to M8 exit:
> "The three legacy CSV fixtures (`switzerland_2206_discharge_20250101.csv`, `switzerland_2282_stage_20250101.csv`, `switzerland_2016_temperature_20200101.csv`) are committed and used to feed the observation-parse tests. Where the new long-form schema diverges from the legacy wide-form output, the divergence is documented in `docs/provider_ports/ch_foen.md`."

### Minor 3 — Executor stopping conditions do not forbid re-creating the `RiverDataFetcher` class shape internally

Tracker §8 stop #2:
> "Do not introduce a public provider class."

This catches the public-surface variant but not the *internal* failure mode: a `ch_foen` implementer who builds `class ChFoenProvider(_BaseProvider): ...` inside the provider package, with abstract methods mirroring `RiverDataFetcher.get_data`, `get_cached_metadata`, `get_available_variables`. That is exactly the abstraction the redesign exists to remove (architecture.md §1: "The old abstraction was one class per country, such as `USAFetcher` or `CanadaFetcher`. The new abstraction is one provider per data source/API"). Internal inheritance with abstract methods is just as wrong as a public class — it is what `RiverDataFetcher` was.

Fix: add to §8:
> "Do not port the country base-class shape from `RivRetrieve-Python/rivretrieve/base.py` (`RiverDataFetcher`, `get_data`, `get_cached_metadata`, `get_available_variables`) into any provider package, public or private. Provider runtime modules expose the function-based contract in architecture.md §9; provider-internal classes are permitted only as bounded implementation details, never as a shared abstract base."

### Minor 4 — Pandas runtime dependency is not pinned to a milestone

M5 introduces `result.to_pandas()` and the long-form pandas export contract. `pandas` is not in `pyproject.toml` (zero runtime deps). M1's dep wording — "Polars and any validation library" — does not name pandas. The tracker treats pandas as implicit. Architecture.md §6 says "pandas export is a convenience, not the internal contract" — but it is still a runtime import path users will hit.

Fix: either declare pandas in M1 (clean), or in M5 alongside the `to_pandas()` method introduction. Don't leave it implicit.

### Minor 5 — Pydantic introduction milestone is ambiguous

M1 says "any validation library selected by implementation." Architecture.md §7 commits provider metadata to Pydantic models. M3 introduces `CatalogProvenance`, common catalogue schemas, schema validation for packaged artifacts. M6 introduces `ChFoenStationMetadata`, `ChFoenProductMetadata`, `ChFoenStationProductMetadata` — these need a validation library.

The tracker doesn't say in which milestone Pydantic is added or whether `pydantic` is the chosen library. Leaving it open is acceptable, but the *dependency-introduction milestone* should be pinned. Otherwise M3 (schema validation) is the first user of Pydantic with no milestone declaring the dep.

Fix: pin Pydantic introduction to M1 (alongside Polars), since both M3 and M6 need it.

### Minor 6 — Nullable common-schema fields for `ch_foen` not addressed

Architecture.md §7 station catalogue common schema includes `elevation_m` and `drainage_area_km2`. Verified at `switzerland.py:115–135`: legacy `SwitzerlandFetcher.get_metadata()` emits `np.nan` for both because the Existenz hydro/locations endpoint does not expose altitude or catchment area. So `ch_foen` station records will have null `elevation_m` / `drainage_area_km2` from day one.

M3 (common schema) and M7 (real `ch_foen` catalogue) do not address null handling for these fields. M6 should plan for it, and M3's schema validation should permit nullables.

Fix: M3 exit should require schemas to declare nullability per-field, with `elevation_m` and `drainage_area_km2` documented as nullable in V1. M6 should reference this and note in `docs/provider_ports/ch_foen.md` that two common fields are unpopulated for `ch_foen`.

## Nits

### Nit 1 — M11 "Architecture sections covered: §0 through §19" is slightly misleading

§19 is the deferrals list, not a commitment. M11's exit criterion ("checklist maps architecture.md §0-§19 to implemented behavior or explicit deferral") is correct, but the header line "Architecture sections covered: §0 through §19" reads as if M11 implements §19. Tightening: "Architecture sections covered: §0 through §18; §19 deferrals are reaffirmed but not implemented."

### Nit 2 — M2 risk note describes the empty-Protocol problem but does not resolve it

> "The provider protocol must avoid promising catalogue or observation behavior that M3-M5 have not introduced yet."

This is the right intuition but it's filed under "Risk / known unknowns" rather than being resolved. Either move the design choice into "In scope" with the chosen approach, or escalate it to a planner-level decision (which is what Major 3 above asks for).

## Suggested consolidation — collapse 11 milestones into 5

The 11-milestone slicing is surgical and easy to review per-commit, but it pays for that by creating intermediate states that cannot exercise the harness end-to-end (e.g., M4 ships discovery against an empty registry; M5 ships `observations` against stubs; M7 ships `ch_foen` catalogue with no observations). Several of those intermediate states are the reason Majors 2 and 3 exist at all. Re-cutting along the natural architectural seams in architecture.md §18 ("Implement the harness and one full `ch_foen` port first") collapses the plan to **5 milestones** without violating any architecture commitment:

| New | Merges | Capability shipped |
|---|---|---|
| **M1' Harness foundation** | M1 + M2 + M3 | Dependencies (Polars, validation library, pandas), shared types (`Issue`, `OnIssue`, `CatalogSource`, `ProviderId`, `ProductId`), registry + `ProviderHandle` Protocol, catalogue envelopes (`CatalogResult`, `CatalogProvenance`, common schemas, `PackagedCatalogArtifact`), `rr.provider_info()`. Tests against an empty registry plus a stub catalogue. |
| **M2' Discovery + observation contracts** | M4 + M5 | Provider-level + global catalogue discovery (`stations`, `products`, `station_products`, `product_info`), `source="packaged"/"live"` handling, `ObservationRequest`/`ObservationResult`/`AnnotationSchema`/`ObservationProvenance`, `to_polars()`/long-form `to_pandas()`, `ProviderHandle.observations()`. All proven against a stub provider. After this commit, the complete no-provider harness is shippable. |
| **M3' `ch_foen` catalogue provider** | M6 + M7 | Translation of `SwitzerlandFetcher.get_metadata()` + Switzerland fixtures into `ch_foen` catalogue generation, maintainer-only `generate_catalogue.py`, packaged `provider.json` + parquets, runtime registration, `rr.providers() == ["ch_foen"]`, real catalogue calls. `ch_foen.observations` returns an `Issue`-wrapped not-yet-implemented result (resolves Major 2 explicitly). |
| **M4' `ch_foen` observations + top-level wrapper** | M8 + M9 | Real `ch_foen.observations` with stitching/windowing/parameter-preference/unit-conversion against the legacy CSV fixtures, row + series annotations, observation provenance, structured issues, plus `rr.observations(...)` thin-wrapper delegation. First true end-to-end retrieval. |
| **M5' Map + closeout** | M10 + M11 | `rr.map_stations()` over the packaged catalogue (with the `leafmap` dependency pinned), architecture conformance checklist, final `docs/provider_ports/ch_foen.md` updates, `docs/discoveries.md` entries. V1 ships. |

### Why this is better than 11

- **Major 3 disappears.** M2' lands the `ProviderHandle` Protocol with its full catalogue + observation method set in one commit, so there is no window in which architecture.md §9's contract is contradicted by an empty Protocol.
- **Major 2 is forced into an explicit decision.** M3' is the only commit in which `ch_foen` exists without observations, and its scope is short enough that "observations returns an `Issue`-wrapped not-yet-implemented result" can be a stated exit criterion rather than a missing one.
- **Architectural seams align with commits.** The new boundaries are exactly the seams architecture.md §18 calls out (harness → catalogue port → observation port → closeout), so each commit is a coherent capability rather than a contract slice.
- **Review surface is smaller in total.** Five PRs ≪ eleven PRs of overhead (description, CI runs, review cycles), even though each is larger.

### What this costs

- **M1' is heavy.** It crosses the tracker's own "no more than ~6-10 files of meaningful logic" target — likely 12-15 files (dependency declarations, `Issue`/`OnIssue`/aliases module, registry, Protocol, catalogue envelopes, schemas, `provider_info()`, plus tests). The planner should accept this overrun explicitly; it is the price of removing the empty-Protocol pathology.
- **M2' adds ~10 public API methods in one commit.** The original tracker called M4's 7-method drop "the exception"; M2' is bigger. Mitigation: split the M2' PR into two reviewable patches landing in a single squash-merge if the team uses PRs, or accept that this is the discovery + observation contract surface and review it as one architectural unit.
- **M3' merges a maintainer-only generator with a runtime artifact landing.** Some teams prefer those separate because the generator changes infrequently after first land. If that matters here, this is the one merge to reconsider.
- **HTTP dep (Major 1) and the "what does `ch_foen.observations` do at M3' boundary" question (Major 2) still apply** — they don't dissolve under either slicing. The planner must address them either way.

### Recommendation

Adopt the 5-milestone re-grouping unless there is a concrete reviewer-bandwidth constraint that argues for the 11-milestone slice. The 5-cut is cleaner architecturally and removes one of the three Majors flagged above without weakening any architecture commitment.

If the planner keeps the 11-milestone slice, that is also defensible — but the empty-Protocol problem and the M7 half-wire then require explicit fixes (Majors 2 and 3 in this critique).

## Lens-by-lens summary

- **L1 Architecture coverage:** ✅ — all §0–§18 sections map to milestones; no orphans. §9 has a caveat (Major 3).
- **L2 §19 deferral hygiene:** ✅ — wide-form pandas, derived products, and vocabulary expansion are explicitly deferred in §7 of the tracker and in M5/M6 "Out of scope" lines. No silent decisions.
- **L3 One-commit shippability:** ⚠️ — M1–M6 are clean. M7 has the half-wired `ch_foen.observations` problem (Major 2). Everything else passes.
- **L4 Dependency graph honesty:** ✅ — every "Dependencies on earlier milestones" entry maps to a concrete consumed artifact. Caveat: HTTP dep (Major 1) means a *missing* dependency edge, not a fabricated one.
- **L5 Exit criteria falsifiability:** ✅ — strong negative controls in M3 ("corrupt packaged artifact raises immediately"), M4 ("invalid `source` raises as a fatal contract error"; three-way `on_issue` matrix), M5 ("annotation names not declared by provider schemas fail validation"), M6 ("normal package import does not import `generate_catalogue.py`"). Best in class.
- **L6 ch_foen reality check:**
  - (a) ✅ — milestone scopes ch_foen as translation, not greenfield: M6 explicitly says "translation-with-redesign" and names the BAFU endpoint and legacy fixtures.
  - (b) ✅ — milestone is not a thin syntactic transliteration: function-based provider module per §9, not a `SwitzerlandFetcher` subclass; metadata represented by Pydantic models, not class fields.
  - (c) ⚠️ → Minor 2 — fixture reuse is cited but not exit-criterion-enforced.
  - (d) ✅ — M6 names `hydro/locations`; M8 names the three CSV fixtures.
- **L7 Legacy Python consultation rigor:** ✅ with one Minor — spot-checked: `base.py` exists with `RiverDataFetcher.get_data` abstract method; `usa.py` exists with USGS `get_data`/`get_param_code`/unit conversion; `uk_ea.py` and `uk_nrfa.py` define `get_metadata()` (live); `usa.py` and `canada.py` do not (Minor 1). `origin/switzerland` blobs all exist (verified via `git ls-tree -r origin/switzerland`). No R-package citations found.
- **L8 Out-of-scope leakage:** ✅ — no public provider class; no global live discovery (M4 explicitly forbids); Polars canonical throughout; V1 vocabulary not broadened.
- **L9 Dependency-introduction order:** ❌ → Major 1 (HTTP), Minor 4 (pandas), Minor 5 (Pydantic). Polars and leafmap are placed correctly.
- **L10 Milestone granularity:** ✅ — M8 is the largest (legacy `switzerland.py` is 354 lines; adding long-form + annotations + provenance + stitching to one provider lands in the 6–10-file target). M4 is justified as the explicit one-commit-many-methods exception. No obvious splits or merges required.
- **L11 Open question rigor:** ✅ — every recommendation in §6 is backed by an architecture.md citation, the design-doc citation, or the legacy branch evidence. The on_missing/on_issue contradiction between design and architecture is surfaced and resolved in favor of architecture.md (correct per architecture.md §0).
- **L12 Executor stopping conditions:** ⚠️ → Minor 3 — missing stop on internal recreation of the country base-class shape. Otherwise strong (11 stops covering deferrals, public classes, Polars contract, on_issue replacement, generate_catalogue import, etc.).
- **L13 Forward-compat with discoveries.md:** ✅ — stop #5 routes contradictions to `docs/discoveries.md`; M11 lists `docs/discoveries.md` as an artifact; M8 funnels port pain into `docs/provider_ports/ch_foen.md`.
- **L14 Test-fixture reuse from RivRetrieve-Python:** ⚠️ → Minor 2 — fixtures are cited under "Legacy Python analogues consulted" for M6 and M8 but not pinned by exit criteria. No proposal to recapture from scratch, so this is Minor, not Major.

## Adversarial probes attempted

- Read the entire tracker (`docs/milestone-tracker.md`, 511 lines) and the entire architecture contract (`architecture.md`, 665 lines) to build the §0–§18 coverage table.
- Ran `git ls-tree -r origin/switzerland` in `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python` and confirmed every blob the tracker cites — `rivretrieve/switzerland.py`, `rivretrieve/cached_site_data/switzerland_sites.csv`, `tests/test_data/switzerland_metadata_locations.json`, `tests/test_data/switzerland_2016_temperature_20200101.csv`, `tests/test_data/switzerland_2206_discharge_20250101.csv`, `tests/test_data/switzerland_2282_stage_20250101.csv`, `tests/test_switzerland.py`, `examples/test_switzerland_fetcher.py`, `docs/fetchers/switzerland.rst` — exists. No hallucinated `origin/switzerland` citations.
- `git show origin/switzerland:rivretrieve/switzerland.py` and read 354 lines. Confirmed `BASE_URL = "https://api.existenz.ch/apiv1"`, `METADATA_URL = f"{BASE_URL}/hydro/locations"`, `INFLUX_URL = "https://influx.konzept.space/api/v2/query?org=api.existenz.ch"`, `MAX_WINDOW_DAYS = 366`, the 6-entry `VARIABLE_MAP` (discharge/stage/water_temperature × daily/instant), `_apply_parameter_preference` (preferred `flow` with `flow_ls` fallback), `_convert_units` (divide `flow_ls` by 1000), daily aggregation via `dt.floor("D").groupby.mean()`. M6/M8 will be translating real, complex provider behavior — including overlapping field preference and unit conversion, both of which architecture.md §17 directs to be represented via row annotations + issues. Tracker M8 names "structured issues for ... timezone/unit ambiguity" but does not name the `flow`/`flow_ls` preferred-fallback collapse — that is a real source of row-level provenance and should appear in M8 exit (Minor — not surfaced separately because it falls under M8's broader scope).
- `git show origin/switzerland:tests/test_switzerland.py` for the first 100 lines. Confirmed the legacy test pins concrete values (246 stations; station `2016`→`Brugg`, lat 47.4825, lon 8.1949, river `Aare`; `range(start: 2025-01-01T00:00:00Z, stop: 2025-01-02T00:00:00Z)` Flux query for gauge `2206`; `Token` Authorization header). These are the ground-truth values M6/M8 tests should match — fuel for Minor 2.
- `grep -n "def get_metadata\|def get_cached_metadata\|def get_available_variables" rivretrieve/*.py` across `RivRetrieve-Python`. Confirmed `get_metadata()` is defined in `uk_ea.py`, `uk_nrfa.py`, `brazil.py`, `japan.py`, `czech.py`, `germany_berlin.py`, `lithuania.py`, `norway.py`, `spain.py`, `poland.py` — but **not** in `usa.py` or `canada.py`. Tracker M4 cites both `usa.py` and `canada.py` as sources for `get_metadata()` legacy analogue → Minor 1.
- Read `rivretrieve/base.py` lines 1–80. Confirmed `RiverDataFetcher(abc.ABC)` with abstract `get_data`, `get_cached_metadata`, `get_available_variables`, `_download_data`. This is exactly the shape architecture.md §1 calls wrong and what stop #2 must (but currently doesn't fully) forbid recreating internally → Minor 3.
- Read `pyproject.toml`. Confirmed `dependencies = []` (zero runtime deps). Cross-referenced against M1 ("required runtime dependencies ... including Polars and any validation library") — no HTTP library, no pandas. Cross-referenced against legacy `switzerland.py` use of `requests` and the M6/M8 endpoints — confirmed the dep gap → Major 1, Minor 4.
- Walked the cross-cutting invariants block (tracker §2) against the M7 commit boundary. Item: "no milestone may leave half-wired public imports or failing placeholder behavior." Item: M5 introduces `ProviderHandle.observations` on the public Protocol. Item: M7 registers `ch_foen` with no `observations` implementation; M8 implements it. Mapped this to a concrete user call (`rr.provider("ch_foen").observations(...)`) and confirmed the tracker is silent on what M7 returns → Major 2.
- Walked architecture.md §9 ("the public provider handle is typed by a `typing.Protocol` that exposes the same public catalogue and observation behavior") against tracker M2's "Public provider handle typed by a protocol" + zero introduced methods. Confirmed the contract gap → Major 3.
- Grepped tracker for any reference to the R repo at `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve`. No matches. Clean.
- Grepped tracker for `on_missing`. Only appearance is in §6 open question #10, which explicitly resolves to `on_issue` per architecture.md. Clean.
- Grepped tracker for `live` to verify §5 coverage. All occurrences land in M3 (live provenance schema), M4 (live source handling + unsupported-issue path), M7 (provider-declared live capability flags), and stop #8 (no global live discovery). No orphan live commitment.
- Counted public methods introduced per milestone against the tracker's stated "no more than two public API methods" target. M1 = 0, M2 = 2, M3 = 1, M4 = 7 (the declared exception), M5 = 3 (`observations` + `to_polars` + `to_pandas` — within the spirit of the rule since the two `to_*` are export methods on `ObservationResult`), M6 = 0, M7 = 0 (no new signatures), M8 = 0, M9 = 1, M10 = 1, M11 = 0. Granularity holds — no covert M4-sized milestones lurking.
