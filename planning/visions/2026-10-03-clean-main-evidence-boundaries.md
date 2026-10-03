# Clean main evidence boundaries

Program: https://github.com/RivRetrieve/RivRetrieve/issues/427
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/431

## Outcome

Complete the evidence-ownership separation between RivRetrieve and its private
source archive across all 14 providers. Current `main`, its maintained guidance,
and the outputs produced by its builds, tests and release workflow must respect
that boundary. An authorised maintainer can obtain exact archived inputs, run the
applicable checks and builds, and understand precisely what their results prove.
Ordinary package users need no archive credentials.

The owner explicitly narrowed the publication review during discovery: assess
current `main` and what it produces. Do not audit or clean Git history, review
historical publication outputs, or modify merged PRs. This replaces the earlier
reachable-history requirement in the Effort and Program. The owner accepts leaving
history unchanged; this work makes no claim that history was inspected or certified.
Repository visibility changes and actual package publication remain separate owner
actions.

## Delivered foundation

Efforts #428, #429, #430 and #478 have landed. Use their delivered results and
current maintained contracts, without reinterpreting their historical acceptance
claims. The private archive already owns the versioned acquisition and integrity
interface. Tests have an explicit source-independent `--logic-only` selection.
Catalogue builds select exact archived support and record declaration and executable
identities. The offline metadata API and approved catalogue products are established.

The #478 delivery includes the exhaustive test audit, accepted dispositions,
intentional reductions and private acceptance records. Apply that testing philosophy
and those decisions. Do not repeat the exhaustive audit, restore retired tests,
preserve obsolete machinery because a test names it, or add a second test framework.
Review subsequent integration changes for new or unexplained tests and unjustified
loss of meaningful protection. Independent review must challenge unnecessary scope
and complexity as well as missing guarantees.

## Responsibility boundary

The private repository owns retained source inputs, reviewed evidence ledgers,
acquisition and acceptance records, evidence-specific acquisition and integrity
tools, source-certification machinery, and tests of that private tooling.

RivRetrieve owns library and domain implementation, catalogue transformations,
library-behavior tests, synthetic fixtures, approved runtime products, and safe
provenance and support references. Classify mixed artifacts by responsibility,
not directory or filename. An evidence-backed library test does not become private
merely because its inputs are private. Conversely, source-certification tooling
must not remain public simply because existing tests import it.

Preserve exact, truthful provenance across this split. Current code-reference and
catalogue-support contracts assume public verifier/declaration identities in places.
Adapt those assumptions where necessary to represent the actual private owners and
reviewed revisions safely. Do not retain shadow public verifiers or duplicate
ledgers to satisfy an obsolete placement rule. Private references must not expose
restricted contents. Authored interpretations, automated transformations, source
originals, derived inputs and runtime products retain their distinct meanings.

Every surviving evidence-consuming test and catalogue build uses the established
shared acquisition/integrity interface and explicit verified inputs. Remove direct
checkout evidence dependencies, duplicate access routes, implicit local fallbacks
and owner-machine lookup paths. Keep historical acquisition-path identities separate
from current lookup locations. Add no downloader, consumer inventory, compatibility
layer or migration guide.

## Purposeful retirement and documentation

Remove the top-level `maintenance/` directory through justified retirement or
verified private transfer of its responsibilities. Do not rename it or transfer
its entire contents without a necessity decision. Actual catalogue transformations
remain with the library; mixed wrappers may need responsibility separation rather
than wholesale relocation.

Account for equivalent leftovers under `docs/verification/`, `docs/provider_ports/`,
`tests/recordings/`, `tests/test_data/` and elsewhere. At discovery,
`docs/verification/` contained 106 tracked files, including 23 Python scripts.
These include tools, examples, source interpretations, historical snapshots and
review records. Do not treat them all as disposable prose. Verify authoritative
archive preservation before removing redundant retained material; never delete the
sole retained original. Preserve historical records as historical records without
leaving conflicting current instructions or historical research/report clutter in
the intended public documentation.

Resolve active responsibilities before removing pages. Brazil's maintenance README
currently delegates build instructions to `docs/provider_ports/br_ana.md`. Update
affected provider-page links when their verification targets are retired. Some tests
use `docs/verification/...` beneath the external retained-evidence root; these are
archive consumer identities, not necessarily checkout dependencies. Do not rename
archived identities simply to eliminate local documentation paths.

Keep `docs/catalogue-evidence.md`, the defining parts of
`docs/catalogue-absence.md`, and necessary catalogue-provenance rules coherent with
the delivered model. The first two define contracts used by all 14 packaged
Croissant descriptors. Do not discard those definitions as historical reports.
The separate #486 Croissant/absence follow-up and the broader documentation writing
redesign remain outside this Effort. Necessary ownership instructions and link
repairs belong here. Maintained code, private archive guidance and index, provider
documentation, agent instructions, tests and packaging must agree.

## Integrated acceptance

Demonstrate the delivered model from fresh, explicitly reviewed checkouts with
external temporary cache, store, input and output roots. Account for all 14 providers
and run applicable archive acquisition, catalogue builds, source-independent tests,
evidence-backed tests, private-tool tests and installed distribution checks.
Review exact executable revisions before granting private evidence access. Tests
receive verified inputs, not acquisition credentials. Never execute unreviewed PR
code with private access.

Keep collection integrity, recording replay, derived-input rebuilds, genuine
source-body verification and live observations distinct. Preserve justified
source/body checks, nested archive/member and publisher-receipt checks, and failure
behavior. Outer-file integrity does not establish inner-package safety. Required
complete positive checks precede related negative provenance regressions.

Record exact revisions, selections, outcomes, limits and blocked checks in the
appropriate private acceptance records, with only safe summaries shared publicly.
Missing mandatory inputs are blocked, never a passing or silently skipped check.
The eight unavailable DWS original PDFs remain unavailable for original-PDF proof;
derived inputs and synthetic PDFs are not substitutes. Existing coverage across
14 providers does not imply complete original-body certification for all of them.
No new research, acquisition campaign or coverage-gap closure is required.

Assess current tracked files and current public-facing provenance, test and build
output, logs, caches, CI artifacts, wheel and source distributions for restricted
material. Reuse the established distribution checks, including meaningful exclusion
controls and installed-artifact behavior. Keep detailed controlled results private.
Verify that the maintained provider-contribution workflow carries code and safe
archive references rather than source corpora. A clean current tree alone is not
proof that a build or test cannot leak its private inputs.

## Release consistency, without redesign

Use the current narrowed standalone vision
`planning/visions/2026-09-30-uv-releases-through-github.md` and the delivered workflow.
It supersedes the two September 30 release-policy comments on #431. The approved
policy preserves manual dispatch, TestPyPI and existing published-prerelease behavior,
uses uv and trusted publishing, and does not add the earlier release-time test gates,
tag/version enforcement or recovery-only dispatch restrictions.

Cross-check archive instructions, source-independent test selection, distribution
checks and the actual build/artifact handoff for consistency and evidence isolation.
Applicable maintainer evidence checks remain distinct from credential-free release
automation. Do not claim the publishing workflow runs tests that it does not run.
Do not introduce new release-time stages, PR/merge/main test CI or private archive
credentials into publication. Report policy inconsistencies rather than weakening
checks or independently changing the release policy. Do not upload to either index,
create releases or tags, or change repository visibility as a demonstration.

## Constraints and stop rules

Preserve source bytes and acquisition identities, source vocabulary and judgement,
unknowns, null values, absent rows and source failures. Do not change established
source claims incidentally or call a later acquisition recovery of an earlier one.
Use existing GitHub repository permissions; add no access-vetting system or Admin
requirement for routine archive work. Private access does not grant redistribution
rights. Versioned private GitHub releases remain the storage basis; fingerprints
detect changes but do not guarantee recovery after asset loss. Add no independent
backup infrastructure.

Fix small clear errors directly and validate them, including one-line bugs and
minor documentation mistakes. For major bugs, stop implementation, open a GitHub
issue labelled `bug`, assign it to CooperBigFoot, and wait for the owner's repair
and explicit permission to resume. Report discovered unsafe exposure without
copying restricted material into issues or logs, and pause for owner direction.
This rule does not authorise destructive evidence operations or weakened checks.

Completion means a coherent current-tree ownership boundary, justified removal of
remaining duplicate machinery, verified integrated behavior and an honest account
of current-output publication limits. It does not certify history, grant permission
to publish, or deliver any of the excluded launch or research work.
