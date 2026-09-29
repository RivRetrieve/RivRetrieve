# Verification evidence

Saved publisher responses let a reviewer check the source facts behind a catalogue
claim or parser result. A later request can return different data. Keep the original
bytes with their request identities, retrieval dates and acquisition receipts.

The [provider evidence index](../../maintenance/evidence/index.json) lists all 14
providers, retained material, applicable checks and known gaps. It separates native
catalogue inputs, genuine runtime recordings, publisher documents, bulk artifacts
and restricted material. A catalogue rebuilt from a native table does not prove
that every original response has been retained.

## Access and storage

Shared collections belong in versioned releases of the private
[`RivRetrieve/verification-evidence`](https://github.com/RivRetrieve/verification-evidence)
repository. Use a personal GitHub account with the existing organization access.
An organization owner administers access; ask an owner if the repository is not
visible. No shared human password or separate evidence-reader team is required.
Making the code repository public must not make the evidence repository public.

Authenticate the GitHub CLI before downloading:

```sh
gh auth status
gh repo view RivRetrieve/verification-evidence --json nameWithOwner,visibility
```

The repository visibility must be `PRIVATE`. Do not paste authentication output,
private response content, request headers or private correspondence into public
issues or logs. Access to the repository does not establish permission to publish
its source material. Check authority to share restricted correspondence before
adding it, even to this private repository.

The owner chose not to keep an independent backup. A Git clone or mirror does not
back up release attachments. Loss of those attachments has no independent recovery
guarantee. Preserve original local evidence during migration; these instructions
do not authorize deleting it.

## Public checks

Ordinary tests use retained, reviewed source recordings and require no private
evidence credentials. From the source checkout:

```sh
uv run python -m maintenance.evidence validate \
  --index maintenance/evidence/index.json

uv run pytest tests/test_catalogue_origin_certification.py -q
```

Index validation checks the records and pinned identities, not the contents of
unavailable private assets. Catalogue origin tests rebuild all providers with
network access denied. Their native inputs and source recordings remain repository
build inputs, outside distributed Python packages.

Provider-specific public commands are in the index. These tests establish behavior
against saved inputs, not current service availability. Do not replace genuine
recordings with synthetic responses or remove assertions to avoid private access.
Some large files under `tests/` and `research/` are active build or test inputs;
directory names alone do not determine what can move.

## Download one exact collection

Choose a provider and an exact collection ID from its index entry. The matching
collection record pins the release ID, release tag, asset IDs, byte sizes and
SHA-256 digests. Its `verification_root` gives the relative directory used by the
provider verifier. Never substitute a mutable `latest` release. An empty collection
list means shared acquisition for that provider is not recorded. Stop rather than
invent an ID or treat local derived tables as the missing collection.

Use an evidence directory outside the source checkout. The following example uses
ThaiWater. Set `COLLECTION_ID` to a real indexed ID before running it:

```sh
export COLLECTION_ID='COPY_EXACT_ID_FROM_INDEX'
export EVIDENCE_ROOT="$HOME/.local/share/rivretrieve/verification-evidence"

uv run python -m maintenance.evidence fetch \
  --index maintenance/evidence/index.json \
  --provider th_thaiwater \
  --collection "$COLLECTION_ID" \
  --destination "$EVIDENCE_ROOT"
```

The command downloads only the selected assets through authenticated GitHub access.
It checks their pinned identities, byte sizes and SHA-256 digests before extracting
them. Safe extraction refuses unsafe archive members. An existing target fails;
the command does not overwrite an earlier collection or silently reuse it.

The extracted collection is at `$EVIDENCE_ROOT/$COLLECTION_ID`. Successful output
identifies the collection, release, assets and relative `verification_root` without
printing private contents. Download success establishes transport integrity, not
provider acceptance. Use the provider verifier next. Keep the collection's
acquisition-relative paths unchanged. A root of `.` means the extraction directory
itself; a named subdirectory means the verifier starts inside it.

## Verify the original source claims

Each provider has different checks. Follow its index entry rather than assume one
parser example establishes national coverage. The complete controlled checks for
Bosnia, France and ThaiWater require the original bodies and receipts. Missing
material is a failed prerequisite, not a reason to skip or weaken a mandatory check.

For ThaiWater, copy `verification_root` from the selected collection record or
fetch output. The retained whole-provider collection uses
`baseline-capture-2026-09-13`. Set the variable before running the complete verifier:

```sh
export VERIFICATION_ROOT='COPY_VERIFICATION_ROOT_FROM_INDEX'
export THAIWATER_REVIEW_EVIDENCE_ROOT="$EVIDENCE_ROOT/$COLLECTION_ID/$VERIFICATION_ROOT"

uv run python maintenance/catalogue/th_thaiwater/scripts/verify_governing_evidence.py \
  --ledger maintenance/catalogue/th_thaiwater/inventory/governing_station_product_evidence.csv \
  --native src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet \
  --evidence-root "$THAIWATER_REVIEW_EVIDENCE_ROOT"
```

For the retained baseline, success verifies 825 stations and 1,650 pairs, including
1,096 available and 554 unknown pairs. Only after that succeeds, run the regression
against the same directory:

```sh
uv run pytest tests/test_thaiwater_governing_evidence.py \
  tests/test_thaiwater_source_outcomes.py -q
```

The complete check and all eight tests must pass, with no skip. An unset evidence
variable skips the private regression. An empty directory can satisfy its negative
exception assertion, so that test alone does not establish that genuine inputs
were verified.

The [Bosnia verifier](../../maintenance/catalogue/ba_fhmzbih/README.md) checks all
180 baseline station-product pairs against private workbook bodies. The
[France verifier](../../maintenance/catalogue/fr_hubeau/README.md) checks the mixed
historical governing acquisitions and their receipts. Its ledger requires the
retained historical `native-2026-08-02.parquet`, not the current Hub’Eau native table
after publication-service separation. HydroPortail has its own
[native inventory rebuild](../../maintenance/catalogue/fr_hydroportail/README.md);
its historical raw witnesses do not establish other selector coverage.

For other providers, preserve the index's limits. Small station fixtures are not
complete national acquisitions. A redacted correspondence record is not the
original email. A compiled bulk store cannot reconstruct a deleted publisher ZIP.
Keep missing originals visible even when the applicable native rebuild passes.

## Full verification and acceptance records

Run full controlled checks when changing governing catalogue claims, their source
bindings, provider verification logic, or collection contents. Run them for a new
collection acceptance as well. A maintainer can request additional full checks for
a public pull request when its changes affect those claims.

Full verification runs in the private evidence repository against an explicitly
reviewed RivRetrieve commit. Its restricted environment supplies evidence access.
Never run unreviewed fork code with those credentials or private data. Public jobs
may validate the index and public fixtures; they cannot certify missing private
bytes. Do not place controlled material in public logs, caches, artifacts, release
assets or Python packages.

Record:

- The exact reviewed source commit and collection IDs.
- Release and asset identities, byte sizes and SHA-256 fingerprints.
- Commands, outcomes, required tests and any skips or blocked checks.
- Source limitations and missing originals, separately from successful checks.
- The environment used to download and verify the collection independently of the
  original acquisition machine.

A public summary may report approved outcomes and fingerprints. Keep private logs
and bodies in the restricted environment. Do not claim shared-download acceptance
until an independent download, integrity check and applicable full verifier have
actually succeeded.

## Review and publish a new collection

1. Recover existing material first. Keep original bytes, receipts, dates and paths.
   Do not recreate originals from native tables or label a new request as an old
   acquisition. Replacement acquisitions need separate review and updated bindings.
2. Review source terms, correspondence authority, URLs, headers and logs. Private
   storage does not itself grant permission to redistribute material. Preserve
   null values, missing rows, source failures and unknown facts distinctly.
3. Separate public test inputs from the controlled collection. Preserve existing
   public tests and reproducible builds. Runtime library calls must not discover
   maintainer caches or private repositories.
4. Build archives with the expected acquisition-relative paths. GitHub requires
   each release asset to be less than 2 GiB and allows up to 1,000 assets per
   release. Split by coherent acquisition boundaries when needed. Record expanded
   sizes and member counts as well as archive sizes and digests.
5. Publish to a new versioned private release. Record the actual release and asset
   IDs and relative `verification_root` in the index. Do not reuse an accepted
   collection identity for new bytes.
   Enable GitHub immutable-release protection where available and verify its actual
   setting and release state. Record an unavailable setting or hosting limitation
   explicitly; do not claim protection that has not been verified.
6. Download through the documented workflow in an independent clean environment.
   Run the complete provider verifier before negative regressions, and save the
   acceptance record. Retain original local evidence throughout migration.

Before making the code repository public, conduct a separate publication-readiness
review of reachable Git history, recordings, archives, terms and provisioning
artifacts. This evidence workflow does not authorize visibility changes, history
rewrites or credential rotation. See the
[architecture](../architecture.md#evidence-and-verification) for the runtime and
catalogue boundaries.
