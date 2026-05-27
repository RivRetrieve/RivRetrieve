# 01-provider-info-and-module-contract — Adversarial Critique

## Verdict (round 3, post-revision)

DISPATCH AS-IS

All round-1 Majors are resolved. All round-2 Minors are folded with
the recommended phrasing. No new issues introduced by the round-3
revision. The plan is internally consistent, citation-verified, and
each `uv run pytest` checkpoint in §6 is green at the named
intermediate state.

## Round-2 → round-3 verification

### Round-2 Minor m1 (T08 step ordering) — FOLDED

- §6 step 2 (line 156) now reads "Add `tests/test_internal_provider_
  info.py` covering T01-T07". T08 is no longer scheduled here.
- §6 step 4 (line 158) now reads "Add or extend registry tests for
  T08-T10". The handle test lands together with the other handle
  tests, after step 3 introduces `_ProviderHandle.info()`.
- `uv run pytest` at step 2 no longer has a `_ProviderHandle.info`
  reference. Verified green.

### Round-2 Minor m2 (T17 naming/assertion) — FOLDED

- §5 T17 (line 151) rewritten as `test_stub_catalogue_functions_
  are_explicitly_unimplemented_in_step_01`: "assert the stub
  `products()`, `stations()`, and `station_products()` functions
  raise `NotImplementedError`, proving they exist for Protocol
  attribute presence but are not step-01 harness behavior."
- This is the programmatic check the round-2 critique recommended;
  it enforces "step-01 placeholder" structurally rather than
  socially.

### Round-2 Minor m3 (fixture-helper duplication) — FOLDED

- §3 line 95: "Stub-private artifact construction lives in
  `tests/_stubs/stub_provider.py` as `build_artifact()`, which
  delegates to the existing `stub_packaged_catalogue_artifact`
  factory passed in by the fixture; it is not part of
  `ProviderModule`."
- §6 step 7 (line 161): "pass the existing `stub_packaged_catalogue
  _artifact` factory into `tests._stubs.stub_provider.build_artifact
  (...)`, and call `fresh_registry.register('stub_provider',
  artifact)` directly. `build_artifact()` must delegate to the
  existing conftest factory rather than duplicating synthetic
  artifact construction."
- Single canonical source of synthetic-artifact shape. Drift risk
  removed. The "or equivalent helper" coin-flip is gone.

### Round-2 Nit n1 (D1 reference) — FOLDED

- §6 step 12 (line 166) now reads "...commit, and tag per project
  instructions and D1's tag-after-bump convention in `docs/
  discoveries.md`." Future executor will not rederive the D1
  decision.

## Major findings (round 3)

None.

## Minor findings (round 3)

None.

## Nits (round 3)

### n1. §6 step 4 does not pin which test file owns T08-T10

The line reads "Add or extend registry tests for T08-T10" without
naming a target file. The executor can reasonably pick either
extending `tests/test_discovery.py` (which already covers handle
return-shape) or adding a new `tests/test_internal_registry.py`.
Either is acceptable. Mentioning the choice would just save a
moment's deliberation. Skip if you want.

### n2. Q3 phrasing "accepts one later Protocol edit"

The deferred Protocol extension is non-trivial (three new members
plus three new types in M2 steps 04-05). The phrasing is cosmetic
under-statement. Not blocking. Pure cosmetic.

## Lens-by-lens summary

L1.  ✅ — scope completeness intact from round 2.
L2.  ✅ — no scope overreach. Protocol surface restricted to four
     architecture.md §9 functions whose types exist.
L3.  ✅ — citations verified in round 1.
L4.  ✅ — test coverage adequate. Negative controls all present.
     T17 reshaped to programmatic `NotImplementedError` check.
L5.  ✅ — fatal-raise inventory intact.
L6.  ✅ — Q3 and Q6 carry their evidence; Q5 spells out the T13
     assertion shape.
L7.  ✅ — no unresolved forward refs; deferred-type Protocol members
     deferred to M2 steps 04-05.
L8.  ✅ — file order keeps `uv run pytest` green at every
     intermediate state. Round-2 m1 ordering fix verified.
L9.  ✅ — stopping conditions cover `register()` temptation, forward
     refs, placeholder aliases, and offline-import drift.
L10. ✅ — every M2 architecture commitment preserved.
L11. ✅ — no speculative abstractions.
L_two_channel. ✅ — extra-column behavior remains M1-recoverable;
     fatal paths raise direct without `on_issue` involvement.
L_m1_inheritance.
- (1) Two-channel: ✅
- (2) CatalogueColumn/Schema reuse: ✅
- (3) JSON-string metadata: ✅
- (4) Public-surface negative control: ✅ (T16 with absences).
- (5) Offline-import invariant: ✅ (T15 with `tests._stubs`).
- (6) `_ProviderHandle` not promoted: ✅
- (7) ProviderInfo row contract isomorphism: ✅ (with
  `ProviderId(...)` wrap at the boundary per §3 line 68).

## Adversarial probes attempted (round 3)

- Re-walked §6 step order against the revised T01-T07 / T08-T10
  split: each step's `uv run pytest` invocation references only
  symbols that exist in the tree after that step's writes. Verified
  green.
- Re-checked `runtime_checkable` Protocol against a module instance
  for T11: Python's `_proto_hook` iterates protocol attributes and
  uses `hasattr(instance, attr)`. Modules support `hasattr`, so
  `isinstance(stub_module, ProviderModule)` correctly verifies the
  four-attribute presence (`info`, `products`, `stations`,
  `station_products`). ✓
- Re-checked T17 against the §3 line 95 contract that the stub's
  catalogue functions raise `NotImplementedError`. The two are now
  consistent: §3 declares the contract; T17 enforces it
  structurally.
- Verified §6 step 7's delegation chain: fixture instantiates fresh
  `ProviderRegistry` → calls `tests._stubs.stub_provider.build_
  artifact(stub_packaged_catalogue_artifact_factory)` → factory
  produces a validated `PackagedCatalogArtifact` via
  `packaged_catalogue_artifact_from_components` (`tests/conftest.py:
  121-136`) → fixture calls `fresh_registry.register("stub_provider",
  artifact)` (`src/rivretrieve/_internal/registry.py:36-56`). The
  chain is single-source-of-truth and runs entirely outside the
  module-level `_registry`. ✓
- Spot-checked the round-2 m2 (T17) folding against the round-1 L4
  "negative-control inventory" requirement: T17 now proves the
  deferral structurally, T15 proves offline import absence, T13
  proves global registry isolation, T14 proves no import-time
  registration, T16 proves public-surface absence, T08 proves direct
  fatal raise. The six round-1-required negative controls are all
  in place. ✓
- Re-read §9 stopping conditions for completeness against round-2
  Major M2 (forward refs) and round-1 Major M1 (`register()`).
  Both temptations are explicit stop-and-surface conditions in §9
  lines 223-224. ✓
- Re-confirmed `docs/discoveries.md` D1 reference in §6 step 12.
  Verified plan's commit-and-tag step matches D1's tag-after-bump
  guidance.

## Round-1 → round-3 trajectory

| Concern | Round 1 | Round 2 | Round 3 |
|---|---|---|---|
| `register()` on Protocol | Major M1 | Resolved | (resolved) |
| Forward-ref strategy | Major M2 | Resolved | (resolved) |
| T08 boundary ambiguity | Minor m1 | Resolved | (resolved) |
| Extra-column escalation | Minor m2 | Resolved | (resolved) |
| T13 vacuous assertion | Minor m3 | Resolved | (resolved) |
| `ProviderId(...)` wrap | Minor m4 | Resolved | (resolved) |
| Step-02 ordering of T08 | — | Minor m1 | Resolved |
| T17 naming/assertion | — | Minor m2 | Resolved |
| Fixture-helper duplication | — | Minor m3 | Resolved |
| D1 tag-after-bump reference | — | Nit n1 | Folded |

The plan is ready for executor dispatch.
