# Provider example verification

This record checks executable fenced examples under `docs/providers/` against
actual publisher services. Text fences are displayed output, not executable
Python. Each page runs in a separate Python session. Python fences on the same
page share their preceding state and run in document order. The runner executes
the exact fence contents and retains a copy beside its output.

## Status

Verification is in progress. The baseline at
`0b443049d50819978030e29e46011ca2101cb337` does not verify the final implementation.
A successful Python exit alone is not a successful retrieval: returned issues,
rows, units and displayed output are checked separately.

## Prerequisites and commands

Execution began on 2026-09-28 (UTC), using Python 3.13.8 and the checked-in uv
lockfile. `uv sync` installed the dependencies. No optional map dependency is
needed by these pages. ANA and NVE credentials were supplied privately through
the process environment. The optional USGS key was absent. Swiss archive access
uses the provider's built-in source credential. Secrets are not recorded here.

The initial free disk space was approximately 317 GB. Both national bulk examples
run their documented `rr.download(...)`, including live transfer, compilation and
certification. They do not reuse a pre-existing national store or replay fixtures.
Japan's reuse example uses the preceding acquisition in the same isolated cache.

From the repository root, set a new cache directory before each verification
round and run the command below once for every page in the inventory, substituting
its name for `PROVIDER`. `REVISION` is the full checked-out implementation commit.
The runner saves the page hash, revision, UTC times, elapsed times, exact code and
sanitized stdout/stderr. Repository commands and Python fence execution use uv.

```bash
export RIVRETRIEVE_CACHE_DIR="$PWD/.verification-cache/baseline"
uv run python docs/verification/provider-examples/execute.py docs/providers/PROVIDER.md docs/verification/provider-examples/baseline/PROVIDER --revision REVISION
```

The inherited uv cache had a missing wheel file. A separate `UV_CACHE_DIR` resolved
that environment problem before any example ran. It did not require a dependency
or source change.

## Inventory

| Page | Python fences | Displayed-output fences | Access |
| --- | ---: | ---: | --- |
| `ba_fhmzbih.md` | 1 | 1 | Live retrieval |
| `br_ana.md` | 4 | 4 | Credentialed live retrieval |
| `ca_eccc.md` | 3 | 2 | National live download and compiled read |
| `ch_foen.md` | 3 | 3 | Live retrieval |
| `cz_chmi.md` | 1 | 1 | Live retrieval |
| `fr_hubeau.md` | 1 | 1 | Live retrieval |
| `fr_hydroportail.md` | 3 | 3 | Live retrieval |
| `jp_mlit.md` | 2 | 2 | Live retrieval |
| `lt_lhmt.md` | 1 | 1 | Live retrieval |
| `no_nve.md` | 2 | 2 | Credentialed live retrieval |
| `pl_imgw.md` | 2 | 1 | National live download and compiled read |
| `th_thaiwater.md` | 2 | 2 | Live retrieval |
| `usgs_nwis.md` | 3 | 3 | Live retrieval |

The baseline tree has 13 pages and 28 Python fences. South Africa is catalogue-only
and has no page under `docs/providers/`; this does not omit an executable fence.
The final verification must inventory the tree again, including any added pages.

## Baseline access limitation

HydroPortail requests for both `validated` and `most_valid` at station `Y251002001`
exhausted timeout retries on 2026-09-28. Both returned zero rows with
`source.request_failed`; the complete page took 376 seconds. Its catalogue
selection ran successfully. This is a live source/access blocker, not a passed
observation example. The documented station, variants and dates were unchanged.

The unchanged page was retried at the same baseline revision on 2026-09-28.
It took 310.76 seconds. `validated` exhausted retries with HTTP 503; `most_valid`
exhausted timeout retries. Both again returned zero rows with
`source.request_failed`. A separate `curl -I --connect-timeout 15 --max-time 25
https://hydro.eaufrance.fr/` probe returned HTTP 200 in 8.57 seconds at 21:07 UTC.
This establishes host reachability, not observation availability. Response cookies
were not retained in the published diagnostic record.
