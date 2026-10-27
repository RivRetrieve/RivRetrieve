# Swiss API provider documentation

Complete [#565](https://github.com/RivRetrieve/RivRetrieve/issues/565), the user-documentation Effort of [the official Swiss port](https://github.com/RivRetrieve/RivRetrieve/issues/545). Users should understand what `ch_foen` retrieves, run a verified example and interpret its results without reconstructing the source investigation. This vision completes #565 when the documentation is reviewed, corrected, verified and merged into `port/swiss-official-api`. Publishing this vision does not complete the issue.

## Adapt the established provider page

Update `docs/providers/ch_foen.md` for the official BAFU API. Follow the existing provider-page pattern, not a new structure. The original Swiss page on `main` has the overview table, a practical retrieval example with output and explanation, publisher context, supported-product tables, series selection, availability, status, time, terms and sources. The port branch currently has a shortened discovery-only page; use the original page and neighbouring provider pages as the structural reference, not as authority for current source facts.

Replace obsolete Existenz details with current delivered behavior. Describe the current provider rather than a migration history. Link general usage instead of duplicating it. Follow `docs/AGENTS.md`; explain hydrological consequences in clear prose, preserve qualifications and avoid implementation details that users do not need. Keep original correspondence and source evidence private.

## Established behavior and facts

The completed port at `bb53c4dca79dfbc0e7e99a1a9d314ab5ff318241` supplies anonymous official GraphQL retrieval and offline discovery. The packaged catalogue has 1,341 stations; this is neither universal product availability nor continuous historical coverage. Source identities, units and parallel variants remain separate. Do not revive Existenz field aliases, credentials, retention, terms or cache identities.

Document the delivered discharge (`discharge`), water level (`stage`) and water temperature (`temperature`) products: ten-minute/hourly means, daily/monthly/yearly mean/minimum/maximum products, and the separate recent raw feed. The public product page's abbreviated list omits some implemented monthly/yearly extrema; use accepted implementation and verification rather than narrowing scope to that list. Do not imply every station publishes every product or calculate unpublished products.

- Archive `tsName` values identify separate variants, not quality selections. Station 2602 has concurrent `TagMittel` and `TagMittel_01`; RivRetrieve does not choose the better-looking record or splice recent readings into aggregates.
- Archive units come from responses; recent units are independently bound to official station-page labels. Explain returned m³/s, metres and degrees Celsius, preserving native-unit distinctions. Sea-level reference labels do not establish a named observation datum; station-altitude LN02 is not an observation-datum binding.
- Ordinary aggregate timestamps mark interval starts and are returned in UTC. Daily/monthly/yearly periods use midnight in fixed UTC+1, including summer. Explain the preceding-date UTC label rather than rewriting it or applying daylight-saving time. Recent timestamps mark measurement end, but exact averaging durations remain unknown. Extrema describe short-term measurements, not extrema of daily means; their underlying measurement duration and occurrence time remain unknown.
- Station 7008's anomalous `MonatsMittel_Orbe_flex` retains unknown support despite BAFU's configuration-error explanation. Its route/name does not establish daily/monthly support, and station operating dates do not establish API coverage. Include only the consequence needed to interpret supported behavior, not the investigation diary.
- Later accepted publisher clarification gives null/0 the meaning raw, 1 unreleased/prechecked, 2 released/checked and 3 released/definitive. Published null remains null. The word `ersetzt` remains unresolved and supplies no replacement lineage or quality ranking. Source status fields remain in original response bodies, not canonical observation/cache columns; do not promise a returned quality column or status selector.
- Recent retention remains unknown: current API documentation contradicts itself between seven days and twelve hours. Do not promise either horizon. A cache cannot recover unseen expired observations. Availability differs by station, quantity, product and period. Distinguish null rows, absent rows and failures; successful examples do not prove continuous coverage. Broad selections can reacquire to discover variants, whereas explicit known variants can reuse covered intervals.

The source papers and correspondence were already investigated and verified through #559–#564. Later comments supersede older issue bodies. In particular, [#561](https://github.com/RivRetrieve/RivRetrieve/issues/561) resolves calendar and null-status meanings, and [#564](https://github.com/RivRetrieve/RivRetrieve/issues/564) records completed port verification and its limits. The continuing private record is `research/swiss-source-access.md` in the verification-evidence repository; use its current instructions and reviewed revisions for any retained-input work. Do not restart broad source certification for prose-only changes or substitute public research notes for mandatory evidence.

## Attribution and checked sources

Public source research was completed on 27 October 2026. Check final link destinations/content, not HTTP status alone: guessed hydrodaten FAQ paths can redirect to the homepage with status 200.

| Source | Use in the page |
| --- | --- |
| [Water observations](https://data.bafu.admin.ch/en/dataproduct-water-observations) | Dataset, source fields, products and UTC labels; retain known limitations of its abbreviated product list and conflicting retention prose |
| [API terms](https://data.bafu.admin.ch/en/lizenz-und-quelle) | Commercial/non-commercial use permitted; attribution required: author, title and dataset link |
| [Open-data terms](https://opendata.swiss/en/terms-of-use) | “Open use. Must provide the source”; do not relabel as CC-BY |
| [API structure](https://data.bafu.admin.ch/api-aufbau) | Read-only access without authentication |
| [Rate limits](https://data.bafu.admin.ch/rate-limits) | 500 requests per client IP per rolling five minutes; excess rejected with HTTP 403, not a promise of automatic waiting/retry |
| [Pagination](https://data.bafu.admin.ch/pagination) | Omitted-limit overflow check at 10,000 rows; explicit limits intentionally cap results. Link rather than narrate query internals unless useful |
| [Hydrodaten FAQ](https://www.hydrodaten.admin.ch/en/questions) | Context for measurement, time and source vocabulary; generic citation recommendation does not override mandatory API attribution |
| [Historical ordering service](https://www.bafu.admin.ch/en/hydrological-data-service-for-watercourses-and-lakes) | Brief additional official service link, not a RivRetrieve provider or runtime fallback |
| [Digital station/parameter directory](https://www.bafu.admin.ch/dam/en/sd-web/T5LfxlNaMOvN/verzeichnis-hydrometrische-stationen-digitale-daten.xlsx) | Explicitly dated 1 January 2023; contextual only if mentioned |

Suggested attribution: **Bundesamt für Umwelt BAFU, Hydrologische Beobachtungen, https://data.bafu.admin.ch/dataproduct-water-observations**. This is a suggested composition satisfying the required fields, not a quotation or official template. The platform identifies BAFU and partner measurement networks; do not imply every observation is independently measured by a single publisher. An access date is useful but is not one of the three expressly required attribution fields.

The separate service offers historical orders beyond the provider's demonstrated scope. Its 40-day online statement does not resolve GraphQL retention. The directory is a January 2023 snapshot even though its parent webpage is newer. Its availability describes digital data at least at daily-mean resolution (daily or finer), not the starting date of a specific finer-resolution product or current GraphQL coverage. Do not introduce workbook ingestion or repeat its broader product list as library capabilities. The old linked general-conditions PDF could not be freshly retrieved; its clauses are unnecessary because route-specific platform terms were verified.

## Practical example and accuracy checks

Retain the established example style: selection, explicit variant where appropriate, `fetch`, first rows, total row count and issues, followed by an explanation. A fresh live run on 27 October 2026 used:

```python
import rivretrieve as rr

selection = rr.find(
    provider="ch_foen", station="2018", quantity="discharge",
    frequency="daily", statistic="mean",
)
daily = rr.pick(selection, variant="TagMittel")
result = rr.fetch(daily, start="2024-01-01", end="2024-01-07", cache="bypass")
```

It returned seven rows. The first three `time`, `time_zone`, `value`, `unit` tuples were:

```text
2023-12-31T23:00:00.000000,+00:00,113.624,m3/s
2024-01-01T23:00:00.000000,+00:00,107.088,m3/s
2024-01-02T23:00:00.000000,+00:00,114.261,m3/s
```

The result included informational `provenance.citation_not_established`, because packaged provider citation is null. Do not display an empty issue tuple or imply failed acquisition. Explain the distinction between the library's missing configured citation and the mandatory attribution documented above. Changing catalogue citation metadata is outside this documentation scope.

Re-execute the final complete example in the target project's `uv` environment with temporary cache/store roots, retain its check date and report actual output. Values can change. Verify any additional snippets, table counts, selector names, source/returned units and output explanations. Fresh public output is a live witness, not a replacement for retained-input certification. Apply existing documentation/evidence checks and retain material under the established evidence process where required. No new testing framework or provider implementation is requested.

Detailed public research reports and the exact exploratory script/output are retained outside the repository at `/Users/nicolaslazaro/.prime/agent/research/swiss565-2026-10-27/`. These optional recovery artifacts are not portable build dependencies or approved evidence collections. The facts and links needed for implementation are carried here and in #565, including the directory-resolution correction.

## Narrow consistency corrections

Check and correct related Swiss claims without restructuring general documentation:

- `docs/usage.md` still says Swiss discharge has no established frequency/statistic; distinguish supported archive products from recent unknowns.
- `docs/catalogue-absence.md` uses obsolete Swiss unknown-CRS/Existenz evidence. Current Swiss stations declare EPSG:4326; choose a factually valid absence example instead.
- `docs/station-metadata.md` lists only page-derived name fields. Include official API `name` and `riverName` alongside retained page enrichment; preserve the distinction between station altitude and observation reference.
- `docs/maintenance/swiss-series.md` contains obsolete source-timestamp-only clipping wording beside current calendar-aware behavior. Align the explanation with delivered behavior.

## One human documentation-review gate

Open the completed provider-documentation PR against `port/swiss-official-api`, with checks and a readable document ready for Nicolas. **Wait for Nicolas to review that document before merging or concluding #565.** This is the single human gate for this Effort. After he reviews, implement his feedback, rerun applicable checks, resolve ordinary review findings and drive the PR and issue to completion independently. Do not request another routine approval round. A new substantive scope conflict or explicit instruction from Nicolas still takes precedence; do not interpret an absence of review as approval.

This gate applies to the provider-documentation implementation PR, not the ordinary publication of this vision. Independent agent review and required repository checks still apply. Merge into the dedicated port branch, not `main`. Closing #565 releases the documentation prerequisite of [#577](https://github.com/RivRetrieve/RivRetrieve/issues/577); it does not complete that review or authorize integration. Thiago's already agreed final Program approval is separately required before the whole port can merge into `main`.
