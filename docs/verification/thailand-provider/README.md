# Thailand page verification

The private source archive retains the historical verification report and source
recording under `docs/verification/thailand-provider/`. Historical live checks and
source extracts describe their acquisitions, not current service availability.

## Offline checks

Follow the [verification guide](../../maintenance/evidence.md) to retrieve the
exact inputs outside the checkout. Set `RIVRETRIEVE_TEST_EVIDENCE_ROOT` to the
external directory with repository-relative member paths. Keep logs and temporary
files outside the checkout.

Run the complete [ThaiWater governing check](../../../maintenance/catalogue/th_thaiwater/README.md)
before negative provenance tests. Set `THAIWATER_REVIEW_EVIDENCE_ROOT` to that
same complete controlled acquisition directory. It is separate from the
repository-relative retained-input root. Missing mandatory inputs block acceptance.

Then run the page replay and provider checks:

```sh
uv run pytest tests/test_th_thaiwater_documentation.py tests/test_th_thaiwater_live.py tests/test_thaiwater_source_outcomes.py tests/test_thaiwater_source_windows.py tests/test_th_thaiwater_acquisition_provenance.py tests/test_th_thaiwater_generate_catalogue.py tests/test_thaiwater_governing_evidence.py -q --tb=no -p no:cacheprovider --basetemp=/path/to/private-verification/pytest-temp > /path/to/private-verification/tests.log 2>&1
```

The parent output directory must already exist. The page test replays the retained
source answer through the public API and checks the displayed examples. Replay
is not live verification. Runtime package users do not need archive access.

## New live checks

The live helper executes both page snippets through the public API. It contacts
the current service, prints source-call details and compares the output with the
page. Keep its output outside the checkout:

```sh
uv run python docs/verification/thailand-provider/verify_examples.py \
  > /path/to/private-verification/live-examples.log 2>&1
```

A changed live answer does not replace the historical recording. The source time
zone, statistic and vertical datum remain unknown where no applicable source fact
establishes them. An agency's data-exchange standard does not by itself establish
that the observation endpoint follows that standard. The retained native table
does not reconstruct the missing complete original metadata response.
