# One coherent testing philosophy

Program: https://github.com/RivRetrieve/RivRetrieve/issues/427
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/478

## Outcome

Make RivRetrieve's tests orderly, useful and understandable across all 14 providers
and both repositories. Review the complete suites, remove pointless tests and
unnecessary machinery, and implement a coherent testing philosophy. Future provider
ports should extend that philosophy instead of inventing their own.

This is a comprehensive cleanup. Completeness applies to the existing tests and
their supporting machinery; it does not demand a search for every conceivable
missing test. There is no test-count, runtime-reduction or schedule quota. Spend
the effort needed to understand the suites, without building a new management
framework or turning cleanup into speculative coverage expansion.

The governing principle is:

> Every test protects a named promise, uses an appropriate independent expectation,
> and runs at the simplest level that can catch the relevant failure. Providers
> share this model; source differences justify exceptions.

## Four principles

### Test promises, not code structure

Protect meaningful behavior, invariants and failure boundaries. A failed request
must remain distinguishable from an empty result. Source unknowns, null values,
absent rows and failure identities must retain their meanings.

Helper names, incidental filenames, implementation choices and exact prose usually
do not deserve tests. Assert them only when that property is an intentional
contract. Refactoring should not break tests unless it changes such a contract.
Historical tests do not earn permanent status merely because they once supported
a migration or passed a previous review.

### Share contracts; test real source differences

Use shared checks for common provider contracts, such as output shape, identity
handling and failure behavior. Provider-specific checks cover real differences:
units, timestamps, pagination, missing-value codes, source quality flags and other
source-specific interpretation. Harmonisation does not imply identical inputs or
assertions for every agency.

A new provider demonstrates the common contract and justifies its distinct checks.
Copying another provider's full suite is not a testing strategy. Preserve source
vocabulary and uncertainty rather than forcing agencies into invented semantics.

### Match the proof to the claim

Choose expectations that can expose the defect the test claims to detect. An
independent expectation need not always come from agency material: a small,
hand-calculated expected value is suitable for a synthetic unit conversion.
Reusing the production transformation to compute its own expected answer cannot
establish that transformation's correctness.

| Input or check | What it can establish |
| --- | --- |
| Small synthetic example | Defined logic behaves correctly against an explicit expectation |
| Archived agency response | The parser or retrieval path handles that retained response |
| Independent source reference | A specific interpretation or transformation agrees with the source |
| Derived native input | A rebuild works from that input, without proving missing originals exist |
| Built distribution | The installed package works and contains the intended public material |
| Live request | The service behaved that way at that moment |

Consistency and propagation checks can be useful, but must be described as such.
Recording replay is not live verification. A successful native-table rebuild is
not independent source certification. Historical snapshots need a stated reason
for remaining authoritative.

### Use the simplest sufficient test

Test a conversion with a small explicit example. Test decoding with suitable
retained responses. Use integration checks to establish that the assembled path
works. Do not repeat a full end-to-end path for every local edge case.

Repeated coverage must protect a distinct failure or integration boundary. Sharing
setup must preserve isolation and must not hide changed or corrupt inputs from
validation. Prefer clear tests with useful failures over elaborate test-only
abstractions. Large changes also require a necessity review: are we adding anything
we do not need?

## Complete audit and implemented cleanup

Account for every starting test definition and parametrized case in RivRetrieve
and the private `verification-evidence` repository. Include checks outside ordinary
pytest collection, standalone verifiers, executable documentation, distribution
checks, inactive or dead tests, fixtures, helpers, mocks, caches and execution or
selection infrastructure. The scope includes every provider and the shared engine,
transport, store, catalogue, metadata, public API, documentation, packaging and
release behavior.

For each test, or explicitly enumerated group of genuinely equivalent cases,
establish its promise, plausible failure, source of expectations, evidence needs,
ownership and cost. Decide whether to keep, simplify, merge, move, replace or delete
it. Explain transferred guarantees and intentional reductions. A green suite or a
retained case count does not justify those choices. Do not hide unaudited parameters
behind file-level summaries.

Keep a bounded decision record that reconciles the complete starting suites with
the final suites, including added and moved cases. Detailed controlled acceptance
records stay private. The record supports this cleanup; it must not become a
permanent per-test registry or ongoing administrative framework. The ticket and
this vision remain the discovery records.

Agents own the audit, dispositions, rewrite and validation. There is no later
owner-approval gate for the philosophy, test removals or proposed rewrite. This
settled direction supersedes the earlier approval requirement. Independent review
must challenge both unnecessary retained machinery and unjustified losses of
meaningful protection. An audit report alone does not complete the Effort.

Address concrete missing protection when it undermines a promise the resulting
suite claims to test. Do not expand the work into a speculative search for obscure
bugs or every possible coverage gap. Apply the existing major-bug rule below when
real problems arise.

Document practical maintainer guidance with examples: what belongs at each testing
level, how expectations are chosen, when private evidence is needed, how a provider
uses the shared contracts, and what justifies an exception. Make the resulting
suite and the guidance agree.

## Evidence ownership and adjacent work

Source evidence comes from the private archive through the established acquisition,
integrity and explicitly selected-input interface delivered by #428 and #429.
Evidence-consuming library tests and catalogue checks receive verified inputs;
they do not discover source corpora in the RivRetrieve checkout. Do not create a
second downloader, inventory, access route or local evidence fallback.

Keep synthetic fixtures, approved runtime products and safe support references
distinct from archived source evidence. They may remain in RivRetrieve. Tests of
private archive tooling belong with that tooling. Evidence inputs and
evidence-specific tooling belong privately; actual library and catalogue
transformations and their behavior tests remain RivRetrieve responsibilities.
Classify by responsibility rather than directory name.

Do not preserve pointless tests by moving them into the private repository.
Implement the test-side ownership changes needed for this cleanup. #431 owns the
remaining evidence/tooling separation, removal of residual duplicate workflows and
final integrated publication-boundary review. It must consume these dispositions
rather than repeat the exhaustive audit or recreate removed tests. This Effort
must remove the test machinery it replaces rather than defer it to #431.

Preserve original bytes and historical records before retiring maintained copies.
Keep controlled material and credentials out of code changes, assertion output,
logs, caches, documentation, CI artifacts and distributions. Execute code with
private evidence only after independent review of the exact revisions. Existing
archive permissions are sufficient; no new approval or access system is needed.

## Delivered baseline and investigation leads

#430 is landed. Its final recorded targets are RivRetrieve
`f5a47492275c24837e0428c48e84dc048c3f3bd5` and private archive
`d2ce02f29c3581f0a46d53d9d18dc7f49ed19ad9`. Inspect the current delivered targets
before establishing this Effort's starting census and comparable measurements.
Do not replay assumptions from the ticket's earlier pre-#430 survey.

The delivered system already has all-provider offline rebuild checks, a
source-independent `uv run pytest --logic-only` route, declared test purposes and
a private controlled coordinator. Reuse these foundations where justified rather
than inventing them again. Current station metadata and catalogue provenance are
part of the audit, not just provider observation parsing.

The ticket's leads include duplicated rebuild/smoke coverage, evidence-file
existence checks, historical reconstruction machinery, expectations computed with
production transformations, and artifact or wording locks. They are questions to
investigate, not predetermined deletions. Preserve justified independent controls,
including source identity and coordinate interpretation. Outer-file integrity does
not imply nested-member safety or valid publisher receipts.

Existing full-positive source checks cover established Bosnia, historical France
and ThaiWater families. All-provider rebuild coverage does not imply complete
original-body verification for every provider. Eight missing original DWS PDFs
remain an explicit limitation. No acquisition campaign or synthetic replacement
may be used to conceal missing originals.

## Verification and completion

Completion requires the implemented cleanup in both repositories and a clear
explanation of the resulting testing model. Every retained case has an identifiable
purpose and justified expectation. Every starting case has an accounted disposition.
New provider guidance makes shared behavior and legitimate exceptions clear.

Measure comparable baseline and final runtimes, including expensive groups and
acquisition or coordination where relevant. Separate measured results from estimates;
performance is evidence for decisions, not a deletion target. Check isolation and
changed/corrupt-input behavior when reusing setup.

Run source-independent acceptance separately from applicable full genuine-input
checks against reviewed revisions in both repositories. Retain justified complete
positive prerequisites before relevant negative regressions. Missing mandatory
material is blocked, never passing or silently skipped. Report known limitations
without turning them into claims of complete source correctness.

Test actual distributions and their evidence/credential exclusions. Keep detailed
controlled results private and publish only reviewed safe conclusions. Independent
final review must verify alignment between the philosophy, dispositions, changed
suites and reported acceptance. No new release or CI policy is authorised.

## Boundaries and bugs

No new provider research, incidental source-claim changes, production redesign just
to satisfy tests, blanket replacement with synthetic inputs, compatibility shims,
migration guides, new framework for its own sake, history rewriting, visibility
change or package publication. Removing a file from HEAD does not remove its Git
history. Archive fingerprints do not provide recovery after attachment loss.

Fix small, clear bugs directly and validate them, including one-line errors,
incorrect comments and minor documentation mistakes. For major bugs, stop
implementation, open a GitHub issue labelled `bug`, assign it to **CooperBigFoot**,
and report the blocker without restricted details. Wait for the owner's repair
and explicit permission to resume. Removing the rewrite-approval gate does not
remove this major-bug rule or authorise weakened checks, destructive evidence
operations or disclosure.
