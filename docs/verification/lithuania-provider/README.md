# Lithuania page verification

Final check 2026-09-28 on macOS arm64, CPython 3.13.8, uv 0.12.1, with `uv sync`.
No credentials are needed. Production baseline: `main` at
`d02b17a84b31fbbdc572f9fcadba9847a13fcbff`, which includes the repairs of
[issue #385](https://github.com/RivRetrieve/RivRetrieve/issues/385) and
[issue #389](https://github.com/RivRetrieve/RivRetrieve/issues/389).
No production code or catalogue was changed by this documentation work.

## Reproduce

For recorded checks, obtain the exact inputs from the private source archive
following the [verification guide](../../maintenance/evidence.md). Set
`RIVRETRIEVE_TEST_EVIDENCE_ROOT` to the external repository-relative input root.
Missing retained inputs block replay verification. The live verifier contacts the
publisher and does not use that root.

From the checkout root, execute all reader snippets in their documented order,
then the behaviour checks:

```bash
uv run python docs/verification/lithuania-provider/verify_examples.py
uv run --with rdflib --with folium pytest -q tests/test_lt_lhmt_documentation.py tests/test_lt_lhmt_live.py tests/test_lt_lhmt_monthly_isolation.py tests/test_lt_lhmt_shared_acquisition.py tests/test_lt_lhmt_generate_catalogue.py tests/test_lt_lhmt_th_thaiwater_public.py tests/test_documentation.py tests/test_supporting_documentation.py tests/test_reference_contracts.py tests/test_documentation_examples.py
uv run python scripts/generate_reference.py --check
```

The verifier uses only the public API with `cache="bypass"`, with no fixtures or
monkeypatches. At 08:22 UTC on 2026-09-28 it matched the page's single example
and its displayed output exactly. The example made two HTTP 200 calls, for the
`2019-12` and `2020-01` historical months of `nemajunu-vms`. The December call
comes from the two-day fetch padding. Its live behaviour checks returned:

| Check | Rows | Nulls | Source calls | Issues |
|---|---:|---:|---|---|
| Stage, `nemajunu-vms`, 2020-01-01..07 | 7 | 0 | `2019-12` 200, `2020-01` 200 | none |
| Discharge, `birstono-vms`, 2024-06-10..12 | 3 | 3 | `2024-06` 200 | none |
| Discharge, `nemajunu-vms`, 2025-06-10..12 | 0 | 0 | `2025-06` 404 | warning `source.http_not_found` |
| Discharge, `nemajunu-vms`, 2024-12-27..30 | 4 | 0 | `2025-01` 404, `2024-12` 200 | none |
| Stage, `juodkrantes-vms`, 2020-01-10..12 | 0 | 0 | `2020-01` 404 | warning `source.http_not_found` |
| Both quantities, `nemajunu-vms`, 2020-01-01..07 | 14 | 0 | `2019-12` 200, `2020-01` 200 | none |

Each check is asserted. The stage check returns 0.45, 0.45 and 0.51 m with
`source_unit` `cm` for the first three days, confirming the conversion in the
page's table. The other checks establish the page's distinctions: a published null
is a row with `value=null`; an unpublished requested month is an identified
warning, not an empty success; an unpublished padding-only month is recorded in
provenance without an issue. One `fetch` selecting both quantities sends one
request per month, and each call record lists both series. Catalogue inspection in
the same run found 97 stations, and daily mean discharge (m³/s to m³/s) and stage
(cm to m) at `nemajunu-vms`, labelled `+00:00` with no established day definition.

The two retained recordings were made with the normal recording CLI on
2026-09-27. To collect a new interaction, set `RECORDING_OUTPUT_DIRECTORY` to a
new directory outside source checkouts:

```bash
uv run python -m rivretrieve._internal.record_observations --provider lt_lhmt --station nemajunu-vms --product discharge_daily_mean --start 2020-01-01 --end 2020-01-07 --out-dir "$RECORDING_OUTPUT_DIRECTORY" --name nemajunu-week
```

The API publishes both fields in one monthly document, so these two monthly
responses serve both quantities. The recordings are retained in the private source
archive and resolved under the external input root at
`docs/verification/lithuania-provider/recordings/`. New recordings must use a separate
output directory; do not overwrite selected historical inputs.
`tests/test_lt_lhmt_documentation.py` replays them
through the page example and the stage-unit check, and checks their output, source
calls, catalogue count, units and index link. Replay is not live verification.

On 2026-09-28 the pytest command above passed 148 tests (one warning), including
the 42 shared-acquisition regression tests for #389. Scoped Ruff lint and format,
generated-reference and diff-whitespace checks also passed. Repository-wide Ruff
reports only pre-existing findings in the Brazil and Canada verification scripts.

## Defects found and repaired

Two production defects stopped this review until they were repaired:

- [#385](https://github.com/RivRetrieve/RivRetrieve/issues/385), repaired by
  [#387](https://github.com/RivRetrieve/RivRetrieve/pull/387): an unpublished
  padding month discarded all requested published days. At `e12f9ee`,
  2000-01-01..05 and 2024-11-01..12-31 at `nemajunu-vms` returned zero rows. On
  `d02b17a` they returned 5 and 61 rows, with the 404 padding calls in provenance
  and no issues.
- [#389](https://github.com/RivRetrieve/RivRetrieve/issues/389), repaired by
  [#391](https://github.com/RivRetrieve/RivRetrieve/pull/391): a `fetch` selecting
  both quantities sent every monthly request twice, although the provider declares
  them co-published. At `ad06730` the both-quantity check above made four calls; on
  `d02b17a` it made two.

## Claims and sources

Publisher pages fetched with HTTP 200 on 2026-09-27:

- [api.meteo.lt](https://api.meteo.lt/) (documentation version 1.4.9, 2026-02-10;
  SHA-256
  `cbc2bc60bbd00332646bc02cbde2d7f593163c7c629b9e388ebcb8e6d046ea2b`): LHMT under the Ministry of Environment; data measured
  at LHMT's stations; `waterLevel` cm and `waterDischarge` m³/s as daily means;
  `observationDateUtc` as a UTC date; historical data from 2000 and the previous
  year from the middle of the current year; the measured feed's 30 days of stage
  and water temperature; null for an unmeasured parameter and 404 for a date
  without stored data; 180 requests per minute and 20,000 per day per IP; the five
  data-use conditions, quoted verbatim on the page. Its extracted text differs from
  the retained recording `tests/test_data/lt_lhmt_terms_licence.html` (2026-08-21)
  only in two example URL dates, so that recording retains every quoted statement.
- [LHMT hydrology](https://www.meteo.lt/klimatas/hidrologija/) (SHA-256
  `7e79b8251ef267aceaea141e8484feb1fa464cbcc1e13e2bbb731a842894c084`): "Hidrologinius stebėjimus Lietuvoje vykdo vandens matavimo
  stočių (toliau – VMS) tinklas, aprėpiantis visą šalies teritoriją. Šiuo metu
  stebėjimų tinklą sudaro 101 VMS, kuriose atliekami vandens lygio, vandens
  temperatūros, oro temperatūros, kritulių kiekio ir vandens debito matavimai."
- [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/): share-alike.

Direct API checks on 2026-09-27 found 97 stations in `/v1/hydro-stations`.
The archived
`docs/verification/lithuania-provider/source-checks/historical-ranges-2026-09-27.json`
keeps the per-station
`/observations/historical` ranges for all 97. End dates were 2024-12-31 (66
stations), 2023-12-31 (18), 2017-12-31 (6), 2013-12-31 (1) and 2024-08-10 (1).
Five stations reported no range: `juodkrantes-vms` (Curonian Lagoon),
`klaipedos-juru-uosto-vms`, `lazdenu-vms`, `palangos-vms` and `sventosios-vms`.
Fifty stations start in 2000.

The archived
`docs/verification/lithuania-provider/source-checks/null-discharge-scan-2024-06.json`
covers the 66 stations whose
historical range ended on 2024-12-31, so that June 2024 lay inside every scanned
range. It was retrieved directly from
`https://api.meteo.lt/v1/hydro-stations/{code}/observations/historical/2024-06`
on 2026-09-27 at about 15:11 UTC. For each station it records `days`,
`null_waterLevel` and `null_waterDischarge`. All 66 returned 30 days, none had a
null stage, and 20 published null discharge on every day. The other 31 stations
were not scanned.

Code facts: `lt_lhmt/config.py` declares a `+00:00` zone, an unknown day definition
and a `00:00` label; `parse.py` keeps source nulls and creates rows only for
published dates.

## Corrections to the original page

- The original example used a removed API (`product=`, `rr.pick`, a full year).
- "Last year's values appear during the current year" was not supported by the
  live ranges; the page now quotes the API and reports the observed delay.
- "RivRetrieve keeps UTC, including for daily means" implied day boundaries that
  are not established; the page now separates the UTC date label from the
  unknown averaging day.
- "Runs the national hydrological network" is now sourced to LHMT's hydrology page,
  with the 101 versus 97 difference left unexplained, as the sources leave it.
- "One station-month per call" now explains shared calls, separate `fetch` calls
  and padding months.
- "Availability is unknown" became the practical consequence for readers.

## Limits

- The observed publication delay is a dated observation, not a fixed schedule.
- The source does not state the averaging day, stage datum or quality status;
  none is inferred.
- Raw publisher HTML snapshots are not retained in the repository beyond the
  retained API recording; the URLs, dates and hashes above identify them.
