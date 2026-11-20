# Chile user documentation

Deliver the user documentation for [Chile Step 7, #737](https://github.com/RivRetrieve/RivRetrieve/issues/737), under [Program #734](https://github.com/RivRetrieve/RivRetrieve/issues/734). A hydrologist with basic Python knowledge should be able to prepare the DGA historical archive, retrieve supported discharge records, and understand the result and its limits.

Completing this work completes #737. Publishing this vision does not complete the issue or authorize implementation. Work stays on `port/cl-dga`; final review in #738 remains separate and requires @thiagovmdon's approval before merging the port to `main`.

## Follow the existing documentation

Add `docs/providers/cl_dga.md` and the ordinary documentation links needed to discover it. Follow `docs/AGENTS.md`, step 7 of `docs/maintenance/provider-ports.md`, and the existing pages in `docs/providers/`. In particular, use `ca_eccc.md` as the precedent for an explicit national download followed by local retrieval. Reuse the existing layout and exact shared retrieval-table columns. Do not design a new documentation structure or repeat the general usage guide.

Include a practical example with verified output, its download prerequisites, and an explanation of what the result demonstrates. Choose the station, period, and amount of example code during implementation, following existing provider pages. There is no requirement for a separate monthly example. A successful example does not establish continuous station or national coverage.

## Explain the delivered capability faithfully

Steps 1–6 are complete on `port/cl-dga`. Start from their current implementation and handoffs, especially the [Step 6 completion record](https://github.com/RivRetrieve/RivRetrieve/issues/742#issuecomment-7039087798), rather than reopening provider design or inheriting the original CR2 proposal.

Cover the source-specific facts that affect use:

- DGA/MOP publishes the selected national historical daily and monthly discharge ZIPs through `mapas2`. `cl_dga` requires explicit download and compilation before local retrieval, with no credentials. Explain preparation and refresh using existing bulk-provider conventions.
- The supported products are `discharge_daily` and `discharge_monthly_mean`, with source and returned units of m³/s. Daily statistic remains unknown; the monthly product is a published mean. RivRetrieve does not calculate these monthly values from the daily result. Explain the consequence for selection filters.
- Time zone and daily temporal meaning remain unestablished. Midnight labels do not establish UTC or interval boundaries. Explain monthly calendar selection according to the delivered behavior without presenting its timestamp carrier as a source fact.
- Duplicate daily dates, including conflicting values, are preserved. Published monthly means do not guarantee a complete month of daily observations: verification found no minimum-day threshold and months based on one day. Do not describe this observed arithmetic relationship as a documented agency quality rule. No source quality/status column was published in the supported files; do not invent quality judgements or annotation schemas.
- Catalogue membership does not guarantee data for a requested period. The verified snapshot has 784 stations and records from 1960 through September 2026, with varying station coverage and no pre-1960 records in these archives. Treat counts and endpoints as snapshot observations, not permanent availability promises. Source publication vintage remains unknown (`None`); access time or ZIP timestamps must not substitute for it.
- Keep supported station metadata and its unknowns consistent with the existing station-metadata documentation. Link the shared explanation rather than duplicate it.
- Explain DGA/MOP attribution and the MOP portal's non-commercial reproduction and citation conditions, with links to the official terms. Written permission requirements for commercial reuse or adaptation and unestablished dataset-specific licensing must remain visible. `license = None` is not unrestricted reuse. RivRetrieve's MIT licence covers software, not source data or packaged metadata; maintainer approval is not agency permission.
- Historical discharge is the delivered scope. Operational Hidrolínea telemetry, river stage, and water temperature remain deferred. State the practical exclusion; keep detailed transport constraints, alternative-route research, and correspondence in the private record.

Keep the detailed investigation and controlled material in the private verification archive. Use public source references and concise consequences in the provider page. Existing Program and Step 6 records supply the evidence handoff, including the ten-basin CAMELS-CL comparison; this documentation task does not repeat that study or turn it into a new public research report.

## Evidence of completion

The provider page and its discovery links follow existing conventions and agree with the delivered provider. Run its practical snippets through the public API against genuine source data using isolated cache/store roots, retain the verification evidence through the existing maintainer process, and show only outputs actually checked. Review exact code revisions before using private evidence. Missing mandatory evidence is a blocker, not a reason to fabricate example output.

Check documentation links and relevant repository checks for the changed surface. Keep source semantics, unknowns, terms, and limitations intact when simplifying prose. This is documentation work, not authorization to expand provider scope or change runtime behavior. If verification exposes a material implementation defect or conflicting source evidence, report it and resolve the boundary before documenting a claim as supported.
