# Poland publication-aware history discovery

## Outcome

Make `rr.download("pl_imgw")` build or refresh a valid store from the history IMGW-PIB has actually published, including during the delay between a hydrological year's end and its publication. Discover publication from authoritative source evidence rather than assuming a calendar-complete year has a downloadable archive.

This standalone production repair addresses [bug #371](https://github.com/RivRetrieve/RivRetrieve/issues/371), found during [Poland documentation PR #291](https://github.com/RivRetrieve/RivRetrieve/pull/291). That review is paused under `planning/visions/2026-09-24-poland-provider-documentation-review.md`. [PR #370](https://github.com/RivRetrieve/RivRetrieve/pull/370) already repaired multi-artifact source vintages; retain its guarantees. PR #291 is context only and entirely out of scope. Do not modify, verify, resume, or merge that documentation PR as part of this work.

## Publication behavior

Use authoritative IMGW-PIB publication evidence to discover available daily archives. The calendar can constrain plausible periods; it cannot establish that an archive exists. Do not repair this by imposing a fixed publication lag or by treating arbitrary HTTP 404 responses as unpublished years.

Download continuous published history from the existing public starting year, 1951, through the latest supported published period. Include a partial hydrological year when monthly archives support it; do not wait for a complete year merely because today's publication layout is annual. The source vintage is the publisher-labelled coverage end of the latest downloaded archive, not the current date, publication timestamp, or latest non-null observation.

Support the evidenced annual and monthly archive forms, including publisher replacements between those forms. Do not permanently assign publication layout using the current 2023 year threshold. Inspect publisher notices, listings, and archive evidence to establish how a replacement can be identified. Do not guess precedence when annual and monthly archives overlap ambiguously. Unsupported formats and unresolved overlap must fail clearly rather than select, concatenate, or deduplicate competing source editions without evidence.

Distinguish an unpublished trailing period from a genuine historical gap. Missing or failed artifacts inside published history must fail closed, not silently truncate the history to the last successful transfer. Discovery failures, malformed source evidence, and transfer failures must not masquerade as ordinary publication delay. If the available evidence cannot establish a safe history, report the failure rather than invent completeness. A failed discovery, download, or compilation must preserve an existing valid store and its provenance; retain established publication, cleanup, and recovery guarantees.

Continuity refers to archive periods, not to daily completeness for each station or variable. Preserve source cells, nulls, absent rows, vocabulary, and unknowns. Do not infer source quality, observation availability, or hydrological meaning from archive presence. Preserve exact downloaded-file provenance and the individual and aggregate vintage validation introduced by #370.

## Repository and source evidence

At authoring, `src/rivretrieve/_internal/providers/pl_imgw/bulk.py` calculates the latest completed hydrological year and plans every archive through that year. `plan_imgw_artifacts` assumes monthly archives before 2023 and annual archives thereafter. `download_imgw_history` transfers the plan and removes already downloaded files if a transfer fails. The compiler also enforces that year-based layout split in `_imgw_artifact_period`; discovery and compilation must agree on accepted source-backed forms without weakening period, identity, ordering, or overlap validation.

`src/rivretrieve/_internal/providers/pl_imgw/declaration.py` adapts the shared download request. The shared `BulkDownloadRequest` already supplies a HEAD probe and transfer dependency, but Poland currently uses only transfer. This is an available mechanism, not a prescribed discovery solution. Keep external-input parsing at its boundary and resource wiring at explicit composition boundaries. Preserve the public API; choose the smallest provider-specific design justified by evidence rather than creating a generic discovery framework.

The reproduction in #371 advances the planning date to 2026-11-01: the planner requests `2026/codz_2026.zip` even though it was absent when checked on 2026-09-25. The preceding 2025 archive was available. The publisher's change list records long publication delays: 2023 added in August 2024, 2024 products added in July/August 2025, and 2025 added in August 2026. These are evidence of the defect, not a schedule to encode.

Authoritative source locations include:

- Daily archive root: https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/
- Publication notice: https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/UWAGA.txt
- Change list: https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/lista_zmian_hydro.txt

The preserved root notice says 2023 and 2024 were published in single annual files for technical reasons, with fields retained but possible field-format changes. It says files will be regenerated using the previous method and announced in the change list. This supports investigating layout replacements, not assuming an undocumented future format. Current source behavior must be rechecked during implementation.

Existing local evidence is under `.worktrees/poland-provider-evidence-2026-09-24/`, including `repro_unpublished_year.py`, its log, and `sources-2026-09-25/`. This is optional supporting evidence, not a durable dependency of the implementation. Some preserved per-year `UWAGA.txt` responses are 404 HTML; do not confuse them with the successfully fetched root notice. The issue contains a standalone reproduction and source references.

## Observable acceptance

The public download path must succeed against a published history when the next calendar-complete year has not yet been published. Returned and reloaded store status must report exactly the downloaded archive coverage end, with ordered exact artifact provenance. Newly available supported monthly periods must extend a continuous history without waiting for the year to finish.

Regression evidence must cover publication delay, no available supported history, partial years, annual/monthly transitions and replacements, historical gaps, duplicate or ambiguous overlapping periods, invalid discovery responses, and discovery/transfer/compiler failures. Include preservation of an existing valid store on failure and the existing source-vintage and certification protections. Exercise the real declaration and compiler as well as discovery, not only isolated planner mocks. Tests must distinguish trailing nonpublication from an artifact disappearing or failing after discovery; the latter is not permission to silently shorten the store.

Recheck the current live publication evidence and run the public full-history download and store verification. Record the source date, discovered coverage, provenance checks, and resulting vintage. Use controlled regression cases for publication delays or replacement states not currently observable live; do not label simulated evidence as live. Run the relevant provider, bulk-store, and public recovery tests plus repository-required lint and type checks. If the live source blocks validation, report the precise blocker rather than claiming successful verification.

## Boundaries

This work is deliberately broader than a calendar patch but remains a Poland-specific repair. There is no resource-driven reason to omit source investigation or thorough verification. There is also no mandate to predict unknown future formats, redesign all providers, change the store format or catalogue, reinterpret observations, or rewrite documentation PR #291. Preserve existing supported source-failure boundaries outside this bulk operation.

The deliverable is the production bug repair PR or commit and its verification evidence. No documentation-review follow-up is part of this work. Publishing this vision does not implement the repair.
