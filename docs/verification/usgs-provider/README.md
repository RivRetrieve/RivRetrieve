# USGS provider-page verification

Candidate: `docs/providers/usgs_nwis.md`, existing PR [#266](https://github.com/RivRetrieve/RivRetrieve/pull/266).
Implementation baseline: `origin/main` at `9247d33`, integrated into the original
`docs/provider-usgs` branch by merge `2f845b7`. No production files changed.
Verification date: 2026-09-22 UTC.

## Exact page execution and publisher evidence

`execute_examples.py` extracts every Python block from the candidate page and runs
them in documented order through the public API, in the worktree's `uv` environment.
It does not replace transport, change library functions, replay previous responses,
or alter snippets. `execution.json` keeps each exact block, stdout, UTC execution
time and SHA-256 of the complete tested page. `execution.log` includes the same
outputs and the offline count. The final run explicitly set the optional
`USGS_API_KEY` environment variable to blank, shadowing any `.env` value. No personal
credential was used.

Each `*.bundle.zip` is the public `rr.to_bundle` export of a returned result.
The exact page snippets do not request receipts. After each result, the script
makes a separate receipt-enabled acquisition through the public API with the same
selection and window, checks identical observation frames, issues and series
definitions, and exports it as `*-with-receipts.bundle.zip`. Its response bytes
therefore belong to a separate fresh source request, not the exact snippet's
network response. The comparison establishes that both returned the same data
for these executions.
Each `*-receipt-0.json` is an exact publisher payload retained using the supported
`rr.fetch(receipts=True)` path. Its `*-origin.json` records URL, parameters,
retrieval time, status, media type and SHA-256 of those bytes. Headers containing
credentials are not recorded. These finite observation requests establish the
shown dates and identities, not whole-history parity, preferred series, current
national availability or historical overlap beyond the requested week.

Fresh live results (exact snippets and separate receipt-enabled acquisitions agree):

- `07374000`, daily mean discharge, January 1–7, 2024: seven rows, no issues,
  one published ID, `unknown` daily zone, m³/s. First three displayed values
  4927.131, 5125.349 and 5238.617, rounded to three decimals.
- `02196000`, daily mean discharge, January 1–7, 2000: fourteen rows across two
  published IDs, no issues. Explicit choice of
  `0df18b246e8f48ec8e6547a92070e94a` returns seven rows and only that ID.
- Both requests retain padded publisher dates outside the requested week in
  receipts. Result frames contain only the requested dates.

An initial evidence-script attempt called a nonexistent serialization method on
the receipt-origin dataclass after a successful first snippet. This was a defect
in the new evidence script, not RivRetrieve. The script now serializes the public
origin fields explicitly; all snippets and receipts were reacquired. No broken
library recording path was bypassed.

## Claim account

| Page claim | Evidence checked on 2026-09-22 | Scope |
|---|---|---|
| USGS publication, network partnership, Baton Rouge station name | [Fresh source research](source-research/README.md), exact source responses and manifests | National source context, not a library station count |
| 50-state-plus-DC scope | Packaged catalogue, `generate_catalogue.py` retained scope and modern source-series projection | Established catalogue scope, not all US territories |
| 26,201 selectable stations, 575 with alternatives, daily discharge 134/24,495 | `counts.json`, recomputed by public `rr.series(rr.find(provider="usgs_nwis"))` | Packaged snapshot; 59,159 concrete series. Not a live network census or overlapping-data assertion |
| Six unknown-statistic continuous records | `counts.json` (four discharge, two stage); `metadata.py` accepts continuous null statistic and does not infer it | Precise instantaneous filter excludes unknown facts |
| Six supported routes, daily publisher statistics, units | `config.py`, `metadata.py`, `conversion.py`; six-route replay tests; fresh v1 daily collection description | Numeric conversion, not scientific comparability; SI-source units also admitted |
| Daily midnight labels with unknown zone/day; continuous explicit offsets | `parse.py:parse_time_label`, `metadata.py:source_series`; first snippet and six-route replay | No day-bound or station-zone inference; continuous example evidence in replay is explicitly historical |
| Series IDs exposed through variant; two null descriptions | `metadata.py`, packaged `source_series.json`, fresh filtered metadata response in source research | `id`/`time_series_id` identify published series, not method/category. No authoritative preference or relationship established |
| Singleton does not require choice; all matches stay separate; explicit selection | All three executed snippets; `fetch.py` and shared selection scope; focused public replay | Additional identities can be discovered in observations. No averaging or winner selection |
| Multiple stations need no manual ID list | Public `find`/`pick` station scopes and `fetch.py` per-station all-matching execution | Code inspection, not a new live multi-station census |
| Null row, absent row and failed call differ | `parse.py:_value`, parser row assembly; `fetch.py` failure outcomes and shared driver; provider and failure-contract tests | Nulls accepted, absent observations not manufactured; short successful examples contain no nulls/failures |
| Approval/qualifiers do not become returned quality flags | `parse.py` validates source field shapes but returned row schema excludes them; provisional statement source capture | No source approval or library quality inference from request success |
| Optional key and restricted credential origin | `declaration.py`, public credential resolution; fresh USGS key guidance and unauthenticated live execution | Higher limits with key; no promised numerical quota or load testing |
| Public domain and requested credit; citation DOI and access date | Fresh copyright and citation responses in source research | USGS-authored/produced data only, not all third-party content |

Source-document checks are fresh acquisitions, separate from snippet execution.
The source research records a guessed URL returning 404 and stale v0 examples in
otherwise successfully acquired publisher guidance. The introduction does not
repeat those version claims. No external-model numerical comparisons or hypotheses
about the two series were adopted. No USGS contact or exhaustive document search
is claimed.

## Offline prevalence method

Group public series by `station_id`, `quantity`, `frequency`, and `statistic`,
then count distinct `variant` IDs in each group. Count distinct stations among
groups with more than one ID. `counts.json` retains the detailed per-group totals.
The denominator is the 26,201 selectable stations, consistent with the root README;
the catalogue separately retains 26,258 station identities. Daily-discharge
alternatives: 134 / 24,495 = about 0.55%; all-group stations: 575 / 26,201 = about
2.2%. Unknown-statistic continuous records stay separate from instantaneous rows.

## Verification commands

From the candidate worktree root:

```text
USGS_API_KEY= uv run python docs/verification/usgs-provider/execute_examples.py
uv run --with rdflib pytest -q tests/test_usgs_provider_documentation.py tests/test_usgs_modern_discovery.py tests/test_usgs_nwis_public_routes.py tests/test_documentation.py tests/test_supporting_documentation.py tests/test_reference_contracts.py
uv run ruff check tests/test_usgs_provider_documentation.py docs/verification/usgs-provider/execute_examples.py docs/verification/usgs-provider/source-research/acquire.py
uv run ruff format --check tests/test_usgs_provider_documentation.py docs/verification/usgs-provider/execute_examples.py docs/verification/usgs-provider/source-research/acquire.py
uv run python scripts/generate_reference.py --check
git diff --check
```

`test_usgs_provider_documentation.py` executes all exact page blocks using these
newly captured publisher bytes through the transport seam and checks the displayed
outputs. It refuses unrecorded request coordinates. This is publisher-response
replay, not another live check. Its separate offline test checks prevalence and
the singleton ID. Existing provider tests cover all six routes and boundary cases;
authored malformed responses test handling, not publisher behavior.

Additional failure/receipt regression command:

```text
uv run pytest -q tests/test_receipts_publisher_payload.py tests/test_source_failure_isolation.py
```

Results and any limits are recorded in `tests.log`, `failure-and-receipt-tests.log`
and `checks.log`. The focused suite passed 58 tests (one rdflib deprecation
warning); the failure/receipt suite passed four tests. Ruff lint, format checks,
generated-reference check and whitespace check passed.

The user's editorial feedback on the introductory explanation is incorporated.
The user then explicitly authorized: “Good you may proceed to completion without
human gates”. This supersedes the earlier human-only gate for this delivery;
the published vision is unchanged. The root agent coordinates final independent
review and completion. This documentation owner has not approved or merged PR #266.
