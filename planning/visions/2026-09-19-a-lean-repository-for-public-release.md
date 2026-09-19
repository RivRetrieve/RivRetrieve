# A lean repository for public release

## Outcome

Prepare RivRetrieve's default branch and package distributions for a public repository and PyPI release. A new reader should see maintained software, useful contributor guidance, current documentation, and necessary evidence, not the residue of a personal AI execution workflow. Prefer the leanest maintainable result over a quick cosmetic cleanup. There is no time-driven reason to retain obsolete tests or artifacts.

This is a standalone vision derived from the maintainer's release-cleanup discussion. It does not acquire Program or Effort provenance from the issues mentioned below. The target branch is `main`.

Lean does not mean reduced functionality, weakened source fidelity, or deleting difficult tests. Preserve current public behaviour, catalogue reproducibility, meaningful regression coverage, and history. GitHub tree contents and wheel/source-distribution contents are separate surfaces; verify both. This work prepares release artifacts but does not itself authorize changing repository visibility, publishing to PyPI, or changing provider support.

## Settled boundaries

- Keep `AGENTS.md` and `CLAUDE.md` as shared contributor guidance. AI-assisted development is not something to hide.
- Delete `.pce/` entirely. Its repository contract belongs to a retired workflow, not the current PCE skills. Preserve any still-useful general contributor facts without recreating that machinery or carrying machine-specific notes forward.
- Keep only durable visions under tracked `planning/`. Keep existing vision paths referenced by issues stable. Remove execution plans, reviews, event streams, draft PR bodies, and similar execution records from the tracked current tree. Do not delete a genuine vision merely because it lives in an older execution directory: preserve its identity, or establish that an existing vision is the complete durable successor before retiring a duplicate. Do not add a replacement tracked execution ledger.
- Allow `planning/visions/*.md` explicitly in ignore rules. Current PCE requires these visions to be tracked and merged on the target branch. Local execution scratch need not be tracked. Ignore rules do not untrack existing files.
- Remove the tracked `scratchpad/.gitkeep`; local scratch space may remain ignored.
- Keep maintained `scripts/`, including reference generation and ANA inventory acquisition. A script is not noise merely because users do not import it.
- Remove `reference/`, currently only the retired South African observation implementation, old tests, and fixtures. No runtime path imports it. Update obsolete archive-presence tests, configuration exclusions, and current statements in `CONTEXT.md`; do not preserve obsolete tests to justify preserving the archive. Its source remains recoverable in Git history (the archive records original source commit `51ce7d87da140568ee4145cd41fef0ac9f39fc45`).
- Preserve Git history. The requirement is a clean current default branch, not erasing historical visibility. No history rewrite.
- Documentation hosting and conversion to Sphinx/MkDocs/Read the Docs are out of scope. Do not introduce or re-enable hosted CI. Local validation remains required.

## Documentation: keep the present, retire delivery history

Historical-document removal was explicitly approved. Keep the recent reader-oriented rewrite: README, documentation index, usage, architecture, API reference, CAMELS example, coverage map and its generator. The substantive rewrite and follow-up reviews occurred September 17–19, 2026; inspect current history because other documentation work can land during implementation. A recent mechanical edit alone does not turn a historical report into current documentation.

Remove these approved historical groups and repair navigation:

- `docs/milestones/`, `docs/milestone-tracker.md`, `docs/milestone-tracker-critique.md`, and `docs/v1-conformance.md`.
- `docs/design/provider-redesign.md`, `docs/design/provider-redesign-review.md`, and `docs/design/legacy-window-rendering-contract.md`.
- `docs/certifications/effort-17-ca-hydat-v7.md` and `docs/certifications/effort-17-ca-hydat-v8.md`.
- `docs/discoveries.md`. Do not transplant its historical tables or wording just to satisfy tests.

Do not delete `docs/design/` indiscriminately: `observation-store-layout.md` remains a normative store specification. Keep `product_dictionary.md`, `catalogue-evidence.md`, `catalogue-absence.md`, and the current maintenance/evidence content of `catalogue-provenance.md`. Some catalogue documentation URLs are used in packaged descriptors.

Provider-port notes require content-level treatment, not wholesale deletion. Provider-specific documentation ownership remains with the colleague. Limit changes there to necessary path/link repairs and factual alignment with the retained evidence. Do not rewrite provider narratives or discard useful source facts under the label of cleanup. Additional ambiguous documentation removals require specific permission rather than an assumption that all old files are disposable. Historical vision text is an audit record, not prose to rewrite to describe today's tree.

## Tests should protect maintained contracts, not freeze old prose

Delete tests whose only purpose is preserving historical files, copied documentation paragraphs, editorial wording, or retired workflow structure. An existing test is not itself a reason to retain its subject. Do not replace these checks elsewhere merely to keep a test count unchanged.

The investigation established these concrete cases:

- Delete `tests/test_discovery_d11_window_cap.py` with the discovery log. Three tests parse historical Markdown and its wording. The fourth combines old unbounded window arithmetic with a required sentence; it does not exercise the current ThaiWater capped-window configuration. No replacement is needed: `test_internal_driver.py` checks actual driver padding, `test_internal_window_planning.py` checks rendering, and `test_thaiwater_source_windows.py` exercises current `rr.fetch` splitting with recorded transport and cache modes.
- In `test_th_thaiwater_generate_catalogue.py`, remove documentation reads from `test_unknown_temporal_support_uses_the_documented_unknown_catalogue_vocabulary`. Existing catalogue checks already cover the generated unknown fields. Its distinct assertion that runtime product semantics are `UnknownTemporalSupport` can join the existing behavioural test; no document wording contract is needed.
- Delete `test_domain_context.py`'s copied-glossary tests and `test_legacy_observation_reference_m7_s4.py`'s archive inventory/README tests.
- Remove archive-only checks in `test_provider_architecture_contracts.py`, `test_cz_chmi_hourly_semantics_regression.py`, and the historically named `test_catalogue_only_br_ana_jp_mlit_no_nve_th_thaiwater.py`. Retain meaningful current provider and transport-boundary tests. Retire `test_no_implementation_baselines.py` when its sole retired-tree subject is removed.
- Remove exact prose checks in catalogue-origin tests and documentation assertions appended to otherwise useful Bosnia/certification tests. Retain digest, publisher-field, source-identity, URL-binding, acceptance, and refusal checks that protect maintained contracts.
- Remove editorial layout/wording assertions, such as requiring architecture links in a particular form, policing removed ADR mentions, or snapshotting coverage-map prose. Retain required attribution in the actual documentation.

Useful documentation checks remain: runnable examples, local links, Python syntax, generated API-reference drift, and advertised catalogue counts against actual catalogue facts. These protect reader-facing behaviour and consistency rather than historical wording. Remove redundant example checks that only encode an old missing-fixture situation when meaningful executable coverage already exists.

Provider-specific tests are not inherently legacy. Keep tests of current parser behaviour, request rendering, cache modes, catalogue semantics, and real source failures. A Markdown extension is not proof of disposable prose: the Brazil daily-source comparison report is parsed as a live source-evidence input and must be assessed accordingly. When a cleanup reveals a genuine bug, follow the repository's regression-before-fix rule using the real failing path; do not manufacture a failing test to justify an editorial deletion.

## Research: separate maintained evidence from completed investigation

At discovery, `research/` held 550 tracked files, roughly 55 MB. It is already excluded from source distributions. There is no direct runtime Python dependency on its paths, but tests, catalogue rebuilding, and provenance verification consume it. Wholesale deletion would break maintained capabilities.

The intended result is no mixed historical investigation directory in the public tree. Retain the minimum necessary evidence and verification tools in maintained locations; remove redundant investigations and bulk. Choose the layout from the actual maintenance responsibilities, not ticket identity. Preserve exact evidence bytes and provenance meaning when relocating them. Update consumers, manifests, rebuild commands, and documentation links together.

Known live inputs include:

- Bosnia `baseline_workbook_access.json`, France `governing_evidence.json.xz`, and Thailand `governing_station_product_evidence.csv`, with associated current summaries/publication evidence.
- All 20 Brazil inventory files at the inspected revision, including archived `*.py.txt` scripts: the capture manifest identifies them as supporting evidence by digest, and production capture materialization verifies their identities. Do not discard them based on their appearance. Failed acquisition attempts and successful retries are distinct evidence.
- Genuine source fixtures and retained verifiers that reject corrupted identity, invented availability, missing bodies, wrong metrics/units/zones, and HTTP-200 source error bodies. Current research tests sometimes copy or scan entire historical trees; separate the maintained contracts from that accidental breadth.

Candidates for removal include completed FINDINGS/HANDOFF/UNRESOLVED/STATION_TABLE/EVIDENCE_INDEX narratives, route-decision histories, obsolete acquisition/probe/table builders, and superseded population accounts. France's old station-product table and two large Sandre recordings account for much of the bulk. Bosnia horizon surveys and Thailand metadata/graph/churn surveys also need dependency separation. Preserve selected real source cases where they support current regressions; do not retain entire surveys merely because an old verifier reads them.

Audit research-verifier tests by maintained purpose. Keep or consolidate checks that protect retained catalogue evidence and real source behaviour. Retire tests devoted solely to retired tooling. Do not turn historical receipts without bodies into claims of source proof, weaken digest/identity checks to make relocation pass, or substitute invented payloads for source recordings. Existing private source corpora stay private; missing bodies do not authorize network reacquisition, publication, or reopening provider terms decisions.

## Branches, worktrees, and ongoing work

You are not working alone. Another agent is implementing drainage-area metadata in PR #254. Use a separate branch and worktree. Do not modify, reset, or remove that agent’s work. Coordinate overlapping changes to packaging, catalogue evidence, and tests. Recheck active branches and worktrees before cleanup.

The intended steady state is `main` plus branches being actively worked on, locally and on GitHub. A clean worktree does not mean destroying ignored credentials, local evidence, or unrelated work. Reinspect live branches, PRs, issues, commits, and all local worktree contents before acting. A squash-merged branch can contain commits not ancestral to `main`; lack of ancestry is not proof of undelivered functionality. Ordinary clean status also does not prove a worktree contains no unique ignored files.

Protect ongoing work. At authoring, this includes South Africa's `vision/effort-17-za-dws` and draft PR #210, usage PR #252, drainage-area PR #254, and CAMELS documentation PR #255. This is a time-sensitive inventory, not an exhaustive or permanent allowlist. The maintainer explicitly identifies South Africa as ongoing despite issue #212's older "Deferred, not delivered" text. Do not archive that effort or close its draft PR as part of cleanup. Removing the retired reference code is distinct from removing replacement work or evidence it needs.

Inactive branch/worktree retirement must preserve unique historical commits and uncommitted/untracked source, notes, receipts, and evidence. Use a verified archive outside the active checkout when needed, rather than archival branches cluttering GitHub. Preserve privacy and do not publish that archive. Do not preserve build caches as evidence. Old source-terms, audit, reconciliation, attempt, and backup branches require this check even when their associated work was delivered.

This vision explicitly scopes cleanup of pre-existing inactive worktrees, not just checkouts created by its implementation. Do not treat this as permission to remove active, ambiguously owned, or unrecoverable state. Establish inactivity and recovery first; preserve and report uncertainty rather than guessing. Prunable Git registrations can still correspond to directories containing local files. Do not use blanket `git clean`, force deletion, or branch-age heuristics. Preserve history reachable only through old branch tips before removing those names. Reconcile the cleanup with current PCE preservation rules and stop for authority if a tool/workflow forbids an otherwise proposed removal.

## Evidence of completion

- `main` contains current software/documentation, contributor guidance, durable linked visions, and necessary maintenance evidence, without the approved legacy trees and execution records.
- Vision paths used by existing issues remain valid. Current documentation links and catalogue provenance references work after relocation; removed historical documents are not resurrected by tests.
- A fresh checkout can run the retained local test and static-check workflow and perform documented offline catalogue verification from the retained public inputs. Private evidence requirements remain explicit rather than silently bypassed.
- Useful behaviour tests pass. Removed tests have identifiable obsolete or duplicate purposes; no provider feature or meaningful source-integrity protection is lost to reach green status.
- Inspect actual built wheel and source archive contents, including a wheel built from the source archive. Required installed data and imports work; planning, execution records, obsolete research, credentials, and local-only artifacts do not leak into distributions. Do not infer contents solely from ignore rules or exclusion configuration.
- Local and remote branch/worktree cleanup reports distinguish retained active work, retired delivered work, and any preserved uncertainty. Unique history and local evidence are recoverable before deletion. Do not declare full cleanup while unresolved unsafe removals remain.

Deliver the cleanup through normal reviewed PRs and local validation. This vision authorizes implementation of the settled cleanup when invoked through the implementation workflow; publication of the vision alone does not start it.
