# Swiss API verification

Verify the complete official Swiss provider against genuine source evidence, fill
material verification gaps and fix bugs found within the agreed port scope.
Delivering this vision completes [Effort #564](https://github.com/RivRetrieve/RivRetrieve/issues/564);
publishing it does not complete the Effort.

Work targets `port/swiss-official-api` under
[Program #545](https://github.com/RivRetrieve/RivRetrieve/issues/545). Keep verification,
fixes and subsequent provider documentation on that branch. Do not merge into
`main`. [#565](https://github.com/RivRetrieve/RivRetrieve/issues/565) completes the
provider documentation. [#577](https://github.com/RivRetrieve/RivRetrieve/issues/577),
assigned to Thiago, is blocked until both #564 and #565 are closed. His explicit
approval of the completed port is required before the final merge into `main`.
This Effort does not perform that review or merge.

## Verify the delivered scope

Steps #559–#563 are delivered. At Swiss branch revision
`36598cdfea3924f6fc9f3aac604fd612b256a317`, official BAFU discovery, retrieval and
cache access replace Existenz under `ch_foen`. Build on their evidence and tests
rather than restarting source research or creating another verification system.

The Program's later scope decision supersedes strict Existenz parity. Verify
BAFU's published discharge, water-level and water-temperature products: archive
ten-minute/hourly means, daily/monthly/yearly mean/minimum/maximum products, and
the separate recent raw feed. Availability varies by station, parameter and
period. Do not reconstruct Existenz's historical stream, calculate missing
products or splice recent readings into archive aggregates.

Follow [provider-port step 6](../../docs/maintenance/provider-ports.md), the
[testing guide](../../docs/maintenance/testing.md) and the
[evidence guide](../../docs/maintenance/evidence.md). Assess the complete path from
offline discovery and source requests to returned observations and cache reuse.
Use genuine retained responses for distinct supported routes and independently
established expected results. Check identities, timestamps and values together,
including native-unit conversion, parallel variants and relevant calendar
boundaries. Preserve null values, absent rows and failed requests as distinct
outcomes; independent successful series must survive supported source failures.

Verify relevant cache behavior, isolation from old Existenz identities, catalogue
rebuild and lineage, and distribution contents. Extend shared contracts and add
Swiss-specific coverage for actual source differences. Match checks to the claims
and changed boundaries, rather than adding redundant tests.

The #563 handoff reports that recent replay matches the exact request, while
archive replay proves unchanged-response public composition, not acquisition
completeness. Assess and close the material acquisition-evidence gap; do not
present composition replay as proof that all requested source rows were acquired.
Keep synthetic controls, recording replay, derived rebuilds, complete source
verification and live observations distinct in the final account.

## Incorporate the new 7008 clarification

Nicolas supplied a further BAFU reply: data displayed for station 7008 result from
an internal configuration error. BAFU identifies Alte Zihl–Thielle as a former
station operating from 1 January 1841 to 30 September 1877. The safe summary is
[recorded on the Program](https://github.com/RivRetrieve/RivRetrieve/issues/545#issuecomment-6451080521).

Retain the original email through the existing private-archive intake process and
update the continuing Swiss research record before adopting changed source claims.
The original is currently supplied locally as `RE_ Anbindung der hydrologischen
Daten an RivRetrieve – Fragen zur API und Dateninterpretation (3).eml` in Nicolas's
Downloads directory. This is an intake location, not a portable build dependency.
Do not copy correspondence into this repository or public artifacts.

This resolves the cause of the anomaly, not the physical meaning of its rows.
Do not infer API coverage from the station's operating dates, assign daily or
monthly support to anomalous rows, or correct their source values or timestamps.
Assess the implementation against this clarification. Bring consequential changes
to source interpretation or supported scope back to Nicolas rather than silently
choosing a new policy. Recent retention and other unestablished source facts remain
unknown unless further evidence resolves them.

## Evidence and completion

Continue the existing private Swiss research record and certification workflow.
Select exact retained inputs and independently reviewed RivRetrieve and archive
code revisions before running code with private evidence. Changes to governing
claims, source bindings, verifiers or collections require their applicable full
checks. Missing mandatory genuine inputs block acceptance; synthetic fixtures,
exploratory samples and skipped checks cannot replace them.

Fix bugs found within the agreed scope, protect the corrected behavior with focused
tests, and rerun affected checks. Keep necessary shared-engine fixes proportionate.
Do not add LINDAS, runtime API/file fallback, a national-download interface or a
compatibility layer for Existenz. Leave exact test selection and reversible
implementation mechanisms to the implementing agent.

Complete this Effort with a reviewable account of the supported scope, exact code
and evidence revisions, completed checks, defects corrected and remaining limits.
Acceptance must cover the complete integration, not merely repeat earlier passing
counts. Keep controlled inputs, detailed private outputs and credentials outside
public logs, caches and distributions; publish only reviewed safe summaries.
Provide #565 and Thiago's later review with the verified behavior and limitations.
Do not close #564 while mandatory verification remains blocked or silently narrow
scope to make the checks pass.
