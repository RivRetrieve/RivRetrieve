# Vision: the engine owns the window

Program: https://github.com/RivRetrieve/RivRetrieve/issues/6
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/10

## Goal / Why

The engine declares a window endpoint as `object`. It genuinely does not say what one is,
so every piece of code that touches a window invents its own answer, and the answers
disagree.

Measured today against the real `convert`: an Arizona gauge (`-07:00`) asked for its own
local day `2020-07-01 00:00` → `23:00` returns **17 rows of 24**, last row `16:00`, no
warning. This is the charting audit's defect, live in `usgs_nwis`, inherited rather than
fixed when #7 landed. `convert` decided a zone-less endpoint means UTC; `usgs_nwis/fetch.py`
truncates to a bare date behind its own `isinstance` guard; `ca_eccc/fetch.py` reads a year
behind a different guard raising a different error type. Padding does not exist anywhere —
`identity_window` is the only `WindowPadder` and pads nothing.

The cost is not the one bug. Nine providers remain to port in #17, six of which carry
their own private window-splitting arithmetic in `reference/legacy_observations/`
(`_split_windows` ×2, `_decompose_windows`, `_iter_years`, `_iter_year_months`, plus
`_query_years` already in `src/`). Each is a fresh chance to re-express the fetch window
in one calendar and the clip window in another — the exact shape the audit found in ten
of eleven providers.

Success is that a window means exactly one thing, the engine performs every arithmetic
over it, and a provider's entire window code is rendering: `fetch_window.start.date`.
A port cannot get the calendar wrong because a port is given no calendar to handle.

## Scope — In

1. **A concrete window endpoint type**, replacing `WindowEndpoint = NewType("WindowEndpoint", object)`.
   A requested window is closed at both ends and expressed as wall-clock time in the
   calendar each station's source publishes. A bare date denotes a whole day, so
   `end="2020-07-31"` reaches the last instant of the 31st while `end="2020-07-31 00:00"`
   stops at midnight. Per ADR 0016.

2. **Boundary normalisation, once.** `start` and `end` are normalised where the request
   enters, so no provider and no polars comparison ever receives an undecided window.
   An endpoint carrying a time zone raises `InvalidObservationRequestError` naming the
   rule and the one-line fix. No naive-vs-aware decision is made anywhere downstream.

3. **Uniform outward padding, engine-owned.** The fetch window is the requested window
   widened by a fixed two days at each end, for every provider, always. The
   `WindowPadder` parameter to `drive` and `identity_window` are deleted — padding stops
   being a seam a provider can participate in.

4. **Engine-owned decomposition into sub-windows.** A provider *declares* a granularity;
   the engine computes the pieces. The granularity set covers what the legacy survey
   found: ISO instant, date, year, year-month, chunk-of-N-years, capped span, and
   `none` for a source that accepts no date parameter at all. Inclusive and exclusive
   stops are both renderable, because `ch_foen`'s Flux `stop` excludes its endpoint.

5. **An open granularity set with exactly one place to widen it.** A provider names its
   granularity; the engine refuses a name it does not know with an error identifying the
   module to add it in. A provider cannot absorb missing arithmetic locally.

6. **Clipping as the last step of convert**, against the same representation the window
   was normalised into. Already the only implementation; it becomes correct.

7. **Two always-on runtime invariants**, checked on every request, not only in tests:
   the fetch window contains the requested window, and after clipping every returned
   timestamp lies inside the requested window. A violation raises `FatalContractError`
   naming the offending row — a stage contract breach, not an `Issue`, per the glossary.

8. **`usgs_nwis` and `ca_eccc` migrated onto it.** `_window_parameter`, `_endpoint_year`
   and `_query_years` are deleted, not rewritten.

9. **Correcting what this vision falsifies.** The Map decision and #13's scope sketch
   both state that interior golden baselines are recorded under UTC-aware requests.
   Those requests now raise. Two call sites in the suite use one, both in
   `tests/test_internal_driver.py` (lines 185, 534); no provider golden baseline does.
   `tests/test_usgs_nwis_observations.py` asks `start="2023-01-01", end="2023-01-01"`,
   which changes meaning from one instant to a whole day — its expected rows change,
   correctly.

## Scope — Out (explicit non-goals)

- **Porting any provider.** That is #17. This vision proves the contract can express all
  nine legacy window patterns by *rendering* them, without fetching or porting.
- **`br_ana` and `no_nve`.** Both require API credentials and are parked by ruling; #90
  covers credentialed providers.
- **Accepting a zone-carrying endpoint as an absolute-interval mode.** Rejected in ADR
  0016; it evaporates on the five sources publishing no zone.
- **Deriving a station's timezone from coordinates**, per ADR 0005.
- **Aggregation of any kind**, per the Map's standing decision.
- **A helper converting a result into each station's own zone.** Named "not yet
  specified" on the Map.
- **Trimming `AGENTS.md`.** It is 648 lines, 458 of them section 4.1, appended one
  provider at a time across the #8 milestone. Real, and not this ticket.
- **Per-provider padding arithmetic**, including the tighter "declare your calendar
  relationship" alternative rejected in ADR 0017.

## Constraints

- **ADR 0016** — a requested window is wall-clock, and a zone-carrying endpoint is
  refused. **ADR 0017** — the engine owns every window arithmetic; a provider only
  renders. Both written in this session and binding.
- **ADR 0006** — `time` and `time_zone` are two columns; UTC conversion is an operation
  the caller performs afterwards, never baked into the result.
- **ADR 0005 / ADR 0007** — `unknown` is first class; a zone is an IANA identifier, a
  strict `±HH:MM` offset, or `unknown`. Never derived.
- **ADR 0008 / 0009 / 0010** — the engine drives the four stages; every provider-facing
  stage returns its value with its issues; a declaration is keyed by product.
- The window object exposes **no arithmetic**: it cannot be added to, shifted, or split
  outside the engine. This is enforced by the type, not by convention.
- The two-day pad is justified because the widest disagreement between any two calendars
  on Earth is 26 hours. Do not "optimise" it to one day.
- A stage-contract violation raises; a fact about the data is returned as an `Issue`.
  The always-on invariants are the former.
- Only `usgs_nwis` and `ca_eccc` have observation code. Neither is a hard case — both are
  forgiving of a sloppy window — so engine-level hostile stand-ins carry the coverage and
  the two real providers carry the proof.
- NumPy-style docstrings; the existing lint, typecheck and test gates apply.
- `reference/legacy_observations/` is evidence, excluded from lint, typecheck and test
  collection. Read it; do not run it or import from it.

## Acceptance criteria (vision-level "done")

Each is an input and an observation. Every one is checkable inside the run that builds it —
committed fixtures and stand-in providers, no live network, nothing deferred.

1. **The design fits all nine.** For each portable legacy provider, its window rendered
   through the new engine matches what its old code produced. `lt_lhmt` over
   `2019-12-20` → `2020-01-10` yields `2019-12`, `2020-01`. `ch_foen` yields its exact
   Flux `range(start: …Z, stop: …Z)` string. Any provider requiring arithmetic to get
   there falsifies the design now rather than in #17.
2. **No provider can compute on a window.** `fetch_window.start + timedelta(days=1)`
   raises. Constructing a `FetchWindow` inside a provider module raises. Both.
3. **The live defect is gone.** Arizona gauge, committed USGS fixture, `2020-07-01 00:00`
   → `23:00` returns **24 rows ending 23:00**. Today: 17, ending 16:00.
4. **A bare date is a whole day.** `start="2023-01-01", end="2023-01-01"` on the USGS
   fixture returns that day's full set of readings, not one.
5. **The guard is not decorative.** A stand-in provider returns one row **one microsecond
   past** the requested end; `rr.observations()` raises `FatalContractError` naming that
   row.
6. **An exclusive-stop source keeps its last reading.** A closed window rendered for a
   source declaring an exclusive stop, with a reading landing exactly on the requested
   end — that reading survives.
7. **Unknown zones are clipped, not excused.** A stand-in with `time_zone="unknown"` and
   rows straddling both edges is clipped correctly and emits **no**
   `convert.unknown_time_zone` warning.
8. **Under-coverage is an issue, not a crash.** A `ba_fhmzbih`-shaped stand-in that can
   only return a fixed span shorter than requested returns its rows plus an `Issue`.
9. **Missing arithmetic has one home.** A provider declaring granularity `"fortnightly"`
   raises, and the message names the module to add it in. Adding it changes nothing
   outside that module.
10. **A zone-carrying endpoint is refused** with an error naming the rule and the fix.
11. `identity_window`, the `WindowPadder` parameter, `_window_parameter`, `_endpoint_year`
    and `_query_years` no longer exist. `grep` finds no window arithmetic under
    `src/rivretrieve/_internal/providers/`.

## Decomposition hints

Risky-first: the survey is what can falsify the whole design, so it comes before the
implementation it would invalidate.

1. **Survey and freeze the granularity set.** Read the nine legacy providers' request
   construction and write the expected rendering for each as a table. This is the
   cheapest possible falsification of the entire vision — if a tenth granularity exists,
   it is found before any code depends on the list of nine. Delivers criterion 1's
   expectations as data.
2. **The window type and boundary normalisation.** Endpoint type, whole-day date
   semantics, zone-carrying refusal. Delivers criteria 2, 4, 10.
3. **The fixed pad, and deleting the padder seam.** Small, and unblocks the invariant.
4. **Decomposition, driven by the frozen granularity table.** Includes the unknown-name
   refusal. Delivers criteria 1, 9.
5. **Clip correctness and the two always-on invariants.** Delivers criteria 3, 5, 6, 7, 8.
6. **Migrate `usgs_nwis` and `ca_eccc`; delete the three helpers.** Delivers criterion 11
   and turns criterion 3 from an engine test into an end-to-end one.
7. **Correct the falsified doctrine.** The two aware-request call sites, the USGS
   observation test's changed expectation, and the wording on the Map and #13.

Steps 2 and 3 are independent of step 1's outcome and can proceed alongside it. Step 4
must not start until step 1's table is frozen.

## Open questions / risks

- **`ch_foen`'s exclusive stop is inferred, not confirmed.** Read off the legacy Flux
  query string (`range(start: …, stop: …)`), not from FOEN's documentation. If Flux's
  `stop` is inclusive here, acceptance criterion 6 tests a case that does not exist —
  harmless, but the granularity set loses a distinction. **Resolve in step 1 by reading
  FOEN/Flux docs.** Does not block; getting it wrong in the safe direction costs one
  unused code path.
- **The granularity set may be incomplete.** The survey read request construction, not
  every legacy provider end to end. A tenth granularity surfacing during #17 is the
  residual risk, and criterion 9 is the mitigation rather than the fix: it guarantees the
  discovery is loud and has one home, not that it will not happen.
- **The two live providers are both forgiving.** USGS accepts a bare date, HYDAT reads
  whole years, so neither exercises a genuine calendar disagreement. The hard cases
  (`pl_imgw`'s wrong day for a Warsaw request, `ch_foen` in UTC, `ba_fhmzbih`'s rolling
  workbook) can only be proven by stand-ins until #17. Accepted deliberately.
- **The always-on invariant is user-facing.** A provider bug becomes an exception in
  someone's notebook that they cannot work around. Chosen over silent edge wrongness and
  consistent with project doctrine, but it is a real cost and the error message quality
  matters more than usual.
- **Permanent over-fetch.** Four extra days on every request, every provider, forever.
  Free for bulk sources, negligible for queried ones, and accepted as the price of making
  the defect class unwritable.
- **No cross-repo scope.** Single repository; no repos block emitted.
