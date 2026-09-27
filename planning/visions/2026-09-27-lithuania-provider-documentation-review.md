# Lithuania provider documentation review

## Outcome and delivery

Update the existing [Lithuania provider documentation PR #293](https://github.com/RivRetrieve/RivRetrieve/pull/293), on `docs/provider-lithuania`, targeting `main`. Deliver a revised `docs/providers/lt_lhmt.md`, its appropriate documentation-index entry, and an accurate PR description. Do not replace it with a new implementation PR.

The original page predates the API and behavior updates incorporated through PR #300. Migrate the documentation itself to the current implementation. Readers need only current behavior, not a migration guide, old API comparisons, or a history of repairs.

The human will review PR #293 and provide feedback before the implementing agent concludes. Address that feedback and wait for the human gate. Do not approve or merge PR #293 on the human's behalf. Publication of this vision does not authorize its implementation automatically.

## Reader experience

Follow `docs/AGENTS.md` as mandatory writing guidance and use the merged pages in `docs/providers/` as strong references. Keep table entries and terminology consistent with those pages while preserving real provider differences. Do not expand this work into rewriting other provider pages.

Explain Lithuania's national hydrological context, who measures observations, who publishes them, and what RivRetrieve provides. Distinguish an agency's publication role from measurement ownership when the evidence requires it. Keep the page an approachable introduction for hydrologists with basic Python knowledge, not a mechanical API reference. Link to the usage guide for general API instruction.

Preserve Thiago's useful prose, research, and structure where accurate. Correct unsupported or obsolete material rather than preserving it for its own sake. Prefer one short practical retrieval, with enough context, actual output, and explanation for the reader to interpret it. Retain the original `nemajunu-vms` example station if live checks support it. Use readable code spacing and current public selection filters.

Include source-specific conditions that affect use: supported quantities and statistics, source and returned units, time labels and known temporal support, availability and publication delays, data status, access limits, and terms and citation. Include only supported claims. Keep verification mechanics and detailed evidence in maintainer records rather than crowding the introduction.

## Verification requirements

Check every factual claim against current code, the packaged catalogue, or authoritative sources, choosing evidence appropriate to the claim. Recheck the original page's national-network description, 97-station count, daily-mean interpretation, stage conversion, historical coverage from 2000, publication delay, separate measured feed, UTC wording, numeric rate limits, licence, attribution requirements, and citation claims. These are subjects to verify, not facts accepted solely because the old page states them.

Execute every final Python snippet through the current public API in the project's `uv` environment. Use live retrieval where applicable, explicitly avoiding cached results when claiming a fresh source check. Execute snippets in their documented order and with their stated prerequisites. Verify displayed outputs, row counts, issues, units, time interpretation, and every promised behavior. Do not silently change the verification script into an easier example than the page contains.

Retain reproducible commands, tested revision, verification dates, exact relevant outputs, source references, and material limitations. Distinguish fresh live retrieval, catalogue inspection, recorded-response replay, and ordinary tests. Recorded tests alone do not establish current live operation. Never describe an unexecuted or blocked example as verified. If a source cannot be reached, report the limitation rather than claiming a fresh check or silently substituting old evidence.

A catalogue entry does not guarantee values for every quantity or requested period. Keep published nulls, absent observations, and failed requests distinct. Preserve source vocabulary and unknowns. A UTC date label does not alone establish the daily averaging boundaries. Do not infer approval or quality from a returned number or lack of issues.

The PR description must accurately summarize the final changes and verification, including the distinction between live and recorded checks and any remaining limitations. Remove obsolete verification claims. Obtain independent review of the complete documentation diff and its evidence before presenting the PR for human review.

## Repository evidence from discovery

Discovery inspected PR #293, `docs/AGENTS.md`, merged Japan, Norway and Hub'Eau pages, Lithuania provider code, and the packaged catalogue. Treat these as starting points and recheck the implementation revision used for delivery.

- The existing PR changes `docs/providers/lt_lhmt.md` and `docs/README.md` and targets `main`.
- Current catalogue inspection found 97 stations. Public `rr.find(provider="lt_lhmt", station="nemajunu-vms", quantity="discharge", frequency="daily", statistic="mean")` followed by `rr.series(...)` found one catalogue candidate. This was catalogue browsing, not live observation verification.
- Provider code lives in `src/rivretrieve/_internal/providers/lt_lhmt/`. The historical route requests one station-month and co-publishes `waterDischarge` and `waterLevel`.
- The inspected mappings describe daily means and UTC labels. The native stage unit is centimetres. Confirm returned units through the full public path rather than inferring them from the native configuration alone.
- No live observation retrieval or fresh authoritative-source verification was completed during discovery. No production defect was established by that discovery.

## Mandatory defect stop

If implementation finds a production-code defect, stop documentation implementation. Open a GitHub issue labelled `bug`, assign it to `CooperBigFoot`, and include reproducible steps, expected and actual behavior, the tested revision, and supporting evidence. [Issue #305](https://github.com/RivRetrieve/RivRetrieve/issues/305) and [issue #324](https://github.com/RivRetrieve/RivRetrieve/issues/324) are examples of the required evidence and distinction between failure paths.

Do not fix production code. Do not conceal the defect by weakening documentation claims, switching to an easier example, bypassing the public path, or disguising a failed verification. Preserve partial work and evidence, identify the blocking issue, and wait until the human reports that the defect is repaired. Then reverify the affected path and final examples against the repaired implementation before continuing. Distinguish a genuine code defect from an incorrect verification assumption or an upstream failure, using evidence rather than speculation.

## Scope and parallel work

This is a documentation review, not a provider feature, catalogue rebuild, API redesign, or production repair. Supporting verification artifacts are appropriate; unrelated refactoring and broad documentation cleanup are excluded.

Poland PR #291 is being worked on in parallel by other agents. Isolate Lithuania changes and preserve all unrelated branches, worktrees, and uncommitted state. Account for concurrent `main` updates when validating current behavior and the index entry. Any additional checkout must be under the repository's `.worktrees/` hierarchy. Use project-native `uv` commands for execution and tests.

Success means PR #293 contains clear, consistent, current Lithuania documentation, every final snippet works as advertised with honest verification evidence, its description matches the delivered work, and the human review and feedback gate has been honored. The implementation agent must leave approval and merge to the human.
