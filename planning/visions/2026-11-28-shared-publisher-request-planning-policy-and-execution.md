# Shared publisher-request planning, policy and execution

RivRetrieve will use one coherent architecture to plan and execute publisher
requests across every built-in provider. Users should obtain safe performance
improvements without tuning provider internals, and should be able to inspect and
configure operational policy through one consistent surface. Providers retain
source-specific knowledge; shared infrastructure controls execution.

This vision implements the confirmed direction in [discussion #1113](https://github.com/RivRetrieve/RivRetrieve/issues/1113).
Completing the implementation and acceptance described here completes that issue.
Publishing this document alone does not complete the issue or implement the design.
Large engine refactors and breaking public or internal changes are allowed and
expected where they serve this outcome. Preserving legacy orchestration is not a goal.

## Adoption covers every publisher-acquisition path

At the reviewed baseline, `72cd90a2c607634dd7925465136db775fc7399e7`, the manifest
contains 21 providers: 18 live providers and three bulk providers. All must adopt
the redesigned architecture:

- Migrate the seven legacy live providers: `ar_ina`, `ch_foen`, `co_ideam`,
  `dk_vanda`, `fi_syke`, `fr_hydroportail` and `usgs_nwis`.
- Adapt the eleven existing planner implementations to the new policy and
  execution contracts. Having a `SourceRequestPlanner` today is not proof of
  compliance with this vision.
- Apply shared execution to bulk discovery, probes, index requests and transfers
  for `ca_eccc`, `cl_dga` and `pl_imgw`. Preserve their distinct compilation and
  publication workflows; do not force them into a live-observation planner shape.
- Include maintained online catalogue acquisition, observation recording,
  authentication exchange and refresh, and requests discovered from responses.
  There must be no separate production path that silently bypasses policy.
- Remove legacy dispatch and redundant execution loops after their useful behavior
  has moved into the shared architecture. Providers that cannot batch declare that
  restriction and still use common planning and execution.

Keep packaged discovery, local store reads, retained-input catalogue publication,
evidence verification and bulk compilation offline. Missing retained inputs must
not trigger replacement downloads. User-owned S3 storage remains outside publisher
rate control, including when it is the destination of a bulk acquisition.

At this baseline, CA/CZ/LT/TH still have active direct-network catalogue capture
CLIs; NVE capture already uses `HttpClient` but also needs the new policy. Migrate
maintained capture paths. The USGS catalogue CLI is now offline-only; retire its
obsolete live RDB acquisition wrapper while preserving historical parsing and
retained-table consumers. Explicitly migrate or retire other retained live helpers,
including the unmanifested `za_dws` capture path, instead of keeping a blanket
catalogue-network exemption. Capturing new material does not approve it as
publication evidence.

## Shared responsibilities and source knowledge

Providers describe native request construction, response interpretation,
source-established restrictions and the meaning of required or optional follow-up
work. The engine owns reusable whole-selection planning, window arithmetic,
deduplication, scheduling, quota accounting, retries, pagination execution and
resource limits. It must handle requests discovered only after earlier responses,
without moving provider-specific interpretation into generic HTTP rules.

The execution contract must support the distinct behaviors already present:

- Shared metadata and artifact acquisitions can serve several stations, products
  or variants without duplicate transfers or lost consumer attribution.
- Required lookups gate their dependent observations. Optional metadata failures
  do not erase observations whose identity is already established.
- Cursor pages form a dependent chain. An incomplete chain cannot establish that
  unseen consumers are empty or absent. Preserve the existing completeness rules
  for candidate rows and coverage rather than publishing provisional success.
- Response-driven window subdivision preserves its parent-call lineage and
  independently successful child intervals when a sibling fails.
- Invalid selectors can have different effects across sources. For example,
  BoM can reject an entire values batch containing an invalid series. Preserve
  source-specific isolation instead of assuming every batch omits invalid items.

Internal contract errors remain fatal. Supported source failures retain their
identity and reason at the established isolation boundaries. Null values, absent
rows, successful empty responses, failed requests and unresolved work remain
separate. Bulk publication stays transactional, even though observation retrieval
can return partial results.

## One inspectable policy surface

Separate three concepts in policy and in its public explanation:

1. Established publisher restrictions, with their applicability and evidence.
2. RivRetrieve operating recommendations, including conservative choices where
   source behavior is unknown.
3. Caller preferences.

Expose coherent controls for attempt rate, longer-period quotas, maximum in-flight
requests, batch/page sizes, request-window bounds, retries and acceptable waiting.
Resolve configuration and resources at explicit composition boundaries, then pass
resolved dependencies to lower-level operations. Callers must be able to inspect
the effective policy, including units, applicable scope and why a value applies.
Exact API names, representation and configuration precedence are implementation
choices, but precedence must be explicit and must not turn publisher restrictions
into ordinary overridable defaults.

Callers may tune operating recommendations and impose tighter limits. They may not
bypass established publisher restrictions or correctness/completeness bounds. An
agency-granted higher quota is an explicit account-specific allowance, not a generic
ignore-limits switch. Do not infer such an allowance from successful requests.

Quota identity follows the applicable source restriction rather than provider ID
or hostname. One provider may use several services; several request families may
share a quota. A request can be subject to several simultaneous restrictions, such
as short- and long-period limits or account and IP limits. Shared origin alone does
not establish shared quota. Keep credential values and secret-derived identities
out of public diagnostics and policy descriptions.

Unknown scope, remaining budget and reset timing remain unknown. Server feedback
can inform execution when its meaning is established, but is not an atomic grant
of capacity. Account for local in-flight work and out-of-order feedback. Do not
invent a reset at local midnight or at the next hour. Label conservative local
accounting as RivRetrieve policy, not as the publisher's algorithm. Preserve the
source status and evidence rather than diagnosing every HTTP 403 as quota exhaustion.
Automatic limit discovery by increasing load until rejection is outside this scope.

## Process-local coordination

Coordinate repeated and concurrent calls within one Python process, across all
participating acquisition entry points. Creating another client or changing caller
preferences must not replenish the shared budget. Authentication token refresh must
not reset a quota that belongs to the underlying account.

Keep mutable quota coordination separate from policy resolution and execution so a
future coordinator for cooperating processes on one host can be introduced. Do not
implement cross-process or distributed coordination in this overhaul, or add unused
infrastructure for it.

Document the guarantee honestly: this coordinates attempts observed within the
process. It does not know prior usage after restart, unrelated software's traffic,
or other processes and machines sharing an IP or credential. Local reservations
cannot guarantee that the publisher will accept a request.

## Bounded, configurable quota waiting

Normal calls use a bounded default. Unattended acquisitions can explicitly allow
longer quota waits, conceptually:

```python
# Normal interactive usage.
rr.fetch(...)

# Allow up to one hour of cumulative quota-induced waiting.
rr.fetch(..., max_quota_wait=3600)
```

The value is in seconds. Exact API spelling and the default duration are left to
implementation. The allowance applies cumulatively across the operation, not
separately to each pause. Overlapping concurrent quota waits count elapsed waiting
once, rather than summing worker wait durations. Normal request pacing, network
transfer and parsing do not consume this allowance. It is not a whole-operation
deadline. Retry behavior remains a distinct policy concern; quota-induced delays
must still respect the quota-wait allowance.

Waiting must be interruptible and explain its reason and remaining allowance.
When the allowance is exhausted, stop the affected work, preserve independently
completed observation results and retain reasons for unresolved consumers. Other
independent work can continue under its own applicable constraints. Preserve the
existing caller issue policy and bulk transactional failure behavior. Do not invent
observations, empty coverage or successful acquisitions for work that was not sent.
If replenishment timing is unknown, disclose that limitation instead of inventing
an ETA or repeatedly probing for permission.

## Safe performance improvements are the default

Enable evidence-supported request sharing, batching, connection reuse and
service-specific bounded concurrency by default. Users should not need an opt-in
flag to obtain these benefits. Keep conservative operating choices where evidence
is insufficient, and allow callers to reduce resource use. There is no universal
worker count or promised speedup.

USGS needs multi-station request planning, not just faster station-by-station sends.
Build on the already-merged page-limit and geometry changes in [#1121](https://github.com/RivRetrieve/RivRetrieve/pull/1121).
Choose batches compatible with endpoint, parameter and statistic selection, request
size and response workload. Do not introduce unintended Cartesian combinations of
parameters and statistics. Establish completeness across interleaved pages before
concluding that a selected station has no data. The proposed GET batching is
supported by reported probes but still requires the applicable retained evidence.

Count actual publisher attempts, including retries, pages, probes, prerequisites,
authentication exchanges and redirect hops under their applicable policy. Preserve
replay safety and credential-origin restrictions. Scheduler waits must not block
unrelated ready work merely by occupying all execution capacity.

Stream bulk responses to temporary artifacts and publish only complete successful
transfers. Truncation, retries and interruption must not expose partial artifacts or
replace a valid committed store. Bound additional working memory and queued or
completed-but-unconsumed work; an in-flight request limit alone is insufficient.
Release or spool provisional content as needed while preserving receipt and
recording guarantees. The final requested dataset has its own unavoidable size.

Concurrency must not change observations, coverage, failure scope or attribution.
Preserve actual call times, attempt evidence and dependency links instead of
fabricating a serial chronology. Recording and replay must continue to identify
requests faithfully; replay must never fall back to the network.

## Acceptance and evidence

Completion requires all-provider adoption and all maintained publisher-acquisition
entry points to use the shared boundary. A successful USGS benchmark or removal of
seven legacy fetch methods is insufficient.

Extend existing shared contracts and focused provider cases. Source-independent
checks should establish cross-call accounting, concurrent reservation, multiple
quota windows, bounded waiting, policy changes without budget reset, actual-attempt
accounting and cleanup after interruption. Exercise optional lookup failure,
late-page failure, subdivision, shared consumers, authentication refresh and bulk
truncation. Vary response completion order and verify equivalent data, coverage and
attribution. Test offline boundaries as well as live composition paths. Use
independent expectations and the simplest sufficient checks rather than copying a
scheduler test suite for every provider.

Run affected source-independent checks during implementation, then the full logic
suite and repository lint, type and applicable documentation/distribution checks.
Run the applicable retained provider recording suites across the shared migration.
Changed request grouping needs genuine source evidence, particularly USGS forced
multi-page batching, interleaved consumers and selector/failure behavior. Existing
singleton recordings remain useful controls, but cannot certify a new wire request
or batch-completeness claim.

Follow the [testing guide](../../docs/maintenance/testing.md) and
[evidence guide](../../docs/maintenance/evidence.md). Use independently reviewed
code/archive revisions and exact retained collections for genuine-input checks.
Changes to governing claims, source bindings, verifiers or selected collections
require their applicable full checks. Missing mandatory evidence blocks acceptance;
it must not be silently skipped or replaced with synthetic or derived originals.
Keep controlled material and credentials outside public files and artifacts.

Measure performance with comparable workloads, policies and equivalent results.
Cover batched observations, independent high-latency requests, long pagination and
bulk streaming. Distinguish request-count reduction from concurrency and pacing
changes; report wall time and additional memory along with acquisition work.
The comment's workload projections and loopback multipliers are not acceptance
thresholds or guarantees. Retained replay establishes source interpretation, not
current service latency or universal concurrency safety.

## Implementation freedom and supporting context

Exact public symbols, policy types, queue representation, thread versus async
execution, connection ownership, bounded defaults and PR sequencing remain with
the implementing agent. Choose them to meet the behavior above. The proposed
thread-pool/process-local-registry combination is a feasible candidate, not a
mandatory design. Neither existing test count nor a particular notebook
`asyncio.run()` failure decides the backend.

Use the [architecture](../../docs/architecture.md), the
[earlier batching study](../experimentation/2026-11-26-shared-source-request-planning.md),
[Freddy's investigation](https://github.com/RivRetrieve/RivRetrieve/issues/1113#issuecomment-7242262088)
and the [subsequent readiness review](https://github.com/RivRetrieve/RivRetrieve/issues/1113#issuecomment-7243385502)
as context. Later confirmed decisions in #1113 supersede conflicting suggestions
in the investigation. Refresh changed repository facts before implementation;
the research did not independently reproduce its reported timings or perform
private-input verification.
