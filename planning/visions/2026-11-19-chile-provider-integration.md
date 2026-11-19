# Chile provider integration

Make the established `cl_dga` catalogue usable for observation retrieval through RivRetrieve's public APIs. Users explicitly download and compile DGA's national historical archives, then query daily discharge and monthly mean discharge from the local store.

This vision delivers [Step 5, #741](https://github.com/RivRetrieve/RivRetrieve/issues/741) of [the Chile Program, #734](https://github.com/RivRetrieve/RivRetrieve/issues/734). Successful implementation and its required checks complete #741. Publishing this vision does not complete the issue or authorize implementation by the publishing agent. Work remains on `port/cl-dga`; full source verification and the ten-basin CAMELS-CL comparison remain in #742, user documentation in #737, and final review by @thiagovmdon in #738 precedes any port merge to `main`.

## Established scope and starting point

Use the direct DGA publications at `https://mapas2.mop.gob.cl/caudal_diario_historico.zip` and `https://mapas2.mop.gob.cl/caudal_medio_mensual_historico.zip`.

The preceding work established catalogue, physical facts, and acquisition behavior. Follow the [Step 4 handoff](https://github.com/RivRetrieve/RivRetrieve/issues/735#issuecomment-7010276234), the [retrieval vision](2026-11-19-chile-retrieval-behavior.md), and the continuing private [research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/cl-dga-source-access.md), including its Step 4 section. Evidence and its acceptance record are linked from that handoff; do not reproduce controlled material in public files or logs.

At authoring, `port/cl-dga` is at `bfa22787` and declares `cl_dga` as `CatalogueOnly`. It already contains catalogue artifacts and `SERIES_MAPPINGS` for `discharge_daily` and `discharge_monthly_mean`. Bring the relevant `main` changes onto the port branch before integration. In particular, #917 (`3a7865bd`) supplies `ClippingAxis.CALENDAR_MONTH` and the shared revision-10 store baseline. Inspect the current contracts rather than copying an older provider implementation.

The retained source snapshot contains 784 stations and data spanning 1960–2026. These are evidence observations, not fixed counts or promises of continuous coverage for future downloads. Keep ZIP-backed station discovery, `ProviderInfoCatalog.license = None`, DGA/MOP attribution, and the existing data-rights distinction between software and provider data.

## Shared support for an unknown publication date

Include the bounded shared-engine change agreed in [the scope discussion](https://github.com/RivRetrieve/RivRetrieve/issues/741#issuecomment-7011111204). It is separate from #917's month-selection feature.

DGA's static archives supply no established source publication date. Permit an explicitly unknown `source_vintage` throughout the bulk download/compile contracts, compiled manifest serialization and validation, and affected consumers. Never substitute retrieval time, HTTP `Last-Modified`, ZIP timestamps, or the latest observation date. Keep artifact URLs and checksums as input identity and keep build time as build time.

Preserve existing behavior and regression safeguards for providers with established source dates, including Canada and Poland. Handle the shared multi-artifact path deliberately: a dated artifact must not silently supply a date for an unlabelled artifact. Leave the precise representation and any necessary store-format handling to implementation, consistent with current repository policy. Update public interface explanations where the meaning of `None` changes.

Initial inspection suggests a focused contract change, not a broad store redesign. If implementation reveals that a broader redesign is needed, return to the maintainer before expanding #741.

## Provider behavior

Connect the catalogue, provider configuration, `BulkStore` declaration, downloader, and bounded-memory compiler through the shared engine. Start with one representative public-API path and extend it to both supported products.

- Download the two national ZIPs with unauthenticated HTTPS `GET` through `BulkDownloadRequest.transfer`, not `HEAD`-based `probe`. Reuse shared TLS verification, retry behavior, storage lifecycle, and disk-space admission.
- Enforce the verified national single-member UTF-8/LF/comma schemas: 13 columns for daily and 14 for monthly. The regional 15-column monthly schema is outside this integration. Treat archive corruption, schema drift, malformed rows, and failed certification as failures rather than empty data.
- Compile with bounded memory into the shared product/year partitions. Retain raw source fields through qualified `SourceColumnDisposition` closure, including date labels, discharge strings, and station metadata. Preserve 8-digit station identifiers, leading zeros, all duplicate rows and conflicting values, genuine zero flows, and supported scientific notation. Do not hard-code the observed station or year counts.
- Reuse the established source-series mappings. Both products use `m3/s`; daily statistic remains unknown and monthly statistic is mean. Do not infer daily means, time zones, timestamp anchors, temporal support, quality rankings, or a universal missing-value rule. Preserve source unknowns and distinguish published nulls, absent rows, and failed acquisition.
- Opt `discharge_monthly_mean` explicitly into `ClippingAxis.CALENDAR_MONTH`: January 15–March 10 selects January, February, and March without claiming a timestamp anchor or complete monthly coverage. Preserve daily calendar-date selection and leave existing timestamp-labelled monthly providers unchanged.
- Querying an unprepared store must explain the explicit download step and start no implicit transfer. A valid station/window selection with no rows yields `OutcomeStatus.EMPTY`. Compilation and refresh must fail before commit on invalid inputs, preserving any prior valid store. A valid refresh atomically replaces the snapshot, including legitimate publisher removals.

Do not recompute the published monthly series from daily data, deduplicate daily records, fill gaps, or impose a minimum-day threshold. The research found monthly averaging over all published daily rows, including duplicates and single-day months; retain the published products independently.

Shared transport currently has a 60-second timeout and buffers the compressed daily ZIP (about 35.8 MB in the retained snapshot), while the uncompressed daily text is about 863 MB. Keep compilation bounded. Do not change the timeout merely to match the earlier 90-second research recommendation; investigate a shared transport change if integration or verification reveals read stalls beyond the current limit.

## Evidence of completion

Develop focused tests alongside implementation under the repository's test-first and testing guidance. Extend existing shared contracts rather than duplicating their coverage.

The completed effort must demonstrate:

- Offline discovery still works and explicit download/compile followed by public-API retrieval works for both products.
- Unknown source vintage survives compilation, manifest validation, and exposed provenance without a fabricated date; dated-source behavior remains protected.
- Daily values, source identities, date labels, duplicate multiplicity, zeros, and leading-zero station codes survive the pipeline. Month-touched selection and year boundaries work through the compiled store.
- Empty selections stay distinct from acquisition or compilation failure, and a failed refresh leaves the prior certified store usable.
- The compiler handles the genuine national inputs within bounded memory and retains the required source fields without weakening validation.

Run affected source-independent checks and the applicable genuine-input checks required by `docs/maintenance/evidence.md`. Review exact code revisions before private evidence execution and extend the existing archive process rather than creating another verification system. Record completed checks and limitations in the continuing private research handoff. Missing mandatory evidence is blocked, not passed. Step 5's integration evidence does not replace Step 6's complete source certification and required random ten-basin comparison.

## Boundaries

Do not expand to CR2 retrieval, regional downloads, Hidrolínea telemetry, stage, temperature, stateful JSF transport, mixed bulk/live provider support, or new hydrological interpretations. Preserve unresolved source semantics and terms. Step 7 owns the full user-facing explanation of MOP conditions and limitations; necessary API docstring changes belong with the changed interfaces here.

Leave compiler mechanics, helper structure, test placement, and other reversible implementation choices to the implementing agent. Reopen research when implementation would otherwise require unsupported source assumptions.
