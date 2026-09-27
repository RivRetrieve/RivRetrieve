# Canada provider documentation review

## Outcome

Update the existing [Canada provider documentation PR #274](https://github.com/RivRetrieve/RivRetrieve/pull/274), including its description, so that every example and explanation describes the current repository accurately. The PR was written before the API and behavior changes incorporated through PR #300. This is a migration of the documentation itself, not a migration guide. There are no users who need backward-looking guidance.

The implementation deliverable is the revised existing PR, ready for Nicolas (`CooperBigFoot`) to review and give feedback. Preserve Thiago’s useful work and authorship where possible. Do not replace the delivery with a new Canada implementation PR.

This is a standalone vision. PR #274 targets `main` and uses branch `docs/provider-canada`. Recheck current Git and GitHub evidence before starting. Use the current implementation on the target branch, not PR #300 as a frozen specification.

## Reader and editorial direction

Read and follow `docs/AGENTS.md` as mandatory writing guidance. Use the merged pages in `docs/providers/` as strong references, especially their practical examples, output explanations, provider context, and source-specific qualifications. These include Brazil, Switzerland, Japan, USGS, Hub’Eau, and HydroPortail.

Write for an educated hydrology reader with basic Python knowledge. Explain Canada’s national hydrometric context, who measures the data, who publishes them, and what RivRetrieve provides. Establish the responsibilities of the Water Survey of Canada, Environment and Climate Change Canada, and provincial, territorial, and other partners from authoritative sources. Do not turn the page into a mechanical API reference.

Keep the provider-page pattern: a useful summary table, one main practical retrieval example with verified output, national context, supported quantities, source-specific conditions, terms and citation, and sources. Additional snippets should serve a concrete reader need. Link to the usage guide for general API instruction. Give code blocks breathing room and explain what the displayed output means.

Preserve useful existing prose when it remains correct. Revise or remove unsupported claims rather than preserving wording at the expense of accuracy. Explain only current behavior. Keep migration narratives, catalogue verification methods, receipt internals, and implementation machinery out of the provider introduction unless needed to interpret the data.

## Scope and current repository facts

The principal file is `docs/providers/ca_eccc.md`. Incorporate its link into `docs/README.md` without losing the provider links already merged there. Supporting verification records and focused documentation validation are in scope. Unrelated provider rewrites, catalogue regeneration, new products, new access routes, production-code changes, and general API redesign are out of scope.

The discovery inspection established these implementation facts. Reverify them against the revision used for delivery:

- Canada retrieves HYDAT through an explicitly downloaded and compiled national archive. Near-real-time services are national context, not additional implementation scope.
- The provider has daily mean discharge and stage source series, backed by `DLY_FLOWS` and `DLY_LEVELS`. Returned units are m³/s and m.
- Public examples should use current `rr.find` quantity, frequency, and statistic filters, rather than the PR’s outdated product-based selection. Use `rr.pick` only when current selection and the example require it.
- `rr.download("ca_eccc")` prepares the bulk store explicitly. Retrieval does not silently start a national download. Without a store, the documented contract is an empty result with an issue.
- For bulk providers, `cache="bypass"` and `cache="reuse"` read the compiled store. `cache="refresh"` is refused; `download` replaces the store. Do not copy online-provider explanations of bypass into this page.
- Canada’s configured time zone and day definition are unknown. Explain the practical meaning of calendar dates and midnight labels without inferring the clock or interval bounds.
- Native source cells and symbols are retained by the compiler. Verify how source status is exposed through the current public result before explaining it; retention in storage alone is not evidence of a public per-row quality field.

Retain station `05OG008` for the main example if verification supports it. Choose a readable historical period with actual returned data. Changing the station or period for a genuinely suitable example is an editorial choice, but must not conceal a discovered code defect.

Check station counts and catalogue availability against the packaged catalogue. A station listing does not promise discharge or stage for every period. Check record-date claims, archive edition and freshness, credentials, download size and disk requirements, time interpretation, null values, absent records, failures, and source status before describing them. Do not repeat the old approximately 1 GB estimate or fixed publication-lag claims without suitable evidence.

Verify applicable licence and citation requirements from authoritative sources. The original page quotes Water Office redistribution conditions and a generic attribution statement; current repository provenance also contains Water Office citation instructions. Establish which statements apply to the HYDAT route and preserve their qualifications. Do not silently apply terms from another route or invent a prescribed SQLite citation from an MDB-specific statement.

## Verification and acceptance evidence

Every factual claim must be supported by current code, the packaged catalogue, or authoritative sources. Repository evidence and publisher evidence answer different questions: code establishes what RivRetrieve does; authoritative sources establish institutional responsibilities, source meanings, and terms.

Execute every final code snippet through the current public API using the project’s `uv` environment. Run snippets in their documented order with explicit prerequisites. Verify displayed values, formatting, row counts, issues, and all promised behavior. Examples must work as advertised without undocumented internal calls, monkeypatches, fabricated outputs, or substituted fixtures.

For Canada, live end-to-end verification means acquiring the real national archive through the public download-and-compile path and then retrieving observations from that compiled archive. A successful local read of an old store or a recorded-response test is not fresh acquisition evidence. Check available resources before the substantial transfer and compilation. Record the source URL, archive edition, retrieval date, tested revision, commands, and actual outcomes. Do not needlessly repeat a successful national download merely because multiple snippets use the same documented store.

Check all final snippets, including archive preparation and any status inspection. Where the page promises missing-store or cache behavior, verify those conditions without damaging unrelated local data. Keep source null values, absent records, and failed requests distinct. Do not imply that a short successful example proves continuous station history or national coverage.

Keep detailed claim checks, execution logs, and supporting evidence in maintainer records, with a concise reader-facing sources section and verification date. Distinguish freshly checked authoritative pages, fresh live acquisition, local retrieval from that acquisition, retained historical evidence, recorded-response tests, and authored tests. Do not label a test replay as live verification. An inaccessible source or incomplete execution remains an explicit verification blocker, not successful acceptance.

The PR description must describe the actual final changes and verification, remove obsolete claims, identify material limitations, and distinguish live checks from recorded tests. Obtain independent review of the complete final documentation diff and its evidence before presenting it to Nicolas. Reverify affected examples after review changes.

## Mandatory defect stop and resume rule

If the implementation agent discovers a code defect, stop implementation and review work. Open a GitHub issue labelled `bug`, assigned to `CooperBigFoot`, with reproduction steps and evidence. [Issue #305](https://github.com/RivRetrieve/RivRetrieve/issues/305) and [issue #324](https://github.com/RivRetrieve/RivRetrieve/issues/324) show the expected reporting standard.

Include the tested revision and environment, exact reproduction commands or script, actual and expected behavior, source requests and responses where relevant, and preserved evidence locations. Distinguish a confirmed code defect from an upstream outage, unavailable data, or a mistaken verification assumption. A recording-path defect also triggers this rule; ordinary retrieval success does not excuse a broken verification path.

Do not fix production code. Do not bypass the defective path, weaken the example, suppress an issue, substitute a different request to conceal the failure, or change documentation to normalize the defect. Preserve partial work and report the blocker. Wait until Nicolas explicitly reports that the defect is repaired. Then inspect the repaired revision, reverify the reproduction and affected public examples, and only then continue. Issue closure or an observed commit alone is not permission to resume.

## Human gate and completion

Update PR #274 itself and its description. Nicolas must review it and provide feedback before the implementation agent concludes. Address that feedback and reverify affected behavior. Do not treat independent agent review as a substitute for this human gate. If feedback has not arrived, report that the PR is awaiting review and wait.

The implementation agent must never approve or merge PR #274 on Nicolas’s behalf. This restriction overrides any generic implementation workflow that would otherwise merge delivery PRs. Publishing this standalone vision through its own documentation PR does not authorize Canada implementation or delivery merging.

Success is a current, coherent Canada page whose factual claims and exact snippets are verified, an accurate updated existing PR, and Nicolas’s review feedback addressed. Do not claim completion while verification, a reported defect, or the human gate remains outstanding.
