# French provider page verification

This is maintainer evidence for PR #264, not reader documentation.
The simplified page was checked against implementation revision
`86d3c564560b19c2901e92744ee06e010c1b5437`. No production files changed.
It introduces the source and explains one daily-discharge example. General API
instruction remains in the usage guide.

## Current live example, 2026-09-20

The single Python block was executed directly from the current page through
`uv run python`, using `cache="bypass"`. `RecordingTransport` wrapped the real
`HttpClient` to retain the source exchange without replaying a response.

Y251002001 daily mean discharge, 2024-01-01 through 2024-01-07, returned **7 rows
and no issues**. The first displayed values are 1.159, 1.144 and 1.159 m³/s, with
`time_zone="unknown"`. CSV presentation rounds values to three decimal places.
The complete printed output matched the page exactly.

The source response was retrieved at `2026-09-20T21:54:00.410920Z`.
Its SHA256 is `522f2f9b9cbe74d285e2bb7c48991fce79e2bffa8b3509cbda6c3d23aaba448f`.

The committed `fr_hubeau_Y251002001_daily_january2024.recording.json` records an
earlier exact request on the same date. The focused test replays that recording
and compares the page's complete stdout. This is regression evidence, separate
from the fresh live source check. It also checks the displayed 7,323-station count
against the packaged station table. Removed availability tables and secondary
examples are no longer test expectations.

To execute the current page against the live service from the repository root:

```sh
uv run python -c 'import re; from pathlib import Path; ns = {}; page = Path("docs/providers/fr_hubeau.md").read_text(); blocks = re.findall(r"```python\n(.*?)```", page, re.S); [exec(compile(code, "fr_hubeau.md", "exec"), ns) for code in blocks]'
```

Remote values can change. The original `product=` call was reproduced before the
first correction and raised `TypeError`; that was obsolete documentation, not a
production defect. No production defect was established during this review.

## External-source checks

`fr_hubeau_documentation_sources.json` records URL, final URL, retrieval instant,
HTTP status and SHA256 for 19 source pages fetched on 2026-09-20. All returned HTTP
200 with substantive content. These checks support the source, quantity, time,
status and terms statements that remain in the simplified page:

- Hydrometry comes from PHyC/Service Central Vigicrues, DREAL and other producers;
  metropolitan temperature comes from Naïades through Hub'Eau. Hub'Eau is OFB/BRGM.
- RivRetrieve reads three daily hydrometric types. Daily maxima are maxima of
  instantaneous values. A UTC date label does not establish the daily support
  clock. Temperature zone and temporal support remain unknown.
- Station and site are distinct. At most one station is active for site discharge
  at a time. RivRetrieve retrieves the selected station's own record.
- Instantaneous access currently requests HydroPortail raw series only. Additional
  statuses and a later documentation update are future work in issue #311.
- Hub'Eau CGU 5.1.3 requires author citation; Licence Ouverte 2.0 requires source
  (at least licensor) and last-update date. HydroPortail legal/FAQ pages establish
  public access but not the same licence or a standard citation.
- No source was inaccessible. Etalab redirected to data.gouv.fr's licence page;
  the obsolete Sandre dictionary was replaced with current HydroPortail help.

## Current validation

- The seven French/provider and documentation modules in local
  `simplified-validation-command.txt`: **66 passed** in 77.36 seconds.
  Two dependency warnings concerned Excel styling and rdflib deprecation.
- Ruff lint and format checks passed for the revised test.
- `uv run python scripts/generate_reference.py --check`: reference current.
- `git diff --check`: passed.
- An independent reviewer reran the two focused page tests: both passed.

The earlier 241-test run and three-example live runs apply to the previous page
revision, not to the simplified page. Their logs remain as historical audit
material; current results are recorded above.

## Local audit material

The only checkout created is
`.worktrees/visions/french-provider-documentation-review`.
Its `planning/evidence/french-provider-documentation-review/` directory retains
`execute_simplified_example.py`, `simplified-live.log`, the fresh
`simplified-live-0.recording.json`, `simplified-validation-command.txt`, and
`simplified-tests.log`, as well as the earlier review's audit material.

Independent source evidence is at `.worktrees/french-source-evidence/` under the
main repository: `claim-matrix.md`, fetch scripts/logs and 19 raw bodies, readable
extracts and receipts. That directory is not a Git checkout.
