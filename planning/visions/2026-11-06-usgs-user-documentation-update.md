# USGS user documentation update

Update `docs/providers/usgs_nwis.md` so users can understand the delivered USGS
coverage and interpret a practical retrieval without reconstructing the research.
This is a focused update that preserves the structure generally used by provider
pages, not a new guide or a broad rewrite.

This vision completes [documentation issue #625](https://github.com/RivRetrieve/RivRetrieve/issues/625)
after the documentation is verified, reviewed by the maintainer and merged. It
does not complete the broader [USGS Program #624](https://github.com/RivRetrieve/RivRetrieve/issues/624).

## Scope

- Reconcile coverage and catalogue facts with the delivered integration, including
  continuous-only stations and supported non-stream sites. The November 5
  verification reports 29,387 selectable stations; the existing page still says
  27,679. Verify current counts rather than copying that historical checkpoint
  without checking the implementation target.
- Keep the river-gauge retrieval as the main practical example and retain useful
  guidance on distinct published time-series IDs and explicit series selection.
- Add a short, source-backed agricultural-monitoring example in prose, using the
  Discovery Farms case established in [#623](https://github.com/RivRetrieve/RivRetrieve/issues/623).
  Explain that published discharge is not necessarily river streamflow or suitable
  for a particular study. Do not add another retrieval tutorial or infer
  site-specific instrumentation.
- Keep supported products, units, access, source status, terms and attribution
  accurate. Correct misleading labels where needed, including the distinction
  between daily/continuous collections and the source-series ID exposed as
  `variant`.
- Preserve limits that affect interpretation: station and series listings do not
  guarantee observations for every date; daily dates do not establish a time zone
  or daily interval bounds; gage height is not sea-level elevation; continuous
  publication does not establish a fixed sampling interval. Describe 365-day
  continuous request partitioning consistently with the delivered behavior and
  existing usage guidance, without presenting it as a retention limit or a proven
  maximum accepted server window.

Follow `docs/AGENTS.md` and step 7 of the provider-port guide. Link general usage
rather than duplicate it. Trim repetition only where useful within the existing
structure. No code or API changes, new products, new documentation hierarchy, or
broader provider-page redesign are intended. Report a discovered implementation
mismatch rather than silently expanding this work into a repair.

## Evidence and acceptance

Build on [verification #626](https://github.com/RivRetrieve/RivRetrieve/issues/626)
and its linked private consolidated assessment. Its delivered checkpoint is
`15d118b736ec8e9091e4ce747efd88ee9d9fb5a7`. Reconcile later changes before relying
on that checkpoint. Keep original evidence and continuing provider findings in
the existing private research record; public documentation explains consequences,
not verification machinery.

Verify changed claims and the retained or changed runnable examples using the
repository's established documentation and evidence checks. Exact example output
must have supporting evidence, with source revisions still possible. Follow the
maintainer evidence guide for genuine inputs and exact-revision review; unavailable
mandatory evidence is a blocker. Do not rerun an unrelated provider review or
invent a new verification system.

The continuous-only stage witness in the verification handoff is an empty interval,
not an example of positive observations. The CAMELS-US comparison gives bounded
confidence for daily discharge and shares USGS origins; it does not validate stage,
continuous products, full history or scientific suitability. Neither needs to
become an additional user-facing example or verification narrative.

Success means the page agrees with supported behavior, preserves the usual
provider-documentation structure, and explains the broader site coverage through
the existing river example plus the short agricultural example. The PR reports
checks performed and any remaining limitations. Exact wording and minor trimming
are left to implementation.

## Human merge gate

Open the provider-documentation PR for the maintainer to review and leave it open.
Do not merge it or enable automatic merging before the maintainer has reviewed it
and explicitly approved merging. Automated checks and independent agent review do
not replace this human gate. Keep #625 open until the approved documentation is
merged and verified. Publication of this vision does not satisfy that gate and
does not authorize implementation by itself.
