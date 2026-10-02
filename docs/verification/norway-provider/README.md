# Norway page verification

The private source archive retains the historical verification report, source
snapshots and recordings for the [Norway provider page](../../providers/no_nve.md).
Follow [verification evidence](../../maintenance/evidence.md) to retrieve exact
inputs. Keep historical reports separate from a new check of the current service.

## Offline checks

Set `RIVRETRIEVE_TEST_EVIDENCE_ROOT` to the external directory containing the
retained repository-relative paths. The tests read recordings, source responses,
capture attestations and the native station table from this directory. Missing
inputs fail the checks. No archive credentials or live service access are needed.

```sh
uv run pytest tests/test_no_nve*.py -q --tb=no -p no:cacheprovider
uv run python scripts/generate_reference.py --check
```

Keep test temporary files and full output outside source checkouts. Failure output
can include source values. The documentation test replays archived responses and
checks the example output, source calls and catalogue counts. Replay does not
establish current availability.

For offline native-table materialization, pass the same input root explicitly:

```sh
uv run python -m rivretrieve._internal.providers.no_nve.generate_catalogue \
  --materialize-record "$RIVRETRIEVE_TEST_EVIDENCE_ROOT/tests/test_data/no_nve_station_catalogue_capture.json" \
  --evidence-root "$RIVRETRIEVE_TEST_EVIDENCE_ROOT" \
  --native-out "$OUTPUT_ROOT/native.parquet"
```

`OUTPUT_ROOT` must name a separate external output directory. The historical
`--repository-root` spelling remains an alias for `--evidence-root`; either spelling
requires an explicit value. Recorded relative paths remain acquisition identities.

## Live checks and new recordings

Configure `NVE_API_KEY` following the provider page's credential instructions.
The live verifier executes the reader examples through the public API:

```sh
uv run python docs/verification/norway-provider/verify_examples.py
```

For a new recording, select a separate external `OUTPUT_ROOT`. Do not overwrite
selected historical inputs.

```sh
uv run python -m rivretrieve._internal.record_observations \
  --provider no_nve --station 2.605.0 --product discharge_daily_mean \
  --start 2024-01-01 --end 2024-01-07 \
  --out-dir "$OUTPUT_ROOT/recordings" --name discharge-week
```

A new acquisition does not replace an archived response under its original
identity. Keep credentials out of retained records and shared output.

## Interpretation limits

Source resolution establishes frequency separately from the source method's
statistic. Published timestamps do not establish exact daily averaging boundaries.
Source quality and correction codes remain uninterpreted diagnostics; a series
version is a separate identity.

A station listing does not establish continuous observations or current
availability for every quantity. A successful example does not establish a
national live inventory or scientific quality approval. HydAPI requests use one
uncapped time window; callers must not assume automatic splitting to satisfy an
upstream observation limit.
