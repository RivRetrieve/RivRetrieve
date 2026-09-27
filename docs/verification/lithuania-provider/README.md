# Lithuania page verification

Checked 2026-09-27 on macOS arm64, CPython 3.13.8, uv 0.12.1, with `uv sync`. No
credentials are needed. Production baseline: `main` at
`ad06730c8a90146353fe16b4ae19369e5d5803ba`, which includes the repair of
[issue #385](https://github.com/RivRetrieve/RivRetrieve/issues/385). No production
code or catalogue was changed by this documentation work.

## Reproduce

From the checkout root, execute all reader snippets in their documented order,
then the behaviour checks:

```bash
uv run python docs/verification/lithuania-provider/verify_examples.py
uv run pytest -q tests/test_lt_lhmt_documentation.py tests/test_lt_lhmt_live.py tests/test_lt_lhmt_monthly_isolation.py tests/test_documentation.py tests/test_supporting_documentation.py tests/test_reference_contracts.py
uv run python scripts/generate_reference.py --check
```

The verifier uses only the public API with `cache="bypass"`, with no fixtures or
monkeypatches. At 16:40 UTC, and again at 18:06 UTC after formatting, it matched both displayed outputs exactly. Each example
made two HTTP 200 calls, for the `2019-12` and `2020-01` historical months of
`nemajunu-vms`; the December call comes from the two-day fetch padding. Its live
behaviour checks returned:

| Check | Rows | Nulls | Source calls | Issues |
|---|---:|---:|---|---|
| Discharge, `birstono-vms`, 2024-06-10..12 | 3 | 3 | `2024-06` 200 | none |
| Discharge, `nemajunu-vms`, 2025-06-10..12 | 0 | 0 | `2025-06` 404 | warning `source.http_not_found` |
| Discharge, `nemajunu-vms`, 2024-12-27..30 | 4 | 0 | `2025-01` 404, `2024-12` 200 | none |
| Stage, `juodkrantes-vms`, 2020-01-10..12 | 0 | 0 | `2020-01` 404 | warning `source.http_not_found` |

These establish the page's distinctions: a published null is a row with
`value=null`; an unpublished requested month is an identified warning, not an empty
success; an unpublished padding-only month is recorded in provenance without an
issue. Catalogue inspection in the same run found 97 stations, and daily mean
discharge (m³/s to m³/s) and stage (cm to m) at `nemajunu-vms`, labelled `+00:00`
with no established day definition.

The two committed recordings were made with the normal recording CLI on
2026-09-27:

```bash
uv run python -m rivretrieve._internal.record_observations --provider lt_lhmt --station nemajunu-vms --product discharge_daily_mean --start 2020-01-01 --end 2020-01-07 --out-dir docs/verification/lithuania-provider/recordings --name nemajunu-week
```

Recording `stage_daily_mean` over the same dates issued byte-identical requests and
received byte-identical responses, because the API publishes both fields in one
monthly document. Only one pair is kept. `tests/test_lt_lhmt_documentation.py`
replays those bytes through both page examples and checks their output, source
calls, catalogue count, units and index link. Replay is not live verification.

The focused and existing documentation, Lithuania and reference tests passed
(121 tests, plus the 25 newcomer-example tests with the optional `folium`
dependency). Scoped Ruff lint and format, generated-reference and diff-whitespace
checks also passed. Repository-wide Ruff reports only pre-existing findings in the
Brazil and Canada verification scripts.

## Defect found and repaired

The first execution, on production `e12f9ee`, found that an unpublished padding
month discarded all requested published days: 2000-01-01..05 and 2024-11-01..12-31
at `nemajunu-vms` returned zero rows. Documentation work stopped, and the defect was
filed as issue #385 and repaired by PR #387. Rerunning the same reproduction on
`ad06730` at 16:38 UTC returned 5 and 61 rows respectively, with the 404 padding
calls retained in provenance and no issues.

## Claims and sources

Publisher pages fetched with HTTP 200 on 2026-09-27:

- [api.meteo.lt](https://api.meteo.lt/) (documentation version 1.4.9, 2026-02-10):
  LHMT under the Ministry of Environment; data measured at LHMT's stations;
  `waterLevel` cm and `waterDischarge` m³/s as daily means; `observationDateUtc`
  as a UTC date; historical data from 2000 and the previous year from the middle of
  the current year; the measured feed's 30 days of stage and water temperature;
  null for an unmeasured parameter and 404 for a date without stored data;
  180 requests per minute and 20,000 per day per IP; the five data-use conditions,
  quoted verbatim on the page.
- [LHMT hydrology](https://www.meteo.lt/klimatas/hidrologija/): the countrywide
  water measuring station network of 101 stations and its measured variables.
- [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/): share-alike.

Direct API checks on the same day found 97 stations in `/v1/hydro-stations`.
The per-station `/observations/historical` ranges for all 97 showed end dates of
2024-12-31 (66 stations), 2023-12-31 (18), 2017-12-31 (6), 2013-12-31 (1) and
2024-08-10 (1); five coastal and lagoon stations reported no range. Fifty stations
start in 2000. A June 2024 scan found 20 stations publishing stage with null
discharge on every day.

Code facts: `lt_lhmt/config.py` declares a `+00:00` zone, an unknown day definition
and a `00:00` label; `parse.py` keeps source nulls and creates rows only for
published dates. The public path sends one request per station, quantity and
month, even when both quantities are selected, as the provenance above shows.

## Corrections to the original page

- The original example used a removed API (`product=`, `rr.pick`, a full year).
- "Last year's values appear during the current year" was not supported by the
  live ranges; the page now quotes the API and reports the observed delay.
- "RivRetrieve keeps UTC, including for daily means" implied day boundaries that
  are not established; the page now separates the UTC date label from the
  unknown averaging day.
- "Runs the national hydrological network" is now sourced to LHMT's hydrology page,
  with the 101 versus 97 difference left unexplained, as the sources leave it.
- "One station-month per call" now includes quantity and padding months.
- "Availability is unknown" became the practical consequence for readers.

## Limits

- The observed publication delay is a dated observation, not a fixed schedule.
- The source does not state the averaging day, stage datum or quality status;
  none is inferred.
- The catalogue's provider description still says co-published products share one
  source call, while the public path sends one per quantity. This affects request
  counts, not returned values, and is left to maintainers.
- Raw source snapshots, the station-range and null scans, the defect reproduction
  and run logs are kept outside the diff at repository-root
  `.worktrees/visions/lithuania-review-evidence/`.
