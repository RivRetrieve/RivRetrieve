# Thailand provider documentation review

## Outcome

Update the existing [Thailand provider documentation PR #297](https://github.com/RivRetrieve/RivRetrieve/pull/297), on `docs/provider-thailand` targeting `main`, with an accurate, readable provider page and PR description. Preserve Thiago’s useful work wherever it remains supported.

The original page predates the public API and provider behavior incorporated through [PR #300](https://github.com/RivRetrieve/RivRetrieve/pull/300). Bring the documentation to the current implementation at execution time. This is a migration of the documentation, not a migration guide for readers. Describe only current behavior; there are no users requiring backward-looking guidance.

This is a standalone vision, not a Program Effort. Publishing this vision does not authorize approval or merge of PR #297.

## Reader and editorial direction

Follow `docs/AGENTS.md` as mandatory writing guidance. The audience is an educated hydrology reader with basic Python knowledge. Use the merged pages in `docs/providers/` as strong references for structure, table entries, explanatory depth and examples. The Norway, Japan, France, Switzerland, Canada, Brazil and USGS pages provide established patterns, with legitimate provider-specific differences.

Explain Thailand’s national hydrological context, who measures and publishes the data, and what RivRetrieve provides. Distinguish ThaiWater’s publication role, HII’s role and source-attributed supplying agencies from claims about ownership, sensor operation or who physically made a measurement. Establish those relationships from evidence rather than inferring them from an agency label.

Keep the page a provider introduction, not a mechanical API reference. Use one practical retrieval example with readable output and explain what the reader should notice. Introduce additional snippets only when a source-specific point genuinely needs them. Explain units, time, availability, data status and terms where they affect use. Link to `docs/usage.md` for general API instructions. Keep implementation and verification mechanics in maintainer records rather than expanding the introduction.

Use consistent names and table labels for equivalent concepts across provider pages. Adapt the Thailand page to the established conventions; do not turn this task into a cleanup of the other providers. Keep the documentation-index entry accurate. Preserve original prose and agency information where correct, revising or removing claims that cannot be supported.

## Repository findings to investigate and carry forward

Discovery inspected PR #297, current ThaiWater code, packaged series metadata, provider port notes and merged provider pages. It did not perform fresh authoritative-source checks or live observation retrieval. These findings direct verification; they do not replace it:

- The original example uses obsolete `product=` selection and station selection through `pick`. Replace it with the current public selection and retrieval API, using `quantity` and other established physical filters only where appropriate. Start with the original stage example at station `1` for June 1–3, 2024 if it remains suitable. Preserve a useful example rather than preserving obsolete syntax.
- Current ThaiWater configuration keeps frequency, statistic and temporal support unestablished. Ten-minute spacing observed in selected responses does not establish a published sampling frequency, an instantaneous statistic, an averaging interval or continuous coverage.
- The packaged series metadata establishes stage’s vertical reference as `above_sea_level` from source unit labels. Its specific vertical datum is unestablished. Stage is returned in metres and discharge in cubic metres per second without numerical scaling.
- Source timestamps have no established time zone. Current configuration preserves source clock labels with `time_zone="unknown"`. Do not infer UTC or Bangkok time from location.
- The configured 365-inclusive-source-date window is a conservative working request size, not a measured API maximum. Engine padding and splitting affect actual requests. The draft’s claim that the API answers at most 365 days must not be repeated as an established source limit.
- Port notes describe 825 catalogue stations and 1,650 selectable station/quantity pairs, with positive availability evidence for 813 stage and 283 discharge pairs. Unknown availability remains selectable. Recompute relevant counts from the current packaged catalogue; do not turn positive evidence into guaranteed observations or complete period coverage. Detailed catalogue-building methods belong in maintainer evidence.
- The draft’s agency counts, 54 contributing agencies, institutional relationships and blanket assertion that no licence or citation request is published need verification. Not finding a licence does not prove that none exists. Describe the evidence and uncertainty precisely without inventing reuse permission.

Relevant implementation and evidence entry points include `src/rivretrieve/_internal/providers/th_thaiwater/`, its packaged `catalogue/`, `docs/provider_ports/th_thaiwater.md`, and the source evidence referenced by those files. Port notes are leads, not authority over current code or source evidence. Current public examples use `rr.find(...)`, `rr.fetch(...)`, and `result.data` and `result.issues` inspection.

## Verification and acceptance evidence

Check every factual claim against current code, the packaged catalogue or authoritative sources, according to the kind of claim. Verify institutional responsibilities, source meanings and terms against authoritative publications. Keep unknowns explicit and qualify claims whose authoritative evidence cannot be freshly checked. Do not claim fresh verification from retained material.

Execute every final Python snippet exactly as documented through the current public API in the repository’s `uv` environment. Use live retrieval where applicable, rather than treating parser tests or direct source requests as proof that the public example works. Make prerequisites and any shared-session ordering explicit. Verify displayed values, row counts, units, time labels, issues and every promised behavior. Account for source revisions without presenting unverified output as illustrative fact.

Use a source-requesting cache mode for live verification. Retain sufficient reproducible maintainer evidence: tested code revision, commands, dates, exact snippet outputs, source checks and their limitations. Clearly distinguish fresh live requests, recorded replay tests, authored test cases and catalogue inspection. Keep secrets and private source corpora out of published evidence. A successful example establishes its station, quantity and period, not service-wide availability.

Check null observations, absent rows and request failures as distinct outcomes where the page discusses them. Neither a returned number nor the absence of issues establishes source quality approval. Do not invent cadence, statistical meaning, quality interpretation, time zones, temporal support, historical coverage or licensing rights.

Review the complete final page against `docs/AGENTS.md`, merged provider conventions and its retained evidence. Obtain independent review of the documentation and verification claims. The PR description must describe the actual revised content, checks performed and remaining limitations, without retaining obsolete API claims or overstating validation. Do not report completion while examples or promised behavior remain unverified.

## Mandatory code-defect stop gate

If implementation or verification reveals a code defect, stop this documentation implementation. Open a GitHub issue labelled `bug` and assign it to `CooperBigFoot`. Follow the evidence quality of [issue #305](https://github.com/RivRetrieve/RivRetrieve/issues/305) and [issue #324](https://github.com/RivRetrieve/RivRetrieve/issues/324).

Include the tested revision and environment, exact reproduction commands or script, expected and actual behavior, request and response evidence where safe, the effect on this documentation review, and preserved evidence locations. Distinguish a demonstrated code defect from an upstream outage, legitimate missing observations or an incorrect verification assumption. Capture the minimum reproduction needed to establish the defect; do not continue unrelated implementation after establishing it.

Do not repair production code. Do not change examples, omit promised behavior or rewrite documentation to conceal or work around the defect. Preserve partial work and report the blocker. Wait until the user explicitly reports the repair, then reverify the affected behavior and final examples before continuing. A closed issue or newly merged code alone does not release this wait gate.

Production code changes and catalogue regeneration are outside this documentation task. Supporting verification artifacts may be added where useful, without expanding into a provider redesign or repository-wide cleanup.

## Delivery and human review gate

Deliver revised documentation and verification evidence through the existing PR #297, with an accurate PR description. Do not replace it with a new implementation PR. Preserve unrelated work and the original contribution history using normal repository practices.

The user reviews this PR before merge and supplies feedback before the implementing agent concludes. After updating the PR and completing independent checks, report it as awaiting human review and wait for that feedback. Address the feedback and reverify affected examples and claims before reporting final completion. The agent must not approve or merge PR #297 on the user’s behalf. Generic implementation workflow merge authority does not override this gate.

Success is a current-only, source-faithful Thailand page whose snippets actually work as advertised, whose factual claims and displayed outputs have inspectable evidence, whose PR description accurately reflects the work, and whose final state has passed the user’s review. Vision publication is separate from implementation and does not satisfy this delivery gate.
