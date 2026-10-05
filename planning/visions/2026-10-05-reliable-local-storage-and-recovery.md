# Reliable local storage and recovery

Program: https://github.com/RivRetrieve/RivRetrieve/issues/514
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/515

## What we are building

RivRetrieve needs a dependable way to keep observations locally. Saved observations
must remain faithful, updates must replace only what they should, failures must be
reported accurately, and interrupted work must be recoverable. Small updates must
not repeatedly copy and examine unrelated observation data.

This is pre-release work in a private, unpublished repository with no users. There
is no backwards-compatibility requirement, migration requirement, deadline-driven
minimal-patch constraint, or reason to preserve a poor internal design. Build a
coherent system and justify its complexity. Available time and resources do not
justify speculative features or abstractions.

The Program's AI-authored findings are evidence to assess against the code, not
independent authority to expand the product. The owner confirmed this outcome after
a plain-language explanation and a code review of both storage paths.

## Two reasons for local storage

Poland and Canada require explicit preparation. `rr.download("pl_imgw")` and
`rr.download("ca_eccc")` retrieve national publisher artifacts, convert them into
local tables, check the conversion against the source, and publish the completed
store. Later `fetch` calls read it. Without that preparation, retrieval reports a
missing store and returns no observations; it never starts a national download.
`find` can still use the packaged catalogue. Calling `download` again prepares a
replacement. This local dataset is the access path for these bulk sources.

Live providers can instead request observations directly. Their observation cache
is optional. Default `cache="bypass"` neither reads nor writes that cache.
`reuse` serves sufficiently covered requests locally and acquires uncovered routes;
`refresh` requests again. Successful answers update the cache. Failed reacquisition
can return earlier successful rows with their original acquisition evidence and the
new failure. These caches accumulate from retrievals and do not require `download`.

Keep these different purposes truthful. Preserve explicit bulk preparation and the
current live-cache default. Do not silently acquire national data, introduce expiry,
or add a network-forbidden mode as part of this Effort.

## The defects and cost we must remove

The existing implementation has substantial source-fidelity checks, but its storage
lifecycle is inconsistent:

- A live request can fail, later recover successfully, and then return the obsolete
  failure on cache reuse. `on_issue="raise"` can raise without a new source request,
  even while the returned data is the recovered data.
- Live updates copy the entire store, repeatedly rewrite a partition when several
  replacements affect it, and validate all staged data. Metadata-only updates can
  incur the same whole-store work. Evidence and coverage checks grow with history.
- Store replacement moves the old directory aside before installing the candidate.
  A process stopped between those actions can leave valid prior data that inspection
  calls absent. Clear does not recognize every namespace created by the writers.
- A live update can publish valid new data and then report a plain failure because
  deletion of its backup failed. Cleanup can also obscure the initiating error.
- Full semantic validation does not bind partition bytes to the contents certified
  at publication. A validly encoded changed value can pass later checks.

Repeated full-store validation also dominates small bulk reads. This Effort owns the
validity contract that makes a better read path safe; #516 owns selective retrieval
and its performance delivery. Do not treat eliminating checks as the solution.

## Required behavior

### Refresh changes only what a successful acquisition establishes

Preserve native values, units, timestamps, time-zone unknowns, source identities,
physical-fact segments, quality vocabulary and duplicate multiplicity. Keep null,
blank, absent rows, successful empty answers and failed requests distinct.

Successful live replacement is specific to source identity, physical facts, time
axis and established interval. A successful empty answer can remove held rows in
that scope while retaining evidence of successful coverage. An independent failed,
unsupported or unresolved scope must not erase successful data or change its
original acquisition time. Fatal internal contract errors still raise regardless
of caller issue policy.

Rolling observation-only snapshots establish the exact observation keys they
contain, not interval coverage. Replace matching keys; preserve previously held
keys absent from the new snapshot and their supporting acquisition evidence. An
empty rolling snapshot does not prove an empty historical interval.

A certified bulk snapshot replaces the prior snapshot, including legitimate
removals. Do not union old rows into it. Source release facts, coverage, acquisition
time and build time are different facts; preserve unknowns. Provider-specific
selection rules, including Poland's shorter-archive question, belong to #517.
This Effort must preserve the evidence those rules need through recovery.

### Current answers and past attempts have different meanings

Persist enough evidence to identify the acquisitions supporting retained rows,
successful empty coverage, matching-series knowledge and reuse eligibility. Preserve
still-applicable failure identities and reasons alongside partial results.

A later successful acquisition supersedes earlier failures only for the scope it
actually establishes. Partial recovery must leave failures active for unresolved
scopes. Reuse after full recovery must not resurrect the superseded failure or
trigger issue policy because of it. Deliver that correction end-to-end in #515.

Separate evidence needed for current state from historical attempts. Do not promise
a permanent acquisition-history archive. Define safe compaction of fully superseded
records without losing dependencies needed to explain retained data or reuse.
Do not erase history indiscriminately just to make a result look successful.
Metadata work must be justified by current evidence and changed scope rather than
unlimited repeated attempts. Any retained historical record must remain distinct
from an active diagnostic.

#516 consumes this persisted authority and supersession contract to project
request-contributing outcomes, issues and source calls. It owns the broader result
projection and batching work; it must not need to redesign storage authority.
Generated store-excerpt receipts remain distinct from original publisher payloads.

### Publication, inspection, recovery and clear agree

Use one coherent lifecycle contract for both store kinds while keeping their
replacement semantics distinct. Identify the selected committed data, unfinished
work, recoverable prior data, cleanup residue and active ownership.

After process termination at a meaningful publication boundary, prior committed
data or fully committed new data must remain discoverable. First-install staging
must not be mistaken for committed data. A recognized unfinished transaction must
not appear simply absent. Never restore a partly deleted backup without validation.

Provide supported explicit recovery and truthful inspection. Recovery must preserve
valid committed data and source-selection safeguards. Report uncertainty rather
than guessing which generation was committed. Clear must report and remove owned
requested state, including recognized interrupted work, without following managed
symlinks into unrelated data or deleting unrelated siblings. Define the managed-path
trust boundary, including configured-root symlinks, explicitly.

Distinguish a failure before commit from a successful commit with cleanup remaining.
Keep the initiating error and cleanup errors, the authoritative data identity, and
remaining owned paths available to the caller. Safe retry must not discard the only
valid copy or mistake cleanup debt for failed acquisition.

Coordinate conflicting write, recovery and clear operations. Never blindly delete
an active lock. Define stale-owner recovery conservatively. Continuous reading
during replacement, distributed coordination, hostile-local-user security and
host/power-loss durability are not required outcomes. Do not claim these guarantees
from exception tests or SIGKILL tests. Choose and document the supported local
process-interruption guarantee and enforce it consistently.

### Trust has a defined scope

Separate publication certification, cheap lifecycle inspection, selected-read safety
and an explicit complete audit. Bind published metadata and data contents to the
validated publication, including a closed inventory of managed files. Define when
replacement or mutation invalidates trust. A mutable path being checked once must
not make it trusted forever. Integrity checks do not authenticate an attacker who
can rewrite both data and their recorded identities.

Preserve complete source-column closure, source inventory/count/identity checks,
and exact source-to-store equality at their appropriate bulk certification boundary.
Accumulated stores must preserve valid links among rows, identities, physical facts,
coverage and acquisitions. Refuse malformed or incompatible content explicitly;
caller issue policy must not conceal fatal store errors.

Document which checks inspection, reads and audit perform. In particular, cheap
inspection cannot claim every observation byte was checked. #516 must receive a
usable contract for request-bounded reads without repeating a national audit.
#517 must receive a usable publication/certification boundary without inventing a
second lifecycle.

### Updates cost what they change

Avoid copying or decoding unrelated observation partitions for a small or
metadata-only live update. Consolidate changes to the same partition within one
update. Preserve unchanged content safely rather than treating previous validation
as permanent trust. Partition-level work is acceptable where its cost is explicit
and measured; a one-row change need not imply one-row physical writing.

Remove avoidable quadratic coverage checks and history-driven metadata growth.
Demonstrate scaling against affected partitions and retained evidence. Do not claim
constant-time metadata work if the implementation still depends on store size.

Resolve roots, workspaces and resource wiring at public composition boundaries;
lower layers receive resolved dependencies. Account for the locations used by
owned temporary work. Admission is an estimate, not reserved disk space. Late
resource failure must preserve valid data and useful errors. Concrete national
capacity estimates and provider build optimizations belong to #517.

## Public API boundary

The confirmed workflow retains explicit `download(...)` for Poland and Canada,
`find`/`pick` selection, and `fetch` retrieval. No rename, new storage object,
per-call root keyword, changed return shape, or change to mixed-provider refresh
semantics was approved during discovery. Currently bulk `bypass` and `reuse` both
read the prepared store, while bulk `refresh` refuses. Preserve that behavior unless
the owner approves a concrete change.

The owner explicitly wants to discuss public API changes. Internal format and
mechanism changes are free of compatibility constraints. Before implementing any
new or changed public signatures, names, returned-state shapes or cache-mode
semantics, present a small concrete proposal with usage examples and consequences
for owner agreement. This is an API design checkpoint, not permission to postpone
the required inspection, audit and explicit recovery outcomes. Prefer a small,
understandable interface and explain prepared bulk data versus optional caching in
plain terms. Keep public documentation and docstrings accurate with delivery.

## Evidence and acceptance

The complete evidence index and six appendices in Program #514 are required context.
They retain code paths, synthetic scripts, actual SIGKILL reproductions, national
measurements, exact identities and limitations. Baseline revision:
`cae286a002f6cc6e80fe9af1ff2d2dfb07f73840`. Discovery also traced the actual public
routes in `discovery.py`, `registry.py`, `bulk.py`, `driver.py`, both providers'
`bulk.py`, and the shared reader, accumulation and certification modules under
`src/rivretrieve/_internal/`. Recheck changed code against the implementation base.

The national baselines were about 60.10 minutes for Poland and 50.92 minutes for
Canada. Repeated 31-row reads were about 397 and 528 seconds, with over 99.9% spent
in full validation. These establish the wider Program's problem, not timing targets
for this Effort. The direct millisecond scans were warmed, excluded full validation,
and compared observation frames and conversion issues rather than all metadata.
National-scale live-update performance was not measured in that investigation.

Delivery must establish:

- Public success, partial failure, full recovery and reuse with accurate rows,
  outcomes, issues, acquisition times and caller issue policy. Include partial
  recovery, independent identities/facts, empty success, inventory changes,
  native/UTC boundaries and observation-only snapshots.
- Inspection, recovery and clear across every owned interrupted state for both
  store kinds. Use actual subprocess termination at meaningful persisted boundaries
  as well as exception, disk/resource and cleanup-failure controls. Compare surviving
  data and prove that active ownership and unrelated paths are protected.
- Integrity refusal for meaningful metadata/data mutation, including a validly
  encoded changed value, replacement and malformed evidence links. Complete audit
  remains available. Verify the distinct detection scopes promised by each operation.
- Small and metadata-only updates with measured before/after elapsed time, data
  copied/read/written, partition rewrite counts and evidence growth. Include repeated
  updates and increasing unrelated data. Deterministic work-count tests supplement
  measurements; do not add fragile laptop-time thresholds.
- Both existing bulk providers integrated with the shared lifecycle, preserving
  certification and source-fidelity behavior. No parallel publication system may
  remain for a follow-on Effort to reconcile.
- Public documentation, tests and explicit handoff contracts for #516 and #517.
  Review the necessity of large diffs and each added abstraction.

Use the project testing and evidence guides. Run affected source-independent tests,
then broader shared-boundary checks, lint and `uv run ty check src`. Use temporary
store/cache roots. Run applicable genuine-input checks through the maintained
private archive interface with independently reviewed exact code and archive
revisions. Missing mandatory material blocks acceptance. Synthetic controls and
fresh national acquisitions do not establish historical governing acceptance.

The baseline's 3,264 selected passing tests did not include its 1,585 deselected
tests. Fresh national originals and receipts had not been adopted as a new archive
collection. Preserve originals; use maintained intake and exact selection rather
than searching historical machine paths or creating a parallel evidence system.
Keep controlled bodies, receipts, outputs and credentials out of public Git, logs,
artifacts and packages. This vision does not authorize a new national acquisition
or destructive evidence cleanup.

## Boundaries and implementation discoveries

Do not absorb #516's selective-read/batching delivery or #517's national decoding,
build optimization and source-publication selection. Necessary integration is in
scope. Unrelated providers, catalogue science, permanent payload archiving, migrations
and speculative cache features are out of scope. Publishing this vision does not
resolve either original report (#392 and #512) or authorize implementation.

For a newly discovered major bug during implementation, stop, open a `bug` issue
assigned to `CooperBigFoot`, and report the blocker without controlled material.
Wait for the owner's merged-fix handoff and verify it before resuming. Minor clear
bugs may be fixed with affected checks and documentation. Confirmed defects already
assigned to this Program are approved work, not newly discovered blockers.
