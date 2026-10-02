# Norway page verification

Checked 2026-09-23 on macOS arm64, CPython 3.13.8, with `uv sync` and a privately
supplied `NVE_API_KEY`. Production baseline: `7dc5597a28737932f8296f3c3ae0a52ffbe2716a`;
feedback edits were tested over merge `2a24d3f11b3a6cb2c2439e3e2a0fc637cda36d00`.
No production code or catalogue was changed.

## Reproduce

From the checkout root, configure `NVE_API_KEY` in the environment or a private
working-directory `.env`, then execute all reader snippets in their documented order:

```bash
uv run python docs/verification/norway-provider/verify_examples.py
uv run python scripts/generate_reference.py --check
```

The verifier uses only the public API, with no fixtures or monkeypatches. On the
feedback revision it matched every displayed output: seven daily means, the two
informational source-code messages, and the separate station-specific version
lists. Fresh HTTP 200 calls at 20:40 UTC acquired `/Series`, then `/Observations`
for station `2.605.0`, parameter `1001`, resolution `1440`, explicit version `1`.
The padded interval was December 30, 2023 through January 9, 2024. Code summaries
cover 11 source rows; the returned seven rows cover January 1–7. Quality `2` and
correction `0` are independent of series version `1`.

The normal recording CLI also succeeded on 2026-09-23. For a fresh acquisition,
select an external `OUTPUT_ROOT` and run:

```bash
uv run python -m rivretrieve._internal.record_observations --provider no_nve --station 2.605.0 --product discharge_daily_mean --start 2024-01-01 --end 2024-01-07 --out-dir "$OUTPUT_ROOT/recordings" --name discharge-week
```

The two archived recordings retain exact publisher bytes and credential header
names, never values. The focused documentation test replays those bytes and checks
all snippet output, source calls and catalogue counts. Replay is not live verification.
The feedback-revision run passed all **95 tests** with one rdflib deprecation warning.
Scoped Ruff lint/format, generated-reference and diff-whitespace checks also passed.

## Offline checks

Retrieve the exact Norway inputs with the private archive instructions linked from
[verification evidence](../../maintenance/evidence.md). Set
`RIVRETRIEVE_TEST_EVIDENCE_ROOT` to the external directory containing the retained
repository-relative paths. The tests use this directory for recordings, source
responses, capture attestations and the native station table. Missing inputs fail
the checks; no archive credentials or live service access are needed.

```sh
uv run pytest tests/test_no_nve*.py -q --tb=no -p no:cacheprovider
```

Keep test temporary files and full output outside source checkouts. Full failure
output can include source values.

For offline native-table materialization, pass the same directory explicitly:

```sh
uv run python -m rivretrieve._internal.providers.no_nve.generate_catalogue \
  --materialize-record "$RIVRETRIEVE_TEST_EVIDENCE_ROOT/tests/test_data/no_nve_station_catalogue_capture.json" \
  --evidence-root "$RIVRETRIEVE_TEST_EVIDENCE_ROOT" \
  --native-out "$OUTPUT_ROOT/native.parquet"
```

`OUTPUT_ROOT` must name a separate external output directory. The historical
`--repository-root` spelling remains an alias for `--evidence-root`; either spelling
requires an explicit value. The recorded relative paths remain acquisition identities.

## Claims and limits

- Fresh authoritative pages in the provider page's Sources were checked on September 23.
  NVE establishes its institutional role, other producers and conditional publication
  restrictions. HydAPI supplies code meanings, registration steps, UTC labels and
  service limits. NLOD 2.0 supplies qualified reuse and attribution conditions.
- The packaged catalogue has 4,902 locations and 3,804 stations with supported series.
  Native station evidence shows the other 1,098 list other parameters, rather than
  missing series metadata. Daily mean counts and all resolution/method combinations
  were checked against packaged source-series facts, not product-name assumptions.
- `no_nve/series.py` establishes frequency separately from statistic and leaves
  temporal support unknown. `parse.py` retains nulls and source-code summaries;
  `fetch.py` isolates versions and failures. `config.py` uses one uncapped
  `iso-instant` window, not adaptive observation-limit splitting.
- No code defect was found. Daily-boundary source wording remains inconsistent;
  no exact interval is inferred. No key-issuance timing, numeric service limit,
  national live census, continuous-history or quality-approval claim is made.

The private archive retains the historical source snapshots, execution records and
recordings. The maintained tests and verifier retain the focused regression and
live-recheck paths.
