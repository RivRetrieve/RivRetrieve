# Swiss API source, scope and access

Complete [Effort #559](https://github.com/RivRetrieve/RivRetrieve/issues/559) with an evidence-backed source-and-access handoff for the official Swiss API port. This is research consolidation and bounded gap resolution, not provider implementation. Verified completion of this vision completes #559; publishing this vision does not.

The port belongs to [Program #545](https://github.com/RivRetrieve/RivRetrieve/issues/545). Follow [provider-port step 1](../../docs/maintenance/provider-ports.md) and the existing [evidence process](../../docs/maintenance/evidence.md). Keep port work on a dedicated branch until complete. This vision may be published on main without delivering the port.

## Settled scope

Replace Existenz with direct official BAFU access for discharge, water level and water temperature. Include the source's ten-minute and hourly means, daily/monthly/yearly means, minima and maxima, and its separate recent raw feed. Retrieve published products; do not calculate missing products or splice raw readings into aggregate series.

The [maintainer's scope clarification](https://github.com/RivRetrieve/RivRetrieve/issues/545#issuecomment-6296750847) supersedes the earlier strict Existenz-parity requirement in the Program and Effort bodies. The objective is to expose what the official API publishes, not reproduce Existenz's historical short-interval stream. Ordinary differences in availability by station, parameter and period are normal provider behavior, not a special scope blocker.

Use ordinary on-demand retrieval and the existing cache as the integration direction. The official GraphQL route is the established candidate for archive and recent requests; prepared CSV files can support research, catalogue construction and evidence. This work must justify the access choice and record its limits, without implementing the declaration. No national-download feature, runtime API/file fallback, LINDAS integration, bespoke historical orders or search for the oldest possible record is requested.

## Build on the existing investigation

Read #545's research and later correspondence summaries in chronological order. The October 20 BAFU reply and subsequent corrections supersede earlier claims that no reply has arrived. Reuse established findings rather than repeating the entire investigation.

Public checks on October 20 confirmed the archive field families in the GraphQL schema, anonymous access, attribution terms and the continuing seven-day/twelve-hour live-retention documentation conflict. Earlier retained probes establish real archive and live examples; schema presence alone does not establish observations at every product family. In particular, sampled yearly queries were empty. Do not turn those samples into a global absence claim.

BAFU endorses official station-page units for the live feed. Archive/live unit discrepancies, unusual series at 7008, exact series meanings and live retention still need appropriate follow-up. Their existence does not require resolving every later Effort before completing source and access work. Preserve representable unknowns; do not invent physical facts to declare access usable.

## Required handoff

Locate the existing Swiss research record in the private verification-evidence repository before creating another. Consolidate useful findings, dated checks, corrections, correspondence and open questions there. Follow that repository's current intake process for originals; temporary paths and public issue summaries are not substitutes for retained evidence. Keep correspondence, controlled inputs and credentials out of public repositories and artifacts.

The handoff must establish:

- The measuring and publishing institutions, intended geographical and product scope, and the identity of the official publication replacing Existenz.
- The selected observation and metadata routes, their access kind, credential requirements, relevant request conditions, terms and required attribution. Distinguish successful access, empty results and failed requests.
- Traceable, small genuine examples of metadata, archive observations and recent observations sufficient to support this Effort's adopted access claims. Reuse retained examples where suitable. Locate and verify their originals, acquisition records and exact archive references; collect bounded replacements under new identities only where needed and permitted.
- A concise comparison with the existing provider that explains the move to official archive products and recent readings, without restoring the superseded like-for-like requirement or demanding exhaustive station parity.
- Remaining questions, the capability or claim each affects, and the later Effort responsible: [catalogue #560](https://github.com/RivRetrieve/RivRetrieve/issues/560), [series meaning #561](https://github.com/RivRetrieve/RivRetrieve/issues/561), [retrieval #562](https://github.com/RivRetrieve/RivRetrieve/issues/562), [integration #563](https://github.com/RivRetrieve/RivRetrieve/issues/563), [verification #564](https://github.com/RivRetrieve/RivRetrieve/issues/564), or [user documentation #565](https://github.com/RivRetrieve/RivRetrieve/issues/565).

Publish a concise, disclosure-safe completion summary on #559, linking the continuing research record and relevant Program context rather than duplicating the investigation. Put material Program-level changes on #545. No new public research framework, production code, catalogue artifacts or user-provider documentation rewrite is required.

## Completion and surprises

A fresh agent must be able to identify the agreed scope, selected access approach, supporting retained evidence, applicable terms and unresolved follow-ups without this conversation. Verify the references and applicable archive intake/integrity checks. If governing claims, source bindings, verifiers or collections change, run the full checks required by the evidence process against reviewed revisions. Report exact checks and limitations; do not claim full provider certification from exploratory access examples.

Missing mandatory evidence or private archive access blocks this handoff's acceptance. Unresolved physical meaning or retrieval details may pass to their named Efforts when they do not undermine this Effort's source/access conclusion. Resolve factual gaps independently. If a finding requires changing scope or accepting a meaningful trade-off, return that consequence to the maintainer instead of silently narrowing the outcome. Obtain authorization before sending new correspondence.

Close #559 only after the handoff and its acceptance evidence are verified. The remaining Program Efforts stay open; this vision does not authorize implementing or merging the complete provider port.
