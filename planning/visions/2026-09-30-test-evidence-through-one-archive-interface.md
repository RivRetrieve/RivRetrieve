# Test evidence through one archive interface

Program: https://github.com/RivRetrieve/RivRetrieve/issues/427
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/429

## Outcome

Every test that needs retained source evidence obtains its exact inputs through
one shared access interface backed by `RivRetrieve/verification-evidence`.
Evidence stays out of the publishable RivRetrieve repository and its outputs.
Developers run tests with minimal friction. Individual tests do not manage
acquisition, credentials or separate archive locations.

All developers have access to the private archive. The purpose is to prevent
publication of evidence, not to introduce access tiers between developers. Use
existing repository permissions and GitHub authentication. Add no extra vetting,
approval system or routine manual download and path-configuration workflow.
The shared interface handles the mechanics needed to supply test inputs. Choose
those mechanics from the existing archive design rather than making developers
coordinate them. An environment variable or separate preparation command is not
a required user-facing design.

This Effort covers testing across all 14 providers. The wider Program gives all
archive consumers one authority. Catalogue build adaptation and claim traceability
remain with #430; final integrated publication-boundary review remains with #431.
Do not absorb those outcomes into this Effort.

## Use the archive already delivered

Effort #428 established the sole current inventory and the standalone `archive`
interface in the private repository. The inventory owns collection, release,
asset and manifest identities; release attachments hold retained material.
The interface already checks asset identities, sizes, digests, extraction bounds
and manifest-bound members. Reuse that authority and its integrity protections.
Do not recreate an archive inventory, downloader or management framework in
RivRetrieve. Local material supplied for execution is a working copy, never a
second maintained collection.

Select exact inputs explicitly. New archive acquisitions must not silently change
which inputs a test uses. Providers advance independently and collections can be
shared; do not require a global evidence version or one collection per provider.
Keep any consumer references limited to what actual tests need. Resolve access
and configuration at composition boundaries; lower-level tests and parsers receive
resolved inputs rather than discovering application state or handling credentials.
Runtime package users need no archive access.

## Preserve what the tests establish

Harmonise access and integrity without imposing common agency payload formats.
Retain provider-specific decoding, exact request matching, boundary assertions,
source failures and the distinction between null values and absent rows. Do not
replace genuine provider recordings with synthetic responses to avoid archive
access. Synthetic controls remain appropriate for source-independent logic and
archive mechanics, but cannot establish genuine source acceptance.

Make the purposes and limits of checks clear:

- source-independent logic checks;
- parser and retrieval regressions against genuine recordings;
- offline rebuilds from derived inputs;
- complete catalogue or governing source verification;
- live-service observations.

A recording replay is not a live observation. A derived-input rebuild does not
prove that original responses exist. Preserve existing coverage and known gaps;
this work does not create missing source evidence or stronger source claims.
Complete positive genuine-input verification must precede negative provenance
regressions where required, including ThaiWater.

For developers with archive access, the normal testing workflow should supply
required evidence through the shared interface without separate per-provider
setup. Contributors without archive access must still have an explicit way to
run source-independent checks. Collection of those checks must work without
private inputs. Requested evidence or full-verification checks fail clearly on
missing access, missing material or invalid integrity; silently skipped checks
are not acceptance. Document commands, prerequisites and what a successful run
actually establishes. Do not describe an evidence-backed suite as credential-free.

## Prevent publication and disclosure

Keep evidence and credentials out of tracked RivRetrieve files, code PR
attachments, public metadata and documentation, packages and distributions.
Prevent evidence-backed execution from exposing material through stdout, errors,
assertion rendering, logs, caches or shared CI artifacts. Merely placing files
outside Git is insufficient. Retain detailed controlled receipts in private
storage and review summaries before sharing them. Existing source-sharing
restrictions still apply despite every developer having archive access.

Preserve the Program requirement to run controlled checks only against explicitly
reviewed code in restricted execution. Never give unreviewed PR code private
evidence or credentials. This is an execution and disclosure boundary, not a new
developer-vetting process. Design the seamless local workflow within that boundary
without inventing a separate approval service.

## Replace existing test access cleanly

Current test inputs are scattered across `tests/recordings`, `tests/test_data`,
`docs/verification`, catalogue maintenance inputs and research paths. Shared
replay helpers, provider-specific manifest loaders and direct archive readers
coexist. For example, `tests/usgs_modern_recordings.py` checks recording identities
and request matching, while French tests read their own archive bundles.
Some modules load input manifests during import. Moving files and deselecting
tests after collection is therefore insufficient for an evidence-free logic run.

`tests/test_catalogue_origin_certification.py` composes provider catalogue inputs
and overlaps with #430. Coordinate shared access and test bindings while leaving
catalogue build semantics and traceability changes to that Effort. Preserve
scientific verifiers, authored declarations and reviewed ledgers in their proper
roles. Classify intermediate artifacts rather than treating every evidence-related
file as a source original or moving executable interpretation into the archive.

Remove replaced fixture loaders, duplicate acquisition paths and maintained
source-tree recordings as this Effort lands. Verify exact archive preservation
before retiring copies; never delete the sole retained original. No compatibility
shims, duplicate legacy paths or migration guides are needed. Do not defer known
replacement cleanup to #431. Keep the change proportional to the real consumers;
a large diff requires a necessity and scope review, not speculative infrastructure.

## Acceptance and limits

Demonstrate the testing workflow from fresh checkouts with exact reviewed code and
archive revisions and precise selected evidence identities. Exercise applicable
genuine-input checks across the existing provider coverage, including complete
mandatory verification affected by changed source bindings. Show that provider
assertions remain intact, unavailable required inputs fail honestly, and the
source-independent route works without archive access. Verify disclosure and
packaging boundaries without publishing the material being checked.

Report commands, outcomes, coverage limits, skips and blocked checks accurately.
Account for all 14 providers without claiming complete original-body coverage
where it does not exist. Missing mandatory evidence blocks acceptance. Do not
weaken checks or substitute derived data for originals. Measure and report the
runtime impact of costly new coverage; keep unchanged expensive inputs reusable
only when test isolation and validation of changed inputs remain intact.

This is consumer refactoring, not new provider research, a new acquisition
campaign, incidental source-claim changes or elimination of historical gaps.
Preserve original bytes, acquisition identities, source vocabulary and unknowns.
GitHub release storage remains the basis; fingerprints detect changed bytes and
do not guarantee recovery after attachment loss. No independent backup system,
history rewrite or repository visibility change is authorised.

The Effort's stop-and-report rule applies: if implementation discovers a bug or
error, including misinformation in documentation, stop, open a GitHub issue
labelled `bug` assigned to `CooperBigFoot`, and report the blocker without restricted
details. Do not fix it incidentally or continue around it. Wait for the owner's
repair and explicit permission to resume. A prior exception granted during #428
is not authority to change this Effort's rule.
