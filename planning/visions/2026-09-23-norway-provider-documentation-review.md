# Norway provider documentation review

## Outcome

Update the existing [Norway provider documentation PR #278](https://github.com/RivRetrieve/RivRetrieve/pull/278), including its description, so that every example and explanation describes the current repository accurately. The PR predates the API and behavior updates incorporated through PR #300. This is a migration of the documentation itself, not a migration guide. There are no users who need backward-looking guidance.

Preserve Thiago’s useful work and authorship where possible. The deliverable is the revised existing PR, ready for Nicolas (`CooperBigFoot`) to review and give feedback, not a replacement implementation PR.

This is a standalone vision. PR #278 targets `main` and uses branch `docs/provider-norway`. Recheck current Git and GitHub evidence before starting. Use the current implementation on the target branch, not PR #300 as a frozen specification.

## Reader and editorial direction

Read and follow `docs/AGENTS.md` as mandatory writing guidance. Use the merged pages in `docs/providers/` as strong references for structure, practical examples, output explanations, national context, and source-specific qualifications. Switzerland, Canada, Hub’Eau, and HydroPortail were inspected during discovery; use the other merged pages where relevant too.

Write for an educated hydrology reader with basic Python knowledge. Explain Norway’s national hydrological context, who measures observations, who publishes them, and what RivRetrieve provides. Establish NVE’s responsibilities and any other measurement producers from authoritative sources rather than assuming that the API publisher produced every observation.

Use a useful summary table, one main practical retrieval example with verified output, national context, supported quantities, source-specific conditions, terms and citation, and sources. Additional snippets should serve a concrete reader need. Link to the usage guide for general API instruction. Give code blocks breathing room and explain what the displayed output means. Do not turn the page into a mechanical API reference.

Preserve existing prose where accurate. Revise unsupported claims rather than preserving wording at the expense of correctness. Describe only current behavior. Keep migration narratives, catalogue verification methods, receipt internals, and implementation machinery out of the introduction unless needed to interpret returned data.

## Scope and repository evidence

The principal file is `docs/providers/no_nve.md`. Integrate its link into `docs/README.md` without disturbing existing provider links. Supporting verification records and focused documentation validation are in scope. Production-code changes, catalogue regeneration, new products or access routes, unrelated provider rewrites, and general API redesign are out of scope.

Discovery established these facts and review targets. Reverify them at the delivery revision:

- The old example selects `product="discharge_daily_mean"`. Current public examples use quantity, frequency, and statistic filters with `rr.find`, and `rr.pick` when narrowing is useful.
- Norway’s current implementation preserves HydAPI version identities. `variant` represents the published version number. Explain the reader-visible consequence of separate source records where it matters, without inventing a preferred or higher-quality version.
- The implementation derives frequency from published resolution and statistic from published method. Internal product names are access coordinates, not sufficient authority for physical claims. Reassess the old three-by-three product grid and its station counts rather than merely changing API names.
- Catalogue evidence is a snapshot. A station listing or an available series does not promise observations for every period, complete historical coverage, or an exhaustive current inventory. Current retrieval acquires version metadata and keeps separately identified outcomes and failures.
- The current series description establishes `+00:00` from explicit UTC timestamp labels. It does not establish temporal support or timestamp anchors merely from resolution. Distinguish the clock of a daily label from established averaging intervals or daily boundaries.
- Verify how source `quality` and `correction` metadata are retained or exposed before describing them. Do not promise public per-row quality fields or infer source judgement.

Retain station `2.605.0` if verification supports a clear practical example. Choose a readable historical period with actual returned observations. A suitable station or period is an editorial choice, but changing one must never conceal a discovered code defect.

Check the packaged station count and all per-quantity or per-resolution counts. Recheck supported quantities, units and conversions, availability, time interpretation, credentials and readiness, key registration, service limits, request splitting, null values, absent rows, failures, source status, licence, and citation. Do not copy the old claims about instant key issuance, manual splitting, availability, or response licence placement without verification. Establish applicable terms from authoritative sources and preserve their qualifications.

## Verification and acceptance evidence

Check every factual claim against current code, the packaged catalogue, or authoritative sources. Code establishes what RivRetrieve does; publisher sources establish institutional responsibilities, source meanings, and terms.

Execute every final code snippet through the current public API using the project’s `uv` environment. Run snippets in their documented order with explicit prerequisites, including credentials. Verify actual output values, formatting, row counts, issues, and every promised behavior. Reader examples must work without undocumented internal calls, monkeypatches, fabricated output, or substituted fixtures.

Use live HydAPI retrieval where applicable. For an online example, `cache="bypass"` can demonstrate fresh source retrieval; verify its actual behavior rather than treating a local cache result as live evidence. Check setup and inspection snippets too. Protect credentials in commands, output, recordings, commits, and PR text. Missing credentials or unavailable services block the affected verification; they do not justify a successful acceptance claim.

Keep dated claim checks, commands, tested revisions, execution logs, and supporting evidence in maintainer records. Keep the reader-facing sources section concise. Distinguish fresh authoritative-source checks, live public-API retrieval, historical evidence, recorded-response tests, and authored tests. A replay is not live verification. Explain that source observations can be revised where displaying dated output, without weakening the requirement that the displayed output match the verified run.

Keep source null values, absent rows, and failed requests distinct. Do not infer approved data quality from an empty issue tuple or continuous history from a short successful request.

Update the PR description to describe the actual final changes, verification, and material limitations. Remove obsolete claims. Obtain independent review of the complete documentation diff and evidence before presenting it to Nicolas. Reverify affected examples after review changes.

## Mandatory defect stop and resume rule

If the implementation agent discovers a code defect, stop implementation and review work. Open a GitHub issue labelled `bug`, assigned to `CooperBigFoot`, with reproduction steps and evidence. [Issue #305](https://github.com/RivRetrieve/RivRetrieve/issues/305) and [issue #324](https://github.com/RivRetrieve/RivRetrieve/issues/324) show the expected reporting standard.

Include the tested revision and environment, exact reproduction commands or script, actual and expected behavior, relevant source requests and responses, and preserved evidence locations. Distinguish a confirmed defect from an upstream outage, unavailable data, or a mistaken verification assumption. A recording-path defect also triggers this rule; ordinary retrieval success does not excuse a broken verification path.

Do not fix production code. Do not bypass the defective path, weaken the example, suppress an issue, substitute another request to conceal the failure, or change documentation to normalize the defect. Preserve partial work and report the blocker. Wait until Nicolas explicitly reports that the defect is repaired. Then inspect the repaired revision, reverify the reproduction and affected public examples, and only then continue. Issue closure or an observed commit alone is not permission to resume.

## Human gate and completion

Update PR #278 itself and its description. Nicolas must review it and provide feedback before the implementation agent concludes. Address that feedback and reverify affected behavior. Independent agent review does not replace the human gate. If feedback has not arrived, report that the PR is awaiting review and wait.

The implementation agent must never approve or merge PR #278 on Nicolas’s behalf. This restriction overrides any generic implementation workflow that would otherwise merge delivery PRs. Publishing this standalone vision through its own documentation PR does not authorize Norway implementation or delivery merging.

Success is a current, coherent Norway page whose factual claims and exact snippets are verified, an accurate updated existing PR, and Nicolas’s review feedback addressed. Do not claim completion while verification, a reported defect, or the human gate remains outstanding.
