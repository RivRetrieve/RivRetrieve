# Shared verification evidence for all providers

## Outcome

An authorized RivRetrieve maintainer can obtain the retained evidence for any
provider, check its integrity, and run the applicable verification from a fresh
checkout without access to another developer's machine. Public contributors can
run ordinary tests without private credentials or downloading all collections.

The code repository is expected to become public soon. Large verification
collections must stay outside its Git history and outside distributed Python
packages. Shared access does not authorize public publication of source material.

Related issue: [ThaiWater acceptance evidence #416](https://github.com/RivRetrieve/RivRetrieve/issues/416).
This is a standalone, all-provider redesign. ThaiWater is a verified starting
example, not the scope boundary. This vision does not declare the issue delivered.

## Why retain evidence

A saved publisher response lets a reviewer check the source facts behind a
catalogue claim or a parser result. A later request may return revised data and
cannot prove what the earlier acquisition contained. Retain original response
bytes and acquisition receipts together, with their actual request identities,
retrieval dates and fingerprints.

Retaining verification evidence does not require publishing a general observation
archive. It also does not require every test to download a country's historical
data. Keep the purpose and limits of each retained collection explicit.

## Settled storage and access direction

Use a separate, organization-owned **private GitHub evidence repository**, with
compressed collections attached to versioned releases. Do not commit the large
bundles as Git blobs or put them in Git LFS in the code repository. Making the
code repository public must not change access to the evidence repository.
The private repository is `RivRetrieve/verification-evidence`. It has been created,
and the implementing maintainer has write access. Collection naming remains an
implementation choice.

Maintainers use their own GitHub accounts. The owner confirmed that everyone in
the organization has access. Use the existing organization access arrangements;
creating separate reader and publisher teams is not required. Document how
maintainers obtain access and who administers it. Do not distribute a shared
human password.

A maintainer workflow must:

1. Select an exact collection version from the provider evidence index.
2. Download only the required assets using authenticated access, such as `gh`.
3. Check expected byte sizes and SHA-256 fingerprints before using the files.
4. Extract safely to a local evidence location outside the source checkout.
5. Run the provider's applicable verifier with explicit paths.
6. Record the code revision, collection identity, commands, outcomes and limitations
   without exposing private response content or credentials.

Pin exact releases and asset identities rather than a mutable `latest` download.
Use GitHub's immutable-release protection where available and verify its actual
settings. Collection updates receive new identities; they do not silently replace
accepted bytes. Preserve original acquisition-relative paths where existing
verifiers depend on them. A locator or fingerprint is not a credential, but review
whether its metadata is suitable for the public index.

GitHub documents a limit of less than 2 GiB per release asset and up to 1,000 assets
per release. Design archive boundaries around actual sizes without weakening
acquisition identity. Do not interpret hosting limits as a guarantee of permanent
availability. An unexpected hosting limitation is a blocker to resolve explicitly,
not permission to put large evidence into source Git or publish private bundles.

Use the private evidence repository as the sole shared storage location. The
owner explicitly chose not to maintain an independent backup. Loss of release
attachments therefore has no independent recovery guarantee; a Git clone or mirror
does not back them up. Demonstrate downloading and verifying the retained evidence
without relying on the original discovery machine. Preserve original local
evidence during migration; this work does not authorize deleting it.

## One process across all providers

The current registry has 14 providers: 11 live providers, Canada and Poland as
bulk-store providers, and South Africa as catalogue-only. Cover all 14 in the
inventory, documentation and migration decisions. Do not silently omit a provider
because it lacks a current live retrieval page.

Distinguish these kinds of material:

- Original acquisitions and receipts used to substantiate catalogue claims.
- Small genuine response recordings used in ordinary parser and retrieval tests.
- Publisher documentation and recorded source terms.
- Native catalogue build inputs, derived tables and their provenance.
- Bulk observation archives needed for particular compilation checks.
- Private correspondence or other restricted review material.

Give every provider an explicit account of retained evidence, its purpose,
location, access, integrity, verification commands and known gaps. Different
providers need different checks. A common index must not imply that a native-table
rebuild proves possession of every original response, or that one runtime example
certifies national product availability.

Keep small, reviewed source recordings that ordinary tests need in the code
repository where appropriate. Move large review collections and controlled material
to shared evidence storage. Existing fixture files vary greatly in size; do not
classify them solely by directory name. Preserve reproducible catalogue builds and
ordinary test behavior when changing paths or download boundaries. Runtime library
calls must not start discovering private evidence repositories or maintainer caches.

Do not manufacture missing originals from derived tables, change historical
acquisition dates, or treat newly requested data as the old response. Recover
existing material first. If originals cannot be recovered, document exactly which
claims remain supported and which full checks remain unavailable. Any replacement
evidence requires an explicit reviewed acquisition and updated bindings. Record a
blocked acceptance check as blocked; never weaken a check or silently mark it passed.
An inventory with documented gaps is not a certificate of complete source-body
coverage. Unresolved mandatory checks must remain visible in the delivery record.

## Verification and public-repository boundary

Public tests remain credential-free and do not require restricted collections.
Keep their genuine fixtures and assertions; do not replace source recordings with
synthetic data merely to avoid access work. They may validate the public evidence
index and retained public material, but cannot certify unavailable private bytes.

Full controlled-evidence verification runs in the private evidence repository
against an explicitly reviewed RivRetrieve commit. Its own restricted environment
provides evidence access. Do not execute unreviewed fork code with those credentials
or data. Public pull requests can receive a maintainer-run full verification when
needed; contributor access is granted separately where appropriate.

A successful full run must establish that its genuine inputs are present and pass
the complete verifier before relying on negative regressions. ThaiWater's existing
cross-station test expects a missing-file or value error; an empty evidence root
can therefore satisfy that test without verifying any real collection.

Preserve failure identity, source unknowns, and the distinction between null
measurements, absent rows and failed requests. Do not infer source judgement,
time zones, measurement producers or redistribution permission during migration.
Record exact evidence and verification identities in an acceptance record. Public
summaries may report approved results and fingerprints; private logs, caches and
artifacts must not leak into public workflows or releases.

## Documentation and agent instructions

Provide one maintainer guide, for example `docs/maintenance/evidence.md`, covering
access, version selection, download, fingerprint checks, extraction, verification,
new collection review, access administration and the lack of an independent backup. Explain why evidence
is retained and which checks a public contributor can run. Include a practical
end-to-end example and expected outcomes.

Provide one provider evidence index used by both people and tooling. Link to it
from relevant maintenance pages rather than copying collection details into many
files. Retain provider-specific explanations where they clarify what a verifier
actually establishes.

Add short instructions to `AGENTS.md`: where the guide and index are, when full
verification is required, how to handle unavailable evidence, and the prohibition
on exposing controlled material through the public repository or its artifacts.
Keep exact commands and frequently changing collection details in the guide/index.
Use current-behavior documentation and readable examples, following `docs/AGENTS.md`.

## Findings that the implementation must preserve

Discovery used revision `c54a78b2ce3811931252f0ef9594d0e383b47672`.
These measurements describe that revision and the inspected local material, not a
promise that every historical acquisition has been recovered.

### ThaiWater: recovered and verified

The original controlled directory exists at the historical handoff location:
`~/.local/share/rivretrieve/review-evidence/effort-225/th_thaiwater/baseline-capture-2026-09-13/`.
It contains all 825 required bodies and receipts. The archive
`complete_raw_evidence.zip` is 25,582,314 bytes with SHA-256
`46320ee0fa6b908c6009f223f59d6daa94f836bdfe3bbf82fee6d4354779c73f`.
The expanded unique body sizes in the ledger total 468,364,099 bytes.
There are 813 new September 13 acquisitions and 12 reused September 11 acquisitions.

The following complete verifier passed against the current ledger:

```sh
uv run python maintenance/catalogue/th_thaiwater/scripts/verify_governing_evidence.py \
  --ledger maintenance/catalogue/th_thaiwater/inventory/governing_station_product_evidence.csv \
  --native src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet \
  --evidence-root "$THAIWATER_REVIEW_EVIDENCE_ROOT"
```

Result: 825 stations, 1,650 pairs, 1,096 available and 554 unknown. With
`THAIWATER_REVIEW_EVIDENCE_ROOT` set to that genuine directory, this command passed
all eight tests with no skips:

```sh
uv run pytest tests/test_thaiwater_governing_evidence.py \
  tests/test_thaiwater_source_outcomes.py -q
```

Without the configured root, the same focused suite reported seven passes and one
skip. Discovery established recovery and integrity; it did not establish shared
access or complete this redesign. No new ThaiWater survey is needed for the
existing acceptance evidence.

### Wider inventory

At the historical controlled root
`~/.local/share/rivretrieve/review-evidence/effort-225/`, retained directory sizes
were 38,596,112 bytes for France, 153,152,544 for Bosnia and 530,575,858 for Thailand.
These totals include archives and expanded copies; they are not unique upload sizes.
France's inspected manifest sets and Bosnia's 820-entry file manifest passed digest
checks. Those checks must not be described as renewed complete provider acceptance.

The source repository's tracked files total approximately 240 MB at the discovery
revision, excluding history. A classified evidence/build-input inventory accounted
for approximately 233 MB, including about 116 MB of test-support material, 24.5 MB
of maintenance material and 26.1 MB of research material. This includes documentation,
metadata and derived outputs, not only measurement responses. External storage
prevents further large Git additions; moving HEAD files does not remove old Git blobs.

| Provider | Evidence and specific boundary |
| --- | --- |
| `ba_fhmzbih` | Complete controlled 180-pair baseline; four retained public cases are only examples. Full verification requires the original manifest and bodies. |
| `br_ana` | Retained national inventory captures and representative runtime recordings; some manual and dictionary originals were deliberately omitted. Preserve safe-derived versus original distinctions. |
| `ca_eccc` | Attested native catalogue and selected HYDAT evidence; small fixtures are not the complete national acquisition or national observation archive. |
| `ch_foen` | Metadata, runtime recordings and publisher documents; source cadence does not establish every downstream temporal-support fact. |
| `cz_chmi` | Attested native catalogue and runtime recordings; small metadata fixture is not the full national response. |
| `fr_hubeau` | Mixed historical governing acquisitions, public bundles and controlled complete bodies; full acceptance needs the private collection. |
| `fr_hydroportail` | Published inventory, probes, and shared historical France lineage; keep route and selector coverage limits distinct from Hub'Eau. |
| `jp_mlit` | Accepted native snapshot and representative HTML/DAT chains; later HTTP 403 prevents treating a current refetch as recovery of the original census. |
| `lt_lhmt` | Retained complete 97-station metadata response and bounded runtime recordings. |
| `no_nve` | Complete active/inactive station captures and runtime witnesses; live refresh credentials are separate from replaying saved evidence. |
| `pl_imgw` | Bulk source fixtures and reviewed geometry lineage; private forwarded correspondence has a redacted record, not established original-byte identity. |
| `th_thaiwater` | Genuine complete corpus recovered and verified as recorded above. |
| `usgs_nwis` | Modern and legacy source evidence and national metadata; retain route-era identities and historical witnesses. |
| `za_dws` | Registered catalogue-only provider; archived-PDF acquisition identities and historical runtime fixtures do not imply current live support. |

Discovery did not locate every original national response for Canada, Czechia,
Japan or South Africa in the inspected tracked material. Committed attested native
inputs still support reviewed offline rebuilds. Do not describe this bounded
inventory as a complete recovery audit or as evidence that catalogue data are wrong.

Useful current entry points are `src/rivretrieve/_internal/provider_manifest.py`,
`docs/architecture.md`, `docs/provider_ports/`, `tests/test_catalogue_origin_certification.py`,
and `maintenance/catalogue/{ba_fhmzbih,fr_hubeau,th_thaiwater}/README.md`.
The earlier handoff is in
`planning/visions/2026-09-13-evidenced-access-across-france-bosnia-and-thailand.md`,
introduced by commit `d3dffc76e7487b6e4b0b1c8504864eff3d4314f4`.
Inspect historical private scripts before use: some retain scratch paths or rewrite
bundles. Prefer current offline verifiers; never accidentally rerun acquisition.

## Permissions and upcoming public release

The earlier owner-approved decision in
[issue #225](https://github.com/RivRetrieve/RivRetrieve/issues/225#issuecomment-5655060163)
kept complete review responses private and excluded publishing a data archive.
It did not establish that all hydrological measurements are confidential. A blanket
ban on source measurement fixtures was explicitly rejected in the historical work.

ThaiWater API redistribution permission remains unestablished. Its website copyright
and privacy policies are not an API data licence. A separate HII telemetry dataset
lists Creative Commons Attribution Non-Commercial; applicability to these API
responses and contributing agencies is unconfirmed. Other providers have different
source terms. Private storage is not a substitute for checking authority to share
particular correspondence, credentials or restricted source material with a team.
Do not reinterpret source terms or grant new public publication authority.

Before switching repository visibility, perform a separate publication-readiness
review of reachable history, archives, recordings, URLs, headers, logs, correspondence
and source terms. The discovery review found no confirmed credential leak, but was
bounded and provides no security or legal clearance. A documented publisher-shared
read-only provisioning artifact in the Swiss provider requires an explicit review,
not an automatic assertion that it is a leaked personal credential. Historical local
paths require review without assuming every path is secret or a runtime dependency.

This vision requires the evidence migration to respect that publication boundary
and expose review dependencies. It does not authorize changing repository visibility,
rewriting Git history, rotating publisher credentials, or automatically publishing
controlled source material. Any required history remediation needs its own explicit
authorization and preservation plan.

## Observable completion

- All 14 providers appear in the reviewed evidence index, including catalogue-only
  and bulk-store providers, with supported claims and missing originals stated plainly.
- Applicable retained collections are available through project-controlled private
  releases. Original bytes, receipts and provenance survive migration unchanged.
- An authorized maintainer or independent clean environment downloads, verifies and
  uses the evidence without the discovery machine or its scratch directories.
- Public-clone tests work without private access. Full controlled checks use genuine
  collections and retain their existing acceptance strength and failure behavior.
- Bosnia, France and Thailand full verifiers are exercised against shared retained
  evidence. ThaiWater's complete verifier and cross-station regression pass together,
  without a skip, and the acceptance record includes the exact code and collection IDs.
- Other providers run their applicable existing checks, with precise limits. A
  missing required original blocks its corresponding claim; a recorded limitation
  cannot be presented as a successful full-body check.
- Existing organization access and public/private job separation are verified.
  Independent backup and restore are outside scope by owner decision.
  Private content does not enter public logs,
  artifacts, caches, release assets or distributed packages.
- The maintainer guide, provider index and concise `AGENTS.md` instructions agree.
  Related maintenance pages no longer rely on an unexplained owner-machine path.

Do not expand this work into a new retrieval API, a universal legal classification
system, a blanket source survey, an archive of all retrieved observations, or
unrelated provider behavior changes. Resolve discovered evidence gaps explicitly
without disguising changed source facts as a storage migration.

## Storage references

- [GitHub releases and asset limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
- [Immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)
- [Backing up a repository, including releases](https://docs.github.com/en/repositories/archiving-a-github-repository/backing-up-a-repository)
- [GitHub Actions token scope](https://docs.github.com/en/actions/concepts/security/github_token)

Implementation must confirm current organization permissions and service settings.
The owner has since created the private evidence repository and confirmed
organization access. Discovery created no release or verification job. No new
teams or independent backup are required.
