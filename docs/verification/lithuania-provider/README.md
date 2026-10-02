# Lithuania page verification

The private source archive retains the historical verification report, source
recordings and source-check results for the [Lithuania provider page](../../providers/lt_lhmt.md).
Follow [verification evidence](../../maintenance/evidence.md) to retrieve exact
inputs. Keep historical reports separate from a new check of the current service.

## Recorded checks

Set `RIVRETRIEVE_TEST_EVIDENCE_ROOT` to the external directory containing the
retained repository-relative input paths. Missing inputs fail the checks.
No archive credentials or live service access are needed for replay.

```sh
uv run pytest tests/test_lt_lhmt_documentation.py tests/test_lt_lhmt_live.py \
  tests/test_lt_lhmt_monthly_isolation.py tests/test_lt_lhmt_shared_acquisition.py \
  tests/test_lt_lhmt_generate_catalogue.py -q --tb=no -p no:cacheprovider
uv run python scripts/generate_reference.py --check
```

Keep test temporary files and full output outside source checkouts. Failure
output can contain source values. The documentation test replays archived
responses to check the example output, source calls, units and catalogue counts.
Replay does not establish current availability.

## Live checks and new recordings

The live verifier executes the page's examples through the public API with
`cache="bypass"`. It contacts the publisher and needs no credentials:

```sh
uv run python docs/verification/lithuania-provider/verify_examples.py
```

For a new recording, set `RECORDING_OUTPUT_DIRECTORY` to a separate external
output directory. Do not overwrite selected historical inputs.

```sh
uv run python -m rivretrieve._internal.record_observations \
  --provider lt_lhmt --station nemajunu-vms --product discharge_daily_mean \
  --start 2020-01-01 --end 2020-01-07 \
  --out-dir "$RECORDING_OUTPUT_DIRECTORY" --name nemajunu-week
```

The API publishes both supported fields in one monthly document. A recording of
that document can therefore support checks of both quantities. A new acquisition
does not replace an archived response under its original identity.

## Interpretation limits

A published null remains a row with `value=null`. An unpublished requested month
has an identified warning; it is not an empty success. An unpublished padding-only
month remains in provenance without a requested-data warning. A shared monthly
request preserves the identities of both selected quantities.

The source's UTC date label does not establish the averaging day's boundaries.
RivRetrieve does not infer a stage datum or quality status. A historical station
listing or observed publication delay does not establish current availability or
a fixed publication schedule.
