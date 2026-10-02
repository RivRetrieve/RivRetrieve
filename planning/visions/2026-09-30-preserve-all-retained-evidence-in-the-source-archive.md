# Keep provider evidence outside the code repository

Related bug: https://github.com/RivRetrieve/RivRetrieve/issues/457
Paused work, outside this vision: https://github.com/RivRetrieve/RivRetrieve/issues/429

## Outcome

Keep RivRetrieve's current code tree free of retained provider evidence. Preserve that
evidence in the private `RivRetrieve/verification-evidence` archive, verify that its
exact bytes can be retrieved, and make evidence-dependent tests and tools read inputs
outside the code repository. Archive publication alone does not complete this work.

This is a code-design and evidence-storage change. Git history and old pull requests
are out of scope and must remain untouched. Older evidence may remain accessible
through them; removing those copies is not a completion requirement.

Provider evidence means material used to build catalogues, check provider parsers,
or support factual statements in `docs/providers`. Examples include downloaded
provider files, saved API responses, extracted source tables, and provider reference
documents. Include unused retained provider evidence found during this work; lack
of a current consumer is not permission to discard the only copy.

Code, test definitions, authored executable interpretation, reviewed declarations,
and approved runtime product artifacts retain their code-repository roles. A filename
such as metadata, fixture, cache, or catalogue does not determine a file's role.
Review mixed files explicitly. Preserve their evidence-bearing original bytes
privately before changing the maintained representation.

This revised vision replaces the previous requirement to complete the failed run's
all-occurrence accounting system. The preservation goal remains. Its custom audit
machinery and unfinished proposals are not prerequisites for delivery.

## The problem and completed work

During #429, the selected archive collections lacked exact copies of some local
inputs used by tests. The originals remained intact. This was a retention/access
gap, not a finding that provider values or scientific claims were wrong.

Some reported inputs are provider evidence. Others are historical RivRetrieve-generated
files used to test behavior such as rejecting obsolete formats. Keep these roles
separate rather than calling every old file provider evidence.

The final status on #457 records two merged private archive preservation slices,
fresh retrieval and exact-byte comparisons, 142 passing historical regression tests,
183 passing governing tests, and 148 passing archive checks for each completed slice.
These are results at their recorded revisions, not new verification of the eventual
implementation target. Reuse the exact collections and valid verification records;
repeat checks when changed code, inputs, or claims require it.

The later implementation stalled in classification of copies and repeated custom
accounting, reader, and launcher reviews. Its final accounting proposal was not
applied. Discovery found later retention candidates without completed preservation
proof, and other groups with archive references but unresolved descriptions or body
checks. Those are starting points for a bounded file-to-archive check, not an accepted
complete inventory. Occurrence counts must not be reported as counts of missing files.

Keep detailed inventories, local report locations, source identities, receipts, and
sensitive acquisition context private. The issue comments and the private archive's
merged intake records provide the starting handoff. Read the existing records; do not
restart their custom execution workflow or accept draft classifications as proof.

## Preserve material with a practical inventory

Build a concrete inventory of retained provider evidence and required historical test
inputs. Inspect maintained source locations and relevant local retained material, while
avoiding a new project to classify every dependency, build output, or temporary copy.
Use existing accounting as a source of candidates rather than as a required schema.
Cover tests, provider research, catalogue maintenance, and documentation source material.
Keep active consumers visible so removals cannot silently break them.

For each retained artifact or supported group, record privately:

- what it is and why it belongs in the archive;
- its exact byte identity, known source or derivation context, and any unknowns;
- its current consumers, if any;
- its exact archive collection/member selection and retrieval/equality result;
- whether its repository copy can be removed, or the concrete blocker.

Find existing exact archive matches first. Preserve missing bytes using the existing
reviewed archive intake, publication, inventory, and retrieval tools. Retrieve selected
material outside source checkouts and compare it with the originals. Do not substitute
new downloads, reconstructed inputs, or synthetic data for historical originals.
Missing publisher originals remain explicit gaps.

Equal bytes can share storage, but must not erase known distinct acquisition identities
or lineage. Preserve useful known context and state unknowns honestly. Do not reconstruct
every temporary copy's history solely to complete accounting. A genuine uncertainty
about safe handling or sharing is a concrete blocker; uncertainty about historical
provenance must not be replaced by an invented claim.

## Review historical tests before retaining their inputs solely for testing

A regression test checks that changes do not break behavior that should continue to
work. Preserve useful provider parsing, catalogue, and source-claim checks. Do not weaken
correctness checks to make evidence removal convenient.

Review tests of historical RivRetrieve formats against intentional current requirements.
Keep tests that protect required behavior and preserve their necessary inputs privately.
Remove demonstrably unnecessary historical tests instead of maintaining obsolete inputs
solely to keep those tests alive. Existing coverage is not automatically a requirement,
but neither is an old format automatically irrelevant. Record the reason for each
removal. Preserve uncertain originals until their disposition is settled.

Public code anchors include `tests/test_retired_physical_fact_formats.py`, which checks
exact baseline-generated files and non-destructive rejection;
`tests/test_ca_eccc_boundary_probe.py`, which distinguishes a derived HYDAT input from a
national original; and `tests/test_ca_eccc_no_days_evidence.py`, which compares extracted
rows with separate publisher recordings. Inspect current code before changing tests.
Do not conflate generated historical outputs, extracted source evidence, and authored
attestations.

## Remove evidence from the current code tree

Remove evidence from the current code tree only after verified private preservation.
Do not delete sole originals or remove active inputs while their retained consumers
still require them. Do not add a local fallback to conceal missing archive access.

Complete #457 independently. Changes to tests and other evidence consumers are in
scope when necessary for evidence removal and continued correctness. Use the existing
archive infrastructure. Do not resume or integrate #429's unfinished drafts, execute
its unreviewed code, or claim its delivery. Leave #429 paused; its implementation will
adapt to the completed #457 changes. Do not break consumers or claim #457 complete
with retained provider evidence still present in the current code tree.

Keep evidence outside the repository while allowing tests, catalogue maintenance, and
documentation verification to use explicitly supplied local archive inputs. Keep runtime
package users independent of archive access. Preserve code, test definitions, authored
interpretation, reviewed declarations, and approved runtime catalogue products here.

Do not rewrite history, clean old branches or PR references, migrate to a new repository,
or audit historical hosted artifacts as part of this work. No history or publication
strategy decision is needed to proceed. Changing repository visibility is outside scope.

## Remove the failed attempt's bespoke machinery

Remove the custom accounting, audit-reader, launcher, review, and retry scaffolding built
for this attempt. Do not finish its pending accounting proposals or create another audit
framework to replace it. Identify task-owned code, copies, and environments concretely;
do not delete an entire working directory based on its name.

Keep the existing useful archive intake, retrieval, manifest/integrity, publication,
and controlled-verification infrastructure. Preserve originals, essential lineage,
accepted preservation records, receipts, and relevant failure/correction records privately
before removing scaffolding. Retaining a record does not require keeping the program that
created it operational. Treat copied source and unique uncommitted work carefully; do not
delete another task's drafts or worktrees, including #429's preserved work.

## Verification and completion

Follow `docs/maintenance/evidence.md` and the reviewed private archive instructions.
Use existing GitHub access; add no vetting system or parallel archive infrastructure.
Only reviewed code may run with private evidence or credentials. Keep controlled material
out of public issues, logs, assertion output, caches, artifacts, and distributions. Review
source-sharing permissions; private storage alone does not establish permission to share.
Runtime package users must not require archive credentials.

Before reporting #457 complete:

1. Account for the retained provider evidence and historical inputs still required after
   the test review. Show exact private archive selections, successful retrieval, and
   original-byte equality. Explain exclusions and remaining limitations plainly.
2. Verify affected retained tests and applicable full genuine-input checks against the
   intended code and collections. Do not count missing inputs, skipped mandatory checks,
   or synthetic substitutes as acceptance. Reuse unchanged valid verification evidence
   with explicit revision equivalence where appropriate.
3. Verify that the intended target branch's current tree contains no retained provider
   evidence and that retained consumers use external archive inputs. Required historical
   test inputs belong in the private archive as well. Leave Git history and old PRs
   unchanged; historical copies do not block completion.
4. Remove unnecessary bespoke task machinery while preserving essential records and
   useful archive infrastructure. Record any uncertain ownership or unique-work blocker.
5. Provide a short privacy-safe completion report and a precise private preservation
   handoff, including revisions, selections, tests, removals, and any unresolved gaps.

Stop with concrete affected files and reasons when blocked. Do not expand into provider
research, source-claim changes, catalogue redesign, complete historical copy reconstruction,
or resumption of #429. Closure requires the agreed outcome, not completion of the former
agent's accounting process.
