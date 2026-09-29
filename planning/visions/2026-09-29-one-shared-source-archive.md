# One shared source archive

Program: https://github.com/RivRetrieve/RivRetrieve/issues/427
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/428

## Outcome

`RivRetrieve/verification-evidence` is the authoritative private archive for retained
source material across all 14 providers. A maintainer or AI agent can find material,
understand its origin and limits, and retrieve exact verified inputs through one
consistent interface. Eventually, every evidence-backed test gets its inputs here.
This Effort establishes the archive and access contract; #429 adapts tests and #430
adapts catalogue tooling and traceability.

Design for agents first. Use clear structure and machine-readable records instead
of lengthy explanations. Shorten the evidence repository README to essential
orientation, access prerequisites, commands and links. Keep maintained instructions
concise, current and free of em dashes. Preserve necessary qualifications and
historical acceptance records without duplicating them in the README.

## Preserve bytes, organise their meaning

Review existing originals, response recordings, receipts, publisher documents,
research support and intermediate inputs. Account for every provider, including
shared collections and known missing originals. Inventory actual retained material;
the current index alone cannot establish what remains on an acquisition machine.
This is a review and consolidation of existing material, not new provider research
or a new acquisition campaign.

Keep original bytes, request identities, acquisition dates and receipts where they
exist. Unknown provenance stays unknown. A later acquisition cannot replace an old
one under its identity. Do not clean, harmonise or convert source payloads into a
common format. Catalogue interpretation and harmonisation remain downstream.
Storage packaging may change while preserving retained member bytes and lineage.

Classify artifacts by their actual role:

- Publisher originals and retained source-response recordings.
- Derived or reconstructed inputs, including native materialisations.
- Authored interpretations, declarations and reviewed ledgers.
- Research context and approved runtime products.

A filename or directory is not sufficient classification. Source corpora belong in
the private archive. Code, test definitions, reviewed declarations, executable
interpretation and approved runtime products belong in the code repository.
Classify mixed and intermediate artifacts explicitly. Do not move executable
interpretation simply because it refers to evidence, or present derived material
as an original.

Retain useful context even when no current test consumes it: receipts, publisher
explanations and records of acquisition limitations. Clearly identify speculative
or unaccepted notes as authored material. Retention does not endorse a claim or
select a consumer input. A genuine failed response may itself support an
error-handling test; it is not automatically disposable.

The implementing agent should investigate suspicious content, unexplained
transformations, misleading descriptions, duplicates and irrelevant clutter. It
may classify, flag and recommend exclusion from accepted inputs. Destructive
removal of questionable or unique material requires owner approval. Retire verified
redundant copies only after proving archive preservation. Never silently destroy
the sole retained original. Actual discovered errors follow the stop rule below.

## One archive contract

The contract answers: what exists, where it came from, what it represents, which
exact version a consumer selects, and how that consumer obtains and verifies it.
Accompanying records describe retained bytes rather than replacing them.

- Distinguish acquisition identity from collection packaging and release identity.
- Record source/request context, acquisition facts, provenance and receipt links,
  material role, integrity, access restrictions and known limitations as applicable.
  Keep private details out of public-facing metadata.
- Support independently advancing acquisitions and providers. A collection can
  serve several providers or consumers. No forced global archive version.
- Make selected inputs explicit and reproducible. Publishing material never
  silently updates a catalogue or test input. No mutable `latest` substitution.
- Provide consistent discovery, selected retrieval, integrity checking and
  publication/intake. Lower-level operations receive resolved dependencies rather
  than discovering owner-machine paths or application configuration.
- Maintain an intake procedure for future research outputs. New-provider code PRs
  carry code and exact archive references, not source corpora or evidence attachments.

An authorised consumer selects exact inputs, downloads a working copy outside
source checkouts, checks pinned identities and bytes, then uses the material.
Working copies are not separately curated collections. Retrieval must not select
inputs through probabilistic relevance judgments.

Do not integrate Jev or add an AI service dependency. Agents can assist the review;
ordinary code checks hashes, duplicate bytes, missing files and references. Record
reviewed decisions so publication, retrieval, catalogue builds and tests do not
require rerunning AI.

## Access and storage

Use private GitHub versioned-release storage in `RivRetrieve/verification-evidence`.
Approval and publication initially remain with the owner, CooperBigFoot. Define
separate read, publish and admin privileges under explicit owner control. A
contribution, merged PR or unintended organisation base permission grants no access.
No new grants are implied by this vision.

The owner has requested repository Admin access. Assume that access for planning,
but verify effective permissions before administrative actions. Repository Admin
and organisation Owner are different roles; organisation policy changes may need
separate owner action. Record unavailable mandatory permission checks as blocked.

Private storage does not establish permission to share source material. Never expose
restricted bytes or credentials in public metadata, docs, logs, caches, CI artifacts
or distributions. Never execute unreviewed PR code with evidence access. Runtime
package users need no archive credentials.

There is no independent backup or recovery guarantee after release-attachment loss.
Pinned identities and fingerprints detect changed material; they do not prevent
deletion. Report actual release protection, without claiming unverified immutability.

## Redesign and delivery boundaries

Existing implementation, schemas, paths and APIs impose no compatibility obligation.
Refactor or replace them fully where useful. Preserve evidence, not incidental
machinery. Remove replaced archive machinery within this Effort. No compatibility
shims, duplicate legacy interfaces or migration guides are required.

This Effort owns material review, preservation, archive organisation, publication,
access and the shared consumer contract. #429 owns test-consumer adaptation and
#430 owns catalogue-consumer adaptation. Coordinate necessary interface changes;
do not delete active consumer inputs before preservation and consumer adaptation.
Dependent Efforts remove the source-tree inputs and bindings they replace. #431
checks integrated consistency and publication boundaries, not deferred cleanup of
archive machinery replaced here.

## Evidence of success

- All 14 providers have a reviewed account of retained material, its classification,
  exact archive references where retained, and honest historical gaps.
- Publication/intake and independent selected retrieval work against genuine inputs
  from a fresh authorised checkout, without acquisition-machine discovery.
- Preservation records establish retained byte and acquisition-identity equivalence
  before redundant copies are retired. Changed packaging does not imply new source
  acquisition or strengthened source claims.
- Integrity failures, denied/missing access and unavailable required inputs produce
  explicit safe failures. Synthetic tests can exercise archive mechanics, but cannot
  establish genuine collection acceptance.
- Applicable full checks pass when collections, governing bindings or verifiers
  change. Record reviewed code revisions, exact collections, commands, outcomes,
  skips and limitations. Missing mandatory inputs remain blocked. Existing known
  historical gaps are not a requirement to acquire replacement evidence.
- Archive guidance, concise README and maintained metadata agree. Catalogue and
  test consumers can use the same explicit contract without runtime credentials.

Keep transport validation, recording replay, derived-input rebuilds and complete
source-body verification distinct. A native-table rebuild cannot certify missing
original responses. Complete genuine ThaiWater verification must precede negative
provenance regressions. Historical France checks require their retained historical
native input, not the current catalogue table.

## Starting points

The existing `maintenance/evidence/` index and acquisition tools already provide
exact release selection, integrity-gated downloads and bounded safe extraction.
Three published collections cover Bosnia, France and ThaiWater; France also serves
HydroPortail. The inventory covers 14 providers, with ten lacking shared collection
bindings at discovery. Publication is currently described in prose; other material
is spread across tests, research, maintenance inputs and native tables.

Inspect `maintenance/evidence/index.json`, `maintenance/evidence/acquisition.py`,
`docs/maintenance/evidence.md`, the evidence repository README and reviewed
verification entry point, and their tests. Earlier deliveries #422, #423 and #424
remain valid historical foundations. The Program supersedes their target policy
of maintaining some source recordings in code Git and relying on implicit
organisation-wide access. Updating those expressly superseded arrangements is
planned work, not a newly discovered unrelated bug.

## Stop and report

If implementation discovers a bug or error, including misinformation in provider
or other documentation, stop implementation. Open a GitHub issue labelled `bug`,
assign it to CooperBigFoot and report the blocker without restricted details.
Do not fix it incidentally or continue around it. Wait for the owner to fix it and
explicitly authorise resumption.

Do not change source claims incidentally, eliminate historical coverage gaps,
rewrite Git history, change repository visibility or redistribute restricted
material publicly. Preserve source vocabulary, unknowns, nulls, missing rows and
source failures. Publication of this vision does not authorise implementation.
