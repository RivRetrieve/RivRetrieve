# Provider example verification

`execute.py` runs the Python fences in one page under `docs/providers/`, in their
published order. Fences on the same page share a Python namespace. Text fences
are displayed output and are not executed. This check contacts live services;
recording-based regression tests remain separate.

## Run a page

Review the implementation and page before using provider credentials. Supply
credentials through the environment. Set a fresh cache location and an output
directory outside source checkouts. `VERIFICATION_OUTPUT` below must name a
private external directory, and `REVISION` is the full reviewed implementation
commit.

```sh
export RIVRETRIEVE_CACHE_DIR="$VERIFICATION_OUTPUT/cache"
uv run python docs/verification/provider-examples/execute.py \
  docs/providers/PROVIDER.md "$VERIFICATION_OUTPUT/PROVIDER" \
  --revision REVISION
```

Replace `PROVIDER` with the page name. The command saves the exact executed code,
page digest, revision, timestamps, elapsed times and stdout/stderr. It refuses
an output directory inside a source checkout. Known credential values are
redacted, but output can still contain source data or request details. Keep it
private and review it before sharing any summary.

A successful exit does not establish successful retrieval. Inspect returned
issues, rows, units and agreement with the displayed output. Canada and Poland
examples run their documented national download and compilation. They can take
considerably longer than individual live requests.

## Retained verification records

The private [source archive](../../maintenance/evidence.md) retains the original
baseline, retry and final execution records, including executed snippets,
outputs and acceptance comparisons. Use its exact collection selections to
retrieve those historical records outside source checkouts.

The September 28, 2026 live-example verification remained incomplete because
HydroPortail observation requests failed. Its records do not establish current
service availability. [Implementation checks](implementation-tests.md) and the
[verification matrix](matrix.md) describe the separate historical code checks.
