# Human-reviewed onboarding before the documentation rewrite

Program: https://github.com/RivRetrieve/RivRetrieve/issues/284
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/287

## Outcome

Users can understand and use the delivered discovery and retrieval interface without knowing its
internal implementation. Explain the simple model: filter established physical facts and preserve
separately published source identities. Increasing specificity is not a quality ranking or a
mandatory ladder of information tiers. Matching physical facts do not establish scientific
interchangeability.

The engine and all-provider work are already landed through Efforts #285 and #286. This Effort
explains that software; it does not redesign the API or repeat provider research. Read the Program
and those delivery records for inherited boundaries and established source limits. Use current
code and recordings for exact API spelling and behavior, not the Program's illustrative snippets.

## Two sequential delivery stages

The human review must shape the wider rewrite, not merely approve two pages after all documentation
has already been written.

1. The first implementation PR rewrites the root `README.md` and `docs/usage.md` only, apart from
   supporting tests or verification changes needed to prove those pages. `docs/usage.md` is the
   existing usage guide referred to as “use.md” during discovery; do not create a second guide.
   Complete AI factual review and executable verification, then present the two finished pages to
   the user. Stop for their feedback and explicit approval. Do not merge their changes before that
   approval and do not begin the remaining documentation rewrite while waiting.
2. Incorporate the feedback, obtain approval for the final versions, and proceed with the remaining
   in-scope software documentation only after approval. Carry the user's editorial feedback into
   that work. AI can author, independently review and verify these remaining documents without an
   additional required human approval gate.

Approval applies to the reviewed contents of both `README.md` and `docs/usage.md`. Further changes
to either require renewed explicit user approval, including changes discovered during the second
stage. AI review and passing tests do not substitute for that approval. Record review feedback and
approval durably on the implementation PR or Effort so a resumed agent can recover the direction
and gate state. Do not infer approval from silence or from approval of this vision.

This vision publication is separate from the first implementation PR. Publishing it authorizes no
implementation. The user review is of the two reader-facing files, not a requirement for the user
to review all supporting tests or all remaining documentation.

## Reader experience and coverage

Keep the README a concise introduction and working entry point. Let the usage guide explain the
workflow progressively, with concrete examples and understandable results. Preserve useful existing
content rather than rewriting mechanically. Readers should not need internal schemas to understand
products, source alternatives or unknown facts. Avoid defensive audit transcripts, discovery history
and stacked disclaimers. Ordinary source citations and relevant limitations remain appropriate.

Across the onboarding and supporting documentation, cover:

- Broad discharge filtering versus established daily-mean filtering; physical quantity versus
  frequency/statistic; temporal support versus update cadence; independently known facts and
  explicit unknowns.
- Brazil's both-series default and optional explicit selection without a preferred alternative;
  Swiss incomplete temporal knowledge; an actual supported singleton; source-series inspection;
  and nonexistent-variant `on_issue` behavior without fallback. Distinguish established no-match
  from unresolved inventory. Use real supported providers and identifiers, not placeholders.
- Selection-time versus retrieval-time knowledge, including response-discovered identities and
  the limits of packaged inventory. A static catalogue is not an exhaustive current or historical
  census.
- Results, issues, partial successes, nulls versus missing rows versus failed requests, units and
  time handling, optional exact receipts and caches. Preserve fatal internal-contract behavior
  outside recoverable source-issue policies.
- Actual migration from the old interface: changed physical filters and removed `product=` input,
  revised result and export contracts, versioned bundles and cache/store refusal with rebuild or
  refetch. Verify precise current versions and commands from shipped code; do not promise silent
  compatibility or fabricate identities for old data.
- Source-series identity is not a harmonised quality score. Provider-specific observation quality
  flags are not added to harmonised output, and equal physical filters do not imply scientific
  interchangeability.

Do not force every reference detail into the README. Allocate detail between onboarding and
supporting pages according to the user's first-stage feedback while retaining the Effort's coverage.

## Remaining documentation and boundaries

After the gate, align generated API/types/capabilities, current architecture, software-owned
capability tables, examples and migration guidance with the delivered interface and the approved
editorial direction. Keep software-owned documentation consistent across all thirteen enrolled
providers, distinguishing live, bulk and South Africa's catalogue-only access.

Provider-specific narratives remain colleague-owned. Coordinate factual impacts without taking
over those narratives. Do not expand source research, invent missing hydrological meaning, add
providers or products, activate South African observation retrieval, or migrate the USGS API.
Documentation hosting, hosted CI, release publication and new ADR collections are excluded.
No unrelated code refactoring or API redesign is authorised. If verification exposes a substantive
software defect that prevents truthful documentation, report it explicitly rather than disguising
it as prose or silently widening the Effort.

## Evidence of completion

The first-stage PR supplies AI verification and explicit user approval for the final contents of
both gated pages. The remaining work demonstrably applies that feedback and passes independent
AI review. A fresh reader can follow the actual installed-package workflow and distinguish physical
meaning, source identity, unknowns and issues without the original conversation.

Execute documented snippets against the delivered public API with appropriate recorded/offline
checks. Test observable behavior and displayed outputs, not just callable names or syntax. Keep
examples reproducible without requiring new live credentials for verification. Generated references
must match shipped signatures and capabilities. Validate local links and installed-package behavior,
and document real breaking changes rather than hypothetical ones. Use the project `uv` environment
and local validation; do not introduce hosted CI as a delivery mechanism.

Existing anchors include `tests/test_documentation.py`, `tests/test_documentation_examples.py`,
`scripts/generate_reference.py`, `docs/reference.md`, `docs/architecture.md`, and
`docs/examples/camels-us.md`. Existing onboarding tests replay publisher transport recordings and
check displayed output, so extend real-path coverage rather than replacing it with mocked results.
Provider and source-series regression tests and the landed delivery records supply behavior evidence.

The Effort is not complete after approval of the first PR alone. Completion requires the remaining
in-scope documentation, verification and consistency work, with the human approval boundary retained
for any later changes to the two gated files.
