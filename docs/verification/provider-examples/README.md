# Provider example verification

This record checks executable fenced examples under `docs/providers/` against
actual publisher services. Text fences are displayed output, not executable
Python. Each page runs in a separate Python session. Python fences on the same
page share their preceding state and run in document order. The runner executes
the exact fence contents and retains a copy beside its output.

## Status

Verification is in progress. The baseline at
`0b443049d50819978030e29e46011ca2101cb337` does not verify the final implementation.
Final execution started at `28d12fb70f75c89ee4ceac497fbbf80ddd768922`.
Its provider tree still has 13 pages and 28 Python fences; no page changed from
the baseline inventory. Final runs use a second fresh cache, including new
national downloads. Results remain pending while the bulk runs finish.

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
Japan's first `cache="reuse"` fetch acquires and persists the selected rows in
the isolated cache. Its repeated reuse fetch reads that acquisition; the earlier
`cache="bypass"` example does not populate the cache.

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
Its captured bash-process wall time was 310.76 seconds, including uv startup
and interpreter shutdown. The runner metadata covers 310.324 seconds inside
Python. `validated` exhausted retries with HTTP 503; `most_valid`
exhausted timeout retries. Both again returned zero rows with
`source.request_failed`. A separate `curl -I --connect-timeout 15 --max-time 25
https://hydro.eaufrance.fr/` probe returned HTTP 200 in 8.57 seconds at 21:07 UTC.
This establishes host reachability, not observation availability. Response cookies
were not retained in the published diagnostic record.

## Checkout provenance

These three checkouts were created for this verification:

- `.worktrees/visions/provider-example-verification`, branch
  `verify/provider-examples-baseline` (renamed from `verify/provider-examples`),
  started from baseline `0b443049d50819978030e29e46011ca2101cb337`.
  Documentation-only evidence commits do not change the code running in its
  baseline bulk processes.
- `.worktrees/visions/provider-examples-final`, detached at
  `28d12fb70f75c89ee4ceac497fbbf80ddd768922`, runs the final implementation.
  It has a separate uv environment and `.verification-cache/final` location.

The runner stored in the first checkout is invoked through `uv run python` from
inside the second checkout. Thus project imports resolve to the final checkout,
not to the runner's evidence directory. The final command for each page is
recorded in its `final/PROVIDER/execution.json`. Credentials remain environment
inputs in both checkouts. No fixture transport, provider monkeypatch, request
window change or pre-existing bulk store was used.

## Runner provenance

`baseline/execute.py.txt` preserves the runner as executed by the baseline
processes. It did not yet record command/Python-version fields in each JSON file;
its exact command template and Python 3.13.8 environment are recorded above.
The original exact-code copies used `.py`; those files were renamed `.py.txt`
without changing their contents so formatters cannot rewrite historical inputs.
`retry/execute.py.txt` and `final/execute.py.txt` preserve the enhanced runner used
for those rounds. It also records the full command and Python version and exits
nonzero after an exception. Both versions label a completed fence `executed`,
not `passed`: source issues and displayed-output agreement require the separate
acceptance check documented in the matrix.

## Final live results

At `28d12fb`, all displayed output matched for USGS, ANA, NVE, Bosnia, Czechia,
Thailand, Hub'Eau, Lithuania, Japan and Switzerland. Source warnings remained
visible: ANA reports the documented unresolved `bruto` level, and openpyxl warns
about Bosnia's workbook style. Neither was hidden or counted as a new failure.

HydroPortail remained blocked on the final implementation. Both unchanged
`validated` and `most_valid` requests exhausted timeout retries and returned zero
rows with `source.request_failed`. Its catalogue-only fence matched. The captured
bash-process wall time was 377.52 s. Final evidence is under
`final/fr_hydroportail/`; it is not a successful observation example. Required
all-provider live acceptance therefore remains incomplete even if every
repository regression passes. Final bulk execution is still in progress.

- `.worktrees/visions/provider-example-evidence` now holds the
  `verify/provider-examples` delivery branch. It merges the reviewed production
  implementation without changing either active compiler checkout. Completed
  output files are copied here byte-for-byte from the original evidence directory.
  This checkout identified reference drift before building documentation. The
  root owns the coverage-docstring/reference correction in a separate PR.
