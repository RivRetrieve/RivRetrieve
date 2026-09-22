# Verified French provider documentation

Program: https://github.com/RivRetrieve/RivRetrieve/issues/312
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/313

## Outcome

Readers can use Hub’Eau and HydroPortail as separate French providers, understand
what each supplies, and interpret a practical retrieval without learning repository
internals. Replace the combined France narrative with two factually verified provider
pages. Keep shared documentation changes minimal. Nicolas Lazaro personally reviews
the four primary documentation files before their implementation PR can merge.

## Scope and current starting point

The primary review set is:

- `README.md`: only necessary provider-count, table, link or directly related corrections.
- `docs/usage.md`: only necessary corrections or concise guidance required by the split.
- `docs/providers/fr_hubeau.md`: rewrite as the Hub’Eau page.
- `docs/providers/fr_hydroportail.md`: add the separate HydroPortail page.

Do not manufacture changes when shared documentation is already correct. At discovery,
the README already listed both French providers and thirteen observation-access
providers: eleven live services and two bulk sources. Verify current declarations
and recompute affected counts; observation access and total registered providers are
different counts. Update `docs/README.md` and directly affected links, references,
examples and checks as supporting consistency work, not a broader documentation rewrite.

Efforts #310 and #311 are landed. Start from current `main` and their delivered
behavior, rather than the provisional processing-stage wording of older tickets.
Relevant delivery records are on those Efforts; implementation PRs are #316 and #318.

Hub’Eau supplies published daily mean discharge (`QmnJ`), daily maximum discharge
(`QIXnJ`), daily maximum stage (`HIXnJ`), and Naïades water temperature. HydroPortail
supplies station-own instantaneous discharge and stage. Its four delivered selectors
are `raw`, `validated`, `pre_validated_and_validated`, and `most_valid`. They are
source selections, not four interchangeable glossary processing stages. There is no
corrected-only or pre-validated-only history through this public route. Explain
selection with the existing `find` / `series` / `pick` / `fetch` API. Unrestricted
retrieval requests all matching supported selectors; explicit selection has no
preference, substitution or fallback. `most_valid` is a source selection, not a
RivRetrieve quality ranking. Do not imply that French processing selections mean the
same thing as Swiss source-field variants or Brazilian consistency statuses.

## Documentation standards and page shape

Follow `docs/AGENTS.md` explicitly. Apply the same reader-oriented standards to the
small README changes. The audience is an educated hydrology reader with basic Python
knowledge, not a software engineer. Explain project-specific concepts where they
first matter. Use factual, concrete prose, focused paragraphs, consistent terminology,
and sufficient explanation rather than compressed jargon. Preserve meaningful
qualifications and unknowns. Avoid em dashes, promotional language and rhetorical
contrastive negation. Give code blocks breathing room and explain useful output.

Both the current French page and the Swiss page `docs/providers/ch_foen.md` are
human-reviewed examples whose writing Nicolas liked. Preserve their organization,
explanatory approach and writing style. The Swiss example is merged PR #289; the
prior French review is PR #264. Treat this work as a refactor of the reviewed French
page into two provider-specific pages, updating facts for delivered behavior rather
than replacing the approved approach with a new style or structure. Each page should introduce the provider, show one
practical verified retrieval and explain the result, then cover supported observations,
source and producer distinctions, relevant station/site distinctions, units, time,
status, availability, access, terms, citation and dated sources. Additional short
selection examples are appropriate when needed to explain HydroPortail variants.
Link to the usage guide for general API instruction.

Keep catalogue verification methods, receipt internals, test history and implementation
mechanics in maintainer or PR evidence, not provider introductions. Preserve useful
source references without copying unrelated material between the two pages. Remove
the superseded combined narrative. No legacy page, compatibility guide or migration
story is required.

## Factual correctness is an acceptance requirement

### Executable examples

Execute the final documented Python snippets through RivRetrieve’s public API in the
project’s uv environment. Verify live source retrieval, using `cache="bypass"` where
applicable, and compare every displayed output with the actual execution, including
units, timestamps, row counts, selected identities and reported issues. Run dependent
snippets in their documented order. Check the final text, not an earlier draft or an
equivalent handwritten script. Explain the output accurately and identify retrieval
dates where values may later change.

Retain reproducible regression coverage for the page examples and affected documentation
contracts. Recorded-source tests complement live verification; they do not establish
that a service is currently reachable. Report source failures honestly and retain the
verification gap for review rather than substituting fabricated or stale output and
calling it live-verified. No unresolved verification gap can be presented as completed
acceptance. Do not hide real informational issues merely to show an empty issue tuple.

### Provider claims

Check provider claims against the current packaged catalogue, retained research and
source evidence, delivered public behavior, and authoritative provider documentation.
Investigate contradictory or uncertain claims before presenting them as facts.
Relevant evidence includes the French provider modules, provider declarations,
`maintenance/catalogue/fr_hydroportail/`,
`maintenance/verification/french-publication-services/`, provider port notes, and the
source references retained in the reviewed pages and functional delivery records.
Recheck authoritative references supporting material claims and record check dates.

Preserve source facts, vocabulary, attribution and unknowns. In particular:

- Separate the publication service from the original measurement producer and the
  Naïades temperature network from hydrometry.
- Keep service-owned catalogues and station/site identities distinct. A listed station
  does not guarantee observations for every quantity, selector or period. Bounded
  retrieval witnesses do not establish complete historical coverage.
- Explain actual unit conversions and established time semantics. Do not infer daily
  support or time zones from a broad source statement. Unknowns remain explicit.
- Distinguish requested selectors from per-observation processing metadata. Do not
  invent quality rankings or infer an undocumented `most_valid` selection algorithm.
- Preserve distinctions between null observations, absent rows, empty successful
  series and failed requests when explaining results.
- Keep terms source-specific. Hub’Eau’s Etalab terms must not be transferred to
  HydroPortail. HydroPortail’s reuse licence and historical measurement authorship
  remain unestablished unless new authoritative evidence establishes them.

Retain verification commands, results, claim sources and unresolved limitations in
review records so a reviewer can inspect the factual basis without cluttering the
reader-facing pages. Preserve useful source evidence and meaningful scientific
regressions while replacing obsolete combined-provider assertions.

## Human review and completion

Prepare the documentation implementation PR with the four primary files clearly
identified, supporting changes explained, and final example and provider-fact
verification evidence available. Obtain independent review and satisfy repository
checks, then leave the PR open for Nicolas Lazaro’s personal review. Explicit approval
from Nicolas is required before merging documentation implementation changes. Passing
automated checks or agent review does not replace this gate. Subsequent revisions must
retain factual verification of the final examples and claims.

This vision’s publication is separate from that human gate. Publishing and merging
this vision authorizes a durable handoff, not implementation or automatic merging of
the later documentation PR. Effort delivery requires the approved documentation to be
merged; a review-ready PR alone is not completed delivery.

No provider implementation changes or unrelated documentation cleanup are included.
If verification reveals a defect, missing capability or contradictory source behavior,
report it to the owner and decide whether a follow-up issue is needed rather than
silently expanding this Effort. Any separately authorized bug fix must first prove
the real failing path with a failing regression, as required by repository rules.
