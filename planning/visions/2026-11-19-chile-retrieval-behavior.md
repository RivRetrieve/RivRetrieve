# Chile retrieval behavior

Associated discussion: [#735](https://github.com/RivRetrieve/RivRetrieve/issues/735), under [Chile Program #734](https://github.com/RivRetrieve/RivRetrieve/issues/734).

Executing this vision completes Step 4 (#735) by establishing and verifying an evidence-backed retrieval contract. Publication alone leaves the issue open. This is research and contract verification, not production provider implementation. Step 5 (#741) owns the downloader, compiler and public-API integration.

## Outcome

Establish how RivRetrieve will acquire, compile and query the two selected DGA national historical exports without silently losing or changing source records:

- `https://mapas2.mop.gob.cl/caudal_diario_historico.zip`
- `https://mapas2.mop.gob.cl/caudal_medio_mensual_historico.zip`

Deliver a defensible handoff covering acquisition, accepted schemas, bounded-memory compilation, date selection, empty answers, failures, revisions and completeness. Completeness means fidelity to the acquired publication, not continuous observations or all records DGA holds. Keep unsupported claims explicit rather than inventing defaults.

Work remains on `port/cl-dga`. Follow Step 4 of `docs/maintenance/provider-ports.md`, `docs/maintenance/evidence.md`, and the private archive's intake and verification rules. Continue the existing private record `research/cl-dga-source-access.md` in `RivRetrieve/verification-evidence`; do not create a competing research record. Keep controlled material and correspondence out of public repositories and artifacts. Review exact revisions before executing code with private evidence.

## Settled scope and fidelity

The selected architecture is `BulkStore`: explicit national-artifact acquisition and compilation followed by local selection. Do not reopen the source choice or add CR2, regional acquisition routes, operational Hidrolínea, river stage or water temperature. Earlier steps established source scope, station identity and physical meaning; use their evidence and existing `providers/cl_dga/series.py` mappings rather than duplicate them.

Preserve:

- Eight-digit station codes, including leading zeros.
- Duplicate row multiplicity, including conflicting values on the same date. Do not deduplicate or average them away.
- Genuine zero flows, scientific-notation values and native source units.
- Native daily `FECHA` and monthly `Año`/`Mes` columns, alongside engine-facing date carriers. Apply the shared source-column disposition contract to every source column.
- The distinction between published nulls or blanks, absent rows, an empty station/window selection and a failed acquisition or invalid archive. Do not fill absent records or invent a universal missing-value encoding.

The Step 3 record reports 6,838,571 daily rows, 235,185 monthly rows and 784 stations in the checked snapshot, including 2,442 duplicate daily station/date keys. These are evidence observations, not fixed future sizes or runtime acceptance constants. Daily statistic and unestablished temporal facts remain unknown. Monthly mean values remain the published product, not a new aggregation computed from daily rows.

## Acquisition and compilation contract

Build on the Step 1 transport observations, distinguishing retained evidence from probes that were not retained:

- Use HTTPS GET through `request.transfer`, not HEAD-based `request.probe`; observed HEAD responses did not describe the ZIP correctly.
- Keep TLS verification enabled with the supported certifi-backed transport. Treat the handoff's read timeout of at least 90 seconds as a starting recommendation to verify, and establish bounded backoff for transient 503 responses and interrupted streams through the shared transport rather than introducing a provider-specific bypass.
- Stream acquisition and process the approximately 863 MB daily and 29 MB monthly uncompressed text with bounded memory. Reuse suitable retained inputs and minimize redundant national downloads.

Establish accepted archive members, encoding, delimiters, column names and types, date parsing, and validation of complete versus truncated or malformed input. The known national monthly schema omits `FECHA`; the regional example includes an empty `FECHA` column. Account explicitly for this evidenced difference without treating it as permission to accept arbitrary schema drift or to add a regional runtime route.

Specify how compilation will satisfy `docs/design/observation-store-layout.md`: native values, source-column preservation, duplicate retention, bounded processing, source/store verification and publication only after validation. Determine source vintage from defensible source evidence under the existing manifest contract; retrieval time and HTTP modification time must not silently substitute for a source release or coverage label. If the contract cannot represent an established source fact, identify the shared gap rather than bypassing it.

Investigate snapshot identification, refresh/revision behavior and completeness limits. Distinguish what one retained edition proves from what requires comparison across editions or agency documentation. Do not promise an update cadence, revision history or exhaustive historical availability without evidence. Establish failure and replacement behavior under shared bulk-store rules so an invalid new artifact cannot be mistaken for an empty successful result or a valid replacement store.

## Date selection and resolved shared dependency

Daily date-only `DD/MM/YYYY` labels use `ClippingAxis.CALENDAR_DATE`, a naive midnight carrier and an unknown time zone. Preserve raw `FECHA` and do not interpret the carrier as a measured instant.

Monthly year/month labels use explicit `ClippingAxis.CALENDAR_MONTH`. A request from January 15 through March 10 selects January, February and March, excluding adjacent months. Preserve raw `Año`/`Mes` and the synthetic first-of-month carrier without asserting a timestamp anchor, time zone or complete observations within a month.

[#915](https://github.com/RivRetrieve/RivRetrieve/issues/915) delivered this opt-in shared capability through [#917](https://github.com/RivRetrieve/RivRetrieve/pull/917), merged to `main` at `3a7865bd`. See the [shared vision](https://github.com/RivRetrieve/RivRetrieve/blob/main/planning/visions/2026-11-19-calendar-month-selection-for-year-month-source-labels.md). This supersedes the earlier Step 3 first-day clipping limitation. Monthly frequency alone does not enable the mode; timestamp-labelled monthly series retain their existing clock-bound behavior.

At authoring, `port/cl-dga` is at `8eb28a10` and does not yet contain that shared change. Step 5 must include it and opt the Chile monthly mapping into the mode. Step 4 may verify the already merged shared behavior against its reviewed revision without merging production changes into the port. Do not reimplement or redesign the resolved shared capability.

Relevant boundaries are `physical_window.py:native_window`, the fact-aware scan envelope in `driver.py:drive_store`, `conversion.py`, and the existing bounded `store/reader.py` query interface. The shared helpers align selected rows, annotations, validation and outcome windows.

## Evidence and completion

Complete Step 4 when:

1. The continuing private research record contains the adopted retrieval contract, supporting evidence references, checked exceptions and explicit unknowns. A safe summary on #735 links the handoff and identifies what Step 5 must implement.
2. Genuine-input checks establish the accepted source schemas, identifier/date/value handling, row multiplicity and publication-relative completeness. Test failure mechanics with suitable controlled cases without presenting synthetic cases as source evidence.
3. Date-boundary expectations cover daily dates and leap days, mid-month monthly selection, adjacent-month exclusion and year boundaries. Reuse #915's shared verification for engine behavior; distinguish it from Chile source parsing and later end-to-end integration.
4. Empty-selection semantics, acquisition/archive failures and safe refresh behavior are specified against existing shared contracts. Missing mandatory evidence or an unrepresentable required fact is reported as blocked, not weakened into a passing check.
5. The Step 5 handoff distinguishes verified source facts, retained unknowns, required provider wiring and any remaining shared gaps. Keep source-certification tooling and controlled inputs in the private archive; run affected source-independent checks for any research-support changes in RivRetrieve.

No production downloader, compiler, provider activation, new source scope, external correspondence or final port approval is authorized here. Step 6 retains the mandatory ten-basin CAMELS-CL comparison; this research does not replace it. Step 7 owns the complete user-facing source terms and limitations documentation. Existing source terms, DGA/MOP attribution and `license = None` remain unchanged.

Leave reversible implementation choices such as batching, temporary storage and helper organization to Step 5 within the established contracts. Execution may use bounded research scripts and verification work needed for this evidence outcome; it must not silently expand into provider integration.
