# SENAMHI provider documentation

Finish `docs/providers/pe_senamhi.md` so readers can understand what the delivered
Peru SENAMHI integration provides, retrieve a practical example, and interpret
its limits without reconstructing the source investigation.

This delivers [Effort #609](https://github.com/RivRetrieve/RivRetrieve/issues/609)
under [Program #534](https://github.com/RivRetrieve/RivRetrieve/issues/534).
Publishing this vision does not complete #609. The Effort completes only after
the provider documentation is verified, read and explicitly approved by the
maintainer, and merged into `port/pe-senamhi`. Keep `main` unchanged. The port's
separate final review and merge approval remain with #610.

## Write for users

Follow [docs/AGENTS.md](../../docs/AGENTS.md),
[provider-port step 7](../../docs/maintenance/provider-ports.md#7-user-documentation)
and the existing [provider pages](../../docs/providers/), including Lithuania
and Hub'Eau. Use their reader-facing patterns rather than copying source-specific
claims: introduce the publisher and supported data, present one verified practical
retrieval example, explain its output, and describe conditions that affect use.
Write for hydrologists with basic Python knowledge. Link general usage rather
than repeat API instruction. Keep detailed research and implementation mechanics
out of the provider introduction.

Describe the actual delivered scope on `port/pe-senamhi`, including PHISIS daily
and hourly series and all nine monthly-archive water-level fields. Explain access
requirements, meaningful source-series distinctions, units, time information,
availability limits, terms and attribution. Inspect the current implementation
and continuing evidence record rather than treating the Program's original
exploratory research as the current contract. Do not expand supported products
or change source interpretation as part of documentation work.

Use one bounded example through the public API, with verified inputs and output
and an explanation of what the reader should notice. Retain its verification
through the existing evidence process. A successful example does not promise
continuous records or complete history. Keep any navigation changes limited to
making the page discoverable through existing documentation patterns.

## Preserve the verification handoff

The [#608 handoff](https://github.com/RivRetrieve/RivRetrieve/issues/609#issuecomment-6558651706)
records the accepted ten-gauge CAMELS-PE visual sanity comparison. It does not
establish PHISIS DAILY `current` as a daily mean or resolve observation-day or
time-zone conventions. Preserve these unknowns in explanations and examples.

Keep the other delivered limitations accurate and understandable:

- `m.s.n.m` establishes an above-sea-level reference, not a named vertical datum.
- Monthly request partitions do not establish observation frequency.
- Published nulls, absent rows and failed requests remain distinct.
- Future-dated observations and negative values are preserved without unsupported
  correction or invented explanations.
- Catalogue membership and bounded acquisition checks do not guarantee data for
  every quantity or period, or a complete historical record.

Continue the private
[SENAMHI research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/pe-senamhi-source-access.md)
and follow the [evidence guide](../../docs/maintenance/evidence.md). Keep original
material and detailed provider findings there. Review exact revisions before
executing with private evidence; keep controlled material out of public artifacts.
Any new source requests must respect established access constraints and the limit
of at most one request per second. Unavailable mandatory evidence blocks the
relevant verification claim; do not invent example output or weaken checks.

## Human review before merge

Prepare the documentation PR against `port/pe-senamhi` and provide the maintainer
with the exact provider file to read. Leave the PR unmerged until the maintainer
has read it and explicitly approved merging. Passing automated checks, agent
review, or completion of the writing does not satisfy this gate. Do not enable
auto-merge while approval is outstanding. Changes to the reviewed file require
approval of the revised content before merge.

Check documentation links and agreement between the prose, example and delivered
behavior. Run the applicable documentation checks and verify the example with
genuine evidence. Report what was checked and any limitations. If verification
reveals a behavior defect or unsettled source claim, surface it rather than
silently changing the provider or claiming the page is complete.

Leave the choice of example station and dates, exact section layout and verification
mechanics to implementation. No implementation or port merge is authorized by
publication of this vision. Human approval of this documentation does not replace
the Program's separate final review and explicit approval for merging into `main`.
