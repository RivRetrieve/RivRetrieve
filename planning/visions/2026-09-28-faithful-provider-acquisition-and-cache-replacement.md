# Faithful provider acquisition and cache replacement

## Outcome

Return every usable observation from independent source acquisitions, preserve the failures beside those results, and replace cached observations only where source evidence justifies replacement. Apply this consistently across all registered providers. A missing annual file, failed month, incomplete page chain, or advancing rolling publication must not silently discard unrelated observations or manufacture successful empty coverage.

This is a standalone vision prompted by [issue #404](https://github.com/RivRetrieve/RivRetrieve/issues/404), not a Program Effort. The scope includes the related defects found during the all-provider investigation and defects discovered while verifying the provider documentation examples. Publishing this vision does not deliver or close the reported bug.

The user prioritizes a comprehensive correction over a narrow Czechia patch. There are no users requiring backward compatibility. Change internal or public contracts and cache formats where justified by the correct design. Do not build compatibility layers or write migration guides. Preserve source fidelity and established useful behavior, rather than preserving accidental implementation constraints.

## What the investigation established

Investigation used production code at `8c07cac027e0e5677be4414edeeb1f26ce1ed500`, the merge of [PR #295](https://github.com/RivRetrieve/RivRetrieve/pull/295). Remote `main` at `a74d5088d1f360314e21eae706bfb11df026f583` had identical production code, dependencies, and tests; its only additional file was a Bosnia review vision. Recheck current `main` before implementation rather than treating these revisions as a frozen target.

PR #295 reviewed Czech provider documentation. It checked one week at a different station and ran existing focused tests. It did not change provider code or test failure among annual downloads. The reported defect is present in the reviewed production code; it is not explained by the reporter using an older release.

### Live Czechia reproduction

On 2026-09-28, the following public selection with `cache="bypass"`, `on_issue="ignore"`, and `receipts=True` reproduced the report:

```python
import rivretrieve as rr

selection = rr.find(
    provider="cz_chmi",
    station="0-203-1-000400",
    quantity="discharge",
)
daily = rr.pick(selection, frequency="daily")
```

| Start | End | Observed rows | Relevant result |
| --- | --- | ---: | --- |
| 2021-10-19 | 2023-12-31 | 802 | Successful retrieval |
| 2022-01-01 | 2022-12-31 | 365 | Successful retrieval |
| 2021-06-01 | 2021-12-31 | 72 | Current source has 72 discharge labels starting October 21 |
| 2021-01-01 or 2021-01-02 | 2021-12-31 | 0 | Missing 2020 file aborts acquisition |
| 2021-10-19 | 2026-12-31 | 0 | Missing 2026 file discards earlier successes |
| 2019-01-19 | 2024-12-31 | 0 | Missing 2019 file aborts acquisition |
| 2010-10-19 | 2019-12-31 | 0 | Missing 2010 file aborts acquisition |

Direct requests to `https://opendata.chmi.cz/hydrology/historical/data/daily/H_0-203-1-000400_DQ_<year>.json` returned 200 for 2021 through 2025 and 404 for 2010, 2019, 2020, and 2026. Availability and values can change. The issue's 214-row June–December count was not reproduced; do not manufacture rows to match it. The future-end request also generated the appropriate future-date information issue.

The engine's two-day padding explains why a calendar-year request fetches neighboring annual files. Removing global padding is not the remedy for acquisition isolation. Keep correct boundary behavior and distinguish padding-only failures from failures inside the requested interval.

### Provider-by-provider findings

All fourteen registered providers were inspected. Except for the Czechia availability checks above, failure reproductions used offline recorded or authored responses through actual repository stages, public APIs, or bulk composition. They establish library behavior, not live incidents at those publishers.

| Provider | Finding and implementation scope |
| --- | --- |
| `cz_chmi` | Annual DQ/HQ requests accumulate payloads until one transport failure escapes. Earlier successes disappear and later years are not attempted. Each annual payload also carries the whole padded request window, causing incorrect outcomes and partial-refresh behavior. Correct both acquisition isolation and source coverage. |
| `th_thaiwater` | Independent 365-day spans have the same abort pattern and whole-request payload bounds. Public replay of a valid first span followed by HTTP 503 returned zero rows, calls, and receipts. |
| `br_ana` | This is currently a credentialed live provider. Monthly daily requests and fixed backward 30-day telemetry spans have the same abort pattern and broad bounds. Monthly planner bounds exist but are ignored. Public daily replay lost a valid January response after the next request failed. |
| `jp_mlit` | Hourly months and daily years are independent chunks. Each chunk has a dependent HTML/linked-DAT acquisition. A later HTML or DAT failure currently aborts all chunks. Monthly bounds are ignored; annual bounds are absent. Public hourly replay lost January's observations after the next HTML request failed. Keep prerequisite HTML evidence; a link-bearing HTML page is not an empty observation response. |
| `fr_hubeau` | Dependent cursor pages have inconsistent failure handling. A valid recorded first page followed by HTTP 503 lost all 20 rows and evidence. The same first page followed by malformed HTTP 200 `{}` retained 20 rows and two receipts, with whole-window success and unsupported outcomes. Retain usable partial evidence consistently while keeping the page chain incomplete. A single page does not prove exhaustive coverage. |
| `usgs_nwis` | Already retains earlier page bytes with an unresolved transaction after late failure. Explicit selectors are independent. Continuous 1100-day spans are currently coupled into one transaction: a failed span prevents later spans and invalidates coverage for the whole request. An existing test intentionally locks that policy. Improve isolation between independently bounded spans while keeping each span's cursor chain dependent. This is a deliberate policy improvement, not the identical CHMI total-loss defect. |
| `ba_fhmzbih` | Source-fixed rolling `*_1Y.xlsx` workbooks are assigned arbitrary requested-window coverage. A recent workbook falsely established empty coverage for January 2000. Advancing a valid workbook's timestamps in a controlled refresh changed 24 held historical observations to zero and removed them from the cache. Correct the distinction between snapshot contents and proven temporal coverage. |
| `ca_eccc` | Bulk composition can replace a newer certified HYDAT release with an older fallback release. A controlled real decode/compile/certification sequence changed vintage 2026-09-22 to 2026-09-21 and 124 rows to 62. HEAD 403 and unexpected 302 responses each produced 366 probes and a misleading release-not-found error, losing the HTTP reason. A dangling artifact-target symlink also permits a write outside the intended target. Address all three. |
| `lt_lhmt` | Existing bounded independent monthly acquisitions preserve successes, failures, receipts, and cache coverage. This is a useful positive model, including shared products. Its source-established 404 meaning must not be generalized to other publishers. Preserve and test this behavior. |
| `no_nve` | Current version-level requests isolate failures; metadata failures remain unresolved. A failed middle version retained both healthy siblings. Current single-interval bounds are appropriate. Preserve this behavior and cover mixed-version refresh. |
| `ch_foen` | Current public singleton-station acquisition retains healthy stations around a failed one. Recent REST versus authenticated archive routing uses the padded request boundary. Single-interval bounds and held-cache failure protection passed focused checks. Direct internal multi-station Flux batching can still discard earlier payloads; correct or make that unsupported contract explicit. |
| `pl_imgw` | Annual/monthly artifacts compose one certified complete-history store. Abort, cleanup, and atomic rollback on an incomplete replacement are appropriate. Vintage and artifact-path guards already exist. Preserve them; do not turn archive members into falsely certified partial stores. |
| `fr_hydroportail` | Independent variant requests already retain failed selectors beside successful ones. Each response matches its full requested interval. Relevant identity and cache checks passed. Preserve variant isolation and verify mixed refresh. |
| `za_dws` | Catalogue-only. Observation acquisition and cache tests are not applicable. Keep explicit observation unavailability; this vision does not authorize implementing a new source. |

Bosnia's direct multi-pair fetch also has unsafe failure/metadata behavior, but its current public driver calls singleton pairs and isolates failures correctly. Treat that and the Swiss batch issue as dormant internal contract defects, not demonstrated public station-isolation failures. Resolve these unsafe contracts without inventing an unrelated batch feature.

### Shared cache and evidence defects

A deterministic CHMI public-API probe used valid authored annual responses, one row on June 1 of each year, and an isolated cache. The request was 2022-06-01 through 2023-06-30. Seed both years with value 1, then refresh with value 2 while returning malformed JSON for one year:

- If 2022 fails, both old values return and the valid new 2023 value is suppressed.
- If 2023 fails, the result contains both old value 1 and new value 2 for the same 2022 date, plus the old 2023 row.
- With no held cache, the healthy year's row returns but no successful coverage or rows are persisted.

These results reach `rr.fetch`; public assembly does not remove the conflict. Both annual outcomes inherit the full request interval. Held fallback and overlap rejection therefore act across unrelated years.

All-success annual retrieval is a successful negative control: both years return and persist. `driver._combine_replacements` combines same-series, same-interval contributions. Do not repeat the disproved claim that successful annual payloads overwrite one another in this case, or remove legitimate shared-transaction aggregation.

Exact disjoint annual bounds should correct these particular cache cases. The driver also composes held and fresh rows during payload iteration, which is order-sensitive for genuinely overlapping outcomes such as dependent pages. Establish correct, order-independent transaction composition; do not use blanket row deduplication to hide contradictory acquisition evidence.

Mapped outcomes have missing call linkage. Two annual requests with identical malformed bytes and equal retrieval timestamps produced two receipts and distinct provenance calls but only one deduplicated unsupported outcome. The mapped outcome identity omits acquisition identity; inventory identity has a similar exposure. Correct annual bounds distinguish these specific years, but repeated same-window acquisitions still need truthful identity. Preserve shared-product call coalescing and the existing acquisition/position-based receipt distinction.

## Required behavior

### Source boundaries and partial results

Keep the overall user request, padded fetch request, independent acquisition interval, dependent transaction completion, source-series identity, and observed row extent distinct. Providers supply source facts; the engine owns window arithmetic and result/cache composition. Use established repository vocabulary and typed boundaries. The implementing agent chooses the mechanism; a new general orchestration framework is not required.

For independent annual, monthly, capped-span, or fixed-backward acquisitions:

- Continue after supported source failures, including failures before, between, or after successes.
- Retain successful observations, publisher payloads, prerequisite evidence, and failed-request identity, interval, reason, HTTP/retry metadata, and call linkage.
- Cache a successful acquisition's justified coverage independently of failed siblings.
- Keep source absence, successful empty response, null observations, unsupported structure, and failed request distinct.

For dependent work such as cursor pages, MLIT HTML/DAT pairs, or complete-history bulk publication, preserve the appropriate transaction boundary. Retained partial page rows and bytes do not establish completed coverage or exhaustive identity inventory. An incomplete chain must not be relabeled as a successful whole query. An incomplete archive must not replace a valid certified store.

Do not infer a missing-file meaning from HTTP 404 alone. Keep padding-only diagnostics unless publisher evidence justifies narrower treatment. Preserve normal caller issue policy and partial-result semantics; fatal internal contract violations must still raise regardless of that policy.

### Coverage and replacement

Source responses justify only the coverage they establish. An annual selector may establish annual acquisition bounds; a rolling workbook without a published completeness interval does not establish arbitrary requested history. Minimum and maximum observed labels are not a completeness proof. Do not invent unpublished temporal support or time zones to make coverage computable.

Successful fresh acquisitions replace their justified intervals, including legitimate empty responses. Failed or unresolved intervals must not erase held successes, become reusable empty coverage, or prevent unrelated successful replacement. Returned fresh/held composition must agree with stored state and evidence, retain actual acquisition vintages, and not depend on processing order. Missing uncached intervals remain uncovered and eligible for retry.

For Canada, refuse implicit fallback to an older release when replacing a newer certified store. Preserve the existing store and explain the reason. This does not prohibit corrections or fewer rows in an authoritative newer release; row counts are not the guard. Preserve unexpected HTTP failure identity instead of interpreting every status as an unpublished date. Keep supported missing-release fallback. Reject unsafe artifact targets, including dangling symlinks. The witnessed symlink behavior is a local path-safety defect, not evidence of remote exploitability.

### Documentation and examples

Every executable code snippet under `docs/providers/` must run successfully against the final implementation. Inventory the final tree, including pages added during delivery. Do not limit this criterion to the Czech example or pages changed by the implementation.

- Execute the snippets as documented, with their documented setup, imports, credentials, optional dependencies, and preceding example state where applicable. Identify displayed output separately from executable code.
- Use actual live services for live examples and perform required bulk downloads for bulk examples. Offline replay tests do not verify a live documentation example.
- Verify that outputs and explanations accurately describe observed behavior, including units, dates, issues, and source availability. Update snippets or prose when needed without choosing an easier example to conceal an unresolved defect.
- Record the exact final code, repository revision, commands, execution date, prerequisites, results, and source/access limitations in appropriate maintainer evidence. Never publish credentials or secret-bearing logs.
- A credentials, network, publisher, or resource blocker is not a pass. Report it explicitly and keep this success criterion incomplete until the example has actually been verified. Do not silently skip expensive examples or count syntactic checks as execution.
- Snippet and implementation defects discovered by this verification are in scope. Keep reader-facing pages focused on current behavior and follow `docs/AGENTS.md`; put detailed verification methods in maintainer records. No migration narrative is required.

## Repository starting points and validation

Inspect these current boundaries rather than copying a provider-specific workaround everywhere:

- `src/rivretrieve/_internal/window_planning.py`: monthly renderings carry bounds; annual, capped, and fixed-backward renderings need review.
- `engine.py`, `source_acquisition.py`, `provider_series.py`, and `driver.py`: acquisition results, bounded failed requests, mapped outcome/inventory identity, receipt/provenance linkage, held fallback, and replacement grouping.
- `store/accumulation.py`, `store/certification.py`, and `_internal/bulk.py`: replacement, atomic publication, artifact paths, and previous source vintage.
- Provider fetch/parse/config/declaration files, particularly Lithuania's `SourceAcquisition`/`FailedSourceRequest` pattern and USGS's incomplete cursor transactions.

Build durable deterministic regressions using actual stage/public composition boundaries and isolated caches. Cover failed first/middle/last/all independent chunks; daily/hourly and shared-product routes; padding versus in-request failure; sparse/null/empty valid responses; malformed source structure; authentication and transport failures; dependent completion; distinct acquisitions with equal bytes/timestamps; and fatal contract behavior. Verify successful partial persistence, failed-interval retry, healthy sibling refresh, correct held fallback, legitimate empty replacement, and order independence. Keep expensive combinations justified and measure runtime impact under the project's contributing rules.

Useful existing witnesses include `tests/test_chmi_source_boundary_isolation.py`, `tests/test_cz_chmi_observations.py`, `tests/test_thaiwater_source_windows.py`, `tests/test_jp_mlit_observations.py`, `tests/test_br_ana_daily.py`, `tests/test_br_ana_telemetry.py`, `tests/test_usgs_observation_acquisition.py`, `tests/test_lt_lhmt_monthly_isolation.py`, `tests/test_lt_lhmt_shared_acquisition.py`, `tests/test_public_series_cache.py`, and the bulk publication/recovery tests under `tests/store/`.

Recorded public-probe inputs included:

- `tests/recordings/br_ana/HidroSerieVazao_15400000_2024-01-01_2024-01-31.recording.json` with a failed next monthly request.
- `tests/test_data/jp_mlit_stage_hourly_2023_html.recording.json` and the corresponding `_dat.recording.json`, followed by a failed next chunk.
- `tests/test_data/fr_hubeau_01001336_temp_2008-07-09_10_p1.recording.json`, followed by HTTP 503 or malformed HTTP 200 `{}`.
- `tests/test_data/ba_fhmzbih_4024_H_1Y.recording.json`: 8,348 observations, with observed labels 2025-09-03 through 2026-09-02. Seed September 4, 2025, then advance workbook labels by one year without breaking its valid structure to reproduce rolling-publication eviction. This is a controlled model, not a claim of an exact publisher retention guarantee.
- Small generated SQLite archives satisfying `HYDAT_SOURCE_SCHEMAS` through actual bulk composition. Offer a newer valid store, then a 404 for its release date and an older valid archive. Verify that the newer held store survives. Exercise constant 403/302 responses and dangling artifact targets separately.

The investigation recorded 458 focused test passes across separate commands: 48 CHMI in 7.76 s; 104 Swiss/Norwegian/South-African/shared-cache tests in 34.11 s; 219 Bosnia/Canada/Poland/HydroPortail tests in 78.49 s; five USGS cases in 0.02 s; 65 Lithuania monthly/shared-acquisition tests in 180.67 s; and 17 selected Thai/Japanese/Brazilian window tests in 10.02 s. These passing baselines coexist with the reproduced defects. They are not a full-suite pass or a claim of unique exhaustive coverage.

At delivery, run the complete applicable repository suite and project checks through `uv`, including normal type checking of `src`, formatting/lint, documentation/reference checks, and every provider snippet. Preserve meaningful failures rather than weakening tests. Provide an all-provider verification matrix distinguishing reproduced corrections, preserved good behavior, catalogue-only non-applicability, and any remaining blockers. Do not claim completion with an unverified required example or an unresolved in-scope defect.

## Boundaries

All related acquisition, evidence, coverage, cache, bulk replacement, and provider-example defects are in scope. New providers, new hydrological products, unrelated feature work, source judgment, gap filling, and a general framework rewrite are not requested. Do not change publisher facts or require a blanket crash on supported source failure. Other agents may be editing provider pages; preserve their work and integrate against current target-branch evidence.

The implementation is complete when the corrected contracts hold across all providers, the reproduced losses and misleading outcomes have focused regressions, healthy existing behavior remains verified, bulk replacement is safe, and every final provider documentation snippet has run successfully with accurate explanatory output. Deliver current-behavior documentation and traceable verification, without compatibility machinery or migration guides.
