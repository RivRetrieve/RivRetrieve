# USGS provider documentation review

## Outcome and delivery

Update the existing [USGS provider documentation PR #266](https://github.com/RivRetrieve/RivRetrieve/pull/266), on `docs/provider-usgs` targeting `main`, with an accurate reader-facing page and PR description. Do not open a replacement implementation PR. This is a standalone vision, with no Program or Effort provenance.

Thiago's page predates the physical-facts API redesign and the modern USGS implementation. Preserve useful structure, wording and contributions where accurate, but investigate every claim rather than mechanically replacing obsolete API calls. The deliverable describes how RivRetrieve works now. It is a migration of the documentation itself, not a migration guide for readers. There are no users requiring backward-looking guidance.

The primary file is `docs/providers/usgs_nwis.md`. Preserve its index link in `docs/README.md` while integrating the current target branch without losing other provider links. Focused documentation tests and durable verification evidence are in scope. Unrelated documentation rewrites and production changes are not.

## Mandatory writing guidance and human gate

Read and follow `docs/AGENTS.md` as mandatory guidance. Both author and independent reviewer must check the revised file against it. The accepted French, Swiss and Japan pages are the strong editorial references, not merely historical PR drafts:

- `docs/providers/ch_foen.md` (PR #289);
- `docs/providers/fr_hubeau.md` and `docs/providers/fr_hydroportail.md` (French documentation work originating in PR #264);
- `docs/providers/jp_mlit.md` (PR #290).

Use their current accepted versions on the target branch. Write for an educated hydrology reader with basic Python knowledge. Explain the national context, who measures and publishes the data, and what RivRetrieve provides. Describe the practical consequences of units, time, source status, availability and terms. Do not turn the page into a mechanical API reference or an implementation audit. Link to Usage for general API instruction. Keep readable, spaced snippets and explain what their outputs demonstrate. Avoid migration narratives, unexplained engineering terms and speculative source meanings.

**The user must review the revised USGS file itself before this work concludes.** Present the exact candidate file and PR, allow feedback, revise as requested, and reverify changed examples and claims. Updating the PR and sending a final report is not a substitute for this human gate. Independent technical review does not replace the user's editorial review. The implementing agent must not approve or merge PR #266 on the user's behalf. Leave it open for the user to merge.

Publication of this vision is a separate documentation-only handoff; it does not waive the implementation PR's human gate.

## Current implementation baseline

[PR #342](https://github.com/RivRetrieve/RivRetrieve/pull/342) merged at `2c1329389441b19b4c39ec2f1c6224dafac36ec4` and delivered the work tracked in issues #279 and #327. Those issues are closed. The user reported the repair and authorized resuming this documentation review. Reconstruct the latest target state before implementing; do not rely on older loaded code or port notes.

Current USGS observation retrieval uses only Water Data API v1 at `https://api.waterdata.usgs.gov/ogcapi/v1/`. The public provider name remains `usgs_nwis`. Do not describe the retired observation route as current, suggest migration work is pending, or add the earlier proposed retirement warning. Do not repeat development-cache incompatibility guidance on this provider introduction.

Inspect current `metadata.py`, `catalogue_series.py`, `fetch.py`, `parse.py`, provider declaration and packaged artefacts under `src/rivretrieve/_internal/providers/usgs_nwis/`, plus the shared public API. `docs/usgs-discovery.md`, the retained modern source evidence and tests are useful navigation aids, not substitutes for checking implementation and authoritative evidence. Older USGS visions and port notes describe historical behavior and may contain superseded facts.

The six supported routes cover daily mean discharge; daily mean, maximum and minimum stage; and continuous discharge and stage. Water temperature support is outside scope. Physical filters must reflect established source facts. In particular, continuous publication does not establish a sampling frequency, and records with unknown statistic must not be advertised as matching `statistic="instantaneous"`.

Daily values retain date labels represented at midnight with unknown day definition/time zone. Do not derive physical day bounds from metadata range timestamps. Continuous observations preserve their published offsets. Explain the current returned representation rather than carrying over old local-offset examples. Verify unit conversions, approval/qualifier handling, present nulls, absent rows and failed requests separately. Approval vocabulary does not establish RivRetrieve quality judgement, and successful retrieval does not establish source approval. Optional source receipts and general issue interpretation belong behind links to Usage unless needed for the example.

Personal credentials are not required for modest public requests; `USGS_API_KEY` is optional. Verify the actual current configuration and authoritative access guidance before stating the credential and rate-limit conditions. Check national context, source publication, terms and citation against authoritative sources for the route now used.

## Published series and the meaning of variant

This distinction was central to discovery and must be clear in the final page:

- Each concrete USGS time series has a publisher ID. Current metadata `id` and observation `time_series_id` identify the same published series; RivRetrieve exposes that ID through `variant`.
- The IDs are specific to published series, not a shared provider-wide menu such as Brazil's `bruto` and `consistido`.
- A station can have more than one separately published series matching the same quantity, frequency and statistic. Those are the alternatives the reader may need to distinguish.
- A populated `variant` field on a singleton does not mean that alternative versions exist. Do not tell readers that every station has variants in that everyday sense.
- Prefer “published time series” and “USGS time-series ID” in prose. Explain once that the ID can be passed to `variant=`. Do not call modern IDs measurement-method names or infer their meaning from the identifier.
- `find` and `series(selection)` expose packaged series offline. `pick` can select a known ID before retrieval. Unrestricted retrieval keeps all matching series and may discover additional identities. No library-selected winner, implicit averaging or collapse across identities is promised.
- Multi-station retrieval does not require a list of manually chosen variant IDs. Select stations and physical facts and fetch. When several matching series are returned, retain `series_id` in analysis rather than assuming station/date alone uniquely identifies a value.
- There is no current public USGS Primary/Secondary selector. Source `Primary` is not a unique preferred-series label, and approval status is not a series variant. Do not add new API capabilities in this work.

These semantics align with the source-fidelity design carried through PR #300; modern publisher identities were introduced by #342. Explain current behavior without putting that development history on the reader's page.

### Prevalence: alternatives are a minority

An offline public-API count on the merged #342 baseline found 59,159 concrete series across 26,201 selectable stations. The catalogue retains 26,258 station identities in the established 50-state-plus-DC scope. Use supported/selectable station counts consistently with the root README, and qualify snapshot availability without suggesting a live-network census.

Grouping `rr.series(rr.find(provider="usgs_nwis"))` by `station_id`, `quantity`, `frequency`, and `statistic`, then counting distinct `variant` values, gave:

| Observations | Stations with multiple matching series | Stations with these observations |
| --- | ---: | ---: |
| Daily mean discharge | 134 | 24,495 |
| Instantaneous discharge | 111 | 13,286 |
| Daily mean stage | 131 | 5,677 |
| Daily maximum stage | 24 | 1,673 |
| Daily minimum stage | 23 | 1,646 |
| Instantaneous stage | 286 | 11,638 |

Across all groups, 575 distinct stations (about 2.2%) had multiple matching series. Stations can appear in several table rows. Daily mean discharge alternatives occur at about 0.55% of its stations. These counts do not establish overlapping observations or live availability. Six additional continuous records have unknown statistic and are not included in the instantaneous rows.

Recompute any count retained in the page against the implementation candidate. Include a concise prevalence explanation so the exceptional multi-series example does not imply every daily-discharge station requires a choice. Do not reproduce this full audit table merely because it is in this handoff. Keep detailed counting methods in maintainer evidence.

## Reader-facing shape and examples

Use the same summary and quantity-table conventions as the accepted provider pages. The quantity table should explain published observations and source/returned units, not lead with internal product names or numeric parameter/statistic codes. Remove the original per-product earliest-record-date table and the “only provider” comparison. Remove the obsolete promise that `rr.as_frame(selection)` exposes published coverage dates.

Keep a short practical daily mean discharge example at station `07374000`, with station context checked against the source. Use physical filters, show a small output preview, returned row count and issues, and explain units and daily labels. A one-week window avoids a needlessly large introductory request. Do not force a singleton variant choice as a prerequisite to ordinary retrieval.

Add a clearly station-specific table and focused example showing the two daily mean discharge series at `02196000`, offline inspection and explicit selection. Full IDs must remain copyable. The table is not a provider-wide list of named categories. Use publisher descriptions if supplied; distinguish missing descriptions from invented meanings. If metadata dates help explain the example, label them as dated metadata bounds, not uninterrupted record coverage or public fields that `rr.series` does not actually expose.

At the discovery baseline:

| Station | USGS time-series ID exposed as variant | Description |
| --- | --- | --- |
| `07374000` | `c9d823a2491f4b639656a11b35a7625d` | null |
| `02196000` | `0df18b246e8f48ec8e6547a92070e94a` | null |
| `02196000` | `4d186669708e4dc18f84d271efb953a1` | null |

The latter two describe daily mean discharge in ft³/s, returned in m³/s. Retained metadata starts both in November 1929; it ends the first in September 2026 and the second on September 29, 2005. Their metadata descriptions do not explain their relationship. Neither range, parent linkage, numerical agreement nor the shared label `Primary` establishes a preferred series. Do not claim USGS recommends fetching all series; returning all matches is RivRetrieve's faithful default, not a scientific recommendation.

### External investigation supplied during discovery

The user supplied a separate model's investigation reporting that the two `02196000` records differ on some overlapping dates, with no located authoritative explanation or preference. It quoted the USGS metadata schema as defining `web_description` to distinguish multiple series for the same location, parameter and statistic. It also reported that both are `Primary`, one has a parent series, and the other has a null parent despite the schema's general parent description.

That report's scripts and raw responses were said to be in the other model's scratchpad, but no durable location was supplied here. It is a research lead, not independently verified evidence for this implementation. Acquire or obtain inspectable evidence before relying on its additional numerical or textual claims. Do not claim earlier sampled years prove identity over the entire historical overlap, interpret modification timestamps as revisions, label the older series superseded, or repeat a hypothesis that the newer series was recomputed. Do not promise the agent searched every USGS document. If no explanation can be established, say the available source descriptions do not explain the relationship. No USGS contact or response is a prerequisite imposed by this vision.

Keep detailed regional surveys, parent analysis and precision comparisons out of the provider introduction. The useful message is that some matching series have unexplained distinctions, are retained separately, and cannot be ranked by RivRetrieve.

## Verification and inspectable evidence

Check every factual claim against current code, the packaged catalogue or authoritative sources. Record the claim, evidence, scope and date in maintainer-facing verification records. Source access failures must remain explicit; retained evidence is not a fresh content check. If network access is unavailable, preserve partial work and report the blocker. Do not substitute a replay for required live verification or bypass access restrictions.

Execute every final code snippet through the current public API in the repository's `uv` environment. Use live retrieval where applicable. Execute dependent snippets in their documented order and verify displayed outputs, row counts, units, time labels, issues, variants and promised selection behavior. Check both singleton and multi-series workflows. A typed or plausible snippet is not acceptance. If final edits change code or the tested behavior, rerun the affected examples. Keep exact tested page content and acquisition/output evidence tied to the candidate revision.

Distinguish fresh live execution, publisher-response replay tests, authored tests and code inspection. Preserve exact source responses/receipts where applicable using supported mechanisms; do not change production code or bypass safety checks to capture them. Run appropriate focused documentation and provider tests and repository checks for changed files. Seek independent review of the full page, final diff, source claims and execution evidence, not merely API syntax.

Discovery evidence is only a starting point. At merged #342, exploratory public runs found:

- Selected `07374000` daily mean discharge for January 1–7, 2024: seven rows, no issues, the same ID before/after retrieval, daily zone `unknown`; first three returned values 4927.1313070080005, 5125.349233152 and 5238.61661952 m³/s.
- Unrestricted `02196000` daily mean discharge for January 1–7, 2000: fourteen rows across the two listed IDs, no issues.
- `uv run pytest -q tests/test_usgs_modern_discovery.py tests/test_usgs_nwis_public_routes.py`: 14 passed in 36.77 seconds.

These exploratory outputs do not constitute execution of the final page, exhaustive historical parity, or raw source capture for this review. Do not relabel #342's historical validation or another model's report as this agent's fresh live verification.

## Mandatory defect stop gate

If implementation or verification finds a code defect:

1. Stop documentation implementation and publication of purportedly verified results.
2. Open a GitHub issue labelled `bug`, assign it to `CooperBigFoot`, and include revision, exact reproduction steps, expected/actual behavior and evidence. Issues #305 and #324 are the examples for quality and specificity.
3. Preserve the partial draft and evidence. Do not fix production code, weaken tests, silently change the example to avoid the defect, conceal it in prose, or bypass a broken recording path.
4. Wait until the user explicitly reports that the defect is repaired.
5. Reconstruct the repaired revision, reverify the affected behavior and final examples, then continue.

A source description being absent or a source service being temporarily unavailable is not automatically a production defect. Classify failures from evidence, disclose verification limits, and never declare the live acceptance gate complete while it remains blocked.

## Final acceptance and exclusions

The revised file explains the US source and one practical retrieval clearly, handles station-specific alternatives without implying universal raw/checked categories, and follows `docs/AGENTS.md` and the accepted French/Swiss/Japan examples. All final snippets work as advertised against the current public API, and every displayed result and material claim has inspectable evidence with honest verification scope.

Update PR #266's description to match its actual final changes and current verification. Do not leave obsolete API, catalogue, time, endpoint or temperature claims in the description. Include verification limits and distinguish live checks from tests. Preserve the existing PR and unrelated contributions.

Do not redesign `variant`, add quality filters, interpret missing source semantics, infer zones/day bounds, expand provider/product scope, implement USGS migration work, or repair production defects within this documentation effort. A broader engineering concern may be reported separately, but is not permission to expand scope.

Present the updated file for the user's review, respond to feedback, and wait for the human gate before concluding. PR #266 remains for the user to approve and merge. This vision does not authorize its approval or merge by any agent.
