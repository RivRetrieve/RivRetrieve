# French provider documentation review

## Outcome

Revise the French provider documentation in [PR #264](https://github.com/RivRetrieve/RivRetrieve/pull/264), update its PR description, and leave it open for Nicolas Lazaro's review. The page must accurately describe the current repository and public API, with executable examples whose outputs support the accompanying explanations. This is a standalone documentation review, not a Program Effort.

The repository is private and has no users requiring migration guidance. Describe current behavior directly. Do not add a migration guide, historical API comparison, or narrative about the review process to the reader-facing page.

## Strong reference and writing requirements

**`docs/providers/ch_foen.md`, as merged in [PR #289](https://github.com/RivRetrieve/RivRetrieve/pull/289), is the strong model for this work.** Read the actual page, not only its PR description. Follow its explanatory style, national and provider context, readable current-API examples, verified outputs, and careful qualifications of source facts. Its useful pattern includes a practical example, explanation of the returned data, source and agency context, available quantities and alternatives, time, status, terms, and dated references.

Preserve Thiago's French-specific structure and useful substance. Improve consistency, clarity, and correctness without replacing the page with a mechanical API reference or copying Swiss-specific behavior. Explain who measures and publishes the French data, the country's hydrological context where relevant, and what RivRetrieve actually provides.

Follow `docs/AGENTS.md` as mandatory writing guidance. Write for an educated hydrology reader with basic Python knowledge. Introduce unfamiliar software concepts through their practical meaning. Keep exact API names, readable snippets with breathing room, source vocabulary, units, uncertainty, and qualifications.

## Scope and repository evidence

The existing PR targets `main` from `docs/provider-france` and introduces `docs/providers/fr_hubeau.md` plus its documentation-index link. Reuse and update that PR and preserve its existing history. Retain the Swiss index entry when integrating current main. Update the PR description to describe the final changes and verification accurately, without stale success claims. Focused example regression tests are within scope; production changes and unrelated provider rewrites are not.

At discovery, main was `4f1b08f3258216a05f6b2a9738f6b29d3b1f2ee6`. Reinspect current main before implementing; this SHA is context, not a frozen implementation target.

The French page's opening snippet currently calls `rr.find(provider="fr_hubeau", product="discharge_daily_mean")`. Current `find` and `pick` signatures in `src/rivretrieve/_internal/discovery.py` use physical filters such as `quantity`, `frequency`, and `statistic`, together with source alternatives such as `variant`; they do not accept `product`. Derive correct French selections from current catalogue and implementation evidence rather than mechanically substituting argument names. The product table, availability counts, time explanation, and status claims also need substantive verification.

Inspect `src/rivretrieve/_internal/providers/fr_hubeau/`, its packaged catalogue, public API behavior, and relevant tests. Check each factual claim, including source routes, geographical coverage, stations versus sites, available quantities and alternatives, units and conversions, availability and historical reach, timestamp and temporal-support semantics, source status, credentials, terms, and citation obligations. Distinguish catalogue candidates from observed availability and preserve unknown facts. Null values, absent rows, and failed requests remain distinct.

[PR #307](https://github.com/RivRetrieve/RivRetrieve/pull/307) established Swiss public historical access; it was not the general discovery-API change. It explains part of the Swiss review history but does not establish French behavior. Current code, catalogue evidence, and authoritative French sources govern French claims.

## Verification and evidence of success

Execute every final Python snippet through the project's `uv` environment against the current implementation. Respect any documented shared-session setup. Check that selections identify the intended series and that retrievals produce the behavior and outputs described. Use real public retrieval with cache bypass where applicable to establish source access; recorded or mocked tests alone do not establish live availability.

Show useful, actually observed output where it helps readers understand the examples. Verify every displayed value, count, unit, time label, and issue statement. Explain relevant conditions and gaps without implying completeness or immutable source values. If upstream values can change, qualify the example accordingly. Do not fabricate or silently substitute output.

Recheck authoritative external references for institutional context, source semantics, quotations, terms, and citation. Preserve French quotations accurately and identify translations. Update checked dates only for sources actually checked. Report inaccessible sources or uncertain claims rather than treating them as verified.

Use focused regression coverage where appropriate, following the Swiss page-example test as a reference. Keep live evidence distinct from recorded regression evidence. Retain inspectable commands, outputs, tested revision, and external-source checks outside reader-facing prose, and summarize the actual results in the PR. Passing tests alone do not establish that prose is true.

Success means the revised page and PR description are consistent with current behavior; all examples have been executed and their promised outputs checked; factual claims have evidence or explicit qualifications; and the PR is ready for human prose review. It does not mean the human review gate has passed.

## Mandatory stop gates

### Code defect

If verification exposes a repository defect, stop the documentation work. Open a GitHub bug report, apply the `bug` label, and assign it to **CooperBigFoot** (Nicolas Lazaro). Include a reproducible public-path example, expected and actual behavior, the tested revision, relevant source evidence, and the effect on PR #264. Distinguish a software defect from an upstream outage or genuinely absent data; report uncertainty honestly.

[Issue #305](https://github.com/RivRetrieve/RivRetrieve/issues/305) is the precedent: a defect discovered during Swiss documentation review was reported separately, repaired, and then the documentation review resumed. Do not repair production code within this work or rewrite claims to conceal the defect. Preserve partial changes and evidence, report the blocker, and wait for Nicolas to report that it is solved. Then verify the affected path again before continuing.

An obsolete documentation example is a documentation correction, not itself a reason to restore the old API or open a production defect.

### Human review

Push the verified documentation revisions and update PR #264, then stop for Nicolas's review. He will assess wording and clarity and provide feedback. Incorporate that feedback when requested, reverify affected examples and claims, and wait for his direction before concluding. Do not approve or merge PR #264 on his behalf. Generic implementation-workflow instructions do not supersede this explicit human gate.

Publishing this vision authorizes only its documentation-publication PR to merge. It does not authorize implementation to begin automatically or authorize the French provider PR to merge.
