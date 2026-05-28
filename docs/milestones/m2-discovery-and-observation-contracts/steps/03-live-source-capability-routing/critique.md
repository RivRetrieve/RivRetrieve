# 03-live-source-capability-routing — Adversarial Critique

## Verdict (round 2, post-revision)

DISPATCH AS-IS.

Both round-1 Majors are resolved. All round-1 Minors and Nits are
folded. The implementation order in §6 now keeps `uv run pytest`
green at every intermediate state, and the two-channel silencing
guarantee for the defensive `LiveCatalogueRoutingNotImplementedError`
is asserted by parametrized tests. No new Majors or Minors
introduced by the round-2 revision.

## Round-1 → round-2 verification

### Round-1 Major M1 (T42–T44 missing `on_issue` parametrization) — FOLDED

§5 lines 153-157 now read:

> T42. `test_catalogue_reader_live_capable_products_raise_defensive_fatal_for_every_on_issue`: capability true plus `source="live"` raises `LiveCatalogueRoutingNotImplementedError` for `on_issue in ("warn", "raise", "ignore")`, with no `IssuePolicyError` chain.

T43 and T44 mirror the matrix for stations and station-products.
§6 step 6 (line 174) reinforces with: "T42-T44 must parametrize over
`on_issue in ("warn", "raise", "ignore")`". §5 line 165 closes
explicitly: "live capability-true fatals are explicitly proven non-
silenceable across every `on_issue` value". The "no
`IssuePolicyError` chain" clause forecloses the `on_issue="raise"`
re-wrap inversion. The two-channel guardrail is now structurally
proven, not socially. ✓

### Round-1 Major M2 (§6 step 4 leaves T10/T11 red) — FOLDED

§6 is now reordered. The new step 4 (line 172):

> Update the existing invalid-source tests in `tests/test_internal_catalogue_reader.py` before changing reader behavior: remove `source="live"` from the `InvalidCatalogueSourceError` cases and keep only values that remain invalid, such as `"archive"`. This preserves T10/T11 intent until T40/T41 supersede it. Run `uv run pytest`.

This precedes the reader change in the new step 5. Walked the
checkpoint sequence:

- **After step 4**: Current reader still raises
  `InvalidCatalogueSourceError` for any value `!= "packaged"`, so
  T10 with `source="archive"` and T11 with `source="archive"` (or
  whatever non-`"live"` value the executor picks) keep raising the
  expected fatal. All other T01–T27 untouched. `pytest` green.
- **After step 5**: Reader now validates `source ∈ {"packaged",
  "live"}`. `"archive"` is still rejected via
  `InvalidCatalogueSourceError`. T10/T11 still green. New live
  unsupported / defensive-fatal behavior is dormant until T28–T45
  arrive in step 6. `pytest` green.
- **After step 6**: T28–T45 added, exercising the new behavior.
  `pytest` green.
- **After step 7**: T23 absence list extended to include the two
  new internal symbols. `pytest` green.

§9 line 249 stop condition ("Any intermediate file order leaves `uv
run pytest` failing…") is now respected by §6's ordering. ✓

### Round-1 Minor m1 (live + malformed filter unspecified) — FOLDED

§3 line 73 commits to the conservative option (b):

> Method input validation happens next for existing fatal contracts.
> In particular, `read_products(source="live", observed_property=123)`
> still raises `FatalContractError`; live unsupported routing must
> not silence malformed product filter inputs.

§4 line 119 echoes the rule at the two-channel guardrail level. T45
(§5 line 159) is the structural assertion:

> `source="live"` with capability false and a non-string product
> filter raises `FatalContractError` directly, with no
> `IssuePolicyError` chain and no live-unsupported result.

This is the strictly defensive read: "fatal misuse stays fatal"
holds across both packaged and live source. The reordering inside
each reader method (source check → filter check → packaged/live
dispatch) is unambiguous. ✓

### Round-1 Minor m2 (PascalCase factory function) — FOLDED

§2 line 27 now reads `Add class LiveCatalogueUnsupportedIssue(Issue)`.
§3 lines 49-58 specifies the subclass shape with a typed `__init__`
delegating to `super().__init__(severity=..., code=...)`. Q1 (line
183) explains why the subclass is preferred over the round-1 factory
form: "the required name is PascalCase and therefore reads as a
type; making it a real `Issue` subclass preserves the tracker-bound
name and avoids a nonstandard factory function".

I verified the pattern compiles under the project's pydantic v2:

- `isinstance(LiveCatalogueUnsupportedIssue(...), Issue)` is `True`.
- The frozen `ConfigDict` is inherited; field mutation post-
  construction raises `pydantic.ValidationError` as expected.
- The subclass does not add new fields, so the existing `Issue`
  schema (severity, code, message, details, provider_id) is the only
  thing pydantic validates.

The `ruff N802` risk that round-1 m2 flagged is also dissolved
because the symbol is now a class, not a function. ✓

### Round-1 Minor m3 (§6 step 2 "if needed") — FOLDED

§6 step 2 (line 170) is now mandatory and concrete:

> Extend `tests/test_internal_issues.py` with focused assertions
> for `LiveCatalogueUnsupportedIssue`: severity, code, provider ID,
> message, and details. Run `uv run pytest`.

The "if needed" coin-flip is gone. Factory-level (now subclass-
level) assertions are co-located with the existing `Issue` tests in
`tests/test_internal_issues.py`. ✓

### Round-1 Nit n1 (T28–T30 fixture dependency) — FOLDED

§6 step 3 (line 171) closes with "This fixture support is required
for T28-T30 and T42-T44." Q9 (line 215) names both consumers
explicitly: "Add a live-capable artifact variant or fixture override
for T28-T30 packaged-capability invariance and T42-T44 defensive
fatal tests." The dependency between the matrix tests and the
fixture extension is no longer implicit. ✓

### Round-1 Nit n2 (per-call re-validation note) — FOLDED

Q5 (line 199) now appends: "This re-validates a row already
validated at artifact-build time, but the duplication is defensive
and small". A future executor optimizing the catalogue reader will
not strip the per-call `ProviderInfo.from_row` thinking it is
redundant work. ✓

### Round-1 Nit n4 (helper names) — FOLDED

§6 step 5 (line 173) names the helpers: "shared private helpers
such as `_empty_frame(schema)` and `_live_provenance()`". The
parallel with the existing `_provenance()` at `catalogue_reader.py:
83-100` is preserved. ✓

### Round-1 Nit n3 (defensive fatal name length) — UNCHANGED, ACCEPTABLE

The planner kept `LiveCatalogueRoutingNotImplementedError` (Q3 line
191). Round-1 explicitly marked this as "Skip if you like the long
form"; the planner picked the long form. The defensive fatal will
appear three times in T42–T44 test names plus three times in
parametrize bodies. Readable, if verbose. No action needed.

## Major findings (round 2)

None.

## Minor findings (round 2)

None.

## Nits (round 2)

### n1. T10 parametrize becomes a single-element list after step 4

§6 step 4 says to remove `source="live"` from T10's parametrize
"and keep only values that remain invalid, such as `"archive"`".
Current T10 (`tests/test_internal_catalogue_reader.py:174`)
parametrizes over `["live", "archive"]`. The straight-line
application drops "live", leaving `@pytest.mark.parametrize("source",
["archive"])`. A single-element parametrize is stylistically
awkward; the test could equivalently inline `source="archive"` and
drop the decorator.

The planner left room for this ("such as `"archive"`"), so the
executor may also expand to a richer set like `["archive", "",
"garbage"]` to keep the multi-value parametrize honest. Pure
stylistic choice. Skip if the executor prefers the single-element
form.

### n2. T45 is products-only; stations/station-products have no analogous filter

§3 line 73 names `read_products(source="live", observed_property=
123)` as the canonical filter-precedence case. T45 (§5 line 159)
tests only `read_products`. `read_stations` has no filter args;
`read_station_products` takes a `stations: Sequence[str] | None`
that does not go through `_ensure_filter_value`. So T45 cannot
be parametrized across methods the way T31–T39 are.

The plan does not claim cross-method coverage for T45, so this is
not a defect — but a future reviewer scanning the test inventory
might expect symmetry with the rest of the matrix. A one-line
clarification in T45 like "(products-only; stations and station-
products take no fatal-validated filter arguments)" would forestall
the question. Skip if the planner prefers the lean wording.

### n3. §9 stopping condition line 239 is correct but could mention the subclass

§9 line 239 reads:

> `LiveCatalogueUnsupportedIssue` is implemented as
> `FatalContractError`, raised directly, or made silenceable by
> bypassing `apply_on_issue`.

This covers the "becomes a fatal" inversion well. Round-1's plan
said "implemented as a direct fatal exception", which made sense for
a factory. The new wording works for the subclass too but could be
sharper: "becomes a subclass of `FatalContractError` rather than
`Issue`" or "is raised as an exception rather than passed to
`apply_on_issue`". Minor wording polish; the current line catches
the intended inversions.

## Lens summary

| Lens | Result (round 2) |
|------|------------------|
| L1. Scope completeness | Pass. |
| L2. Scope over-reach | Pass. |
| L3. Citation verification | Pass. Pydantic frozen subclass pattern locally verified to compile and preserve `isinstance(...,Issue)`. |
| L4. Test coverage adequacy | Pass. 18 tests T28–T45 cover the matrix; T42–T44 now parametrize over `on_issue`; T45 closes the live + malformed-filter hole. |
| L5. Error handling completeness | Pass. Filter validation under live path now explicitly fatal. |
| L6. Open question rigor | Pass. Q1 updated to defend the subclass; Q5 notes defensive re-validation; Q9 names both fixture consumers; Q10 calls out the T10/T11 update ordering. |
| L7. Deferral hygiene | Pass. |
| L8. Implementation order | Pass. §6 reordering keeps every checkpoint green. |
| L9. Stopping conditions | Pass. Twelve concrete signals including the two-channel inversions. |
| L10. Architecture commitment compliance | Pass. Two-channel guarantee now structurally tested. |
| L11. Speculative abstraction | Pass. Three customers each for `_empty_frame` and `_live_provenance`. |
| L_two_channel (STEP-03-CRITICAL) | Pass. Defensive-fatal silencing assertion is now in T42–T44. |
| L_capability_lookup (STEP-03-NEW) | Pass. |
| L_method_to_capability_mapping (STEP-03-NEW) | Pass. |
| L_m1_inheritance (1) Two-channel | Pass. |
| L_m1_inheritance (2) CatalogueColumn/Schema reuse | Pass. |
| L_m1_inheritance (3) JSON-string metadata | Pass. |
| L_m1_inheritance (4) Public-surface negative control | Pass. T22 unchanged; T23 extended in §6 step 7. |
| L_m1_inheritance (5) Offline-import invariant | Pass. T24 unchanged. |
| L_m1_inheritance (6) `_ProviderHandle` private | Pass. |
| L_m1_inheritance (7) `ProviderInfo` row contract | Pass. |

## Adversarial probes attempted (round 2)

1. **Try to silence the defensive fatal via `on_issue="ignore"`.**
   T42 now asserts `LiveCatalogueRoutingNotImplementedError` is
   raised for every `on_issue` value, with no `IssuePolicyError`
   chain. Probe blocked. ✓

2. **Try to break intermediate pytest green.** Walked §6 step-by-
   step. Step 4 modifies tests first; step 5 modifies the reader
   second. After step 4, the still-old reader keeps raising fatal
   for `"archive"`; after step 5, the new reader still raises fatal
   for any value outside `{"packaged", "live"}`. T10/T11 stay green
   across the boundary. Probe blocked. ✓

3. **Try to slip a malformed product filter past the live unsupported
   route.** §3 line 73, §4 line 119, and T45 jointly assert that
   `_ensure_filter_value` runs before the live branch decision.
   Probe blocked. ✓

4. **Try to make `LiveCatalogueUnsupportedIssue` a class that
   subclasses `FatalContractError` instead of `Issue`.** §2 line
   27 fixes the parent to `Issue`; §9 line 239 stops the executor
   if it subclasses `FatalContractError` instead. Probe blocked. ✓

5. **Try to drop `tests/test_internal_issues.py` extension as
   redundant.** §6 step 2 is now mandatory, not "if needed". Probe
   blocked. ✓

6. **Try to leak the new internal symbols to the public surface.**
   §2 line 22 adds both to the public-surface absence list; §6 step
   7 schedules the actual T23 list extension. T22 (exact public
   surface) catches accidental exports between steps 1 and 7.
   Probe blocked. ✓

7. **Try to introduce a constructor change to `CatalogueReader`.**
   Q5 (line 197-199), §3 line 68, and §9 line 242 stop signal.
   `ProviderInfo.from_row(self.artifact.provider_info)` per call
   preserves the step-02 constructor shape. Probe blocked. ✓

8. **Try to force `read_stations(source="live")` through a filter-
   validation step that does not exist for stations.** The plan's
   filter-precedence rule (§3 line 73) is scoped to `read_products`
   because that is the only method with `_ensure_filter_value`
   guards. Stations and station-products have no such fatal pre-
   check, so the live branch dispatches directly. No inconsistency
   between the rule and the per-method bodies. ✓

9. **Try to use the rich fixture for live-capable tests without a
   real override.** §6 step 3 commits to extending conftest with a
   live-capable variant; Q9 names T28–T30 and T42–T44 as the
   consumers. The fixture is required, not aspirational. Probe
   blocked. ✓

10. **Try to find a pydantic frozen-subclass implementation hazard.**
    Locally constructed a frozen `Issue` analogue and subclassed it
    with a custom `__init__` calling `super().__init__(**fields)`.
    `isinstance(instance, Issue)` is `True`; mutation raises
    `ValidationError` (frozen inherited). The pattern from §3
    lines 49-58 is sound under pydantic v2 as used in this project.
    No hazard. ✓
