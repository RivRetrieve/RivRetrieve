# Fast trustworthy local reads

Program: https://github.com/RivRetrieve/RivRetrieve/issues/514
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/516

## Outcome

A small request should read the local data it needs without repeatedly examining
all national observations. Multi-station requests should share preparation rather
than repeat it for each station and route. Return faithful observations and the
evidence needed to interpret the requested result for Poland, Canada and optional
live-provider caches.

This is pre-release work with no users, backwards-compatibility requirement or
minimal-patch constraint. Choose a coherent design, but justify every abstraction
and large change. A faster result is unacceptable if it changes source meaning,
hides an applicable failure or relies on unchecked mutable files.

## Starting point

Effort #515 is landed through PR #521, merged at
`789cda762cb6b4c4678305221a6d7470a0a0d2e5`. It supplies the shared publication,
recovery, integrity and successful-supersession contracts. Its delivery and the
complete six-comment investigation index in Program #514 are required context.
Historical findings describe `cae286a002f6cc6e80fe9af1ff2d2dfb07f73840`; recheck
current code rather than treating every historical defect as still present.

At the reviewed implementation base:

- `store/reader.py` has metadata-only status. Query still verifies every partition
  digest and runs complete observation validation before its selective scan.
- `store/integrity.py` exposes `inspect_integrity` and `verify_files` for explicit
  partition identifiers. This is the landed boundary for selected-read integrity.
- `discovery.py` dispatches retrieval by station. The live driver can query again
  for each reused route. Public batching must remove repeated store preparation
  without widening source requests or collapsing independent outcomes.
- `driver.py` still has broad evidence-return paths, including whole-manifest
  source calls for held rolling observations. Store compaction alone does not
  establish request-specific provenance.

These paths are under `src/rivretrieve/_internal/`. The normative store contract is
`docs/design/observation-store-layout.md`. Keep it accurate when narrowing the read
validation scope.

## Read only the necessary observation data

Choose conservative candidates using product, year, station, time, source series
and physical-fact restrictions. Preserve required padding across year boundaries.
Conversion remains the authority for physical conversion and exact clipping;
selection must provide every row that conversion needs. Do not infer time zones or
collapse distinct series because their physical facts match.

Share metadata preparation and selected integrity work across stations and routes
within a public request. Repeated requests must not repeat a national observation
audit. Request-wide sharing must remain tied to the current committed generation,
not become permanent trust in a path or mix metadata and observations from different
generations. Preserve the existing refusal of active or interrupted work.

Separate the actual costs. Metadata and closed-inventory inspection may depend on
store size; do not describe it as constant time. Selected-file hashing reads bytes
at partition granularity. Observation decoding should prune unrelated partitions
and row groups using the conservative request predicates. Account for unavoidable
candidate row-group granularity rather than promising one-row physical I/O.
Do not scan unrelated observations for semantic validation before applying those
predicates, and do not mistake a selective-looking query plan for bounded work.

## Keep the integrity guarantee explicit

Use the shared publication authority from #515. Inspect current metadata and the
closed managed-file inventory, then verify selected partition bytes against their
original published content identities before use. Preserve relevant observation,
identity, fact and acquisition-support consistency guarantees. There is no
unchecked-cache mode or permanent path-only validation cache.

The detection scopes are deliberately different:

- Publication validates the new generation. Bulk certification also preserves
  source-column closure, source inventory/count/identity checks and exact
  source-to-store equality.
- Status inspects lifecycle, inventory and metadata without checking observation
  contents.
- A read checks the current metadata and the selected observation contents needed
  for its answer. Unselected observation-byte corruption need not be discovered by
  every small request; a relevant later read or complete audit detects it.
- `audit_cache` remains the explicit complete local integrity and consistency
  check. It does not repeat comparison with original publisher archives.

Missing, incompatible or malformed stores retain their established outcomes and
refusals. Fatal store or internal contract errors must not be suppressed by caller
issue policy. Meaningful mutation or replacement must invalidate relevant trust,
including a validly encoded changed value and edits with restored modification
time. This does not add hostile-local-user security, continuous reading during
replacement, distributed coordination or host/power-loss durability.

## Return evidence for this request

Project persisted evidence onto the requested result, including acquisitions that
support held rows, successful empty coverage, inventory conclusions and applicable
diagnostics. Retain the evidence dependencies needed to interpret those claims.
An inventory is source evidence with its original scope and completeness; do not
rewrite it as a filtered inventory or fabricate membership conclusions.

Exclude unrelated acquisition history and superseded failures. Preserve active
failures for unresolved scopes alongside independent successful data. The
`supporting_outcomes` relation from #515 can support an inventory dependency, but
must not become an active diagnostic or trigger issue policy. Do not independently
redefine successful supersession or remove evidence simply to shorten a result.

Preserve acquisition identities, original retrieval instants and unknowns.
Explain the meaning of returned acquisition times and calls consistently for fresh,
held and mixed results. Reuse is not a new publisher acquisition. Preserve original
issue identity, reason, context and counts; an acquisition-wide count must not be
presented as a newly calculated count over selected rows. Provider-level unknown
license or citation information remains applicable where appropriate.

Generated store-excerpt receipts remain distinct from publisher payloads. Keep
selected native fields and the evidence needed to interpret excerpts without
pretending that original source bodies are stored or newly retrieved.

## Preserve the public workflow and source facts

Keep `find`/`pick`, `fetch`, explicit bulk `download`, and the existing public
signatures and result shapes. No public interface change is currently needed.
If implementation exposes a genuine need for one, present a concrete proposal with
examples and consequences for owner agreement before changing it.

Poland and Canada still require explicit national preparation. Bulk `bypass` and
`reuse` read the prepared source; bulk `refresh` refuses. Missing prepared data
must not trigger a national download. Live `bypass` still avoids observation-cache
reads and writes. Live `reuse` requires inventory knowledge and successful coverage
for the requested identities, facts and time axis. An uncovered route reacquires
its full requested interval with padding; covered siblings can remain local.
No default change, expiry or network-forbidden mode is included.

Preserve native values, units, timestamps, quality vocabulary, physical facts,
unknowns, source identities and duplicate multiplicity. Null, blank, absent rows,
successful empty answers and failed requests remain distinct. A failed acquisition
must preserve supported held data and its original acquisition evidence. Successful
empty replacement and partial recovery retain their #515 semantics. Rolling
observation-only snapshots establish matching observation keys, not interval
coverage or withdrawal of absent keys. Bulk snapshots remain replacements rather
than unions with historical rows.

## Evidence of success

Acceptance must establish both correctness and bounded read work:

- Exercise small, multi-station, multi-product, year-boundary and mixed-coverage
  requests for both store kinds. Include independent series and facts, native/UTC
  boundaries, empty success, partial failure/recovery and rolling observations.
  Compare physical and canonical data, types, nulls, duplicates and conversion
  issues. Check outcomes, inventories, source calls, acquisition times, receipts
  and caller issue policy separately; correct observation frames alone are
  insufficient.
- Detect actual unrelated physical reads or decoding and repeated metadata or
  integrity preparation. Include increasing unrelated observations and multiple
  stations sharing candidates. Count metadata inspection, byte hashing and row
  decoding separately. Use deterministic work-count regressions rather than
  fragile absolute timing assertions or query-plan text alone.
- Retain malformed-store controls and test mutation, replacement, stale trust and
  the documented difference between selected-read detection and complete audit.
  Keep full audit available for both store kinds.
- Repeat the pinned national read measurements for Poland and Canada, including
  first and repeated small requests. Add multi-station measurements and applicable
  live-cache controls. Record exact code/input identities, machine, runtime,
  methodology and equivalence scope. Use isolated cache/store roots, serialized
  workloads and a local-read benchmark that cannot fall back to the network.
- Deliver accurate public documentation and docstrings with the code. Explain the
  status/read/audit distinction and the meaning of returned evidence plainly.

The historical January 2023 daily-discharge requests used Polish station
`149180010` and Canadian station `02GA010`. They returned 31 rows in
401.334/397.224 seconds for Poland and 529.120/528.456 seconds for Canada.
More than 99.9% was full validation. Validation opened all 228/344 partitions;
the padded candidate set needed two. Direct scan-plus-conversion diagnostics took
2.62/7.55 milliseconds after public reads warmed the data. They excluded complete
validation and did not compare all result metadata. They are diagnostic lower
bounds, not safe replacement implementations or end-to-end latency promises.
Do not claim OS-cold measurements without controlling and documenting that state.

Use `docs/maintenance/testing.md` and `docs/maintenance/evidence.md`. Run affected
source-independent checks, broader checks appropriate to the shared boundaries,
lint and `uv run ty check src`. Applicable genuine-input acceptance uses the
maintained private archive interface and independently reviewed exact code and
archive revisions. Missing mandatory evidence blocks acceptance. Synthetic tests,
derived witnesses and fresh acquisitions cannot stand in for historical originals
or establish claims those inputs do not support.

The investigation's fresh national originals and receipts were not adopted as a
new archive collection. Verify present availability through maintained archive
intake and exact selection; fingerprints alone do not establish access. Preserve
originals and keep controlled bodies, receipts, outputs and credentials out of
public Git, logs, artifacts and packages. This vision does not authorize new
national acquisition, source redistribution or destructive evidence cleanup.

## Scope and implementation discoveries

#516 owns selective retrieval, shared request preparation and request-specific
returned evidence for both store kinds. It owns the demonstrated resolution of
original report #512 for both Poland and Canada, with measured acceptance and
merged-delivery links. Vision publication alone does not complete that report.

#515 owns storage authority, lifecycle, recovery and successful supersession.
#517 owns national discovery/transfer, decoding/build throughput, resource planning
and provider-specific snapshot selection. Neither follow-on Effort needs the other
to land. Do not introduce a parallel integrity/publication system, migration
machinery, unrelated provider expansion, scientific reinterpretation or a rewrite
of the private archive.

For a newly discovered major bug during implementation, stop implementation, open
a GitHub issue labelled `bug`, assign it to `CooperBigFoot`, and report the blocker
without controlled material. Wait for the owner's merged-fix handoff, then verify
that it removes the blocker before resuming. Minor clear bugs may be corrected
with affected checks and accurate documentation. Confirmed defects already assigned
to this Program remain approved work.

Publishing this vision authorizes no implementation. Implementation begins only
through the separate handoff for this Effort.
