# Verification evidence

The private [source archive](https://github.com/RivRetrieve/verification-evidence)
maintains the retained-material inventory, collection identities, acquisition
records, known gaps and archive tools. Its README gives access prerequisites and
commands for discovery, exact retrieval, intake and publication. Use an explicitly
reviewed archive revision and existing GitHub access. Runtime package users need
no archive credentials.

## Obtain exact inputs

Select an exact collection from the archive. The archive tool checks release and
asset identities, byte sizes, SHA-256 digests and extraction limits. For
manifest-bound collections, it also checks the manifest and retained members.
Download to a directory outside source checkouts, then pass the verified local
input directory to the relevant verifier. Do not substitute a mutable `latest`
release, search acquisition-machine paths or silently replace a selected input.
Publishing archive material does not select it for a test or catalogue.

Collection integrity establishes which bytes were retrieved, not whether they
support a source claim. Keep acquisition identities, original bytes, receipts and
known limitations. A native-table rebuild cannot certify missing original
responses. A later acquisition cannot replace an earlier one under its identity.
Pinned fingerprints detect changed material; they do not prevent attachment loss
or provide an independent backup.

## Verify source claims

Provider interpretation, reviewed declarations and source-claim verifiers remain
in RivRetrieve. Retained source material and required historical test inputs live
in the private archive. Tests and catalogue tools receive verified local inputs
explicitly. Packaged catalogues remain in RivRetrieve and work without archive access.
Historical provenance paths identify the original acquisitions; they do not locate
files in the current checkout.

Catalogue publication receives an explicit selection of verified members and public
code references. The selection records each adopted member's collection, manifest,
artifact identity, digest, size and archive revision. The archive's material role
and the member's use in the build remain separate. Adding a collection does not
change a provider's selected inputs.

Use the private coordinator's catalogue-input mode for catalogue rebuild tests.
Select both the reviewed executable revision and the declaration revision explicitly.
The current coordinator requires these revisions to match. Whole-file declaration
references identify reviewed ledgers as well as Python declarations. A build's
publication entry point is separate from the executable references for catalogue
conversion, observation assembly and metadata projection. Authored constants retain
their declaration reference without becoming automatic source derivations.
The coordinator writes a restricted input handoff and an external product
directory; builds do not write into the reviewed checkout. The build fixture selects the provider's declared native and
recording support and verifies their exact local bytes. Only those adopted members
enter packaged provenance. The full restricted receipt is not a package artifact.

Review the resulting station metadata, provenance, descriptors and distribution
contents before copying approved products into RivRetrieve. New name mappings need
both retained-input checks and a separate disclosure decision. Keep candidate field review and disclosure decisions separate from verification
of adopted mappings. Compare existing area fields with their approved baseline
without changing scalar values, units or absence states.

Use the provider's instructions:

- [Bosnia](../../maintenance/catalogue/ba_fhmzbih/README.md): complete baseline
  workbook checks require the controlled source bodies and receipts.
- [France](../../maintenance/catalogue/fr_hubeau/README.md): historical governing
  checks require the retained historical native table, not the current Hub’Eau
  catalogue table.
- [HydroPortail](../../maintenance/catalogue/fr_hydroportail/README.md): native
  inventory rebuild and the limits of historical source witnesses.
- [ThaiWater](../../maintenance/catalogue/th_thaiwater/README.md): complete
  genuine-input verification must precede negative provenance regressions. The
  archive coordinator supplies the verified governing inputs after that positive
  check passes. A skipped test or an exception from missing files does not establish
  acceptance.
- [Brazil](../../maintenance/catalogue/br_ana/README.md): digest-bound supporting
  inputs and retained recordings used by the offline rebuild.

## Run tests

The [testing guide](testing.md) explains each layer's purpose, expected answers
and ownership. Use it when adding or changing coverage.

Run source-independent checks from the RivRetrieve checkout without archive access:

```sh
uv run pytest --logic-only
```

Collection does not open private inputs. This route includes synthetic controls,
packaged-catalogue checks and public declarations. It does not establish acceptance
of genuine source inputs.

For retained-input tests, run the private archive coordinator from a clean,
reviewed archive checkout. Authenticate with existing GitHub access. Both full
commit IDs must identify independently reviewed code. Follow the archive README
for restricted storage and execution prerequisites.

For example, the Canada HYDAT `NO_DAYS` checks use sparse SQLite row witnesses and
separate publisher recordings. The reconstructed database is not a complete
publisher artifact. Run those checks with:

```sh
uv run --isolated --locked python -B verify.py \
  --reviewed-archive-sha "$REVIEWED_ARCHIVE_SHA" \
  --code-checkout /path/to/reviewed-rivretrieve \
  --reviewed-code-sha "$REVIEWED_CODE_SHA" \
  --output "$NEW_PRIVATE_ACCEPTANCE_DIRECTORY" \
  --tests -- tests/test_ca_eccc_no_days_evidence.py
```

Use `--tests -- tests` for the whole test suite. Without `--tests`, the coordinator
runs its full governing checks and fixed regression group. Selected tests declare
the consumer paths they need; the private archive maps those paths to exact
collection members. The coordinator acquires and verifies the selected inputs,
runs required complete positive verifiers, then runs exactly the collected tests.
No per-provider downloads or manual path configuration are needed. Missing access,
missing material, changed bytes, changed test selection and skipped requested
checks fail the controlled run.

Tests receive one repository-relative working copy through `retained_evidence_root`.
`RIVRETRIEVE_TEST_EVIDENCE_ROOT` and `THAIWATER_REVIEW_EVIDENCE_ROOT` are internal
coordinator handoffs, not proof of archive membership or normal developer setup.
Tests do not acquire evidence or receive archive credentials. Detailed output,
receipts, caches and temporary files remain in restricted storage. Review the safe
summary before sharing it.

Test purposes remain distinct:

| Selection | What a passing check establishes |
| --- | --- |
| `--logic-only` | Source-independent behavior against synthetic controls or public package inputs |
| `-m recorded` | Parser or retrieval behavior against genuine retained recordings |
| `-m derived` | An offline rebuild or check of derived inputs, not the existence of original responses |
| `-m governing` | The specific catalogue or governing-source assertions in the selected checks |
| `-m live` | An observation of a live service, when such a check exists |

Pass `-m` selections after `--` in the archive command. Tests may have more than one
purpose. A recording replay is not a live observation. Selecting a governing
regression does not itself certify every source body; its declared full-positive
prerequisites run first. Historical coverage gaps remain recorded in the archive.

Other provider checks and retained-input limits are recorded in the private
archive and provider maintenance notes under `docs/provider_ports/`.

Run applicable full checks when governing claims, source bindings, verifiers or
collections change. Missing mandatory material is blocked, not a passing or
silently skipped check. Keep recording replay, native rebuilds, complete source-body
verification and live-service observations distinct. Synthetic archive-mechanics
tests do not establish genuine collection acceptance.

The private archive also maintains the full-check coordinator. It runs against an
explicitly reviewed RivRetrieve commit and records exact collections, fingerprints,
commands, outcomes, skips and limitations. Follow its current instructions rather
than reconstructing a verification run from historical acceptance records.

## Protect controlled material

Run only reviewed code with private evidence or credentials. Tests receive local
inputs, not archive credentials. Keep private bodies, request details, credentials
and evidence-backed output out of public issues, assertion output, logs, caches,
CI artifacts and distributions. Review summaries before sharing them. Downloading
outside Git does not by itself prevent disclosure, and private archive access does
not establish source-sharing rights.

Preserve originals and historical acceptance records. Retire redundant copies only
after proving archive preservation and obtaining required owner approval. New
provider code PRs carry code and exact archive references, not source corpora or
private attachments. See the [architecture](../architecture.md#evidence-and-verification)
for the runtime and catalogue boundaries.
