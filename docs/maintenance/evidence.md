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

Use the provider's instructions:

- [Bosnia](../../maintenance/catalogue/ba_fhmzbih/README.md): complete baseline
  workbook checks require the controlled source bodies and receipts.
- [France](../../maintenance/catalogue/fr_hubeau/README.md): historical governing
  checks require the retained historical native table, not the current Hub’Eau
  catalogue table.
- [HydroPortail](../../maintenance/catalogue/fr_hydroportail/README.md): native
  inventory rebuild and the limits of historical source witnesses.
- [ThaiWater](../../maintenance/catalogue/th_thaiwater/README.md): run the complete
  genuine-input verifier before negative provenance regressions. Set
  `THAIWATER_REVIEW_EVIDENCE_ROOT` to the same verified directory. A skipped test or
  an exception from missing files does not establish acceptance.
- [Brazil](../../maintenance/catalogue/br_ana/README.md): digest-bound supporting
  inputs and retained recordings used by the offline rebuild.

For retained-input tests, set `RIVRETRIEVE_TEST_EVIDENCE_ROOT` to a verified
directory outside source checkouts. Preserve the inputs' repository-relative
layout under that directory. Tests read it through the `retained_evidence_root`
fixture. There is no checkout fallback or automatic download.

For example, the Canada HYDAT `NO_DAYS` group contains sparse SQLite row
witnesses and separate publisher recordings under
`tests/test_data/ca_eccc_hydat_no_days/`. The reconstructed test database is not a
complete publisher artifact. After retrieving the selected group, run:

```sh
uv run pytest tests/test_ca_eccc_no_days_evidence.py -q --tb=no -p no:cacheprovider
```

Missing inputs block these checks. The tests do not download inputs or use archive
credentials. Keep full failure details private; assertion output can contain source
values. The private archive records the exact collection and member selections.

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
