# Thailand page verification

Checked 2026-09-24 (UTC) on macOS arm64, CPython 3.13, with `uv sync`. No credentials
are needed. Tested revision: merge `32a5c5b792bc21ab5bb4c9f4eabdbda7005ba6bd`, which
brings `docs/provider-thailand` up to `main` at `e1ed6505f3575d8c74e327ff6de7eb27d62ace11`.
No production code or catalogue was changed.

## Reproduce

From the checkout root, execute both reader snippets in their documented order against
the live API:

```bash
uv run python docs/verification/thailand-provider/verify_examples.py
uv run pytest -q tests/test_th_thaiwater_documentation.py tests/test_th_thaiwater_live.py tests/test_thaiwater_source_outcomes.py tests/test_thaiwater_source_windows.py tests/test_lt_lhmt_th_thaiwater_public.py tests/test_th_thaiwater_acquisition_provenance.py tests/test_th_thaiwater_generate_catalogue.py tests/test_thaiwater_governing_evidence.py tests/test_record_observations.py tests/test_documentation.py tests/test_supporting_documentation.py tests/test_reference_contracts.py
uv run python scripts/generate_reference.py --check
```

The verifier uses only the public API with `cache="bypass"`, with no fixtures or
monkeypatches. At 10:59 UTC it matched every displayed line: 432 stage rows, the two
informational provenance issues, and 432 null discharge rows with a `success` outcome.
Each snippet made one fresh HTTP 200 call to `waterlevel_graph` for station `1`, with
`start_date=2024-05-30` and `end_date=2024-06-05`. `rr.to_utc` refused the stage result
because its 432 rows have `time_zone="unknown"`.

The recording was made the same day with the normal CLI:

```bash
uv run python -m rivretrieve._internal.record_observations --provider th_thaiwater --station 1 --product stage_reported --start 2024-06-01 --end 2024-06-03 --out-dir docs/verification/thailand-provider/recordings --name station-1-june-2024
```

Its 1,008 graph rows are identical to a direct request made at 10:46 UTC. The discharge
snippet sends the same request, so one recording serves both snippets. The focused
documentation test replays it and checks the snippet output, padded request dates,
10-minute spacing in this response, series facts, the `to_utc` refusal, catalogue
counts and the index link. Replay is not live verification. The run passed
**161 tests, 1 skipped**: the private-corpus acceptance check in
`test_thaiwater_governing_evidence.py` needs bodies that are not in the repository.
Scoped Ruff lint and format, the generated reference and `git diff --check` also passed.

## Claims and limits

- **Live behaviour, 2026-09-24.** A 2023-01-01 to 2024-06-03 stage request made two
  source calls, 2022-12-30 to 2023-12-29 and 2023-12-30 to 2024-06-05, and returned
  74,880 rows, 10,771 of them null. Selecting both quantities sent the identical
  request once per quantity. A malformed station identifier sent directly to the API
  returned `result: "NO"` with a message; the corresponding error issue is covered by
  authored cases in `test_thaiwater_source_outcomes.py`, not by a live public request.
  On 2026-09-24 `waterlevel_load` listed 804 stations (HII 330, RID 314, FOP 89,
  EGAT 71), including station `1`.
- **Packaged catalogue.** 825 locations; every station lists `stage_reported` and
  `discharge_reported`. Availability is `available` for 813 stage and 283 discharge
  pairs, `unknown` for the rest, from graph requests over 2026-06-08 to 2026-09-06 or
  2026-08-31 to 2026-09-06. Published record bounds are null for all 1,650 pairs.
  Agency counts come from `native.parquet`: HII 329, RID 328, FOP 95, EGAT 73.
- **Code.** `config.py` sets `time_zone="unknown"`, `UnknownTemporalSupport`, and a
  365-inclusive-date `capped-span` window described as a conservative working size.
  `SERIES_MAPPINGS` gives m and m3/s without scaling and stage `above_sea_level` with
  no datum. `parse.py` keeps nulls and turns `result: "NO"` into an `error` issue.
- **Sources.** ThaiWater's site is a script application; its current
  `app.chunk.js` was searched. The footer counts 54 agencies; history text gives 52 and
  "53 agencies, 12 ministries". It links cookie and privacy policies and a privacy
  notice; no data licence, terms or citation text was found. HII's homepage places HII
  under the Ministry of Higher Education, Science, Research and Innovation and says HII
  developed the National Hydroinformatics Data Center. The Government Data Catalog
  record `gdpublish-water-level` (HII, modified 2026-02-23) lists HII telemetry
  10-minute water levels in m MSL under Creative Commons Attribution Non-Commercial,
  distributed through `tiservice.hii.or.th`, not this API. `data.hii.or.th` timed out and
  `data.go.th` did not resolve from this network, so their copies were not checked.
- **Standards not applied.** ThaiWater's data-exchange standard defines 10-minute water
  levels as readings at the labelled time, stage in m MSL referenced to Royal Thai
  Survey Department benchmarks, and a domestic datetime format without an offset. It
  governs exchange between agencies and does not state that `waterlevel_graph` follows
  it, so the page does not infer statistic, datum or zone from it.
- No code defect was found. No licence permission, time zone, sampling interval,
  statistic, datum, continuous coverage, quality approval or ownership by the attributed
  agency is claimed.

Exploratory logs, the direct API response, source snapshots and the fetch log are
preserved outside the Git diff at `.worktrees/thailand-provider-evidence-2026-09-24/`
in the maintainer checkout.
