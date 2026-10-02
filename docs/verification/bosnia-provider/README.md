# Bosnia page verification

The private source archive retains the historical verification report, acquisition
records, source extracts and execution output under
`docs/verification/bosnia-provider/`. Those records describe their recorded runs;
they do not establish current service availability.

## Offline checks

Follow the [verification guide](../../maintenance/evidence.md) to retrieve the
exact retained inputs outside the checkout. Set `RIVRETRIEVE_TEST_EVIDENCE_ROOT`
to the external directory with repository-relative member paths. Keep logs,
temporary files and generated output outside the checkout.

Run the complete [Bosnia governing check](../../../maintenance/catalogue/ba_fhmzbih/README.md)
with the separately supplied controlled workbook corpus. Then replay the provider
checks using the retained inputs:

```sh
uv run pytest tests/test_ba_fhmzbih_recorded_public.py tests/test_ba_fhmzbih_generate_catalogue.py tests/test_ba_fhmzbih_acquisition_provenance.py tests/test_bosnia_workbook_evidence.py -q --tb=no -p no:cacheprovider --basetemp=/path/to/private-verification/pytest-temp > /path/to/private-verification/tests.log 2>&1

uv run python docs/verification/bosnia-provider/inspect_catalogue.py \
  --native "$RIVRETRIEVE_TEST_EVIDENCE_ROOT/src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet" \
  > /path/to/private-verification/catalogue.log 2>&1
```

The parent output directory must already exist. Missing mandatory inputs block
verification. The retained native table cannot reconstruct missing publisher
originals. Runtime discovery and retrieval do not need archive access.

## New live checks

These helpers make fresh source requests. Their outputs describe new acquisitions
and must not replace historical recordings under the old identities. Run only
reviewed helpers, and keep their downloaded bodies and logs outside the checkout:

```sh
uv run python docs/verification/bosnia-provider/check_sources.py \
  --source-requests "$RIVRETRIEVE_TEST_EVIDENCE_ROOT/docs/verification/bosnia-provider/source-requests.json" \
  --out /path/to/private-verification/new-source-bodies \
  > /path/to/private-verification/new-source-checks.log 2>&1

uv run python docs/verification/bosnia-provider/check_workbooks.py \
  --out /path/to/private-verification/new-workbooks \
  > /path/to/private-verification/new-workbook-checks.log 2>&1
```

Workbook blanks, absent rows and failed requests remain distinct. The source does
not establish an observation time zone in these recordings. Source terms and
quality vocabulary remain uninterpreted. A successful replay checks the recorded
interaction; it does not establish continuous coverage or current source behavior.
