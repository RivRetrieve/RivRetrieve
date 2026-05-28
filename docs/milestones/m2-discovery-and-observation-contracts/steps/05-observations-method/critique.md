# 05-observations-method — Adversarial Critique

## Verdict (round 2, post-revision)

**DISPATCH AS-IS.**

All seven round-1 Minors and all five round-1 Nits are folded. No
new Majors or Minors introduced by the round-2 revision. The
revision is surgical: each fold is a targeted clarification or
narrow scope tightening, not a redesign. The §6 ordering is now
green at every file-sized checkpoint, the two-channel assertions
are explicit on every fatal path, the always-on annotation
validation is called out as a deliberate architecture-stricter
interpretation, and the empty-result path is now typed at every
layer of `ObservationResult`.

### Round-1 → round-2 verification

- **m1 (validation order defense)** — FOLDED. §3 line 114 adds:
  "The module-presence check intentionally happens before request
  construction. A missing module is a stable registry wiring
  fatal, so reporting `ObservationsUnavailableError` first is
  clearer for artifact-only handles than letting call-site input
  errors mask the unregistered dispatch path. Registered-module
  calls still construct `ObservationRequest` before provider
  execution, so no fatal-input case can reach the provider
  module." Q5 line 288 mirrors the same reasoning. The
  L_handle_dispatch guarantee — no fatal-input case reaches the
  module call — is now stated explicitly. ✓
- **m2 (always-on validation tightening)** — FOLDED. §3 line 116
  now reads: "This is an explicit tightening of
  `architecture.md:556`, which says the harness validates names in
  tests or debug validation. The architecture does not forbid
  production-time enforcement, and the check is cheap, structural,
  and enforces the provider contract... No architecture addendum
  is needed unless a later provider port shows the cost is
  material." Q4 line 284 adds: "This is a deliberate
  stricter-than-debug interpretation, not an accidental read of
  §13." ✓
- **m3 (§6 ordering ambiguity)** — FOLDED. §6 step 2 now does the
  stub extension, §6 step 3 does the Protocol expansion. Line 253
  explains the stub gains three functions before they are required
  by the Protocol, so T11 remains green. Line 254 says the Protocol
  expansion lands after the stub already satisfies the new
  members. Line 266 closes: "the stub-first order in steps 2-3 is
  required. Do not expand the Protocol before adding the stub
  functions, because that would make the existing
  runtime-checkable conformance test fail at a file-sized
  checkpoint." The alternative atomic-batch path is gone. ✓
- **m4 (conftest change mandatory)** — FOLDED. §6 step 7 line 258
  now reads: "Modify `tests/conftest.py::registered_stub` to call
  `fresh_registry.register("stub_provider", artifact,
  provider_module=stub_provider)` at `tests/conftest.py:340`.
  `RegisteredStub` itself does not need a `module` field because
  the module reference lives inside the handle." The "only if
  useful" qualifier is removed. ✓
- **m5 (T89-T93 chain-absence assertions)** — FOLDED. T89 now
  reads: "missing `start` raises `InvalidObservationRequestError`
  with no `IssuePolicyError` chain and the provider spy is not
  called." T90, T91, T92, T93 each include the no-chain assertion
  inline rather than inheriting it from the §6 step 9 reference. ✓
- **m6 (provenance.request shape)** — FOLDED. §3 line 150 now
  specifies `request={"provider_id": str(request.provider_id),
  "stations": list(request.stations), "products":
  list(request.products), "start": request.start.isoformat(),
  "end": request.end.isoformat()}`. T84 line 196 adds: "and
  provenance `request` mirroring the normalized input." The stub's
  provenance contract is now executable. ✓
- **m7 (empty result typed frames)** — FOLDED. §3 line 143 adds:
  "Unknown-only calls still return a fully typed empty
  `ObservationResult`: `data`, `row_annotations.data`, and
  `series_annotations.data` are zero-row Polars frames carrying
  the canonical `ObservationDataSchema`,
  `RowAnnotationTableSchema`, and `SeriesAnnotationTableSchema`
  dtypes." T86 line 200 updated: "unknown IDs produce empty but
  typed canonical data, empty but typed row/series annotation
  tables, and no issues, not a fatal." This forecloses the
  AnnotationTable validation failure path on the empty case. ✓
- **n1 (@staticmethod decorators)** — FOLDED. §2 lines 32-34 now
  declare `@staticmethod def row_annotation_schema...`,
  `@staticmethod def series_annotation_schema...`, `@staticmethod
  def observations...`. §6 step 3 calls them "three new
  `@staticmethod` Protocol members". Convention matches existing
  four members. ✓
- **n2 (hardcoded stub IDs)** — FOLDED. §3 line 135: "These IDs
  are hardcoded into `stub_provider.observations`, independent of
  the registered artifact's stations/products tables. The default
  artifact contains only `"station-1"` / `"level"` and the rich
  fixture contains the rest, but the stub observation
  implementation does not consult either catalogue." Q6 line 292
  also clarifies the decoupling. ✓
- **n3 (T109 ProviderModule / _ProviderHandle absence)** — FOLDED.
  T109 line 246 now reads: "public surface remains unchanged;
  `ObservationsUnavailableError`, `ProviderModule`, and
  `_ProviderHandle` remain absent." ✓
- **n4 (T11 / T102 relationship)** — FOLDED. §6 step 4: "add or
  rename T102 for the seven-member Protocol... T11
  (`test_stub_provider_module_has_provider_module_attributes`) is
  unchanged in intent; T102 is its expanded seven-member sibling."
  T102 line 232: "this retains the existing T11 conformance intent
  at the full surface." ✓
- **n5 (T99 non-spy validation)** — FOLDED. T99 line 226: "use
  distinct row and series annotation IDs and bad module results
  to prove both tables are checked, avoiding monkeypatch
  dependence on how `validate_annotation_names` is imported." ✓

### Round-2 spot checks

- **No new public symbols introduced**: §2 lines 23-26 still pin
  `{"providers", "provider", "provider_info", "stations",
  "products", "product_info"}` plus `__version__`. ✓
- **No round-2 scope creep**: revisions touch §2 internal surface,
  §3 behavior, §4 unchanged, §5 test wording, §6 step order, Q4
  and Q5 explanations. No new files, no new symbols, no new
  exception classes beyond `ObservationsUnavailableError`. ✓
- **Stopping conditions §9 unchanged**: same 14 stop conditions
  as round 1. ✓
- **Deferrals §8 unchanged**: 12-entry deferral list intact. ✓
- **Two-channel invariant**: every fatal in §4 still subclasses
  `FatalContractError` and raises direct, never through
  `apply_on_issue`. The inline no-chain assertions on T89-T98
  prove non-silenceability. ✓
- **Implementation order is now executable as-written**: walked
  steps 1 → 11. Step 1 (issues.py add) has no call sites; pytest
  green. Step 2 (stub extension) adds three functions not yet
  required by Protocol; T11 green. Step 3 (Protocol expansion)
  declares members the stub already has; T11 green. Step 4 (T102
  add) lands once stub and Protocol agree. Step 5 (_module field
  default None + register signature) preserves
  `tests/test_internal_registry.py:103,132`. Step 6 (T104/T105)
  cover the new register signature both ways. Step 7 (conftest)
  switches the fixture to the three-arg register. Step 8 (handle
  observations + schema methods) lands the dispatch code. Step 9
  (handle observation tests) covers T84-T101 and T106. Step 10
  (offline import) preserves T108. Step 11 (T109) extends the
  deferred-absence list. Every step ends green. ✓

No further revision required. Dispatch.

---

## Original round-1 verdict (preserved for audit)

**Verdict: DISPATCH WITH MINORS FOLDED.**

This plan is structurally sound on the load-bearing decisions: the
seven-member ProviderModule is reached without authorizing a
`register()` member; ObservationRequest construction lives on the
handle (not the module); fatal-only error handling everywhere; the
two-channel pattern is honored across module-absence, request
validation, and annotation-name violations; the public Protocol
promotion and rr.provider() narrowing are deferred to step 06; no
recoverable observation issues are introduced; the stub provider
catalogue methods remain `NotImplementedError`; the registry
signature change picks the back-compat default that preserves the
two direct `_ProviderHandle` constructions in
`tests/test_internal_registry.py:103` and `:132` without churn.

The issues below are real, but none are architecture-breaking. They
are about (a) one validation-order choice that the brief
specifically called out and the plan reverses without defending the
reversal, (b) one architecture.md-vs-implementation tightening that
deserves an explicit interpretation note, (c) two implementation
ordering ambiguities the executor should not be left to resolve mid-
step, and (d) some test-spec tightening that the existing
`_has_issue_policy_error` pattern can absorb without re-planning.
Fold these into a revised plan; do not send back.

---

## Major

(None.)

---

## Minor

### m1. Validation order inverts the brief without defending the inversion

§3 line 103 places the `_module is None` check **before**
`ObservationRequest.from_inputs(...)`. The critique brief's
L_handle_dispatch lens explicitly listed the desired order as:

> (a) Build ObservationRequest via from_inputs — fatal on bad inputs.
> (b) Check module is registered — fatal if not (Q5=(a)).
> (c) Dispatch to module.observations(request, on_issue=...).
> (d) Run validate_annotation_names ... (row).
> (e) Run validate_annotation_names ... (series).
> (f) Return result.

The plan picks (b) before (a). Both orderings prevent any fatal
input case from reaching the module call — the contract guarantee
in L_handle_dispatch's "Any reordering that lets a fatal-input case
reach the module call = Major" is not violated either way — so this
is not the Major the brief warned about. But the choice has a
user-visible consequence: an artifact-only handle (no `_module`)
called with missing `start` raises `ObservationsUnavailableError`,
not `InvalidObservationRequestError`. The plan's tests do not
exercise this combination (T89-T93 use `registered_stub`; T94 uses
an artifact-only handle but always sends valid request inputs), so
the inversion is internally consistent. It is also defensible — the
plan can argue that "no module" is a wiring fatal that should be
the loudest signal regardless of input shape, because it surfaces a
registration bug before any user-input bug can mask it. But the
plan does not make that argument explicitly. Either reorder to
match the brief, or defend the reversal in §3 with one sentence and
update Q4/§3 narrative to acknowledge the choice and its
trade-off.

Recommendation: defend, do not reorder. Wiring fatals are stable
across calls; input fatals are call-site-dependent. Reporting the
wiring fatal first is friendlier to the executor implementing a
non-yet-registered provider.

### m2. Always-on annotation-name validation tightens architecture.md §13 line 556

Architecture.md line 556 reads: "The harness validates annotation
names in tests or debug validation." Q4 picks always-validate at
every handle call (§3 line 114). The plan defends this as cheap and
structural, which is true, but the wording "tests or debug
validation" reads as a deliberate softening of where the check
fires — not an unspecified default. Always-on validation is a
permissible tightening (architecture does not forbid it), but it is
load-bearing for M3+: any provider that emits an annotation row
must declare the schema, every handle call, with no debug toggle to
disable.

This either belongs as a one-line discoveries.md candidate (D3) or
as an explicit "we are choosing to enforce stricter than
architecture.md §13 line 556 reads" note in §3. The plan currently
does the latter implicitly but does not name the divergence. Add a
sentence acknowledging the tightening, and either log a D3
candidate or note that no addendum is needed because architecture
silence on production-time enforcement is permissive.

Recommendation: keep always-validate; add a one-sentence note in
§3 explicitly calling out the tightening; no D3 needed unless a
later milestone shows the cost.

### m3. §6 step 2-3 ordering is left as the executor's choice; pick one

§6 step 2 expands the `ProviderModule` Protocol to seven members.
§6 step 3 extends the stub. The plan acknowledges (line 248 and
line 261) that step 2 alone leaves
`isinstance(stub_provider, ProviderModule)` returning `False`, and
breaks T11 (`test_stub_provider_module_has_provider_module_attributes`)
at the file-sized checkpoint. The plan then offers two options
without picking one:

- "implement steps 2 and 3 as one edit batch before running
  `uv run pytest`, or"
- "temporarily update the stub first using currently unused
  functions and then extend the Protocol."

Either is valid. But the project invariant is "`uv run pytest` green
at every milestone boundary" plus the step-internal convention of
"green at every file-sized checkpoint" inherited from M1. Leaving
the choice to the executor invites a non-green checkpoint if they
mis-batch. Pick one in §6, and remove the alternative.

Recommendation: pick "extend the stub first, then expand the
Protocol." The stub gets three concrete function definitions; T11
keeps passing because `ProviderModule` does not yet require those
members; the next checkpoint expands the Protocol, and T11 still
passes because the stub now has the members. This avoids any
atomic-batch coordination across two files in one micro-step.

### m4. §6 step 7 phrasing on conftest is misleading

§6 step 7 reads: "Modify `tests/conftest.py::RegisteredStub` only
if useful to expose the module explicitly; the minimum change is
`fresh_registry.register("stub_provider", artifact, provider_module=stub_provider)` at
`tests/conftest.py:340`."

The conftest change is not optional. T84-T101 all depend on the
`registered_stub` fixture's handle being dispatchable, which
requires the module to be passed at registration. "Only if useful
to expose the module" implies an alternative path. There is none —
without the conftest change, every handle-observation test in
T84-T101 either skips dispatch or raises `ObservationsUnavailableError`
instead of running the real test path.

Recommendation: rephrase step 7 as a mandatory edit. Drop the "only
if useful" clause. Specify that `RegisteredStub` itself does not
need a `module` field (the module reference now lives inside the
handle), only the `register(...)` call needs the extra kwarg.

### m5. T89-T93 do not explicitly state the no-IssuePolicyError-chain assertion

§5 enumerates T89-T93 as "parametrized over `on_issue`; missing X
raises InvalidObservationRequestError and the provider spy is not
called." Compare to T94: "raises `ObservationsUnavailableError`
for all policies with no `IssuePolicyError` chain." T94 is explicit
about the chain absence; T89-T93 rely on §6 step 9's generic
reference to "the existing `_has_issue_policy_error` /
`_issue_policy_error_chain` pattern from registry/catalogue/
observation tests."

This is the structural guardrail that the project has consistently
applied to every fatal raise (M1 §5 negative-control inventory; T74,
T82 from step 04; T42-T44 from step 03). The plan should not let
T89-T93 inherit it by reference when T94, T97, T98 state it
explicitly. Make all input-validation fatal tests state the chain
absence assertion the same way, or add one sentence in §5 saying
T89-T93 all include the chain assertion.

Recommendation: add "with no `IssuePolicyError` chain" to T89-T93
inline, mirroring T94's wording.

### m6. Provenance.request shape unspecified in the stub spec

§3 line 145 says `provenance: ObservationProvenance(source="stub",
provider_id=request.provider_id, catalogue_version="2026.01",
request={...})`. The `{...}` is a placeholder. `ObservationProvenance.request`
is typed `dict[str, object] | None`. The stub will need a concrete
serialization (probably the four request fields plus `on_issue`),
and at least one observation test should assert on it (T87 spies
the request object received by the module but no test asserts the
provenance round-trip).

Recommendation: specify the stub's provenance.request as a flat dict
of the request's exposed fields: `{"provider_id": ..., "stations":
list(request.stations), "products": list(request.products),
"start": request.start.isoformat(), "end": request.end.isoformat()}`.
Either add an assertion to T84 that provenance.request mirrors the
input, or note explicitly that this stays unverified in M2.

### m7. Empty-result T86 needs an explicit annotation-table shape

T86 says unknown station/product combinations "produce empty
canonical data and no issues". `ObservationResult` requires
`row_annotations` and `series_annotations` to be non-None
`AnnotationTable` instances, not `None`. An empty data path
implies empty `AnnotationTable` instances with the correct schema
and zero rows. `AnnotationTable.__post_init__` calls
`validate_catalogue(..., on_issue="raise")` and the existing
`ObservationDataSchema` validation expects column types to match.
Empty Polars frames need their dtype schema specified explicitly;
constructing `pl.DataFrame()` gives no columns and would fail.

The stub spec in §3 lines 142-148 does not address the empty case.
The executor must either (a) always emit an empty-but-typed
`AnnotationTable` for every unknown-only call, with the correct
column schema and zero rows, or (b) emit a typed empty result by
re-using the canonical schemas. Specify which.

Recommendation: add to §3 stub spec: "Empty-result calls return
`ObservationResult` with `data`, `row_annotations.data`, and
`series_annotations.data` as zero-row Polars frames carrying the
canonical schemas (`ObservationDataSchema`, `RowAnnotationTableSchema`,
`SeriesAnnotationTableSchema`)."

---

## Nits

### n1. New Protocol members should be `@staticmethod` to match existing convention

`src/rivretrieve/_internal/provider_module.py` currently declares
all four Protocol members with `@staticmethod`. §2 lines 30-34 add
three new members without specifying the decorator. The convention
is implicit, but the plan should make it explicit for consistency
with the existing four.

### n2. Stub-known IDs decoupled from catalogue artifact may surprise executor

§3 lines 130-131 declare the stub's accepted observation universe
as `{station-1, station-2, level, flow, level_hourly, level_max}`,
while the default `stub_packaged_catalogue_artifact` fixture only
seeds `station-1` and `level`. The rich fixture seeds the rest.
The plan explicitly says the stub does not consult the catalogue
(line 128, line 138), so this is intentional and not a bug — the
observation method's accepted universe is decoupled from the
catalogue. But an executor reading T85 ("bulk station_product")
might assume the catalogue must contain `station-2` etc. Add a
one-line note in §3 stub-known IDs section: "These are hardcoded
into stub_provider.observations, independent of the registered
artifact's stations/products tables, because the stub does not
consult the catalogue."

### n3. T22 / T23 absence-list discipline

§2 line 26 and T109 add `ObservationsUnavailableError` to the
deferred-absence list. §6 step 11 says: "Modify
`tests/test_package.py` deferred absence list to include
`ObservationsUnavailableError` for T109. Do not change the public
present set." Verified against `tests/test_package.py:18-49` — the
current present set is `{providers, provider, provider_info,
stations, products, product_info}` plus `__version__`; the
deferred list already covers `ObservationDataSchema`,
`RowAnnotationTableSchema`, `SeriesAnnotationTableSchema`,
`InvalidObservationRequestError`, `ObservationDataSchemaError`,
`AnnotationSchemaViolationError`. Adding `ObservationsUnavailableError`
extends the existing pattern cleanly. Nit: also re-affirm
`ProviderModule` and `_ProviderHandle` absence after the Protocol
expansion — both should still be absent, but T109's enumeration
should be explicit that the seven-member Protocol does not change
their absence status.

### n4. T11/T17 update is implied, not enumerated

T102 says "stub_provider satisfies expanded provider module
Protocol" — this is the modern T11. The plan does not explicitly
say "T11 is superseded by T102" or "T11 is retained and continues
to pass." Since `isinstance(stub_provider, ProviderModule)` still
returns `bool` after expansion (and `True` once the stub has the
seven members), T11 should keep passing without edits. Confirm
this in §6 step 4 by adding: "T11
(`test_stub_provider_module_has_provider_module_attributes`) is
unchanged; T102 is its expanded sibling at the seven-member level."

### n5. T99 spy mechanism unspecified

T99 says "spy `validate_annotation_names` or use module schemas/
results with distinct annotation IDs to prove both tables are
checked." Monkeypatching `validate_annotation_names` requires the
handle to import it through the module attribute, not via `from
... import validate_annotation_names`. The plan does not pin which
import style to use. Defer to the executor with a hint, or pick:
the simpler approach is to use distinct annotation IDs in the
stub's row vs series declarations and emit one that violates each
schema in turn. This avoids a monkeypatch and any import-style
constraint.

---

## Lens summary

- L1 (scope completeness): ✓. Three handle methods, three
  ProviderModule members, registry signature change, stub
  extension, conftest fixture extension, annotation-name
  validation hook all covered.
- L2 (scope over-reach): ✓. Public Protocol promotion, rr.provider
  narrowing, public exports, rr.observations, recoverable issues,
  real provider modules, wide-form pandas, ch_foen annotation IDs,
  ProviderModule.register() are all out (§1, §8, §9).
- L3 (citation verification): Q1 back-compat verified against
  `registry.py:83` and tests/test_internal_registry.py:26-69. Q3
  observation signature verified against `architecture.md:425` and
  `ObservationRequest` shape at `observations.py:69-92`. Q11 file
  lines verified against `tests/test_internal_registry.py:103`
  and `:132`. All three claims hold.
- L4 (test coverage adequacy): ✓ overall. Single/bulk (T84/T85),
  missing start/end (T89/T90), empty stations/products (T91/T92),
  undeclared annotation × row/series (T97/T98), module-unregistered
  (T94), schema delegation (T100/T101), register back-compat
  (T104/T105), T11/T17 expansion (T102), T25 preservation (T103).
  Missing inline chain-absence assertion on T89-T93 noted as m5.
- L5 (error handling completeness): ✓. Every fatal in §4 maps to
  a typed exception with raise-directly behavior. The validation
  order question (m1) does not violate completeness, only error-type
  legibility.
- L6 (open question rigor): ✓. Q1, Q3, Q4, Q5, Q11 each grounded
  in concrete file/line evidence or architecture/tracker quotes.
  Q4 takes a permissive interpretation of architecture.md:556 — see
  m2.
- L7 (deferral hygiene): ✓. Step 06's surface is not smuggled
  into step 05.
- L8 (implementation order): mostly ✓; m3 calls out the residual
  ambiguity at steps 2-3 of §6.
- L9 (stopping conditions): ✓. The §9 list is comprehensive and
  matches the plan's scope guards.
- L10 (architecture commitment compliance): ✓. Tracker line 13
  (keyword-only, require start/end), line 24 (six-field
  ObservationResult), line 26 (declare-then-emit), line 30 (fatals
  raise immediately) all honored. Architecture.md §9 seven-member
  contract reached.
- L11 (speculative abstraction check): ✓. No loader layer, no
  provider-module cache, no abstractions "for the future second
  provider."
- L_two_channel: ✓. ObservationsUnavailableError subclasses
  FatalContractError, raises direct, parametrized over `on_issue`
  with no-IssuePolicyError-chain at T94. T97/T98 likewise.
  T89-T93 noted at m5. No new recoverable Issue path.
- L_handle_dispatch: ✓ on the contract guarantee (no fatal-input
  case can reach the module call); m1 notes the order reversal vs
  the brief.
- L_module_signature: ✓. Takes typed `ObservationRequest` (Q3
  option (b)); all three new members typed correctly; no
  register-like member.
- L_stub_invariants: ✓. Catalogue methods stay NotImplementedError
  (T103). Stub does not register at import (T107). tests._stubs.*
  absent (T108). m7 catches the empty-result annotation-table edge.
- L_m1_inheritance: ✓ across all seven bullets. _ProviderHandle
  remains private; T22 unchanged; T23 absence list grows by one;
  T24/T15 untouched; ProviderInfo row contract untouched; schema
  representation reused, not re-invented.

---

## Adversarial probes attempted

- **Could a malformed module bypass `validate_annotation_names`
  via `__getattribute__` games or by returning a forged
  `AnnotationTable` with mocked `.data`?** No — `AnnotationTable.__post_init__`
  already calls `validate_catalogue(..., on_issue="raise")`, which
  catches non-frame `data`. `validate_annotation_names` reads from
  the already-validated table.
- **Could the registry's new `provider_module=None` default be
  silently stored as `None` for a provider that does support
  observations, leaving observations broken?** No — the conftest
  fixture changes (m4 above) close this for the stub. Real
  providers in M3+ will register their modules explicitly. The
  back-compat path (T105) covers the artifact-only legitimate
  case.
- **Could T86 (empty result for unknown IDs) silently regress to
  raising a fatal because empty annotation tables fail
  `validate_catalogue`?** Possible — m7 above flags this. Empty
  Polars frames need their schema specified at construction.
- **Could the handle's `_module is None` check be skipped on
  `row_annotation_schema()` or `series_annotation_schema()`?**
  §3 lines 122-124 explicitly raise `ObservationsUnavailableError`
  on both. T95 and T96 cover. ✓
- **Could the §6 step 2 → step 3 ordering produce a non-green
  pytest run if executor takes them sequentially?** Yes — m3.
  Plan must pick one path.
- **Could the ProviderModule Protocol expansion accidentally make
  `_ProviderHandle` look like a ProviderModule?** No —
  `_ProviderHandle` has different members and is not the
  Protocol's target. `isinstance(_ProviderHandle(...), ProviderModule)`
  returns `False` because `_ProviderHandle.info` requires `self`
  while the Protocol declares `info` as `@staticmethod`. Worth
  asserting in a one-line nit test but not required.
- **Could `ObservationsUnavailableError` leak into the public
  surface if the executor accidentally re-exports `issues.py`?**
  T109's deferred-absence list (extended per §2 line 26) catches
  this. ✓
- **Could the `_module` field on a frozen dataclass break field
  ordering for the existing direct constructions?** No — `_module`
  is added with a default, so it can follow `_artifact` without
  forcing positional changes. Verified against
  `tests/test_internal_registry.py:97-103` and `:126-132`, which
  both use keyword arguments only.
- **Could T87 (spying the stub's observations function) be foiled
  by Python's static-method dispatch through the Protocol?** No —
  the handle holds a reference to the imported stub module object;
  monkeypatching `stub_provider.observations` rebinds the attribute
  on that module, which the handle resolves at call time.
- **Could the always-on annotation validation produce false
  positives on legitimate empty annotation tables?**
  `validate_annotation_names` reads `table.data["annotation"].unique()`.
  On an empty Polars frame with the right schema, this returns an
  empty series; the `undeclared` set is empty; no raise. ✓
