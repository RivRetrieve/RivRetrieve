# USGS retained inputs

Retrieve exact collections through the private [source archive](https://github.com/RivRetrieve/verification-evidence).
Keep the verified inputs outside source checkouts, with their repository-relative
paths below one input directory. The archive retains modern observation recordings,
source documents, metadata pages, historical catalogue inputs and their acquisition
records. Runtime discovery uses the packaged catalogue without archive access.

## Verify offline

Set `RIVRETRIEVE_TEST_EVIDENCE_ROOT` to that input directory. Run the provider tests
with a private external temporary directory and save output privately:

```sh
uv run pytest -q tests/test_usgs_*.py --basetemp "$PRIVATE_TEST_OUTPUT"
```

These checks cover exact-coordinate replay, documentation examples, source-body
integrity, catalogue input validation and deterministic catalogue rebuilding.
Missing required inputs fail the checks. They do not trigger a download or use a
repository copy. Shared engine and documentation tests also use these recordings.

The catalogue build takes explicit local inputs:

```sh
uv run python -m rivretrieve._internal.providers.usgs_nwis.generate_catalogue \
  --native "$RIVRETRIEVE_TEST_EVIDENCE_ROOT/src/rivretrieve/_internal/providers/usgs_nwis/catalogue/native.parquet" \
  --modern-metadata "$RIVRETRIEVE_TEST_EVIDENCE_ROOT/research/usgs-modern-coverage" \
  --evidence-root "$RIVRETRIEVE_TEST_EVIDENCE_ROOT" \
  --out "$PRIVATE_CATALOGUE_OUTPUT"
```

The recorded source-path identities in provenance stay unchanged. The explicit
evidence root resolves them to local archive inputs. `monitoring_locations.json`
is a runtime catalogue product and remains packaged.

## Coverage comparison and acquisition

`scripts/audit_usgs_coverage.py --output EXTERNAL_DIRECTORY --compare-only`
repeats the historical coverage comparison from a writable external copy of its
retained inputs. It writes comparison results there. Acquisition additionally
requires `--baseline-catalogue` and `--native`; use a new external output directory
to preserve the original acquisition. A new response cannot replace an older one
under its acquisition identity.

Documentation acquisition tools also require explicit paths. `execute_examples.py`
takes `--page` and `--output`. `source-research/acquire.py` takes a retained
`--requests` JSON file and `--output`. These tools make network requests; offline
verification replays retained responses instead.

## Historical tests

The retired WaterServices raw-count and raw-method tests did not execute the
current provider. Their originals remain in the archive. Current modern parser,
route, cache and artifact-refusal checks remain, as do bounded historical-to-modern
value comparisons in `test_usgs_modern_evidence.py`. Independent legacy acquisition
identities are not mapped to modern series by coincident values.
