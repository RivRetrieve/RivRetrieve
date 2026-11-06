# Review, fix, and merge performance PRs 691–693

## Outcome

Review and deliver [#691](https://github.com/RivRetrieve/RivRetrieve/pull/691),
[#692](https://github.com/RivRetrieve/RivRetrieve/pull/692), and
[#693](https://github.com/RivRetrieve/RivRetrieve/pull/693). Fix material defects,
preserve their performance benefits and existing behavior, verify the final
combination, and merge the PRs through the normal repository process.

This is bounded review and remediation, not an architectural redesign. The user
wants confidence that the performance work is correct and useful before it lands.
Publication of this vision does not implement fixes or merge the performance PRs.

Related discussion: [#675, Improve test suite runtime](https://github.com/RivRetrieve/RivRetrieve/issues/675).
This vision delivers the three existing PRs, not every follow-up proposed in #675.
Leave #675 open for its remaining scope unless completion is separately agreed.

## Preserve the purpose of each PR

- **#691:** reduce test runtime through parallel execution, shared distribution
  builds, and detached fixture reuse. Its lazy fields delay copying already
  validated test data. They do not defer production catalogue loading or validation.
- **#692:** accelerate series materialization, selection table construction and
  station metadata. These changes affect library users as well as tests.
- **#693:** accelerate provenance processing, catalogue validation and bundle I/O.
  These are production changes too; preserve the bundle format and validation
  contracts.

The PRs were split into independent changes against `main`. Recheck their current
heads, base compatibility, review state and combined behavior before delivery.
The reviewed starting heads were `e14a16c2586c0e5429ca4a7da4a6935bec099dd6`
(#691), `a1c6f8fed5f78efcdc55a67ca5f8e4c374fbc704` (#692), and
`72ea2ff616e1b9c06de7cbac8563a239ba7121c2` (#693). Treat later changes as new
review input. The PR bodies and #675 contain existing timing evidence; those
measurements do not independently prove correctness or each optimization's value.

## Review and fix proportionately

Confirm suspected defects before changing code. Use focused failing regression
checks, make the smallest sufficient fixes, and rerun affected checks. Preserve
useful optimizations rather than replacing them solely because a simpler design
is imaginable. Changes to performance-sensitive paths need comparable timing
before and after the fix.

The initial review identified these concrete leads:

- **#691:** `tests/test_catalogue_descriptor.py` caches input bytes using a
  fingerprint that omits `station_metadata.parquet` and USGS
  `monitoring_locations.json`. Verify that changing or removing either input
  reaches fresh loading and validation. Installed-distribution verification
  subprocesses also omit the worker's `POLARS_MAX_THREADS` setting from their
  explicit environment. Check whether this defeats intended thread partitioning.
  A descriptor-bytes cache appears to save no work; remove it if confirmed.
- **#692:** a station-scoped source description with `series_id=""` previously
  received a generated ID. The new materializer can retain the empty ID through
  unchecked construction, producing a series rejected by its normal model.
  Preserve valid identity behavior. This was observed with synthetic data, not
  claimed to occur in shipped catalogues.
- **#693:** the fast bundle decoders test `origin` membership in sets before
  checking its type. A JSON array or object can raise `TypeError` rather than
  reaching canonical validation. Preserve malformed-input rejection behavior.

Stopped preliminary work produced failing synthetic tests for these cases, but
no production fixes or commits. Any recovered local tests are review material,
not accepted implementation or a substitute for reproducing against current heads.

Review the surrounding changes for other material regressions, especially test
isolation, stable identifiers, table ordering and null semantics, provenance
closure, and malformed-input handling. The handwritten model constructors,
serializers and validation shortcuts in #692/#693 deserve scrutiny because they
repeat domain rules. Their presence alone does not mandate removal. The same
applies to #691's custom scheduling and manual fixture copying. Fix demonstrated
problems or justified material risks without turning this into a redesign or an
exhaustive optimization study.

Surface major bugs and any proposed substantial production-code work to the user
before implementing a remedy or merging the affected work. This includes broad
refactors, changes to architecture or validation ownership, public behavior changes,
and defects with significant data-correctness or provenance consequences. Explain
the evidence, affected behavior, likely scope, options and performance implications
so the user can decide how to address them. Discovery and bounded reproduction may
continue; they do not authorize the major fix. Routine narrow fixes may proceed
within this vision's existing behavior and performance constraints. If the required
scope is uncertain, ask rather than silently expanding the work.

## Verification and performance

Follow the repository testing and evidence guides and use `uv` for execution.
Keep caches and stores isolated. Changed or corrupt fixture inputs must reach
validation; fixture reuse must not conceal them. Preserve source facts, unknowns,
validation boundaries and the existing distinction between missing data and failure.
Do not weaken assertions, exclude tests, or introduce new skips to achieve speed.

Record exact revisions, commands, Python version, worker/thread settings, selected
workloads and cache conditions. Compare equivalent outputs as well as elapsed time.
Use the same machine and settings for before/after comparisons, distinguish cold
from warm operation, and do not run competing timing workloads concurrently.
Separate benefits from parallel execution from changes to production algorithms.

The unmodified current implementation of each PR is the performance baseline for
its fixes, not the slower pre-PR `main`. Record the exact baseline heads before
editing. Compare the final combination with the corresponding unmodified
combination under equivalent conditions as well. Do not reset the baseline after
a fix or use remaining gains over old `main` to excuse a regression.

No demonstrated performance regression is accepted without explicit user approval.
Investigate slower measurements to distinguish regression from noise, and report
measurement variability and limits honestly. If a necessary correctness fix slows
the implementation, surface the evidence and options and pause the affected work
for the user's decision. Do not silently accept the slowdown, weaken correctness,
or merge around the decision. Do not invent an allowed regression threshold or
require reproducing another machine's published timings.

For acceptance:

- Add or extend focused regression coverage for each confirmed defect and run
  affected source-independent suites after fixes.
- Exercise representative changed production operations, including selection
  frames, metadata, catalogue loading and bundle round trips, as applicable to
  the fixes. Retain representative before/after timing evidence.
- Run the full source-independent suite on the final combination, including the
  parallel mode introduced by #691. Check relevant serial behavior and fixture
  isolation rather than assuming parallel success proves both.
- Run formatting, lint, source type checking and applicable documentation or
  installed-distribution checks. Review failures against the exact changes; do
  not hide change-related failures behind an unrelated baseline problem.
- Apply mandatory genuine-input checks if changes reach governing claims, source
  bindings, verifiers or collections. Review exact revisions before using private
  evidence, keep controlled material private, and report unavailable mandatory
  evidence as blocked. Synthetic or packaged-input checks do not replace it.

## Delivery and boundaries

Keep fixes with their respective PRs where possible, preserve others' work, and
review the final diffs and verification evidence before merging. Respect required
checks and approvals; do not bypass branch protection. Confirm the merged target
contains the reviewed changes and that the final combined verification applies
to the delivered revisions. Summarize fixes, preserved performance, checks,
limitations and merge commits in concise GitHub records.

Success means all three PRs are reviewed, material defects are resolved,
performance benefits remain supported by comparable evidence, applicable checks
pass, and the changes are verified merged into `main`. A blocked PR remains
explicitly blocked, not silently counted as complete.

Do not add production lazy catalogue loading, Polars-backed selections, reduced
installed-wheel evidence checks, a new test-tier framework, automatic diff-based
test selection, or unrelated provider changes. Those were deferred in #675.
Leave reversible implementation details and merge order to the implementing agent.
