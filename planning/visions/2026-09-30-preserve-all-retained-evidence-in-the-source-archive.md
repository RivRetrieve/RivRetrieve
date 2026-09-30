# Preserve all retained evidence in the source archive

Related bug: https://github.com/RivRetrieve/RivRetrieve/issues/457
Blocked work, outside this vision: https://github.com/RivRetrieve/RivRetrieve/issues/429

## Outcome and scope

Establish verified preservation in the private `RivRetrieve/verification-evidence`
archive for all retained evidence still held in RivRetrieve. Account for unused
and historical material as well as inputs used by current tests. Do not limit the
repair to the first unmatched files reported in #457 or to mandatory regressions.

The owner's final requirement is that no retained source evidence remains in the
maintained RivRetrieve repository tree. The archive is its sole maintained home.
Code, test definitions, reviewed executable interpretation, authored declarations
and approved runtime product artifacts retain their code-repository roles. A file
being called metadata, a fixture or a cache does not establish its role.

This vision repairs #457 only. #429 remains paused and outside scope. Do not resume
its consumer refactor, change its preserved drafts or deliver its shared test-input
interface. The owner will decide when to resume #429 after #457 is closed. This
repair must provide complete preservation accounting and exact archive references
that make the subsequent removal safe. It does not authorize deleting active
inputs before their consumers have verified replacements. Do not claim that archive
publication alone achieves the final evidence-free repository state.

## Why the blocker exists

#429 is changing how tests obtain evidence. Its selected 14 archive collections
were reported to lack exact copies of some retained historical and derived inputs.
The local originals were preserved. This is a retention and access gap, not evidence
that provider values or scientific claims are wrong.

Some tests deliberately consume old outputs. For example, a test opens an obsolete
observation store and checks that RivRetrieve refuses it without altering its bytes.
A current download or a regenerated old-looking store cannot replace that historical
input. Other tests compare extracted source cells with separate retained recordings.
Derived inputs remain valuable evidence, but they must not be relabelled as untouched
publisher originals.

The issue's unmatched list is a starting point, not a complete or authoritative
classification. Its correction identifies five actual metadata fixtures and retracts
a guessed Polish filename. Do not repeat the guessed filename as an existing input
or infer that all files in an unmatched directory are scientifically required.
Absence of a current test consumer is also not permission to discard retained evidence.

## Classify and preserve the material

Use the private preservation accounting and the actual repository contents to build
an artifact-level inventory. Cover retained evidence across test recordings, test
data, verification documents, maintenance and research inputs, and any other retained
source locations found during inspection. Inspect the preserved #429 accounting
without treating its unreviewed implementation as executable or authoritative.
Do not turn reproducible build output or incidental dependency caches into evidence.

For each candidate, establish its role, exact byte identity, known acquisition or
derivation identity, current consumers if any, and its archive disposition. Distinguish
publisher originals, response recordings, extracted subsets, generated historical
artifacts, acquisition records and authored interpretation. Mixed files need explicit
review; do not move maintained executable declarations into the archive simply because
they mention evidence. Preserve original mixed-file bytes where they are evidence;
do not rewrite historical inputs to make classification easier.

Find an exact existing archive match or retain the existing bytes through the reviewed
intake workflow. Record the selected collection and member identity privately. Equal
bytes do not erase distinct acquisition identities. Preserve known lineage and record
unknowns honestly. Review source-sharing permissions using the existing archive rules.
If material cannot be classified or safely retained, report a concrete blocker rather
than dropping it, inventing provenance or declaring the inventory complete.

No new provider acquisition, reconstruction, synthetic substitute, changed source
claim or weakened regression is part of this repair. Historical derived inputs must
remain historical derived inputs. Missing publisher originals remain known gaps.

## Evidence from discovery

The following findings come from static code inspection at public revision
`30a34b54cace1e3476f099a409000ca436c50a66`. They identify consumers and purposes;
they do not prove archive preservation or successful test execution.

- `tests/test_retired_physical_fact_formats.py:17-104` consumes the historical
  French retired-facts store and bundle, checks baseline producer identity and
  exact digests, and verifies non-destructive rejection. These are generated
  historical artifacts. The attestation has a separate declaration role.
- `tests/test_french_artifact_boundaries.py:13-192` uses a different historical
  French archive for store and bundle boundary tests. Related consumers include
  `tests/test_packaging_carries_catalogues.py:466-480` and
  `tests/test_catalogue_evidence.py:849-858`. Do not conflate these artifacts with
  the retired-facts fixtures or assume every member has established lineage.
- `tests/test_ca_eccc_boundary_probe.py:34-137` compiles the retained derived ZIP
  through the production HYDAT compiler. It reads an attestation from the committed
  compact store, but reads observation values from the newly compiled store.
  Directory-level references therefore do not establish that every stored file is
  a mandatory test input. Related ZIP consumers are
  `tests/test_source_series_bulk.py` and `tests/store/test_bulk_public_recovery.py`.
- `tests/test_ca_eccc_no_days_evidence.py:19-91` inserts retained extracted HYDAT
  rows into an authored representative database, decodes them and compares cells
  with publisher CSV recordings. The row excerpt is distinct from a national
  original database. The same module also consumes publisher documents and an
  authored audit record; these roles must remain distinct.
- `tests/test_fr_hydroportail_variants.py:216-275` consumes a historical cache and
  export bundles to check old-format refusal and missing variant identity. The
  code establishes their historical generated role, but does not check a producer
  revision or digest attestation there.
- Four `tests/test_data/*_metadata.json` files have real content consumers:
  `ca_eccc_metadata.json` in `tests/test_ca_eccc_catalogue.py:159-188`,
  `jp_mlit_metadata.json` in `tests/test_jp_mlit_catalogue.py:259-265,640-646`,
  `cz_chmi_metadata.json` in `tests/test_cz_chmi_generate_catalogue.py:437-500`,
  and `za_dws_metadata.json` in `tests/test_za_dws_generate_catalogue.py:164-200`.
  Code supports source/native-subset roles, not a claim that each whole JSON file
  is an untouched publisher response.
- For `br_ana_metadata.json`, the inspected Python consumers establish only a
  file-existence check in
  `tests/test_catalogue_only_br_ana_jp_mlit_no_nve_th_thaiwater.py:153-161`.
  Its material role still requires classification. Limited content coverage does
  not exclude it from this repair's all-evidence inventory.

These are research anchors, not the full inventory. Read the functions at the pinned
revision if line numbers move. Discovery did not inspect retained payloads, recheck
the reported manifest comparisons, search every older release or run genuine-input
verification. Do not present those unperformed checks as evidence of success.

## Reuse the archive already available

Static inspection of private archive revision
`1040ea574a778eb112e48fda834f2b85690e9c09` found an existing path for this repair:

- `docs/intake.md` describes classification, sharing review and retention.
- `archive/catalogue.py` distinguishes derived inputs from publisher originals
  and defines exact collection selections.
- `archive/manifest.py` binds member sizes and digests, acquisition links and
  derivation information. Missing lineage must remain an explicit limitation.
- `archive/intake.py` packages unchanged bytes and checks extracted equivalence.
- `archive/publication.py` verifies uploaded assets and leaves acceptance
  unevaluated. Publication is not scientific verification.
- `archive/acquisition.py` checks selected assets and manifest-bound members
  before exposing input roots.

Revalidate against the explicitly reviewed revision used for implementation.
No new archive infrastructure is indicated by discovery. Use existing intake,
publication and the sole current inventory rather than adding a parallel downloader,
manifest authority or fallback directory. A supplemental retention collection is
appropriate when existing collections cannot supply the required identities; its
layout should follow the actual material, not speculative provider uniformity.

Use exact collection, release, asset and manifest identities. Do not select mutable
`latest` references or silently change consumer selections. Pinned identities detect
changed bytes; they do not make release storage undeletable or provide an independent
backup. Preserve original receipts and record new acceptance separately.

## Verification and completion

Follow `docs/maintenance/evidence.md` and the private archive's reviewed instructions.
Run only explicitly reviewed code with private evidence or credentials. Keep detailed
inventories, restricted paths, acquisition details, payloads and receipts private.
Prevent leaks through assertion output, errors, logs, caches, public PRs, artifacts
and distributions. Existing GitHub access is sufficient; add no developer-vetting
system. Archive access does not override source-sharing permissions.

Before claiming #457 repaired:

1. Complete the all-evidence accounting. Every candidate has a supported disposition;
   every retained evidence artifact has verified archive preservation, whether or not
   it has a current consumer. Non-evidence exclusions have recorded reasons.
2. Publish missing retained material through reviewed intake and register exact
   selections in the archive's existing inventory. Do not rebuild or reacquire it.
3. Retrieve the selected collections into a fresh location outside source checkouts.
   Verify archive integrity and exact original-to-retrieved byte equality. Packaging
   success or a local copy alone does not prove retrievability.
4. Establish that required historical regression inputs can be supplied from those
   retrieved bytes. Run the affected existing regressions and applicable full genuine
   checks through reviewed execution, without implementing #429's shared interface,
   changing assertions or introducing maintained fallback paths. If that verification
   cannot be completed independently, report the remaining blocker; do not count
   missing material, skipped tests or synthetic checks as genuine acceptance.
5. Record exact public/private code revisions, collection selections, commands,
   outcomes, limitations and unresolved gaps. Provide a privacy-safe completion
   summary and a precise private handoff for subsequent consumer binding and removal.

Do not retire sole originals or active source-tree copies merely because a release
exists. Require verified preservation and the applicable owner approval before any
retirement. Source-copy removal must not break consumers while #429 remains paused.
This vision does not authorize Git history rewriting, provider research, catalogue
redesign, execution of unreviewed preserved drafts or resumption of #429. Closing
#457 records the verified retention repair; the owner separately authorizes #429.
