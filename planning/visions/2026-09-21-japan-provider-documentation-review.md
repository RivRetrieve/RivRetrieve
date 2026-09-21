# Japan provider documentation review

## Outcome and scope

Update the existing Japan documentation [PR #290](https://github.com/RivRetrieve/RivRetrieve/pull/290),
branch `docs/provider-japan`, targeting `main`. Deliver a readable, fact-checked
`docs/providers/jp_mlit.md`, an accurate PR description, and focused example regression
tests where useful. Preserve Thiago's useful structure, substance, authorship, and
existing history. Integrate current main without losing the existing provider-index
entries. Limit changes to the Japan page, its necessary existing documentation-index
integration, and directly relevant verification material. Do not rewrite other provider
pages or shared guides. Do not replace the provider PR or rewrite its history.

This is standalone documentation work. PR #290 predates the public API and behavior
updates incorporated through [PR #300](https://github.com/RivRetrieve/RivRetrieve/pull/300).
Use the current implementation, including later changes, rather than freezing behavior
at #300. The repository has no users who need backward-looking guidance. This is a
migration of the documentation itself, not a migration guide for readers.

The user, Nicolas Lazaro (`CooperBigFoot`), is the human review gate. Once the page has
been rewritten and verified, leave PR #290 open for him to read and give feedback.
Do not approve or merge it on his behalf. Passing tests and independent agent review
do not replace his wording and clarity review. Do not declare the work concluded
before his feedback and direction. This boundary overrides implementation workflows
that normally end by merging their implementation PRs.

## Required editorial references

Read all three current pages in full before writing, not just their PR descriptions:

- `docs/providers/ch_foen.md`: Switzerland, reviewed in PR #289.
- `docs/providers/fr_hubeau.md`: France, Hub'Eau.
- `docs/providers/fr_hydroportail.md`: France, HydroPortail.

The French references include the work begun in PR #264 and the later split into two
provider pages. Follow their explanatory approach, not obsolete text from an earlier
PR revision. Follow **`docs/AGENTS.md` as mandatory writing guidance** and the root
project instructions.

Write for an educated hydrology reader with basic Python knowledge. Explain Japan's
national context, who measures and publishes the observations, and what RivRetrieve
provides. Distinguish stations administered by MLIT's Water and Disaster Management
Bureau from unsupported claims about all Japanese hydrometry. Establish each actor's
role from authoritative evidence rather than assuming the publisher made every
measurement.

Preserve a flexible, reader-oriented structure: country/provider title and navigation,
summary table, a practical retrieval with useful verified output and explanation,
measuring and publishing responsibilities, available quantities, source-specific
conditions, time, data status, access, terms, citation, and dated sources. Preserve
useful Japanese source quotations and clearly identified translations where they aid
understanding. Do not copy Swiss or French facts into the Japan page or impose an exact
heading order when Japan needs a different explanation.

Keep prose concrete and approachable. Explain conditions near the claims they qualify.
Give code blocks breathing room. Link to the usage guide for general API instruction.
Do not turn the introduction into an API reference, a parser audit, a catalogue-counting
method, or a narrative about this investigation. Detailed verification belongs in PR
or maintainer evidence rather than the reader-facing page.

## Current behavior to investigate and explain

Recheck the public API, packaged catalogue, Japan provider code, tests, and authoritative
source evidence before making claims. Important discovery findings are starting points,
not permanent acceptance constants:

- The old `rr.find(..., product="discharge_daily")` example is obsolete. Current public
  selection uses physical filters such as `quantity="discharge"` and
  `frequency="daily"`. Use `find`, `series`, `pick`, and `fetch` only where they help
  explain the actual task. Do not add `statistic="mean"` to Japan's daily selection:
  the current evidence does not establish that statistic.
- The catalogue inspected during discovery listed 1,023 stations and four candidate
  records per station: hourly/daily stage and hourly/daily discharge, corresponding
  to MLIT KIND 2, 3, 6, and 7. Catalogue membership does not establish data availability
  for every quantity or period. Avoid a per-product station-count table that suggests
  confirmed coverage where availability is unknown.
- Stage is returned in metres and discharge in m³/s. Frequency labels do not establish
  means, temporal support, interval anchors, hydrological-day definitions, or stage
  datums. Preserve unestablished facts rather than inferring them from product names.
- Returned `time_zone` is `unknown`. Daily labels are represented at midnight; hourly
  source labels run from 1 to 24, with 24 represented at midnight on the following
  date. Explain only the consequences needed to interpret the example. Do not infer
  JST, UTC, or an averaging period from geography or timestamp formatting.
- Source flags and their treatment require careful explanation. Provisional `*` values
  can be returned with `source_tentative`; non-observation markers have distinct
  issues. The parser summarizes affected cells with counts and first/last source
  labels. `result.issues` does not identify every affected observation row, and the
  observation table has no per-row provisional flag. Hourly and daily legends differ.
  Verify each claimed flag meaning against the relevant source format. Do not infer
  formally verified status merely because a numeric cell has no flag.
- Daily retrieval uses annual source files; hourly retrieval uses monthly files.
  A small requested interval can therefore obtain a larger source record. Returned
  rows are clipped to the requested interval, while issues can describe the wider
  source response. Verify and explain this if the final example exposes it. Preserve
  distinctions between null values, absent rows, empty results, and failed requests.

### Successful live retrieval, not a service-wide failure

Discovery initially received HTTP 403 on direct software requests to MLIT's homepage
and usage-guidance page, with the text “This site prohibits data acquisition using
tools, etc.” Those informational-page checks did **not** test observation retrieval.
They do not establish that the R package or the Python provider is broken, or that
MLIT recently changed the observation service. Do not repeat that unsupported
conclusion or restart an alternative-provider search because of it.

On 2026-09-21 at approximately 19:59 UTC, the following public-path retrieval was
executed using `uv run python` from the checkout at
`0eec366c7a538cfabef10d7e1fb50461de1ca7fe`:

```python
import rivretrieve as rr

selection = rr.find(
    provider="jp_mlit",
    station="305071285512040",
    quantity="discharge",
    frequency="daily",
)

result = rr.fetch(
    selection,
    start="2020-01-10",
    end="2020-01-11",
    cache="bypass",
    receipts=True,
)
```

It returned two discharge rows:

| Source time label | Time zone | Value | Unit |
|---|---|---:|---|
| 2020-01-10 00:00:00 | unknown | 34.39 | m3/s |
| 2020-01-11 00:00:00 | unknown | 32.14 | m3/s |

The retrieval outcome was `success`. Both ordinary source requests returned HTTP 200:
`http://www1.river.go.jp/cgi-bin/DspWaterData.exe` with KIND 7, station
`305071285512040`, `BGNDATE=20200101`, `ENDDATE=20201231`, and `KAWABOU=NO`, followed
by its publisher-provided `/dat/dload/download/…dat` link. No request-identity change,
access workaround, or cache substitution was used. The meaning of `KAWABOU=NO`
remains unestablished; it need not appear in reader-facing documentation.

The result also contained one informational `source_missing` issue reporting 17
source slots, first label `2020年4月30日`, last label `2020年7月1日`. These refer to the
annual source response, not missing values in the two requested January days.
Do not suppress real issues merely to show an empty issue tuple.

This is a bounded live witness, not proof of every station, period, or product. It does
not verify the original PR's full-year 2020 example. Execute every final authored
snippet, including a full-year retrieval if retained. Recheck current behavior rather
than treating these values as immutable. A different concise example period can be
chosen on evidence, not to conceal a defect.

## Responsible access and caching

Describe the actual MLIT access guidance and data-reuse terms accurately and separately.
Check quotations, citations, version numbers, and qualifications against authoritative
sources. Successful retrieval proves technical access for that request, not unrestricted
permission, and an informational-page refusal does not prove observation failure.
Do not characterize MLIT's warning as harmless or claim that reducing request volume
creates an exemption the source has not stated.

The user wants responsible request sizes and local caching explained. Current live
retrieval defaults to `cache="bypass"`. Explicit `cache="reuse"` can serve a fully
covered request from local storage; an uncovered scope requires retrieval. Cached
answers can differ from later source corrections. Verify the exact behavior promised
by any cache example, including whether a repeated covered request makes source calls.
Use a controlled cache location for verification so unrelated user state is preserved.
Do not say caching is automatic by default, saves the first download, or guarantees
that an enlarged request downloads only missing dates. Fresh live verification must
be distinguishable from a cache hit even if the final reader example recommends reuse.

No production cache-default, throttling, transport, or provider changes are authorized.
No new source, regional provider, paid subscription, file-import workflow, R port, or
national acquisition campaign belongs in this review. The alternative-access research
was exploratory and was not adopted. The user rejected manual-file acquisition as the
intended workflow. Do not contact MLIT or another organization or disclose the private
repository as part of this effort.

## Verification and regression evidence

Execute every final Python snippet against the current public API in the project's
`uv` environment. Run dependent snippets in their documented order and session. Check
actual selections, outputs, units, timestamps, counts, issues, and any promised cache
behavior. Include useful displayed output and explain what the reader should notice.
Check the final text, not only an earlier script with similar operations.

Use live retrieval where applicable. Recorded-source regression tests complement live
execution; they do not establish current service reachability. Reuse existing recordings
where suitable and add focused example regressions where useful. Do not mislabel old
fixtures, mocked calls, or cache hits as fresh source observations. Do not fabricate
outputs or silently omit issues. Date live outputs where source revisions can change
them, and report any remaining verification gap honestly.

Check every factual claim against current code, the packaged catalogue, or
authoritative sources as appropriate: institutional responsibility, geography, quantities,
units, time and temporal support, station counts, availability, source status, access,
terms, and citation. Resolve contradictions before publication or retain an explicit
qualification. Update a source's checked date only when it was actually checked.

Useful repository anchors, to verify in the implementation checkout:

- `docs/AGENTS.md`, the three provider reference pages, `docs/usage.md`,
  `docs/reference.md`, and `docs/architecture.md`.
- `src/rivretrieve/_internal/discovery.py`, the retrieval driver and cache code, and
  `src/rivretrieve/_internal/providers/jp_mlit/`.
- Japan's packaged catalogue and source-series evidence.
- `tests/test_jp_mlit_observations.py`, `tests/test_jp_mlit_live_regression.py`,
  `tests/test_jp_mlit_catalogue.py`, `tests/test_jp_mlit_html_outcomes.py`,
  `tests/test_jp_mlit_acquisition_provenance.py`, and the related source recordings.
- The Swiss and French provider-example regressions for the existing testing approach.
- MLIT's homepage, `https://www1.river.go.jp/caution.html`, and the cited
  `https://www1.river.go.jp/WDBrules_20251210.pdf`, together with retained source evidence
  when fresh informational-page access is unavailable. Mark historical evidence as such.

Older provider-port notes can be stale; current code and source evidence take precedence.
Follow repository-native checks and library-specific data assertions. Do not add hosted
CI or unrelated validation infrastructure. Keep tested revisions, commands, actual
results, source checks, and limitations inspectable in the PR or supporting evidence.
Update the PR description to match the final page and verification, removing stale API,
status, access, and success claims without erasing the existing commit history.

## Mandatory stop and human review gates

If implementation or verification reveals a bug or blocking problem, **stop the
documentation work**. Open a GitHub issue labelled **`bug`**, assign it to
**CooperBigFoot**, and include the tested revision, reproducible steps, expected and
actual behavior, source evidence, and the effect on PR #290. Follow
[issue #305](https://github.com/RivRetrieve/RivRetrieve/issues/305) as the reporting
precedent. Distinguish an internal defect from an upstream failure, genuinely absent
data, or an inaccessible informational page; do not invent a diagnosis. If the problem
is not yet classified, state that uncertainty in the report. An obsolete documentation
call alone is a documentation correction, not a reason to restore a removed API.

Do not fix production code, change a test to hide a defect, or rewrite documentation
around it. Preserve partial work and evidence. If issue creation or assignment fails,
report that blocker explicitly. Wait until Nicolas reports that the problem is repaired,
then reverify the affected path before continuing.

After the rewritten page, final snippets, supporting tests, and PR description have
been checked, obtain independent review and hand the existing open PR to Nicolas.
Identify the rewritten file and summarize actual verification and remaining limitations.
Stop for his personal review. Incorporate requested feedback and reverify affected
claims and examples before asking him to assess the revision. Do not approve or merge
PR #290, proceed to another provider, or declare acceptance on his behalf.

Publishing this vision is a separate operation: only its vision-publication PR may
merge under the authoring workflow. Publication does not start implementation or
satisfy the provider documentation's human review gate.
