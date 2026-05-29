# Adversarial Critique — 02-conformance-and-v1-closeout

Reviewer: adversarial step reviewer (M5, FINAL). Critique of `plan.md` against `architecture.md` §0–§19, `docs/milestone-tracker.md` §3 (M5), step-01 `plan.md`/`execution.md`, `docs/discoveries.md` (D1–D10), `docs/provider_ports/ch_foen.md`, and the live `tests/` tree.

## Verdict

**DISPATCH WITH MINORS FOLDED.**

This is a docs/evidence step that lands one executor-authored conformance artifact (`docs/v1-conformance.md`), three §19 absence gap-fillers, final `ch_foen` port notes, an optional discoveries closeout note, and a minimal README usage section. I attacked the plan on the dimension that matters most for a V1 sign-off gate: checklist honesty. I swept **every** test name cited in the §3 mapping table (≈90 distinct names) — all exist in `tests/`. I opened the load-bearing negative controls by hand (listed under *Adversarial probes attempted*) and each is a genuine fail-on-regression control, not a test that passes regardless. I found **no** §0–§18 commitment that lacks an implementing milestone and is being quietly papered over. No arch amendment, no second provider, no §19 implementation, no REPORT.md authorship. The artifact is correctly kept separate from the orchestrator's report.

No Major. No ESCALATE. The Minors below are refinements that strengthen honesty/precision and should be folded into the executor brief; none blocks dispatch.

## Major findings

None.

## Minor findings

### M1 — §5 row cites weaker negative controls than the suite actually provides; "live" realization must be labeled precisely

- Plan line 69 (§5 row) negative controls: `test_catalogue_reader_invalid_source_remains_direct_fatal_for_all_methods`, `test_catalogue_reader_packaged_products_unchanged_by_live_capability`, `test_ch_foen_live_products_unsupported_uses_m2_routing`.
- Contract: architecture.md §5 commits four things — default `source="packaged"`; live never mutates packaged; unsupported live returns a normal result + warning issue; `source="live"` calls the provider *when supported*. No V1 provider declares any `live_*` flag (`tests/_stubs/stub_provider.py:25-27`, ch_foen all-False per `provider.json`), so the "calls provider when supported" branch is exercised only by **stub** live-capable providers, where the reader raises a *defensive fatal* because no real live fetch exists.
- The strongest §5 negative controls are therefore `test_catalogue_reader_live_capable_products_raise_defensive_fatal_for_every_on_issue` (+ stations/station_products siblings, `tests/test_internal_catalogue_reader.py:433/444/455`) and the `..._raise_wraps_unsupported_issue` / `..._ignore_returns_issue_without_warning` family. The plan's row does not cite them.
- Fix: have the executor (a) cite the `live_capable_*_raise_defensive_fatal_for_every_on_issue` controls in the §5 row, and (b) label §5 honestly in the artifact — realized = packaged default + unsupported→warning + live-capable→defensive-fatal + no-mutation; **no V1 provider performs a real live fetch**. This prevents a future reader from inferring live-fetch is exercised end-to-end. Conformant per §5 ("when supported"), but the label must say so.

### M2 — §9 verification count is not reconciled with the three new gap-filler tests

- Plan line 233 states "Expected test state before this step: 439 collected, 437 passed, 2 skipped" (matches step-01 `execution.md:25`). §4/§6 then add three new tests to `tests/test_m5_exit_criteria.py`.
- The plan never states the expected *post-step* count (~442 collected, folium-skip caveat aside). A reviewer/executor checking the final sweep against the only number in the plan (439) would see a mismatch.
- Fix: state the expected post-gap-filler collected count explicitly (baseline 439 + 3 = 442, modulo folium gating), so the final-sweep delta is pre-registered rather than improvised.

### M3 — §1 and §8 lean on the same three §19 gap-fillers as their negative controls; artifact must not imply independent behavioral NCs

- Plan lines 65 (§1) and 72 (§8) both answer "gap-filler needed? Yes" and point at the planned vocabulary/derived absence tests. Those same tests are §19's controls (lines 83, 93-108).
- This is legitimate cross-referencing — but in the final checklist it risks reading as if §1 and §8 each have a dedicated behavioral negative control when in fact the V1-scope guarantee for both is the *single* set of §19 absence checks (`test_v1_observed_property_vocabulary_remains_river_gauge_scope`, `test_v1_products_are_not_rivretrieve_derived`).
- Fix: when authoring the rows, have §1/§8 explicitly reference the §19 absence controls as shared evidence rather than restating them as if independent. Keeps the "one control, three rows" relationship honest.

## Nits

- N1 — Gap-filler tests #2/#3 (plan lines 99-108) call `rr.products()`, which returns a `CatalogResult`; the executor must read `.data`/`to_polars()` before asserting `derived`/`observed_property`. Within executor authority; flag only so it is not forgotten.
- N2 — README usage section (plan lines 138-144, Q6) is gated by tracker line 278 ("only if needed"). The plan's justification (no user-facing V1 method is documented) is defensible and the plan already forbids tutorials/live-network/second-provider/§19 examples. Keep it to a compact `Usage` block; do not let it grow into a guide. Not over-reach as written.
- N3 — §0 row (plan line 64) uses structural proxies (T120, 7-method protocol, offline-import) as the negative control for "no speculative shared abstractions." The plan correctly labels these `structural/process`. Acceptable; just ensure the artifact does not present them as behavioral tests of the process commitment itself.

## Lens-by-lens summary

- **L1 Scope completeness** ✅ — §3 table maps every section §0 through §19; §19 reaffirmed via three explicit absence controls. None skipped.
- **L2 Scope over-reach** ✅ — No §19 implementation, no second provider, no arch amendment, no REPORT.md. README is tracker-permitted and constrained. Gap-fillers are absence checks only.
- **L3 Citation verification** ✅ — Spot-checked arch §5/§7/§15/§19 against the document and tracker M5 §3 (lines 266-301); plan's characterizations are accurate. Provider-port token concern is real (`docs/provider_ports/ch_foen.md:78-82` already says map must not depend on the token path).
- **L4 Test coverage adequacy** ✅ — All ≈90 cited test names verified present in `tests/`. Three gap-fillers enumerated, offline, green-keeping (assert currently-true absences).
- **L5 Error-handling completeness** ✅ NA-leaning — Docs/test step; gap-fillers introduce no runtime failure modes (no folium, no network, no new provider code).
- **L6 Open-question rigor** ✅ — Q1–Q6 recommendations are evidence-backed (artifact separation, row format, structural labeling, §19 controls, README gate).
- **L7 Deferral hygiene** ✅ — §19 reaffirmed; each of wide-form/derived/vocabulary has a real negative control that would fail if the deferral were implemented.
- **L8 Implementation order** ✅ — §6 adds gap-fillers (asserting current-true absences) before docs, verification last; pytest stays green at every boundary.
- **L9 Stopping-conditions adequacy** ✅ — §8 names the gap-escalation condition (any §0–§18 commitment with no implementation milestone) and the overclaim/non-existent-test condition. §1 hard rule restates it.
- **L10 Architecture-commitment compliance** ✅ — Plan forbids editing architecture.md and promoting discoveries; recommendations are post-V1 candidates only (D5).
- **L11 Speculative-abstraction check** ✅ — No new abstraction smuggled in; gap-fillers are absence assertions, not types/protocols.
- **L_two_channel** ✅ — Both directions proven. Fatal-regardless-of-on_issue: `test_corrupt_artifact_still_raises_under_ignore` raises `CorruptCatalogArtifactError` under `on_issue="ignore"` (opened, genuine). Recoverable-routes-through-on_issue: `test_fatal_contract_error_is_separate_from_on_issue` (opened) asserts `FatalContractError` is not raised by `apply_on_issue` and `IssuePolicyError` is not a `FatalContractError`. §15 row cites both.
- **L_inherited_patterns** ✅ — Cites T120 (`test_deferred_public_names_remain_absent_after_provider_handle_promotion`, present) and 7-method protocol (`test_provider_handle_protocol_declares_exactly_seven_public_methods`, present) for no-public-type-promotion; offline-import test present for packaged/offline. Step-01 flip kept `StationMap`/`MissingOptionalDependencyError` private.
- **L_legacy_citation_fidelity** ✅ — Expected NONE; plan cites only arch/tracker/tests for its mapping. No fabricated `origin/switzerland` citation. (D10 path discipline not triggered by a docs/conformance step.)
- **L_vocabulary_boundary** ✅ — §1/§8/§19 vocabulary guarantee proven by new `test_v1_observed_property_vocabulary_remains_river_gauge_scope` (subset of exactly discharge/stage/water_temperature; deferred terms absent). Product dictionary confirms only those three observed properties and `derived: false` (`docs/product_dictionary.md`).
- **L_offline_invariant_explicit** ✅ — §4/§10 cite `test_import_rivretrieve_does_not_import_providers_stubs_or_generators`; the folium/leafmap/ipyleaflet `sys.modules` assertions live *inside that same function* (`tests/test_offline_import.py:7` fn, `:17` folium assert), so the citation now also covers the map backend per step 01.
- **L_asymmetric_encoding_round_trip** ✅ — §7 cites `test_ch_foen_generator_artifacts_validate_against_all_catalogue_schemas` (generator side; `tests/test_ch_foen_generate_catalogue.py:80`, exercises dict→JSON-string→validate), paired with loader-side `test_metadata_column_is_opaque_json_object_string` / `test_metadata_column_rejects_non_object_json`. Generator-side round-trip is covered, not only the loader (addresses D8).
- **L_conformance_honesty** ✅ — Opened 3 cited controls (see probes below); each exists and is a genuine negative control. Whole-table sweep: all cited names resolve to real `def test_...` functions.
- **L_checklist_completeness** ✅ — Every §0–§18 row present; §19 fully reaffirmed with controls. No section absent or hand-waved.
- **L_negative_control_presence** ✅ — Every "realized" row carries a named negative control (not merely a positive existence test); §0/§18 process rows use labeled structural controls.
- **L_gap_honesty** ✅ — Actively hunted for a §0–§18 commitment marked realized/deferred but actually unimplemented. §5 live-fetch is the closest candidate and is architecturally permitted ("when supported"); harness routing + defensive-fatal + unsupported-warning are all implemented and tested. Not a gap (see M1 for the labeling refinement).
- **L_artifact_separation** ✅ — `docs/v1-conformance.md` is the artifact; plan lines 19/56 explicitly exclude REPORT.md and keep the checklist out of it.
- **L_D7_probe** ✅ NA — Docs step; D7 (Pydantic extras/ty) not triggered. Plan §5 records D7 as a closeout note only.
- **L_D9_probe** ✅ NA — Docs step; step-01 execution confirms popups touch no `json.loads` walk, so D9 is inert. Plan §5 records it as closeout context only.

## Adversarial probes attempted

Three checklist rows spot-checked by opening the cited test (centerpiece L_conformance_honesty requirement), plus two whole-suite existence sweeps.

1. **§15 (Issues and error policy) — fatal-regardless-of-on_issue.** Row cites `test_corrupt_artifact_still_raises_under_ignore`. Opened `tests/test_internal_packaged_catalogue_artifact.py:395`: it deletes `stations.parquet` and asserts `load_packaged_catalogue_artifact(..., on_issue="ignore")` raises `CorruptCatalogArtifactError`. **Genuine negative control** — if a regression let a corrupt artifact pass under `ignore`, this fails. Confirms L_two_channel direction (a).

2. **§15 (Issues and error policy) — recoverable routes through on_issue, fatal does not.** Row cites `test_fatal_contract_error_is_separate_from_on_issue`. Opened `tests/test_internal_issues.py:202`: parametrized over `on_issue`/issue severities; asserts `apply_on_issue` raises `IssuePolicyError` (not a `FatalContractError`) only for the policy cases and does not raise otherwise. **Genuine negative control** — confirms L_two_channel direction (b).

3. **§7 (Catalogue record model) — asymmetric JSON-in-Parquet round trip, generator side.** Row cites `test_ch_foen_generator_artifacts_validate_against_all_catalogue_schemas`. Opened `tests/test_ch_foen_generate_catalogue.py:80`: generates the catalogue from the committed fixture and runs `validate_catalogue(...)` against all four schemas plus `packaged_catalogue_artifact_from_components(...)`; the sibling `:55` test `json.loads`-decodes the generator's `metadata` column. **Genuine negative control on the generator side** (the D8 trap) — a generator that forgot `json.dumps` on `metadata` would fail validation here, not only at the loader.

4. **Whole-table existence sweep (two passes).** Extracted every distinct test name from the §3 mapping table (≈90 names across §0–§19 positive evidence and negative controls) and grepped `def <name>` in `tests/`. Result: **ALL PRESENT** — zero fabricated or stale citations. (First pass false-negatived due to a zsh word-splitting bug in my own loop; re-run with `${=names}` confirmed all present, including `test_map_stations_*`, `test_*_for_every_on_issue`, `test_ch_foen_*`, token-sanitization, annotation, stitching, and protocol controls.)

5. **§19 gap-filler feasibility.** Confirmed the three proposed tests are absence checks implementable offline: `to_polars`/`to_pandas` exist and no `to_wide`/`to_pivot`/`to_dataframe_wide` exists (`src/rivretrieve/_internal/observations.py:216/219`); product dictionary has only discharge/stage/water_temperature observed properties and `derived: false` rows. The gap-fillers will be real fail-on-regression controls (adding a derived product or a new vocabulary term breaks them), not tests that pass regardless.
