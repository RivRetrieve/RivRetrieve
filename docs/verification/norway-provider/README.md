# Norway provider documentation verification

Checked on 2026-09-23 for [the provider page](../../providers/no_nve.md).
This record distinguishes public live execution, source-page checks and replay tests.

## Revision and environment

- Existing delivery branch: `docs/provider-norway`, PR #278. Thiago's original
  commits `abaaa6f` and `09ca105` were retained, followed by the merge described below.
- Production baseline: `origin/main` at `1f719e0033a980e4a5528ca660a2f66475ff4b63`.
- Tested merge revision: `a898c799c06eb3b42131d115914cad91b4c5c367`, with only
  documentation, verification scripts and the documentation test added afterwards.
- macOS 15.7.3 arm64; CPython 3.13.8; RivRetrieve 0.1.49; `uv sync` from the lockfile.
- The inherited uv cache contained a missing wheel. Setup succeeded with a separate
  repository-local uv cache; this was an environment problem, not a library defect.
- `NVE_API_KEY` was supplied privately through the process environment. No key is
  present in scripts, logs or recordings. No registration form was submitted.

## Commands and results

Run these commands from the checkout root after `uv sync` and setting a valid
`NVE_API_KEY`. The examples verifier reads and executes every Python snippet in the
page, in order, compares stdout exactly, and reports the public result's source calls.
It uses no internal API, fixtures or monkeypatches.

```bash
uv run python docs/verification/norway-provider/verify_examples.py
uv run python docs/verification/norway-provider/catalogue_check.py
uv run python docs/verification/norway-provider/probe.py
```

- `examples.log`: both final snippets matched their displayed output. `providers()`
  reported `ready`; the actual successful requests, not that readiness string,
  established acceptance of the configured key.
- `live-probe.log`: earlier exploratory public retrieval with `receipts=True`,
  full issues and provenance. It returned seven non-null observations. The two
  informational source-code summaries each cover 11 padded source rows.
- `catalogue.log`: 4,902 catalogue locations, 3,804 stations with supported series,
  and 15,023 version/resolution series rows. It contains every per-resolution and
  per-statistic station count, including raw-resolution unknown frequencies and
  instantaneous methods at daily/hourly resolutions. A station can have several
  methods or versions; category counts need not add to a unique station total.

The public live requests used `cache="bypass"`. Provenance contains fresh HTTP 200
calls to `/api/v1/Series` with station `2.605.0`, parameter `1001`, followed by
`/api/v1/Observations` with explicit version `1`, resolution `1440`, and the
engine-padded interval `2023-12-30T00:00:00Z/2024-01-09T23:59:59.999999Z`.
The returned seven rows cover January 1–7, 2024, labelled at 11:00 UTC. The first
three values, rounded to three decimals, are 401.750, 415.396 and 444.500 m³/s.

The normal recording entry point was checked separately, without bypassing its
credential composition or engine path:

```bash
uv run python -m rivretrieve._internal.record_observations --provider no_nve --station 2.605.0 --product discharge_daily_mean --start 2024-01-01 --end 2024-01-07 --out-dir docs/verification/norway-provider/recordings --name discharge-week
```

`recording.log` records success. The two files in `recordings/` retain exact fresh
publisher bytes, transport parameters, times and HTTP status. They include the
metadata call and explicit-version observation call. The credential header name
is retained, never its value. The JSON response envelope includes
`license: "https://data.norge.no/nlod/en"`; no claim is made about an HTTP licence header.

## Claim checks

| Claim | Authority and check |
|---|---|
| NVE responsibility; other measurement producers | Fresh NVE Hydrology, Stasjonsnettet, Hydrologiske pålegg texts in `sources/`; no old institutional station counts reused |
| Restricted recent data | Fresh NVE publication guidelines dated February 4, 2026; 14-day stage/discharge period is conditional, not a universal lag |
| Credentials and service limits | Fresh HydAPI documentation and registration page; source registration steps checked without submitting; issuance time and numeric limits not claimed |
| Readiness, retrieval and cache bypass | Public examples and provenance; `providers()` only checks configuration presence |
| Units, quantity, statistic and frequency | `providers/no_nve/series.py` maps response parameter, unit, method and resolution independently; values need no scaling for supported units; `catalogue_check.py` checks actual packaged facts |
| Catalogue counts and availability | `find().locations`, `series()` and all grouped counts in `catalogue.log`; snapshot, not exhaustive live national inventory |
| Versions and scoped failures | `no_nve/fetch.py` and `metadata.py`; fresh metadata/version-1 retrieval; replay tests cover multiple versions and failures independently |
| Splitting | `no_nve/config.py` declares `iso-instant` without a size cap; `window_planning._plan_iso_instant` returns one rendered interval; `fetch.py` loops stations, products and explicit versions; no adaptive observation-limit subdivision |
| UTC and unknown support | Fresh HydAPI text explicitly states UTC and 11:00Z daily labels but calls daily calculation basis “Norwegian normal time” UTC-1; `series.py` establishes `+00:00` without interval support or anchor facts |
| Quality/correction exposure | Fresh response and `parse.py`: informational summaries, not per-row quality columns; counts include padded rows; public `receipts=True` retains observation bytes |
| Nulls, empty answers and failure isolation | Current parser plus recorded tests `test_no_nve_live.py` and `test_no_nve_public_routes.py`; fresh seven-day example has no nulls and does not independently prove these other states |
| Terms and attribution | Fresh HydAPI and NLOD 2.0 text: attribution, licence link and modified-data conditions preserved; CC BY compatibility is qualified for databases |

Code paths above are relative to `src/rivretrieve/_internal/`.
[source findings](sources/findings.md) and [retrieval manifest](sources/retrieval-manifest.json)
identify fresh authoritative checks. Text snapshots retain publisher wording with
HTML whitespace normalized, URLs, retrieval time and status. Manifest hashes are
of the retrieved HTML, not the text extraction. These pages are not live
observation-response evidence.

## Tests

```bash
uv run pytest -q tests/test_no_nve_documentation.py tests/test_no_nve_live.py tests/test_no_nve_public_routes.py tests/test_record_observations.py tests/test_documentation.py tests/test_supporting_documentation.py tests/test_reference_contracts.py
uv run python scripts/generate_reference.py --check
uv run ruff check tests/test_no_nve_documentation.py docs/verification/norway-provider/*.py
uv run ruff format --check tests/test_no_nve_documentation.py docs/verification/norway-provider/*.py
```

`tests.log`: **95 passed**, one existing rdflib deprecation warning. Generated
reference check passed. Formatting and lint were checked separately.

The new `test_no_nve_documentation.py` executes the exact page snippets through
public API calls while replaying the two fresh recordings. It checks displayed
stdout, issue codes, explicit version, calls and catalogue counts. This is an
**authored offline regression test**, not a second live retrieval. Existing tests
replay older recordings and authored source-failure controls; their passing does
not establish current availability for all routes. The historical
[conformance record](../../../tests/evidence/no_nve_conformance.md) supplies context,
not a claim of fresh national acquisition.

## Delivery-revision recheck

After the page and test were committed at
`b1e122a6cea548432b5b57b706053c1ad448b8ad`, the same live verifier was run again.
`final-examples.log` records matching stdout and fresh HTTP 200 metadata and
observation calls. `final-tests.log` records the focused documentation replay
and catalogue-count recheck. Later evidence-only commits do not change the page,
its snippets, the production baseline or that test.

## Limits and review gate

No catalogue regeneration, production changes or new products were made. No code
defect was found during these checks. No national live inventory census, rate-limit
stress test, key-issuance timing test or complete-history retrieval was performed.
A short successful example and code summaries do not establish quality approval,
continuous history or an exhaustive current source inventory.

Independent review and Nicolas's review feedback remain required. The PR must not
be approved or merged by the implementing agent. This record does not claim that
the human gate has been satisfied.
