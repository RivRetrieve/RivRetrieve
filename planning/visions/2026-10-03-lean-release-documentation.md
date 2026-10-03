# Lean release documentation

## Outcome

Prepare RivRetrieve’s non-provider documentation for its first public release. Replace inherited AI-written explanations with a coherent, lean account of the current package, grounded in its implementation. Existing pages are candidates for rewriting, consolidation or removal, not a structure to preserve automatically.

The primary audience is AI agents helping people use and develop RivRetrieve. The same documentation must remain clear and useful to humans with hydrological knowledge and basic Python skills. This is not permission to write compressed machine-oriented prose, duplicate the API in another format or introduce agent onboarding infrastructure.

The owner has confirmed the scope and writing direction below. This is a standalone documentation vision, not an Effort under the source-archive Program. Implementation changes documentation and its necessary example checks and navigation, not runtime behavior or the release process.

## Protected content and delivery

- Leave the human-authored root `README.md` and `docs/providers/**` unchanged. The owner values their current content and has reviewed the provider pages. Do not apply general editorial changes, snippet rewrites or new output requirements to these protected files in this sweep.
- Keep the generated homepage reflecting the root README. `docs/hooks.py` copies that README into `docs/index.md`; do not independently rewrite the generated page or change its source ownership.
- Keep the API reference generated from public docstrings through the existing mkdocstrings NumPy handler. Do not replace it with a handwritten API reference or a second reference for agents. Correct relevant factual docstring defects if inspection establishes them; do not repeat a blanket docstring rewrite already delivered by the API-documentation work.
- Preserve the existing MkDocs build and publication arrangement. `.github/workflows/deploy-docs.yml` publishes the built site to `RivRetrieve/RivRetrieve.github.io`; `/Users/nicolaslazaro/Desktop/work/rivretrieve.github.io` is the paired output checkout, not another source project. Do not change publication triggers, transport, target repository or release policy. Navigation and source content may change without redesigning delivery.
- This work prepares documentation. It does not publish the first package release, change repository visibility or authorize a broader public launch.

## Writing philosophy

Follow `docs/AGENTS.md` throughout edited prose and public docstrings. Explain current behavior in plain, precise language. Use stable domain terms, useful headings and direct links so an agent can find the relevant fact without reading unrelated internals.

Each explanation has one authoritative home. Guides explain tasks and interpretation; docstrings specify individual interfaces; provider pages own source-specific introductions and conditions. Link instead of repeating parameter lists, provider narratives or detailed contracts.

Lean means removing redundant information, overly long explanations and unnecessary code examples. It does not mean deleting qualifications that determine how data can be interpreted. Explain practical consequences rather than implementation history, defensive arguments or delivery records. For example, an unknown statistic does not match an explicit mean-statistic filter. Avoid multiple snippets that teach the same operation with slightly different arguments.

## Structure and responsibilities

Use these responsibilities to organize the site. Exact filenames and navigation mechanics are implementation choices; adding more pages requires a distinct reader need.

- **Home:** the protected README-backed entry point.
- **Usage:** one compact shared guide to selecting, inspecting, retrieving and interpreting observations. Explain physical filtering and separately published series where readers need them in that workflow. Do not retain a separate product dictionary that repeats the explanation.
- **Providers:** existing reviewed pages, unchanged.
- **API reference:** generated signatures, constraints, returned interfaces, units and failure behavior. Make it discoverable as a primary reference rather than treating all API users as library developers.
- **Station metadata:** supplied by the separate metadata work described below. Do not redesign or pre-empt that guidance.
- **Station map:** retain its exploration purpose and ensure non-protected supporting claims and counts match the delivered catalogue. No map-platform redesign.
- **Contributing:** concise participation policy, distinct from instructions for changing code.
- **Architecture:** explain RivRetrieve’s philosophy and design, including why its responsibilities and boundaries exist. It is not a historical port account, a storage-schema dump or a second usage tutorial.
- **Testing:** preserve and integrate the current testing philosophy and practical guidance delivered by PR #485. This is important maintained documentation, not historical verification clutter.
- **Development instructions:** concise setup and commands for a person or agent implementing an agreed change. Keep them distinct from participation policy and the testing philosophy, without growing a large contributor handbook.

The existing CAMELS-US example and standalone USGS discovery page have no automatic right to remain separate pages. Keep a separate worked example only when it teaches a useful task or interpretation absent elsewhere. Preserve necessary current contracts, including machine-readable catalogue definitions, without assuming their present surrounding prose or navigation is optimal.

## Explain the current physical-facts API

The relevant redesign is the outcome of Program #284 and its shared-engine/provider work, including PR #300. PR #300 verified the provider application of the model; subsequent changes also belong to the current API. Inspect current code and tests rather than freezing documentation to that PR.

The shared guide must make these practical facts understandable:

- Quantity, frequency, statistic and other physical facts can be known independently. Established quantity and units do not establish a daily mean, a time zone, a daily interval or a water-level datum.
- Broad physical selection can include series whose more specific temporal facts are unknown. An explicit predicate matches only established matching facts.
- Several separately published source series can share the same physical description. Retrieval preserves every matching supported identity unless the caller narrows it; the library does not choose a preferred series or infer a common quality ranking.
- A packaged catalogue is a snapshot, not proof of exhaustive historical availability. Retrieval can discover additional matching identities.
- Results preserve the distinction between null values, absent rows, successful empty series and failed requests. Explain how to inspect issues and retrieval outcomes, not only numeric rows.
- Returned units and time labels must be interpreted according to established source meaning. Unknown temporal meaning remains unknown.

Architecture explains why these principles shape the design and how the shared engine and provider implementations divide responsibilities. The generated reference remains the authority for exact arguments, returned columns, types and failure contracts.

## Participation policy

Welcome bug reports, issues and suggestions for new data providers. Encourage contributors to share agency links and scripts they have personally used to retrieve data. These can be useful inputs without being ready-made provider implementations.

Ask contributors to discuss a proposed change in an issue before submitting a pull request. PRs are welcome after that discussion. Do not invite unsolicited implementation PRs or imply that every provider suggestion must arrive with a complete adapter. Technical development and testing guidance supports agreed changes; it does not change this participation policy.

## Examples and verification

Every code snippet in the documentation delivered or rewritten by this sweep must be tested. Show the relevant output, so readers can see what the operation produces. The sole output exception is a snippet whose purpose is only to demonstrate the API; it still needs an appropriate check. The protected README and provider pages remain untouched.

Use a small number of purposeful examples with readable spacing and accurate outputs. Prefer a focused projection or summary over an unexplained full table. Do not invent expected results, imply a recorded answer is a current live response, or omit failed/empty requested series from a completeness claim.

Reuse the existing documentation tests and the testing principles delivered by #485. Match verification to the claim. A syntax-only API illustration, an offline catalogue operation and an observation retrieval do not require the same proof. Execute runnable examples through the project’s uv environment. Source-backed assertions need the established genuine-input workflow, not fabricated replacements or new ad hoc recording infrastructure. Missing mandatory evidence blocks the relevant verification; it is not a skipped success.

Keep outputs permitted for publication distinct from private evidence. Reuse safe reviewed example outputs where appropriate, and do not copy restricted source bodies, credentials or private execution logs into documentation or build artifacts.

## Separate work and the cleanup handoff

These boundaries are settled. Do not repeat their discovery, perform their work here or silently expand this sweep.

- **#427 / #431: evidence and historical-file cleanup.** The owner-approved handoff is https://github.com/RivRetrieve/RivRetrieve/issues/431#issuecomment-5969029194. #431 owns dispositions, verified private preservation or retirement, tools, records, archive identities, affected links and publication-boundary checks for the remaining material under `docs/verification/`, `docs/provider_ports/` and equivalent locations. This sweep will not move evidence, retire that tooling, verify archive copies or reinvestigate the cleanup. Use #431’s delivered result. If it is not yet available, proceed on independent documentation work and report the dependent integration as pending rather than taking over cleanup.
- The desired published docs contain no historical research, verification-report or proposal clutter. #431 must account for the verification links from nine protected provider pages. Any link-only changes required by its removals belong there, not in this sweep. It must also preserve necessary machine-readable definitions and current instructions while separating evidence ownership.
- **#484: metadata redesign and documentation.** Assume that work supplies its own accurate documentation. Leave `docs/station-metadata.md` and metadata-specific explanations/examples in other pages to that work. Integrate its delivered links and structure without prescribing the proposed metadata shape or rewriting its semantics here.
- **#486: Croissant contribution and absence workaround.** This dedicated follow-up owns checking the upstream gap, filing with MLCommons and settling documentation for the shipped local absence property. Treat it as handled outside this sweep; do not retain an unfiled upstream proposal as ordinary documentation.
- **#438: agent onboarding.** A future agent entry point or skill remains separate. Do not deliver `prompt.md`, a skill, a duplicate API corpus or agent setup machinery here.
- **PR #485 / #478: testing rewrite.** Integrate its delivered testing documentation and interfaces; do not redo its test-suite audit or rewrite. It was open at discovery, reviewed at commit `f9bf0b1b1a1cca3b7bcb49bd339cfe719685814d`. Use the eventual merged result rather than treating that intermediate revision as permanent authority.

## Inspection findings to resolve against the implementation baseline

These are concrete leads from discovery, not frozen output wording or permission to alter package behavior:

- `docs/usage.md` describes cache reuse too broadly as all-or-nothing for a request. Current reuse is decided per station/access route; an uncovered route can be fetched while another is reused.
- Its unconditional HTTP 404 warning claim needs qualification: provider-defined empty responses in request padding can be ignored without an issue.
- Explain retrieval-outcome inspection, including unresolved outcomes without a concrete series identity. A data-only coverage table does not account for entirely failed or empty requested gauges.
- `docs/design/observation-store-layout.md` still describes accumulated revision 7 while inspected code and architecture use revision 8 with coverage-axis and observation-only snapshot semantics. If retained as a detailed current contract, reconcile it with delivered code rather than duplicating its detail in Architecture.
- The map’s total of 78,175 matched the inspected catalogue, but its Norway and South Africa breakdowns were stale. Recompute supporting claims from the implementation baseline rather than hard-coding this discovery’s numbers.
- Catalogue evidence and absence pages define URIs used by packaged descriptors. Lean prose does not authorize deleting a live vocabulary definition. Respect #431 and #486 ownership instead of rebuilding catalogue products as incidental documentation cleanup.

## Evidence of completion

The final documentation has clear responsibilities, consistent terms, fewer repeated explanations and no second API reference. A reader or agent can understand physical selection, distinguish source identities, retrieve observations and interpret outputs and failures without reading the implementation.

Review all non-protected documentation in scope against the delivered code, including generated reference content where claims matter. Verify the shown outputs and every in-scope snippet through the appropriate existing checks. Run the applicable reference-freshness and strict MkDocs build checks, review the rendered navigation and links, and confirm that the same publication workflow still targets the paired repository. A local build is not evidence of deployment.

Demonstrate that the protected README/provider content and publication arrangement remain unchanged by this sweep. Account concisely for kept, consolidated, rewritten and removed pages in the implementation handoff; do not create a permanent review registry or another historical report under docs. Distinguish completed verification from integration still waiting on separately owned work. Do not claim complete first-release documentation while known dependent links, definitions or metadata/testing integration remain unsettled.
