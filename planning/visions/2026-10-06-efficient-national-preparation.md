# Efficient national preparation

Program: https://github.com/RivRetrieve/RivRetrieve/issues/514
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/517

## Outcome

Make complete national preparation for Poland and Canada do justified work at
understandable resource costs. Investigate the path from publisher discovery and
transfer through decoding, compilation, certification and publication. Improve
clearly wasteful work where a sound design can remove it without weakening source
fidelity or failure safety.

There is no required speedup, completion-time target or fixed memory/disk ceiling.
The owner explicitly accepts the measured 60-minute Polish and 51-minute Canadian
build times if the remaining work is justified. Do not manufacture a performance
win, weaken checks or add complexity merely to obtain a lower number. Demonstrate
what changed, measure its effects, and explain costs that remain. This clarification
supersedes the ticket's earlier direction to require measured improvements for both
providers: both must be investigated and measured, but neither has a mandatory
speedup threshold.

This is pre-release work with no users or backwards-compatibility requirement.
A coherent redesign is allowed. Justify abstractions and large changes; do not add
migration machinery, legacy shims or speculative features.

## Existing contracts and evidence

Start from the delivered shared storage and local-read contracts:

- Effort #515, PR #521, merged at
  `789cda762cb6b4c4678305221a6d7470a0a0d2e5`, establishes publication, integrity,
  ownership, recovery, status, clear and successful-refresh semantics.
- Effort #516, PR #530, merged at
  `e3cce58bdf8ed5a907eda21046b152ac7b9d87ff`, establishes shared request preparation,
  selective reads and request-relevant evidence. Preserve those delivered outcomes.

Use the shared lifecycle rather than creating a second publication, recovery or
integrity system. Preserve the distinction between failure before publication and
a successful commit with cleanup still required. Existing guarantees concern local
process interruption with a running operating system and filesystem. This work does
not promise power-loss durability, continuous concurrent reads during replacement,
network-filesystem coordination or security against a hostile local user.

Read the complete six-comment evidence index in Program #514, the current store
contract, and original issue #392 including its shorter-archive discussion. The
investigation at `cae286a002f6cc6e80fe9af1ff2d2dfb07f73840` is historical evidence,
not a requirement to preserve its candidate implementation suggestions or rerun
unchanged investigation steps.

| Historical national measurement | Poland | Canada |
| --- | ---: | ---: |
| Compilation | 3,606.204 s | 3,055.091 s |
| Observation rows / partitions | 59,629,260 / 228 | 79,811,984 / 344 |
| Final store | 222.930 MB | 412.848 MB |
| Source-unit journal peak | 8,587.080 MB | 239.601 MB |
| Three full validations, total | 606.470 s | 777.842 s |

Poland's sampled simultaneous cache/temp footprint reached 9.156 GB, excluding
retained originals and disposable download copies. The configured admission floor
was 6 GB. Its compilation and independent replay decoded monthly artifacts eight
times and annual artifacts fourteen times: 6,954 decoder invocations and 5,220 sort
preparations. Sort preparation took 1,664.502 seconds, including decoding, filtering
and SQLite preparation. That is not isolated sorting time. Journal insert/update
wrappers consumed only 98.102 seconds, so shrinking the journal alone cannot remove
most latency. Account for buffers and sorting iterators that remain live together.

Canada's four ZIP extractions totaled 3.782 seconds. Eliminating those alone would
barely change its baseline. Its journal is much smaller than Poland's. Investigate
source decoding, row expansion, writing, reconciliation, repeated validation and
certification with separate attribution. Do not add inclusive parent/child timings
or generalize one provider's resource costs to the other.

## Download means permission to replace the snapshot

Calling `rr.download` authorizes replacement by the newly acquired, valid publisher
snapshot. If Poland previously covered October and the newly listed valid history
ends in September, do not refuse solely because that endpoint moved backwards.
Do not require a second confirmation or a coverage-reduction override. Explain the
replacement behavior in public documentation.

Preserve supported completeness rules within the discovered history, including
refusal of missing interior periods, malformed or ambiguous listings and unsupported
overlapping editions. A failed request, incomplete transfer or invalid archive is
not a valid shorter snapshot. Such failures must preserve the prior valid store.
Successful replacement must faithfully contain the new snapshot; never union removed
rows from the old store back into it.

Do not infer why the publisher removed data. A shorter history establishes neither
intentional withdrawal nor failed acquisition. Keep publication/release identity,
coverage end, acquisition time and build time distinct. Poland's current coverage-end
floor is the behavior this decision changes. Canada's same/newer dated release may
already contain fewer rows. Its safeguard against falling back to a genuinely older
dated release is a separate source-selection rule and is not removed by the
shorter-coverage decision.

`fetch` must not silently acquire a national dataset. Preserve explicit national
acquisition through `download` and the distinction between prepared bulk source
material and optional live caching. No cache-default or unrelated API change is
part of this outcome.

## Fidelity and resource safety

Retain native source cells and all supported physical/source columns, units, time
labels, source-series and physical-fact identities, quality vocabulary, unknowns
and duplicate multiplicity. Keep null, blank, absent rows, successful empty results
and failed requests distinct. Do not change hydrological interpretations or invent
unpublished products to obtain faster processing.

Preserve independent source inventory, count and identity/substitution checks,
declared source-column closure, and complete source-to-store certification. Removing
redundant work must retain the proof those checks establish. Count equality alone
cannot detect equal-count substitutions. Invalid internal output remains fatal and
must not be hidden by caller issue policy. Reversible choices of decoding, sorting,
batching and scratch representation belong to the implementing agent.

Resolve actual paths and resource dependencies at composition boundaries. Plan for
transfer buffering, extracted source data, sorting and reconciliation scratch,
source inputs, candidate output and the previous store while they coexist. Account
for the actual filesystems used, without double-counting bytes already reflected in
available-space measurements. A small emitted batch does not prove bounded total
memory when many iterators or buffers remain alive.

Replace misleading resource assumptions with evidence-backed planning and clear
limits. Admission estimates do not reserve disk space. Handle late disk/resource
failures through the existing lifecycle, preserving prior committed data, external
originals and truthful cleanup outcomes. Tests must exercise actual workspace and
failure boundaries, including separate filesystems if supported.

## Acceptance

Demonstrate correct complete national preparation for both providers against exact,
reviewed genuine inputs. Compare all retained physical/source columns, identities,
units, time labels, null/blank/absence distinctions, duplicate multiplicity and
provenance. Preserve full certification and independent omission/substitution
controls. Protect the new shorter-coverage replacement behavior as well as refusal
of genuinely incomplete or invalid acquisitions and safe failed refreshes.

Measure the full preparation path, distinguishing discovery/transfer from local
compilation and certification. Use comparable retained-input runs for local work;
state when network acquisition measurements use different inputs or conditions.
Record source identities, executable revisions, runtime, machine, method and limits.
Serialize heavy national measurements. Include actual workspace peaks and memory
behavior, and account for old/new/source coexistence during replacement. Sampling
can miss brief peaks; per-path allocated bytes are not unique physical storage.
Do not claim OS-cold timing or unmeasured physical I/O.

Add deterministic work-count and resource-scaling regressions that detect the
specific waste being removed. Avoid fragile absolute laptop-time assertions.
Measure both providers even if one has no justified optimization. Explain any
regression or trade-off and judge it against the intended outcome rather than a
promised percentage. Tests, public documentation and measured acceptance belong in
this Effort; no separate cleanup ticket is needed.

Use `uv` and the maintained testing and evidence guides. Run affected and appropriate
broader source-independent checks. Use the private archive's maintained exact
selection and full-check interface for genuine-input acceptance, with independently
reviewed public and archive executable revisions. Run applicable complete governing
checks when source bindings, claims, verifiers or collections change. Missing
mandatory material blocks the corresponding acceptance; do not skip, narrow or
substitute derived data for required originals.

The Program's original evidence described fresh national originals as retained but
not yet adopted. The later #516 delivery records exact national inputs preserved
and retrieved through the maintained archive, with certified baseline stores and
national comparisons. Establish current selection and availability through that
interface; do not assume old acquisition-machine paths or that historical passing
runs certify changed code. Preserve originals, receipts, limitations and failed-run
evidence. Keep controlled data and credentials out of code Git, public records,
logs, caches, CI artifacts and packages. Fresh acquisition cannot silently replace
historical input identity. Evidence preservation does not require a new user-facing
archive-retention feature.

## Boundaries and delivery

Own provider-specific discovery/transfer, decoding, partition preparation,
reconciliation, certification integration, publication selection and realistic
resource planning. Request-path scan/batching optimization, live-cache redesign,
provider expansion and rewriting the private evidence system are outside scope.

Follow the ticket's major-bug rule: for a newly discovered major bug, stop
implementation, open a `bug` issue assigned to CooperBigFoot, and report the blocker.
Wait for the owner's merged-fix handoff and independently verify it before resuming.
Minor related fixes may be made directly with affected checks. The confirmed defects
already assigned to this Program remain approved work.

This Effort owns the verified disposition of original report #392, including its
resource report and shorter-archive consideration. Record measured conclusions and
merged-delivery links. A justified remaining build cost is acceptable under the
owner's decision above. Publishing this vision does not establish resolution,
delivery or landing. Both issues remain open. Implementation starts only through
the explicit handoff after this vision is published and verified.
