# Poland provider verification

The private [source archive](https://github.com/RivRetrieve/verification-evidence)
retains historical acquisition reports, source snapshots and execution results.
Use its inventory for exact collection selections and their limits. Those records
do not establish current service availability or replace a new verification run.

## Retained-input checks

Retrieve the exact Poland inputs following the [evidence guide](../../maintenance/evidence.md).
Set `RIVRETRIEVE_TEST_EVIDENCE_ROOT` to their external directory, preserving
repository-relative paths. Tests do not download inputs or use archive credentials.
Missing inputs block the checks.

Set `PRIVATE_TEST_OUTPUT` and `PRIVATE_CATALOGUE_OUTPUT` to fresh directories
outside source checkouts. Set `PRIVATE_LOG_DIR` to an existing private external
directory. Keep temporary stores, generated catalogues and logs at these locations.
Run from the repository root:

```sh
uv run pytest tests/test_pl_imgw_*.py tests/test_poland_documentation.py tests/store/test_pl_imgw*.py -q --tb=no -p no:cacheprovider --basetemp "$PRIVATE_TEST_OUTPUT" > "$PRIVATE_LOG_DIR/poland-tests.log" 2>&1

uv run python -m rivretrieve._internal.providers.pl_imgw.generate_catalogue \
  --native "$RIVRETRIEVE_TEST_EVIDENCE_ROOT/src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet" \
  --terms-recording "$RIVRETRIEVE_TEST_EVIDENCE_ROOT/tests/test_data/pl_imgw_terms_regulations.html" \
  --out "$PRIVATE_CATALOGUE_OUTPUT" > "$PRIVATE_LOG_DIR/poland-catalogue.log" 2>&1
```

The catalogue generator takes explicit local paths. Native-table refresh also
requires `--fixture` and `--roster` paths and their recorded provenance instants.
It does not discover archive inputs.

`tests/test_poland_documentation.py` compiles the retained annual archive and
checks the public retrieval snippets with network access disabled. It compares
the displayed output, source identity, catalogue facts and unknown-zone refusal.
This protects the reader example; it is not live acquisition evidence. The other
provider tests preserve native cells, verify exact catalogue regeneration and
check non-destructive refusal of retired store formats.

## Public-service checks

The example verifier uses the public API. It compares each printed result with
the output block in the provider page. Set `PRIVATE_CACHE_DIR` to an external
cache directory and keep its log private:

```sh
RIVRETRIEVE_CACHE_DIR="$PRIVATE_CACHE_DIR" uv run python docs/verification/poland-provider/verify_examples.py > "$PRIVATE_LOG_DIR/poland-public-examples.log" 2>&1
```

This command downloads and compiles the national archive. It is separate from
retained-input verification. To check an already prepared store without a new
download, run:

```sh
RIVRETRIEVE_CACHE_DIR="$PRIVATE_CACHE_DIR" uv run python docs/verification/poland-provider/verify_examples.py --reuse-store > "$PRIVATE_LOG_DIR/poland-store-examples.log" 2>&1
```

## Interpretation and limits

The catalogue describes daily source products with an unknown statistic. A mean
filter therefore does not admit these products. Stage is converted from centimetres
to metres. Time labels retain an unknown time zone; no day boundary is inferred.
Native blank cells, publisher null codes and numeric observations remain distinct.

Catalogue provenance distinguishes recovered coordinate inputs from later
corroboration. The reader page attributes the coordinates to GRDC. Preserve the
recorded acquisition distinction when rebuilding the catalogue.

A successful reader example does not establish continuous station history,
national coverage, a series statistic, vertical reference, coordinate reference
system or quality approval. Verification does not decide which legal conditions
apply to a particular use. Consult retained source records for the reviewed
interpretation and its source limits.

The compiler refuses a listed history ending before an existing valid store.
The question of intentional publisher withdrawals remains recorded in
[#392](https://github.com/RivRetrieve/RivRetrieve/issues/392#issuecomment-5866204605).
