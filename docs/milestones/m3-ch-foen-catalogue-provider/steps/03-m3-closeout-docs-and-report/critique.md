# 03-m3-closeout-docs-and-report — Adversarial Critique

## Verdict

**Approve with required tightenings.** The plan's structure, scope discipline, and citation discipline are sound. Two Major findings must fold into the docs/REPORT before dispatch — both center on the M4 hand-off (token policy framing and capability-flag revisit). The remaining Minor and Nit items are tightenings.

The plan correctly stays in the "docs + sweep + REPORT" lane: no architecture edits, no new public surface, no M4 implementation work. The §4.2 audit is accurate against the actual test files (verified). The discovery inventory (D3 + D6/D7/D8/D9) is complete and correctly cited. The fixture facts (246 / Brugg / 1476) and commit SHAs (760f3fe, 99fa125) are all verifiable.

---

## Major findings

### M1 — Token-policy framing is stale; upstream has already declared the token public

Plan §3.1 Issues, §3.1 Q1 answer, §3.2 §7 surprises, and §7 Q1 all frame the legacy `INFLUX_TOKEN` as an unresolved credential whose policy "M4 must decide … public/documented service credential or … secret." That framing was correct at step-02 Q12 time, but is no longer current.

The latest commit on `thirdparty/RivRetrieve-Python @ origin/switzerland` is `cd9b030` — message: **"Restore public Switzerland token"**. The literal token at `rivretrieve/switzerland.py:40` is intentionally present *because upstream classifies it as a public service credential*, not despite the maintainer leaving a secret in source. The Authorization header use at `:200` therefore is not a "secret leak risk" — it is documented as a public-credential call pattern.

Why this is Major: the M4 hand-off the REPORT writes will shape M4 planner's first 30 minutes. If §3.2 §7 says "M4 must decide token policy" without citing `cd9b030`, the M4 planner will scope secret-management work (env vars, redaction, vault story) that upstream has already removed from the table. The actual M4 risks are narrower: (a) confirm the public-token classification still holds at M4 start by re-reading the head of `origin/switzerland`, (b) document the token in `docs/provider_ports/ch_foen.md` as a publicly-declared service credential with provenance to `cd9b030`, (c) decide whether to embed it as a literal, read it from configuration, or both. None of these is "secret vs public — to be decided."

**Required fix:** plan §3.1 §5 Issues, §3.1 Q1, §3.2 §7, and §7 Q1 must:

- Cite `origin/switzerland` HEAD `cd9b030` "Restore public Switzerland token" by SHA and subject.
- Reframe the M4 hand-off from "decide token policy" to "confirm upstream's public-token classification at M4 start, then decide embedding mechanics (literal vs config)."
- Keep the "M3 target carries no token because catalogue-only" sentence; that fact is unchanged.

The Q12 step-02 citation is still correct as historical record; what changed is the upstream maintainer's own classification.

### M2 — M4 hand-off omits capability-flag revisit

Plan §3.2 §7 surprises and §3.2 §9 M4 checklist enumerate annotation-schema extension, placeholder removal, observation result/parser types, fixture CSVs, top-level `rr.observations(...)` wrapper, and provenance/issue obligations. None mentions the capability flags on the `ProviderInfo` row.

The provider artifact ships `live_stations=False`, `live_products=False`, `live_station_products=False`, and `bulk_observations="false"` (verified from `provider.json`). These reflect M3's catalogue-only scope honestly. M4 must decide whether implementing live observation retrieval flips `bulk_observations` from `"false"` to e.g. `"window_required"` or similar, *and* the practical question of whether `live_*` catalogue flags change (they probably do not — Existenz.ch hydro/locations is still maintainer-side). If M4 does flip any flag, the generator must be re-run and the packaged `provider.json` regenerated.

This is high-leverage because M2 routing logic in `test_ch_foen_capabilities.py` (verified, lines 18/34/50/58) keys off these flags; an M4 PR that adds observation work without updating capabilities will silently leave runtime behavior inconsistent with provider declarations.

**Required fix:** add to plan §3.2 §7 ("Surprises and candidate updates for M4 prep") and §3.2 §9 ("Ready for M4" checklist) a bullet: *"Decide whether implementing observation retrieval flips `bulk_observations` away from `"false"` (likely yes); if so, re-run `generate_catalogue.py` and re-commit the packaged `provider.json`. The three `live_*` catalogue flags should remain False unless M4 also adds live catalogue calls, which is out of M4 scope."*

---

## Minor findings

### m1 — `docs/milestone-tracker.md` line citations don't point at M3 goal/exit criteria

Plan §1 cites `docs/milestone-tracker.md:152` for "M3 tracker goal and exit criteria" and `docs/milestone-tracker.md:186` for the same. Verified against the current file:

- Line 152 is `Invalid `source` raises as a fatal contract error.` — this is M2 exit criteria, not M3.
- Line 186 is the M3 "Public API surface introduced or changed" bullet (`No new signatures; rr.providers() now includes "ch_foen"…`), not exit criteria.
- M3 header is at line 164; M3 goal is at line 166; M3 exit criteria are at line 198.

Harmless if the executor opens the tracker, but the planner clearly was reading a stale file. Update to `:166` (goal) and `:198` (exit criteria).

### m2 — D7 and D9 are listed but not surfaced as M4 obligations

Plan §3.2 §6 correctly lists D3 + D6/D7/D8/D9 as M3 discoveries. Plan §3.2 §7 surfaces only D8 round-trip encoding as an M4 obligation ("Observation result generation will face the same D8 serialization/provenance obligations"). D7 (`extra="allow"` constructor kwargs trip ty) and D9 (`isinstance(x, Mapping)` narrows to `Never` under ty) are equally load-bearing for M4 if observation parsing uses Pydantic models with extras or walks `json.loads` output.

Add to §3.2 §7: *"D7 and D9 apply directly to M4 observation parsing. Any Pydantic observation model with `extra="allow"` must be tested via `model_validate({...})`, not constructor kwargs. Any `isinstance` check on `json.loads`-produced data must use concrete `dict`/`list`, not `Mapping`/`Sequence`."*

### m3 — Closeout-tag hedge is unnecessary

Plan §7 Q5 recommends `v0.1.17` but hedges "confirm with coordinator if they intended separate tags for M3 steps 01/02 after the fact." The tag inventory verified locally (`v0.1.14` M2 close → `v0.1.15` step 01 → `v0.1.16` step 02) already follows the step-granular convention codified in D1. M3 step 03 is `v0.1.17`. No coordinator confirmation needed; drop the hedge to avoid manufacturing decision overhead at execution time.

### m4 — Provider-port "Issues" and REPORT §7 carry duplicate content

Plan §3.1 §5 (provider-port Issues) and §3.2 §7 (REPORT surprises) overlap heavily: both carry token-status, placeholder shape, D6–D9 pointers. The prompt does require both, so this is not scope drift; the risk is the two say the same thing slightly differently on execution, then drift. Add an executor checkpoint to §6A/§6C: *"after writing both, diff the token-status and placeholder bullets for substantive consistency."*

### m5 — §4.2.3 "Public handle path … is not explicitly covered" is correct (verified)

Confirmed by grep: no test in `tests/` calls `rr.provider("ch_foen").observations(...)`. Only `tests/test_ch_foen_module.py:51` exercises the module-level placeholder. The plan's recommendation to add one parametrized test covering `raise`/`ignore`/`warn` plus default is right-sized. The candidate name `test_ch_foen_handle_observations_placeholder_returns_result_for_all_on_issue` is fine.

Note: be explicit in the new test that the public-handle path validates annotation tables against empty schemas (per `module.py` shape), so the test exercises the M2 validation seam, not just the module return value.

---

## Nits

### n1 — "fixture-backed parser/query tests" vocabulary drift

Plan §3.1 Q1 ends with "fixture-backed parser/query tests should isolate observation semantics from credential policy." The vocabulary used elsewhere is "fixture-backed observation CSVs" (§3.2 §9). Use the same term for consistency.

### n2 — `1476` not mentioned in §3.2 §5 inventory

Plan §3.2 §5 calls out the `246` and `Brugg` fixture facts but omits `1476` (station_products height). The step-02 execution.md does call it out at `:61`. The provider-port doc/§3.1 catalogue-mapping table should include the `246 × 6 = 1476` arithmetic explicitly so the REPORT inventory cross-references match.

### n3 — "M3 step 01" vs "M3 step 02" tag column in REPORT §1

Plan §3.2 §1 says "include test counts" but doesn't pin the tag column to existing tags. Per local inventory: step 01 → `v0.1.15`, step 02 → `v0.1.16`. Pin these so the REPORT table is concrete on first write.

---

## Lens-by-lens summary

- **L1 — Scope completeness.** ✓ provider-port doc, sweep audit, REPORT §1–§9 all covered. Outline matches M1/M2 shape exactly.
- **L2 — Scope over-reach.** ✓ no code edits beyond optional sweep tests; no architecture edits; no product-dictionary edits; M4 work is deferred not done.
- **L3 — Citation verification.** Spot-checked:
  - `tests/test_provider_handle.py:92` → T117 def line ✓
  - `tests/test_package.py:11`, `:26` → T119/T120 def lines ✓
  - `tests/test_ch_foen_module.py:43, 47, 51` → annotation-schema tests + parametrize line ✓
  - `tests/test_ch_foen_generate_catalogue.py:41, 50` → 246/Brugg test defs ✓
  - `tests/test_offline_import.py:7` → offline probe def ✓
  - `src/rivretrieve/_internal/providers/ch_foen/module.py:68, 72, 76` → annotation schema + observations placeholder ✓
  - `origin/switzerland:rivretrieve/switzerland.py:40` → `INFLUX_TOKEN = …` ✓ (line 200 also lines up with Authorization header block ✓)
  - `origin/switzerland:tests/test_switzerland.py:36-45` → 246/Brugg legacy assertions ✓
  - Commit SHAs 760f3fe and 99fa125 ✓
  - `docs/milestone-tracker.md:152, :186` → ✗ (see Minor m1)
  - Catalogue artifacts: 246 stations, 1476 station_products, 6 products, all `unknown` availability, all `False`/`"false"` capability flags ✓
- **L4 — Test coverage audit accuracy.** §4.2 correctly characterizes coverage gaps. The two "narrow explicitness gaps" (envelope/provenance and public-handle observations) are real — verified by reading the actual tests.
- **L5 — Document quality.** Outline coherent; tone consistent with M1/M2 REPORTs.
- **L6 — Open-question rigor.** Q1–Q6 each have a recommendation and rationale. Q1 needs the Major-M1 update.
- **L7 — Deferral hygiene.** All deferrals (M4/M5/post-V1) are real and isolated. No hidden dependencies that block step 03.
- **L8 — Implementation order.** 6A (provider-port doc) → 6B (sweep audit) → 6C (REPORT) → 6D (verification) is correct. 6A and 6C could in principle run independently, but the prompt's serial ordering ensures the provider-port doc settles first and the REPORT can quote it.
- **L9 — Stopping conditions.** Adequate. Covers behavior-family gap, step-02 decision invalidation, token reconciliation, missing-D-entry, public-API drift, architecture-commitment drift, and T117/T119/T120 regression. Stopping rule on §4.2 audit expansion is good.
- **L10 — M4 hand-off completeness.** **Insufficient.** See Majors M1 (token framing stale) and M2 (capability flags omitted), plus Minor m2 (D7/D9 not surfaced as M4 obligations). This is the highest-leverage lens for the step, and the plan needs all three fixes folded in.
- **L11 — Speculative content.** Plan does not pre-commit to M4 design beyond what architecture and product-dictionary already say. ✓ Caveat: the §3.2 §9 checklist item "fixture-backed observation CSVs to commit/use" cites legacy fixtures that are already in tracker scope; not over-commitment.

### N/A lenses (explicitly stated)

- **L_two_channel** — N/A for a docs/REPORT step; no `apply_on_issue` code touched. Stated.
- **L_inherited_patterns** — N/A; no code changes. Stated.
- **L_offline_invariant** — N/A; no imports added. The audit re-runs the existing probe at §4.2.5 / §6D. Stated.
- **L_protocol_conformance** — N/A; no code changes. T117 is re-run, not extended. Stated.

### L_legacy_citation_fidelity

All legacy citations in the plan that I checked against `thirdparty/RivRetrieve-Python @ origin/switzerland` resolve correctly: line 40 `INFLUX_TOKEN`, line 200 Authorization header, line 41 SOURCE, line 42 COUNTRY, lines 44–80 VARIABLE_MAP, lines 151–162 station-metadata extraction, `tests/test_switzerland.py:36-45` 246/Brugg fixture assertions, `tests/test_data/switzerland_metadata_locations.json:1` fixture top level. The single material lapse is omission of upstream HEAD `cd9b030` "Restore public Switzerland token" — captured under Major M1.

### L_vocabulary_boundary

Plan accurately represents the canonical / ch_foen-specific / dropped classification committed in step 02:

- All six legacy variables → canonical V1 IDs. Verified against `products.parquet`: `discharge_daily_mean`, `discharge_instantaneous`, `stage_daily_mean`, `stage_instantaneous`, `water_temperature_daily_mean`, `water_temperature_instantaneous`. ✓
- No ch_foen-specific product IDs. ✓
- No dropped legacy products. ✓
- `native_id` resolves to `flow` / `height_abs` / `temperature` (preferred parameters). ✓

No drift between docs and artifacts.

### L_fixture_binding

REPORT §5 attributes 246 / Brugg to:
- `tests/test_ch_foen_generate_catalogue.py:41` (`test_ch_foen_generator_station_count_matches_legacy_fixture`) ✓
- `tests/test_ch_foen_generate_catalogue.py:50` (`test_ch_foen_generator_station_2016_brugg_matches_legacy_fixture`) ✓
- Legacy origin: `origin/switzerland:tests/test_switzerland.py:36-45` ✓

Attribution is correct. Adding `1476` for `station_products` height (nit n2) makes the inventory complete.

---

## Adversarial probes attempted

1. **Token-status currency.** Read `origin/switzerland` HEAD via `git log --oneline -1`. Surfaced `cd9b030 "Restore public Switzerland token"`. Plan does not cite or acknowledge this commit despite Q12 being the entire basis for the token framing. → **Major M1.**

2. **Capability-flag downstream.** Read `provider.json` artifact: all `live_*` False, `bulk_observations="false"`. Searched §3.2 §7 / §3.2 §9 for "capability", "bulk", "live_". No M4 obligation around flag revisit. → **Major M2.**

3. **Discovery completeness.** Read `docs/discoveries.md` D1–D9. D6–D9 are step-02 logs; D3 is the step-01 resolution. Plan §3.2 §6 lists exactly these. D4/D5 are M2 step-06 origin; plan correctly does not surface them as M3 events. → Pass.

4. **Audit accuracy on §4.2.3 (handle observations).** `grep -rn 'provider(.ch_foen.).observations' tests/` returns no hits. Plan's claim that the public-handle observations path is not explicitly tested is correct. → Pass.

5. **Audit accuracy on §4.2.1 (envelope/provenance).** Read `tests/test_ch_foen_registration.py:13, 21, 28, 35`. All four assert `.data.height` and row filter behavior; none asserts `CatalogResult` envelope, `provenance.source`, or `provenance.provider_id`. The plan's "data rows but not all envelope/provenance details" characterization is accurate. → Pass.

6. **Audit accuracy on §4.2.2 (live rejection).** Read `tests/test_ch_foen_capabilities.py:18, 34, 50`. All three cover `products`/`stations`/`station_products` with `warn`/`raise`/`ignore` branches. Plan's "no new test expected" is correct. → Pass.

7. **Mapping table vs artifacts.** Read `products.parquet`, `stations.parquet`, `station_products.parquet`, `provider.json`. All six product IDs match plan §3.1.2. Heights 6/246/1476 match. `provider_info.name` matches plan and `test_ch_foen_module.py:19`. All False/`"false"` flags match plan §3.5. The packaged `provider.json` metadata JSON has additional `fixture_*` keys not enumerated in plan §3.5 (`source_url`, `legacy_source` was the minimum); plan said "at least", so OK. → Pass.

8. **Tracker line numbers.** Opened the tracker. Lines 152 and 186 from plan §1 do not match what they claim. → **Minor m1.**

9. **Tag inventory.** Local `git tag --list` shows `v0.1.14`…`v0.1.16` for M2 close → step 01 → step 02. Plan recommendation `v0.1.17` for step 03 is correct; the coordinator-confirmation hedge is unnecessary. → **Minor m3.**

10. **No M4 work hidden in 6A/6C.** Read the §3 outline. The "Annotation" section in §3.1 stays at "schemas are empty in M3, by design; M4 owns real observation annotations." No premature schema extension. The §3.2 §7/§9 surfaces M4 obligations as recommendations, not changes. → Pass on L_premature_M4_work; the Major findings are about *under-specification* of the hand-off, not over-implementation.

---

**Bottom line.** Fold in Majors M1 and M2, plus the five Minor tightenings, and dispatch. The plan otherwise demonstrates the discipline this step needs: no scope creep, accurate test-coverage characterization, and a faithful audit of step-02 artifacts.
