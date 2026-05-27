# 02-catalogue-methods-packaged — Adversarial Critique

## Verdict (round 3, post-revision)

DISPATCH AS-IS.

All round-2 findings are resolved. The plan is internally consistent,
citation-verified, and every `uv run pytest` checkpoint in §6 is now
green at the named intermediate state. No new issues introduced by the
round-3 revision.

## Round-2 → round-3 verification

### Round-2 Minor m1 (§6 step 9 vs. `rr.X` exports) — FOLDED

§6 step 9 (line 187) now reads:

> Add `tests/test_discovery.py` global discovery coverage for T17-T21
> and T27, importing the new functions directly from
> `rivretrieve._internal.discovery` until step 10 promotes them
> through `rivretrieve.__init__`; do not call `rr.stations()`,
> `rr.products()`, or `rr.product_info()` at this checkpoint. Run
> `uv run pytest`.

The instruction matches the existing in-file convention at
`tests/test_discovery.py:13` (`from rivretrieve._internal.registry
import …`). After step 10 the functions become bound at both
`rivretrieve.stations` and `rivretrieve._internal.discovery.stations`,
but the tests added in step 9 will continue using the internal import
shape — that is fine; the behavior tested is identical.

The "do not call `rr.stations()` … at this checkpoint" prohibition is
sharper than just "import internally" because it forecloses the
careless executor who imports internally but then writes
`rr.stations()` out of habit. ✓

### Round-2 Nit n1 (T19 Q10 Option B breadcrumb) — FOLDED

§8 line 251 now reads:

> Canonical product-dictionary-backed `rr.product_info()` semantics:
> deferred until architecture/product authority requests Q10 Option B.
> Hard rationale: step 02 deliberately chooses Option A, equivalence
> with `rr.products()`, because no runtime product-dictionary
> catalogue artifact exists yet.

A future planner reading §8 will find the explicit reference point;
the T19 wording no longer needs to carry the full Option A/B context
inline. ✓

### Round-2 Nit n2 (§3 → Q1 cross-reference) — FOLDED

§3 line 92 now ends with "see Q1 for the class-shape rationale". The
provenance-divergence semantics and the class-shape justification are
explicitly linked. ✓

### Round-2 Nit n3 (Q1 "single reader" overstatement) — FOLDED

Q1 (line 197) tail revised from "single reader for handle and global
paths" to:

> Free functions would be leaner, but they would repeatedly thread
> the same artifact/provider state through every call and make the
> source-validation, filtering, and schema-validation contract easier
> to diverge across handle and global paths.

The shared contract is named precisely (source validation, filtering,
schema validation), and the deliberately-non-shared piece (handle-
level vs. global provenance) is left out — matching §3 line 92's
explicit "global path constructs provenance at the discovery layer"
wiring. ✓

## Major findings (round 3)

None.

## Minor findings (round 3)

None.

## Nits (round 3)

### n1. Test-description shorthand `rr.X()` survives in T17-T21 / T27 even though step 9 tests do not call `rr.X()`

T17/T18/T19/T20/T21 and T27 still describe behavior using
`rr.stations()`, `rr.products()`, `rr.product_info()` in backticks.
After §6 step 9's "do not call `rr.stations()` … at this checkpoint"
instruction, the test descriptions and the test code's import shape
will not match in the version-controlled tree (the code imports from
`_internal.discovery`; the docstring/test-name shorthand says `rr.X`).

This is purely documentation drift. The same callable is exposed at
both paths after step 10, so the test still proves what the
description says it proves. A future reader scanning the test names
will not be misled.

Skip if you want. If you do want to address it, the cheapest fix is
to swap the test descriptions to refer to the function by bare name
(`stations()`, `products()`, `product_info()`) rather than the public
`rr.` shape — but that loses the visual hint that these are
public-surface functions. Net: cosmetic.

### n2. Step 9's "do not call `rr.stations()` … at this checkpoint" reads as a transient prohibition

The §6 step 9 wording implies the executor can later switch the tests
to `rr.X` form once step 10 lands. The plan does not call out whether
step 10 (atomic) or step 12 (lint/test gates) should perform that
switch. The simplest answer is "do not switch" — the tests work as
written and the internal import shape is fine permanently. Worth one
sentence saying so, otherwise a sharp executor may add a redundant
"sweep test_discovery.py to use rr.X" sub-task. Pure cosmetic.

## Lens-by-lens summary

L1.  ✅ — scope completeness intact from round 2.
L2.  ✅ — no scope overreach.
L3.  ✅ — citations verified in round 1; unchanged.
L4.  ✅ — test coverage adequate; all chain-empty assertions in
     place (T11, T12); T22/T23 union explicit; T25 rename in place;
     T27 method-level monkeypatch.
L5.  ✅ — fatal-raise inventory complete.
L6.  ✅ — Q1-Q10 each have evidence; Q10's Option A/B framing makes
     the semantic choice visible; Q1 phrasing now precise.
L7.  ✅ — §8 deferrals complete and rationale-backed; new Q10 Option
     B deferral folded.
L8.  ✅ — file order keeps `uv run pytest` green at every
     intermediate state. Round-2 m1 (step 9 import shape) verified
     folded; step 10 atomic edit verified folded.
L9.  ✅ — stopping conditions cover the new failure modes added in
     round 2 (non-string-filter fall-through, intermediate-pytest-red
     general guard).
L10. ✅ — every M2 architecture commitment preserved.
L11. ✅ — Q1 now names the exact shared contract (source validation,
     filtering, schema validation); the class's value proposition is
     precise rather than overstated.
L_two_channel. ✅ — every fatal path raises direct; T11 and T12
     enforce structurally.
L_m1_inheritance. ✅ — all seven sub-items verified in round 2 and
     unchanged.
L_source_semantics. ✅ — fatal stopgap raises before reader work;
     step 03's replacement seam at the top of each method.
L_filter_columns. ✅ — every planned filter backed by a schema
     column; runtime type validation prevents Polars coercion silence.

## Adversarial probes attempted (round 3)

1. **Probe: does the new §6 step 9 instruction actually pin the
   import shape?** The wording "importing the new functions directly
   from `rivretrieve._internal.discovery`" combined with "do not call
   `rr.stations()` … at this checkpoint" leaves no executor latitude
   for a `rr.X` call at step 9. ✓

2. **Probe: does the step 9 → step 10 transition leave any test
   stale?** Step 10's atomic edit modifies `__init__.py` (adds three
   exports) and `tests/test_package.py` (updates exact-set + absences
   union). It does not touch `tests/test_discovery.py`. The step 9
   tests use `_internal.discovery` imports — the same callable
   referenced by `rr.X` after step 10. No test goes stale. ✓

3. **Probe: does Q1's tightened wording undercut the class shape?**
   The revised Q1 names three concrete shared contracts (source
   validation, filtering, schema validation). All three are tested
   in T01-T12. The handle-level provenance construction is shared
   between `_ProviderHandle.*` and the reader (per §3 lines 76-85),
   so the class has four pieces of shared logic, not three. Q1 could
   add "handle-level provenance defaults" as a fourth, but the
   omission is not load-bearing — §3 already documents the four
   pieces. Pure phrasing; not blocking.

4. **Probe: does the Q10 Option B deferral entry in §8 conflict with
   the absence of `rr.product_info()` from §1's scope?** §1 line 9
   explicitly names `rr.product_info()` as in-scope for this step,
   and Q10 Option A is the chosen semantic. §8 line 251 defers
   Option B specifically. No conflict — the public name ships in
   step 02 with Option A semantics; Option B is a future-step
   semantic change behind the same public name. ✓

5. **Probe: re-verify atomic step 10 keeps pytest green.** Step 10
   modifies two files in one logical change before invoking
   `uv run pytest`. `__init__.py` gains three exports; `test_package.py`
   gains the matching exact-set assertion + absences union. Both
   halves land in one commit boundary. ✓

6. **Probe: are T22 and T23 still mutually consistent after the
   round-2 union expansion?** T22 (exact set =
   `{providers, provider, provider_info, stations, products,
   product_info}` plus `__version__`). T23 (20-name absences union).
   Intersection of T22's exact set and T23's absences union is
   empty. ✓ No name appears in both.

7. **Probe: re-walk every §6 step's pytest checkpoint:**
   - Step 1: `InvalidCatalogueSourceError` no call sites. ✓
   - Step 2: `CatalogueReader` no call sites. ✓
   - Step 3: T01-T12, T26 against existing fixture; all symbols
     exist. ✓
   - Step 4: fixture extension, default preserved. ✓
   - Step 5: extends T04-T09 against richer fixture. ✓
   - Step 6: adds handle methods; existing tests unaffected. ✓
   - Step 7: adds T13-T16 in registry tests; renames step-01 stub
     test for T25. ✓
   - Step 8: adds discovery functions; not yet exported. ✓
   - Step 9: adds T17-T21 + T27, imports via `_internal.discovery`.
     ✓
   - Step 10: atomic `__init__.py` exports + `test_package.py`
     update for T22-T23. ✓
   - Step 11: extend `test_offline_import.py` only if needed; T24
     still passes. ✓
   - Step 12: lint/typecheck/test gates. ✓
   - Step 13: bump-my-version + commit + tag. ✓

   Every checkpoint is green.

8. **Probe: re-confirm `tests/test_internal_provider_module.py:37` rename in T25 leaves no broken references.** The
   step-01 test name appears only in:
   - `tests/test_internal_provider_module.py:37` (rename target).
   - `docs/milestones/m2-discovery-and-observation-contracts/steps/01-provider-info-and-module-contract/execution.md:58`
     (frozen audit-trail document — must not be edited).
   - The round-3 plan §5 T25 wording (planning text).
   
   No production-code reference; the rename is safe. ✓

## Round-1 → round-3 trajectory

| Concern | Round 1 | Round 2 | Round 3 |
|---|---|---|---|
| §6 step 10 `__init__.py` ordering | Major M1 | Resolved (atomic step) | (resolved) |
| T22/T23 absences as replacement | Minor m1 | Resolved (explicit union) | (resolved) |
| T11 chain check missing | Minor m2 | Resolved (T11+T12 chain) | (resolved) |
| CatalogueReader/global provenance wiring | Minor m3 | Resolved (§3 line 92) | (resolved) |
| Runtime filter-type validation | Minor m4 | Resolved (§3+§4+§9+T12) | (resolved) |
| T24 ownership ambiguous | Minor m5 | Resolved (T25 in-place) | (resolved) |
| `rr.product_info()` semantics | Minor m6 | Resolved (Q10 explicit) | (resolved) |
| §6 step 9 vs. `rr.X` exports | — | Minor m1 | Resolved (line 187 wording) |
| T19 Q10 Option B breadcrumb | — | Nit n1 | Resolved (§8 line 251) |
| §3 cross-reference clarity | — | Nit n2 | Resolved (§3 line 92 tail) |
| Q1 "single reader" overstatement | — | Nit n3 | Resolved (Q1 line 197) |

The plan is ready for executor dispatch.
