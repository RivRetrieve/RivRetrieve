# 06-providerhandle-protocol-promotion Critique

## Scope and verdict summary

Reviewed `plan.md` against the ten review lenses and the M2 tracker exit
criteria (`docs/milestone-tracker.md` §3 L149-158, surface §3 L114-128,
Protocol shape §3 L120-126).

The plan is correctly framed as pure surface promotion plus a closeout
integration sweep, with no new behavior, no new fatal classes, and no new
issue paths. Two minor enumeration gaps were folded inline; one nit is
recorded for the executor.

## L1. Architecture coverage

Every M2 exit-criterion bullet from L149-158 is mapped to T118 in plan
§2 and §5. Cross-check:

| Tracker bullet (L149-158) | Plan §2 mapping | T118 covers |
| --- | --- | --- |
| Public `ProviderHandle` Protocol with full method set | line 17 | T110, T116, T117 |
| Provider+global catalogue → `CatalogResult`, no provider API for packaged | line 18 | yes |
| Invalid `source` raises fatal | line 19 | yes |
| Unsupported `source="live"` warn/raise/ignore | line 20 | yes |
| Fake provider observations one and many | line 21 | yes |
| Missing `start`/`end` raises before provider execution | line 22 | yes |
| Annotation-name validation | line 23 | yes |
| `result.data == to_polars() == to_pandas()` | line 24 | yes |
| `uv run pytest` passes | line 25 | implicit |

No tracker bullet is unmapped. No exit-criterion gap that would force
new behavior was discovered. M1 boundary checks (`rr.providers()` order,
`rr.provider("missing")` fatal) are not part of M2 exit criteria and are
already pinned by `tests/test_m1_exit_criteria.py` — see Nit N1 below.

## L2. Public surface

- T22 expansion in plan Q12 / §5 T119 is correct: `ProviderHandle` is
  alphabetically first in the present-set; `__version__` continues to be
  asserted separately via `vars(rivretrieve)`.
- T23 absence-set: plan §5 T120 enumerates nine remain-absent names. The
  existing `tests/test_package.py::deferred_names` list contains ~26
  symbols; T120 must continue to assert all of them except
  `ProviderHandle`. See Fold F1.
- No accidental promotion of helper types — plan Q9 explicitly keeps
  `ObservationResult`, `CatalogResult`, `AnnotationSchema`,
  `CatalogSource`, `OnIssue`, and catalogue schemas internal.
- `ObservationResult` intentionally non-public is articulated in Q9
  (used only in return-type annotation). Lens passes.

## L3. Two-channel pattern

Plan §4 explicitly forbids new fatal classes and new Issue-routed paths.
Plan §7 reinforces with "No new fatal exception classes" and "No new
Issue-routed paths". No `ProviderHandleProtocolViolationError` or
similar invention. Lens passes.

## L4. Protocol shape correctness

Cross-checked plan Q3 (lines 45-52) against tracker L120-126 and against
the concrete `_ProviderHandle` in `src/rivretrieve/_internal/registry.py`.

- `info()` — exact match.
- `products(*, source, observed_property, frequency, statistic, on_issue)`
  — names, kw-only marker, defaults match.
- `stations(*, source, on_issue)` — exact match.
- `station_products(stations: Sequence[str] | None = None, *, source, on_issue)`
  — positional `stations`, then kw-only `source` and `on_issue`. Matches
  concrete (`registry.py` L66-72).
- `row_annotation_schema`, `series_annotation_schema` — exact match.
- `observations(*, stations, products, start, end, on_issue)` — exact
  match.

Generic return parameters diverge from the tracker:

- Tracker writes `CatalogResult[ProductCatalog]`,
  `CatalogResult[StationCatalog]`, `CatalogResult[StationProductCatalog]`.
- Plan declares `CatalogResult[pl.DataFrame]` to match the concrete
  implementation in `registry.py` and `discovery.py`.

This is the right structural-conformance call: declaring catalogue
aliases on the Protocol without the concrete returning the aliased type
would break `isinstance`/`ty` strict conformance. Plan Q3 (lines 51-53)
and D3 candidate #2 (line 229) document the divergence as deliberate
and defer the alias decision to a later step. Lens passes.

## L5. _ProviderHandle conformance

- Concrete methods are instance methods (registry.py L38-113). Plan Q4
  keeps Protocol methods as instance methods — conformance is real.
- Plan Q4 declines nominal inheritance, relying on structural
  conformance. Justified.
- `_module` field on `_ProviderHandle` is not declared on the Protocol
  (Q5). Correct: it is registry wiring, not user surface.
- T112 asserts `isinstance(handle, ProviderHandle)`; T117 introspects
  each Protocol method's signature against tracker L120-126. The
  signature comparison is programmatic rather than a static table —
  acceptable and stricter than a docstring table.

Lens passes.

## L6. Public type narrowing

Plan §6 step 2 changes
`provider(provider_id: str) -> object` to
`provider(provider_id: str) -> ProviderHandle` in
`src/rivretrieve/_internal/discovery.py`. The re-export through
`src/rivretrieve/__init__.py` (§6 step 3) carries the annotation.

T114 (plan line 158) covers both layers:
- runtime: `typing.get_type_hints(rr.provider)["return"] is ProviderHandle`
- static: `uv run ty check` over a typed reference pattern
  `handle: rr.ProviderHandle = rr.provider("stub_provider")`.

Lens passes.

## L7. Test coverage (integration sweep)

Plan §2 and §5 T118 walk the M2 exit-criterion bullets. Plan adopts the
M1 monolithic precedent — one integration test, one assertion block per
bullet. Lens passes.

The optional "M1 boundary continuity" item (`rr.provider("missing")`
fatal re-check, `rr.providers()` deterministic order) is not in M2
tracker exit criteria; it is re-pinned by `test_m1_exit_criteria.py`.
Recorded as N1 below; executor may include the assertion in T118 for
defense-in-depth but is not required to.

## L8. Out-of-scope drift

- New files: `src/rivretrieve/_internal/handle.py`,
  `tests/test_provider_handle.py`, `tests/test_m2_exit_criteria.py`. No
  others. ✓
- Behavior changes to `_internal/observations.py`,
  `_internal/registry.py`, `_internal/catalogue_reader.py`,
  `tests/_stubs/stub_provider.py`: explicitly forbidden in §7. ✓
- Discovery.py: changes are limited to the `-> ProviderHandle` return
  annotation and the corresponding import. ✓
- Per-commit patch bump: §6 step 8 calls out
  `uv run bump-my-version bump patch` for the executor. ✓

Lens passes.

## L9. Stopping conditions

Plan §9 lists five specific stopping conditions tied to M2 closeout:

- Integration sweep cannot be written without new behavior → surface as
  step 05 (or earlier) defect.
- Module layout causes a circular import → revise the proposal, do not
  paper over.
- `ty check` rejects the Protocol or the `rr.provider` narrowing.
- `_ProviderHandle` signatures do not structurally match → step 05
  defect, not a step 06 fix.
- `runtime_checkable` cannot be made meaningful without nominal
  inheritance → revisit Q2/Q4.

These are M2-specific, not generic "stop if blocked" language. Lens
passes.

## L10. Q1-Q12 coverage

All twelve Qs are answered (plan §3 Q1-Q12). Q4 (no inheritance),
Q7 (circular-import shape), and Q9 (no signature-symbol exports) are
each answered with rationale. Lens passes.

## Folds applied this turn

### F1 — T120 absence-set must enumerate the full existing list, not nine names

Lens L2. Plan §5 T120 listed nine names. The existing
`tests/test_package.py::test_deferred_public_names_remain_absent_after_catalogue_surface`
asserts ~26 deferred names; T120 must continue to assert all of them
except `ProviderHandle`. Folded into plan §5 T120 to reference the full
existing `deferred_names` list and call out that only `ProviderHandle`
moves from absence to presence.

## Nits not folded

### N1 — Optional M1-boundary re-pinning in T118

Lens L7. M1 boundary items (`rr.providers()` deterministic ordering,
`rr.provider("missing")` raises `UnknownProviderError`) are not M2 exit
criteria and are already pinned by
`tests/test_m1_exit_criteria.py::test_m1_exit_criteria_smoke_sweep`.
Executor may add a small assertion to T118 if it reads naturally inside
the same sweep, but absence is not a defect.

## Deferred (D3 candidates)

Carried forward verbatim from plan §8; no new D3 items surfaced during
review:

- D3-1: Whether `ObservationResult` and other annotation dependencies
  should become public for users who want to spell return types
  directly.
- D3-2: Whether to add public/internal type aliases for catalogue
  payload shapes (`ProductCatalog`, `StationCatalog`,
  `StationProductCatalog`) so the Protocol can return
  `CatalogResult[StationCatalog]` instead of `CatalogResult[pl.DataFrame]`.
- D3-3: Choice of stable Protocol-introspection pattern
  (`__protocol_attrs__` vs explicit filter) once Python/runtime support
  is verified.
- D3-4: Whether the package should adopt an explicit `__all__` before
  broader public API growth.

## Verdict

DISPATCH WITH FOLDED MINORS

Folds:
- F1: plan §5 T120 absence-set enumeration extended to preserve the
  existing `tests/test_package.py::deferred_names` list minus
  `ProviderHandle`.

Nits (executor discretion):
- N1: optional `rr.providers()` + `rr.provider("missing")` re-pin
  inside T118.
