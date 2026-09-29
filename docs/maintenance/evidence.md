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

Retained collections are attached to versioned releases of the private
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

### Release protection

GitHub reported `immutable: false` for the three historical releases and all
14 manifest-bound collection releases published on September 29, 2026. These
releases are not protected by GitHub release immutability. This observed release state does not establish the repository or
organization setting.

The index pins each release and asset identity, byte size and SHA-256 digest.
The download tool rejects missing identities and changed bytes. These checks do
not prevent replacement or deletion, and a digest cannot recover a deleted file.
Updates must receive new collection identities. The owner authorized these
versioned releases without immutable-release protection; the lack of an
independent backup remains unchanged.

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
SHA-256 digests. Its `input_roots` map names consumer inputs to relative directories. The
`verification` entry gives the provider verifier's root. Never substitute a mutable `latest` release. An empty collection
list means shared acquisition for that provider is not recorded. Stop rather than
invent an ID or treat local derived tables as the missing collection.

Use an evidence directory outside the source checkout. The following example uses
the manifest-bound ThaiWater collection `th_thaiwater-2026-09-29-v2`. Its exact release
and asset identities are in the index:

```sh
export COLLECTION_ID='th_thaiwater-2026-09-29-v2'
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
identifies the collection, release, assets and relative `input_roots` without
printing private contents. Download success establishes transport integrity, not
provider acceptance. Use the provider verifier next. Keep the collection's
acquisition-relative paths unchanged. A root of `.` means the extraction directory
itself; a named subdirectory means the verifier starts inside it.

## Verify the original source claims

Each provider has different checks. Follow its index entry rather than assume one
parser example establishes national coverage. The complete controlled checks for
Bosnia, France and ThaiWater require the original bodies and receipts. Missing
material is a failed prerequisite, not a reason to skip or weaken a mandatory check.

For this ThaiWater collection, the indexed `input_roots.verification` is
`retained/baseline-capture-2026-09-13`. Confirm that value in the selected record or fetch
output if choosing another collection. Set it before running the complete verifier:

```sh
export VERIFICATION_ROOT='retained/baseline-capture-2026-09-13'
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

## Shared archive contract

The public index uses schema version `2`. It lists explicit collection selections,
provider checks and gaps. It retains three historical packages and selects
14 manifest-bound collections. The France collection serves both Hub’Eau and
HydroPortail. A separate context collection serves all 14 providers. Publication
checks passed for their 30 assets. Independent retrieval verified all 4,178 retained
artifacts against the published manifests. The applicable complete Bosnia, France
and ThaiWater checks passed, including the ThaiWater positive check before its
negative regressions. Complete governing source-body checks apply to those three
collections. Other catalogue, native-input and recording checks still read their
existing consumer inputs; they do not certify every archived source body. These
results preserve the recorded source scope and gaps. They do not establish source
completeness or public redistribution rights. Each collection pins a release, compressed assets and
named `input_roots`. A non-null `manifest` binds the private manifest's relative
path and SHA-256. Fetch verifies every compressed asset before extraction, then
checks the manifest, provider bindings and every retained member. Historical
packages with `manifest: null` remain identified historical inputs. They do not
establish acceptance under the manifest contract.

The private `CollectionManifest` uses schema version `1`. Its records separate:

- Acquisition record keys from retained original event identities. An archive key
  does not recover an unknown original identity, date or request. Unknown facts
  use `null`. Repeated acquisitions remain distinct even when their bytes match.
- Artifact identity from its member path, byte size and SHA-256. Artifact roles
  distinguish publisher originals, response recordings, derived inputs, authored
  interpretations and declarations, research context, runtime products and receipts.
- `derived_from` and `receipt_refs` from the retained bytes themselves. References
  must resolve within the manifest. Missing originals remain explicit limitations.
- Collection packaging from the exact GitHub release and asset identities created
  by publication. A new package does not establish a new source acquisition.

The typed schema is in
[`manifest.py`](../../maintenance/evidence/manifest.py). Artifact paths identify
regular files relative to the supplied source directory. The manifest describes
every retained file, but excludes its own generated `collection-manifest.json`.
Detailed provenance, private request context and receipts stay in the private
manifest. Public location-level material records identify reviewed native inputs and mixed
collections. Collection role lists summarize the roles present; the private
manifest classifies individual members. A directory name does not classify every
file inside it.

Python callers use `acquire_collection` with an explicit index, provider,
collection, destination and source-checkout roots. Its `SelectedInputs` result
contains the collection, working-copy root and resolved named input paths. Test
and catalogue consumers receive those paths. They do not resolve credentials,
search owner-machine directories or choose a mutable latest release.

## Intake and publication

1. Review existing material before preparing a collection. Keep original bytes,
   receipts, dates and source vocabulary. Do not recreate originals from native
   tables or label a later request as an old acquisition. Review sharing rights;
   private storage does not establish permission to redistribute material.
2. Write a private manifest with the actual roles and acquisition facts. Keep
   speculative or unaccepted notes as authored material. Mixed directories require
   artifact-level review. Preserve active test and catalogue inputs until their
   consumers have been adapted.
3. Run offline intake against an explicit source directory and private manifest.
   Choose a new destination outside source checkouts and separate from that source:

   ```sh
   uv run python -m maintenance.evidence intake \
     --manifest "$PRIVATE_MANIFEST" \
     --source "$RETAINED_FILES" \
     --destination "$PREPARED_ROOT"
   ```

   Intake inventories and hashes every supplied file, refuses links and unsafe
   paths, and checks exact manifest membership. It creates bounded archive assets,
   extracts them into staging and compares each retained member with the manifest.
   It leaves source files unchanged. Its output is
   `$PREPARED_ROOT/$COLLECTION_ID`, with a private `preparation.json` and archives.
   This establishes packaging equivalence, not source acceptance.
4. After reviewing the executing code, publish that preparation to a new release:

   ```sh
   uv run python -m maintenance.evidence publish \
     --prepared "$PREPARED_ROOT/$COLLECTION_ID" \
     --release-tag "$COLLECTION_ID" \
     --output "$PRIVATE_PUBLICATION_RECORD" \
     --purpose 'Reviewed retained source collection' \
     --limitation 'Publication does not establish provider acceptance.'
   ```

   Purpose and limitation arguments must contain only reviewed public facts.
   Publication checks that the exact repository is private and that its collection
   identity and tag are unused. It creates a new draft, uploads verified assets,
   checks returned identities, downloads each exact upload and verifies its bytes.
   Only then does it publish the release. It records observed immutability without
   changing repository settings or claiming a recovery guarantee.

   The new private output directory retains `release.json`, then
   `draft-selection.json`, and after success `publication.json`. A partial upload
   remains a draft. If GitHub completed publication before a later check or local
   write failed, the release may already be public to authorized repository readers.
   Inspect the recorded identity before retrying. The tool never deletes a draft,
   replaces a release, overwrites a local record or updates a consumer selection.
5. Review the exact collection record from `publication.json` before adding its
   selection to the public index. Keep private acquisition facts out of that index.
   Download independently with reviewed code and run all applicable full checks.
   Save acceptance separately from publication. Complete genuine ThaiWater checks
   precede negative regressions; historical France checks use the retained
   historical native input.

New-provider code PRs carry code and exact archive references, not source corpora
or private attachments. Retention does not endorse a claim or select a consumer
input. No intake or publication command authorizes deleting retained material.
Retire verified redundant copies only after proving archive preservation and
obtaining any required owner approval.

Before making the code repository public, conduct a separate publication-readiness
review of reachable Git history, recordings, archives, terms and provisioning
artifacts. This evidence workflow does not authorize visibility changes, history
rewrites or credential rotation. See the
[architecture](../architecture.md#evidence-and-verification) for the runtime and
catalogue boundaries.
