# NRFA retrieval behavior

Deliver evidence-backed, tested source acquisition for the ten NRFA API flow and
stage products on `port/uk-nrfa`. Requests must preserve the published records and
expose failures without claiming unsupported completeness.

Implementing and verifying this vision completes [#594](https://github.com/RivRetrieve/RivRetrieve/issues/594).
Publishing this document does not complete the issue. Provider coordination remains
in [#347](https://github.com/RivRetrieve/RivRetrieve/issues/347), with shared context
in [#582](https://github.com/RivRetrieve/RivRetrieve/issues/582).

## Scope and delivery boundary

The scope is the current API publication of `gdf`, `ndf`, `gmf`, `nmf`,
`gauging-flow`, `gauging-stage`, `amax-flow`, `amax-stage`, `pot-flow`, and
`pot-stage`. Current means the archive served at retrieval time, not real-time
observations. Keep all ten source identities and the physical meanings established
in [#595](https://github.com/RivRetrieve/RivRetrieve/issues/595).

Deliver working acquisition code, request declarations and focused tests, together
with retained evidence supporting the adopted request rules. Keep the provider
registered as `CatalogueOnly()`: public observation retrieval must remain unavailable.
Connecting the stages through the public API belongs to
[#590](https://github.com/RivRetrieve/RivRetrieve/issues/590). Full integration
verification and user documentation remain in their coordinated later efforts;
this effort still owns verification and documentation of the behavior it introduces.

Rainfall, numbered bulk peak-flow releases, enquiry-only records, EA stitching,
derived replacement products and automatic catalogue refresh remain outside scope.
Implementation and corrections stay on `port/uk-nrfa`; merging into `main` requires
Thiago's explicit approval through the final review in #597.

## Research belongs with implementation

The implementing agent owns the remaining source research. Establish rules from
genuine evidence before encoding them, and develop tests alongside each behavior.
Do not repeat settled scope discovery or ask the maintainer to choose routine
request mechanics. Return to the maintainer when evidence requires narrowing scope
or accepting a meaningful limitation. Report unavailable mandatory evidence as
blocked rather than weakening acceptance.

Follow step 4 of [the provider-port guide](../../docs/maintenance/provider-ports.md)
and [the evidence guide](../../docs/maintenance/evidence.md). Continue the existing
[private NRFA research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/nrfa-source-access.md).
Reuse suitable retained evidence and obtain additional bounded originals through
the archive's existing intake and verification process. Follow the recorded
permission and private test-retention decisions from #587; do not reinterpret them
as unrestricted redistribution or storage permission. Keep original responses,
correspondence and detailed evidence private. Public issues carry safe summaries.

The [official API documentation](https://nrfaapps.ceh.ac.uk/nrfa/nrfa-api.html)
was reviewed on 16 November 2026. It documents one station and one data type per
JSON time-series request, inclusive start/end filters, explicit date labels and
optional flags. Use explicit `dates=true` and `flags=true` to preserve the labels
and source flags consumed by the existing decoder. FEH formats ignore date filters
and are not a fallback for this JSON acquisition contract.

No pagination, response cap or numerical rate limit was found in that documentation.
These omissions do not establish their absence. The response `interval` describes
a temporal span and cannot prove the number or completeness of sparse events.
The API publication can change retrospectively; a response creation timestamp is
not an immutable dataset revision. Earlier successful downloads are evidence of
those responses, not certification of retrieval behavior.

Resolve the consequential gaps during implementation:

- Establish actual boundary behavior for daily, monthly and event labels, including
  partial-month requests and time-of-day edges. Keep request filtering separate from
  the physical interval represented by a value.
- Establish selectors, request limits, any pagination or caps, and defensible
  completeness checks. Compare suitable larger requests with their smaller
  partitions where useful; matching responses support the tested request rule,
  not a guarantee of gap-free historical observations.
- Distinguish empty windows, unavailable station/product combinations, published
  nulls, absent rows, invalid requests and service failures using genuine examples.
  A successful HTTP status alone does not establish a valid or complete answer.
- Establish relevant revisions and source-retention limits without assuming an
  immutable historical archive. Keep client cache/storage permissions separate
  from source availability and use existing transport behavior where suitable.

Keep the investigation proportionate to these claims. This vision does not prescribe
an exhaustive benchmark, a new evidence framework or arbitrary request constants.

## Fit the existing contracts

At `port/uk-nrfa` revision `b66cebc0c4c81325ba5ff8543dc81681cf84de49`,
`uk_nrfa/series.py` already defines all ten products and decodes explicit-date JSON
responses into rows and annotations, including flags and original labels. It also
provides helpers for source peak-rejection metadata. Reuse these definitions rather
than adding another interpretation layer. Preserve source rejection lists without
filtering measurements or deriving new quality judgements. Establish any auxiliary
metadata acquisition needed to carry these existing annotations faithfully.

Daily labels use calendar-date selection. Monthly labels use a nominal first-of-month
carrier with their original `YYYY-MM` string retained; that carrier does not establish
a physical interval start or timezone. Preserve the settled physical facts and
unknowns from #595 rather than inferring new facts from request syntax.

The shared window planner owns acquisition bounds. Declare evidence-backed rules
through `WindowDeclaration` / `ProductWindowDeclarations`; providers consume the
rendered bounds without shifting them. Preserve final label-selection behavior.
Use the existing transport, `SourceAcquisition`, payload origins and bounded failure
contracts. Independent successful requests must remain usable when another request
fails, with its identity and reason retained. Fatal internal contract errors must
still raise.

No shared-engine limitation was demonstrated during discovery. Use the existing
design first. If concrete evidence demonstrates a required behavior cannot be
preserved, report it and raise a dedicated shared-engine issue rather than hiding
an incompatible rule in provider code or redesigning shared contracts speculatively.
Leave module layout, chunk sizes, concurrency and retry details to implementation,
subject to source evidence and existing project rules.

## Acceptance

- All ten products have a defensible acquisition contract and tested source-request
  behavior. Tests detect boundary loss, unsupported completeness claims and confusion
  between empty responses and failures at the simplest sufficient level.
- Genuine retained examples support the adopted selectors, boundary rules and response
  meanings. Evidence limitations and unresolved source facts remain explicit in the
  continuing private record. Synthetic tests do not replace required genuine checks.
- Acquisition preserves source bytes and call origins for the existing decoding
  stages, including explicit labels and flag-bearing values, without inventing
  missing observations or silently dropping independent failures.
- Affected source-independent tests and applicable controlled evidence checks pass
  against reviewed revisions. Follow the repository testing and evidence guides;
  keep controlled material out of public artifacts.
- Public NRFA observation retrieval remains unavailable. The handoff to #590 explains
  the acquisition contract, supporting evidence, remaining limits and integration
  work without claiming end-to-end delivery or gap-free source coverage.
