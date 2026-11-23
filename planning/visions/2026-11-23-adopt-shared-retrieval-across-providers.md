# Adopt shared retrieval across providers

Complete [#951](https://github.com/RivRetrieve/RivRetrieve/issues/951) by removing repeated interpretation of source responses wherever the shared retrieval contracts apply. A caller should receive the same observations, source context and independent outcomes after a migration. Implement this effort on `program/938-efficient-shared-retrieval` under the [Program’s agreed scope](https://github.com/RivRetrieve/RivRetrieve/issues/938#issuecomment-7100576546).

## Build on the provider audit

Start with Kratzert’s [audit of 19 providers](https://github.com/RivRetrieve/RivRetrieve/issues/938#issuecomment-7094994897). It identifies repeated work by source path, including providers where metadata and observation responses behave differently. Reconcile the findings with the code on the Program branch and credit the six representative integrations already landed. For example, the audit flagged metadata or page decoding in `ba_fhmzbih`, `ch_foen` and `fi_syke`. Check which of those paths still repeat work and whether the interpretation is valid in the context that consumes it.

Use the contracts and examples in Steps 4 and 5 of the [provider port guide](../../docs/maintenance/provider-ports.md).

- When acquisition already interprets a page or prerequisite response, pass that interpretation to parsing when the product, scope and known-series context match. USGS and Hub’Eau demonstrate pagination, and Argentina demonstrates a prerequisite lookup. [Acquisition handoff in #949](https://github.com/RivRetrieve/RivRetrieve/pull/970)
- When several selected products consume one response, decode it once and retain each product’s result or failure. Lithuania, Peru and Austria show how this works both for responses inspected during acquisition and for those first decoded during parsing. [Shared-product decoding in #950](https://github.com/RivRetrieve/RivRetrieve/pull/990)

Remove superseded parsing or reuse mechanisms from migrated paths. Record why an already efficient live path needs no change. Compiled-store providers benefit from the [shared-table work](https://github.com/RivRetrieve/RivRetrieve/issues/953), and catalogue-only providers have no observations to retrieve. Changes to HTTP request grouping and malformed-pagination behavior belong to separate follow-up work.

## Evidence for completion

Account for every provider. Record which paths migrated in this effort, which earlier integrations cover, and the reason for each no-change decision. Recheck the provider list on `main` before closing #951 and include ports merged during the Program.

For each migration, compare equivalent requests before and after the change. Check observations, series identity and physical facts, annotations, completeness, issues, outcomes and provenance, including original receipts. Preserve the distinctions between null values, absent rows, successful empty responses and failures. Where applicable, exercise a late-page or prerequisite failure and a product failure alongside a successful sibling. Preserve fatal internal contract validation.

Demonstrate that the repeated work identified on a migrated path is gone. For representative workloads, report comparable work counts, CPU time, elapsed time and peak memory. Use the [verification guide](../../docs/maintenance/evidence.md) for applicable retained-source checks and report any unavailable mandatory evidence as blocked. The audit’s timings provide context for comparison.

## Final Program review

Once all #938 work is complete and verified, open one PR from `program/938-efficient-shared-retrieval` into `main`. Adversarially review the combined changes, address findings, assign the PR to `kratzert`, and leave it open for his final review.
