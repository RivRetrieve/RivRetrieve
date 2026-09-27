# Comprehensive test suite streamlining

## Outcome

Make RivRetrieve's full test suite substantially faster, smaller where coverage is redundant,
and easier to maintain. This is a comprehensive, aggressive review of the whole suite, not a
patch limited to the slowest files. Invest the time needed to challenge each test's value.
Aggressive means removing waste, not silently losing distinct behavioral guarantees.

Both tests and library performance are in scope. Library changes require strong justification
from measured benefits to real library use, not merely a faster test run. Preserve public
behavior, source fidelity, required validation, and established isolation boundaries.

Keep all offline checks in the default `uv run pytest` run. Do not obtain a speedup by hiding
expensive checks in an opt-in suite, adding skips, or weakening assertions. No fixed runtime
or test-count target has been agreed. Demonstrate substantial measured improvement and explain
remaining costs rather than optimizing toward an arbitrary number.

## Parallel work and coordination

Other agents and contributors are actively working in this repository. The implementing
agent is not alone: provider behavior, documentation, tests, and `main` may change during
this effort. Do not assume the initial checkout, file inventory, or baseline remains current.

- Use a dedicated branch and isolated worktree below the repository's `.worktrees/` directory
  for implementation and long-running measurements. Do not switch branches in the shared
  root checkout. During discovery publication, another session switched that checkout while
  work was in progress; isolation is necessary, not hypothetical.
- Inspect current open PRs, branches, worktrees, and reachable agent activity before assigning
  ownership. Coordinate overlapping files and guarantees before editing them. Refresh this
  evidence before integration rather than treating a starting snapshot as permanent ownership.
- Preserve other contributors' uncommitted, unpushed, and incomplete work. Do not reset, clean,
  remove, or overwrite their changes or worktrees. Apparent duplication may be part of an
  active behavior change; understand it before deleting or consolidating tests.
- Give delegated workers clear ownership and the same parallel-work warning. Use separate
  worktrees for concurrent editing where shared files or checkout state could interfere.
- Record the exact revision and relevant execution conditions for each timing run. Coordinate
  expensive runs when possible; concurrent CPU or disk load can distort comparisons even in
  separate worktrees. Do not attribute another change or resource contention to this cleanup.
- Fetch current `main` before integration, reconcile concurrent changes without dropping their
  guarantees, and validate the combined result. The final whole-suite review must account for
  relevant tests added or changed while this work was underway.

## Evidence from discovery

The initial local run collected 4,640 cases and finished in 4,198.75 seconds (69m 59s):
4,637 passed, 3 skipped, 78 warnings. Collection took about 6.2 seconds. Summed pytest phase
times were 521.7 seconds setup, 3,656.2 seconds call, and 13.0 seconds teardown.

The run used the repository's uv environment on macOS ARM64 with Python 3.13.8, without
parallel execution or coverage collection. Its command was `uv run pytest --durations=0
--junitxml=<output>` plus an external read-only reporting plugin recording test/phase timing
as JSONL. The checkout revision recorded at launch was
`1fa8edd4c0aff84ce6f2e00b1ca9131adff5e530`. This was a local working-checkout run, not a
hermetic benchmark. Main subsequently advanced; re-establish a controlled baseline on the
implementation starting revision and preserve comparable timing evidence with delivery.
The original temporary timing files are not required to implement this vision.

| Test file | Total phase time | Important detail |
| --- | ---: | --- |
| `tests/test_fr_hydroportail_variants.py` | 354.8 s | 81 cases, primarily call time |
| `tests/test_usgs_nwis_measurements.py` | 344.3 s | 78 cases; 340.2 s setup, 2.5 s call |
| `tests/test_usgs_nwis_sentinels.py` | 137.8 s | 30 cases; 136.1 s setup, 1.0 s call |
| `tests/test_live_numeric_public.py` | 131.8 s | 24 cases |
| `tests/test_documentation_examples.py` | 124.8 s | Executable examples provide real coverage |
| `tests/test_catalogue_origin_certification.py` | 123.1 s | Full-scale certification needs separate evaluation |
| `tests/test_pl_imgw_annual.py` | 102.7 s | One exact annual archive compile accounts for nearly all time |

### Confirmed repeated cost

`tests/conftest.py::clear_provider_registry` clears the registry before and after each test.
A later public discovery call enters `discovery._ensure_default_providers_registered`, then
`providers.registration.register_manifest`, which loads and validates all 14 packaged
provider catalogues even for a request naming only USGS.

A separate cProfile run of one cold `rr.find(provider="usgs_nwis", station="07374000",
quantity="discharge", frequency="daily", statistic="mean")` confirmed this path. Of about
7.68 profiled seconds, 7.53 were in provider registration and 7.39 in the 14 artifact loads.
Evidence relation validation accounted for about 4.73 seconds. Profiling overhead means these
are attribution evidence, not ordinary wall-time estimates. The profile recorded about
45 million function calls. Much of the cost is repeated Python validation, not disk access.

Potential improvements include safely reusing pristine validated test inputs, avoiding
unrelated national data for focused behavior tests, and improving justified production
registration/validation costs. These are investigation leads, not prescribed mechanisms.
Do not remove registry isolation or globally cache arbitrary paths as a shortcut. Tests of
loading, invalid artifacts, registration, and corruption must still exercise the real boundary.
Shared objects must not leak mutation, stale state, or order dependence between tests.

Other leads:

- `tests/_catalogue.py` already caches a catalogue reader, while public registration bypasses
  it. `tests/conftest.py::_packaged_provenance` independently loads national catalogues for
  synthetic fixtures. `tests/_provenance.py` reconstructs legacy provenance for some field checks.
- Seven packaging cases perform nine builds across catalogue-carrying, input-exclusion, and
  drainage-area checks. Their files total about 86.6 seconds, so builds do not explain most
  of the hour. One fresh dependency install permits network variability. Reuse is worth
  investigating, but preserve installed-distribution, outside-repository, and sentinel tests.
- Some `test_record_observations.py` cases use a fake sender with the real transport clock,
  retaining real pacing waits. Most retry tests already use virtual clocks. Do not remove
  actual pacing coverage when eliminating incidental sleeps.
- Some loopback servers retain the default shutdown polling interval. This is a smaller cost.
- Files named "live" often replay recordings. Classify by actual behavior, not filenames.

## Comprehensive coverage review

Inventory the suite by the guarantee being checked, the layer where it is checked, its cost,
and overlap with other tests. Account for the whole suite, not only the examples above.
Classify areas as retained, simplified, consolidated, moved to a more focused test boundary,
or removed, and give a practical explanation of coverage changes. A giant permanent
per-test bureaucracy is not the goal; an inspectable review and delivery account is.

Prefer exhaustive edge-case coverage at the narrowest meaningful boundary, plus enough
public-path cases to prove integration. Challenge Cartesian products of value, policy,
quantity, and variant when they repeatedly prove the same shared behavior. Preserve
combinations that can reveal a distinct interaction rather than reducing them mechanically.

Initial cleanup candidates, to verify against current code before acting:

- `test_documentation.py` has nearly identical README and quickstart single-day replays;
  the quickstart-named test does not execute that page. Reconcile these with actual page
  execution in `test_documentation_examples.py`.
- `test_m1_exit_criteria.py` repeats discovery behavior covered by focused tests.
  `test_m5_exit_criteria.py` performs retrieval for adapter/absent-helper assertions.
- `test_usgs_nwis_sentinels.py` reuses measurement helpers and repeats many invalid-value,
  policy, and coverage cases from `test_usgs_nwis_measurements.py`. Preserve any distinct
  negative-value or bundle behavior when consolidating.
- Exact mathematical module-docstring wording, constructor AST/keyword ordering, and
  syntax-specific scans forbidding one test assertion style can constrain editing without
  protecting library behavior. Challenge these rather than automatically maintaining them.
- Documentation link checks and printed-output-presence checks overlap in places.

Do not treat every static check, snapshot, or documentation test as worthless. Architectural
ownership constraints may need static checks; packaged-data completeness may need data-scale
checks. Executable documentation exercises real public behavior. A generated-file freshness
check is not automatically a substitute for model-field and enum coverage. Preserve useful
checks at an appropriate scope and remove duplication on evidence.

## Constraints on optimization

Preserve distinctions between published nulls, absent rows, empty results, failed requests,
unsupported inputs, and unknown physical facts. Preserve source-series identity, units,
receipts, provenance, partial-result failure isolation, and cache correctness. Fatal internal
contract errors must remain fatal independently of caller issue policy.

Keep meaningful integration, packaging, recorded-source, and full-scale catalogue validation
coverage in the default offline suite. Do not suppress the intentional nominal-window negative
type-check fixture. Do not introduce live provider dependencies to replace deterministic tests.
Do not solve a shared-fixture problem solely by throwing parallel workers at it.

For each production change, provide a before/after measurement of representative real library
use, explain the user benefit, and demonstrate preserved validation and invalidation behavior
where relevant. Test-only acceleration and production benefits must be reported separately.
Do not bypass required validation or weaken public guarantees to save time. Broader API or
behavior changes are not authorized merely because they might improve a benchmark.

## Prevent recurrence

Add a clear, actionable contributor rule in the root `README.md`. This location is an explicit
requirement, not a substitute reference only in another instruction file. Keep it concise and
consistent with the README's reader-oriented style.

The rule should require a distinct behavioral or architectural reason for a test, checking
existing coverage before adding another test, justifying expensive end-to-end combinations,
safely reusing expensive unchanged inputs, and measuring the runtime impact of costly new
coverage. Discourage exact wording and code-shape locks unless the locked property is itself
an intentional contract. Avoid creating another brittle wording test for the rule itself.

## Evidence of completion

- The whole suite has been reviewed; delivery explains consolidation/removal decisions and
  how distinct guarantees remain covered, including any material residual risks.
- The default full offline suite passes after the changes. Existing environmental skips and
  warnings are explained; new skips or reduced default collection are not used to conceal work.
  Legitimate removal/consolidation of redundant tests will reduce collection and is expected.
- Comparable before/after full-suite timings show substantial improvement. Report total time,
  setup/call/teardown costs, slowest remaining areas, case counts, environment, and commands.
  Separate measurement noise, cold/warm effects, and changed coverage from actual speedups.
- Shared fixtures or caches are validated for isolation and stale-data/corruption safety as
  applicable. Focused tests still fail for the errors they claim to guard against.
- Production changes, if any, have strong measured user-facing justification and regression
  evidence. A decision not to change production code is acceptable if evidence does not justify it.
- The root README contains the prevention rule. Relevant documentation remains accurate, and
  project-native lint/type/test checks pass.

This document authorizes a later implementation workflow. Its publication changes only the
vision; it does not itself implement the cleanup or the README rule.
