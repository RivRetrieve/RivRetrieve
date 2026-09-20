# French provider page verification

This is maintainer evidence for PR #264, not reader documentation.
The public implementation was tested at merge revision
`2123e13a0fc5f51c4f837d2ccab9e680f0628d86`, which integrates main
`d87682e35dcbe837daa0a0fcfa4ca17ddf2d8594` into the existing French documentation
branch. No production files changed.

## Live examples, 2026-09-20

All three Python blocks were executed in document order in one namespace through
`uv run python`. Both fetch blocks used `cache="bypass"`. `RecordingTransport`
wrapped the real `HttpClient` to retain source exchanges, without replaying responses.

| Example | Live result | Source-response SHA256 |
|---|---|---|
| Daily mean discharge, Y251002001, 2024-01-01 through 2024-01-07 | 7 rows; no issues; first values 1.159, 1.144, 1.159 m³/s; zone unknown | `522f2f9b9cbe74d285e2bb7c48991fce79e2bffa8b3509cbda6c3d23aaba448f` |
| Daily discharge discovery, then `pick(statistic="max")` | Two physical candidates, daily max and mean; one after narrowing | Offline catalogue, no HTTP request |
| Raw instantaneous stage, Y251002001, 2020-01-01 through 2020-01-02 | 576 rows; no issues; first values 0.347, 0.345, 0.343 m; UTC; published_id raw | `ced762c5fd6f096c0e9402a4d4b4ed3d7d97248573fda28e2da535a4cd26962a` |

The daily exchange was retrieved at `2026-09-20T21:17:50.294115Z`; the stage exchange
at `2026-09-20T21:17:51.978491Z`. CSV presentation rounds values to three decimal places.
The daily recording is committed as
`fr_hubeau_Y251002001_daily_january2024.recording.json`. The existing
`fr_hydroportail_H_padded.recording.json` matches the exact stage request and all
printed stage outputs, so a duplicate 684 KB recording was not added. The new live
stage exchange remains in the local evidence directory. The old stage recording is
regression evidence, not evidence of the new live service check.

To run the current page again against the live services from the repository root:

```sh
uv run python -c 'import re; from pathlib import Path; ns = {}; page = Path("docs/providers/fr_hubeau.md").read_text(); blocks = re.findall(r"```python\n(.*?)```", page, re.S); [exec(compile(code, "fr_hubeau.md", "exec"), ns) for code in blocks]'
```

Remote data can change. The offline test separately executes every displayed block
against exact recorded requests and compares stdout with the displayed output.
It also compares the availability table with packaged Parquet counts using Polars.

## Catalogue and source interpretation

The packaged catalogue contains 7,323 stations and 33,139 applicable station/product
pairs: 6,454 hydrometry stations with five candidates and 869 temperature stations
with one. Positive evidence totals 20,966 pairs; 12,173 remain unknown. Counts are
mixed-date acquisition evidence, not continuous/current availability. The six table
counts were recomputed from `station_products.parquet` and matched the page.

The original example was executed before the edit. It raises
`TypeError: find() got an unexpected keyword argument 'product'`.
The new page-example regression test also failed before the page revision.
This was an obsolete documentation API call, not a production defect.

An intermediate snippet inspected `variant` and returned `None`. Narrow inspection
confirmed intentional behavior: `raw` is `SeriesMapping.published_id`, and the
`variant` filter accepts published IDs as well as distinct variant labels.
Both selection and result expose `(published_id="raw", variant=None,
requested_variants=["raw"])`, with no issues. The final example inspects
`published_id`; no defect or production repair was needed.

## External-source checks

`fr_hubeau_documentation_sources.json` records URL, final URL, retrieval instant,
HTTP status and SHA256 for 19 source pages fetched on 2026-09-20. All returned HTTP
200 with substantive content. Etalab redirected to the current data.gouv.fr licence;
Sandre redirected to the full, obsolete HYD 2.3 XML dictionary, so the reader page
uses current HydroPortail station/site help instead.

The independent source review established:

- Hydrometry comes from PHyC/Service Central Vigicrues, DREAL and other producers;
  metropolitan temperature comes from Naïades through Hub'Eau. Hub'Eau is OFB/BRGM.
- Hub'Eau's eight elaborated source types exceed the three daily types RivRetrieve
  reads. Daily maxima are maxima of instantaneous values. A UTC source date label
  does not establish the daily support clock. Temperature support remains unknown.
- Station and site are distinct. HydroPortail states at most one station is active
  for site discharge at a time. A specific activation-table claim was removed
  because checked help prose did not establish that detail.
- All four French glossary quotations were checked in full. RivRetrieve's selected
  source identity is raw; row status/quality fields remain in optional receipts.
  The HydroPortail UI has configurable zones; the page's UTC statement concerns
  RivRetrieve's validated response route.
- Hub'Eau CGU 5.1.3 requires author citation; the linked Licence Ouverte 2.0 also
  requires source/licensor and last-update date. “Raw data” in the terms does not
  establish sensor-validation status. No ready-made citation string was identified.
- HydroPortail legal/FAQ pages establish public access but not the same licence or
  a standard citation. Hub'Eau terms are not silently extended to HydroPortail.
- No authoritative source was inaccessible. No production defect was established.

## Validation results

- `uv run pytest -q` over the 16 French/provider and documentation test modules
  listed in local `validation-command.txt`: **241 passed** in 257.06 seconds.
  Two unrelated library warnings concerned an Excel default style and rdflib's
  deprecated `ConjunctiveGraph`. This was a focused run, not the full test suite.
- `uv run ruff check tests/test_fr_hubeau_documentation.py`: passed.
- `uv run ruff format --check tests/test_fr_hubeau_documentation.py`: passed.
- `uv run python scripts/generate_reference.py --check`: reference current.
- `git diff --cached --check`: passed.
- A fresh independent reviewer reran 15 focused tests and all three final page
  blocks against live sources. Tests passed and every displayed output matched.
  The reviewer found no actionable issue in the source/code/prose review.

## Local audit material

The only checkout created for the work is
`.worktrees/visions/french-provider-documentation-review`.
Its `planning/evidence/french-provider-documentation-review/` directory retains
execution scripts, original-example failure, before/after regression logs,
final live output, full live recordings, catalogue output, identity investigation,
and validation commands/logs. These are local audit artifacts, not packaged data.

Independent external evidence is at `.worktrees/french-source-evidence/` under the
main repository: `claim-matrix.md`, fetch scripts/logs and 19 raw bodies, readable
extracts and individual receipts. That directory is not a Git checkout.
