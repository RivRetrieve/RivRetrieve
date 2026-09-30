# uv releases through GitHub

## Outcome and authority

Prepare a reliable PyPI release process with clean versioning and uv throughout.
Publishing a normal GitHub release is the maintainer's deliberate publication
instruction. Checks, builds and package tests must succeed before its distributions
reach PyPI.

This is a standalone vision arising from review of [PR #454](https://github.com/RivRetrieve/RivRetrieve/pull/454)
and the release proposal in [#441](https://github.com/RivRetrieve/RivRetrieve/issues/441).
It is not an implementation handoff for the broader historical Effort #9 or an
Effort in the evidence Program. The owner approved the design below. An implementing
agent may choose ordinary implementation details, but must bring material release
policy changes or redesign proposals back to the owner rather than decide alone.
There is no arbitrary size or time limit that requires retaining an inadequate design.

Actual launch is outside this work. Do not publish packages, create a release or
release tag, or change repository visibility to verify the implementation. The code
repository remains private during this work; this is a temporary development state,
not a permanent restriction on the future public project. Opening the repository
and making the first release are separate actions for another day.

## Version preparation

- Start at `0.1.0`, replacing the stale `0.1.49` development version.
- Use `uv version` for version preparation. Keep `pyproject.toml` as the version
  source and have `rivretrieve.__version__` read installed distribution metadata
  rather than maintaining another version literal.
- Remove the obsolete `bump-my-version` dependency and configuration. Keep package
  metadata, runtime version reporting and the lockfile consistent.
- Maintainers commit version and lockfile changes before preparing the GitHub
  release. The publishing workflow does not bump versions, create tags or generate
  release notes. Release notes live in GitHub releases and explain relevant changes.
- Before 1.0, breaking changes increment the minor version, for example `0.1.2` to
  `0.2.0`. Compatible improvements and fixes increment the patch version. Notes for
  breaking changes explain how users should adapt.
- Preserve the completed stale-tag cleanup. PR #446 published that cleanup's vision;
  issue #444 records deletion of the old tags without changing package metadata.
  Discovery found zero remote tags. Do not recreate those tags or rewrite history.

## Publication contract

Keep `.github/workflows/publish-pypi.yml` and its production environment named
`pypi`, preserving the identities used by Freddy's trusted-publisher setup.

Publishing a normal GitHub release triggers automatic package publication. Also
provide a manual recovery route for an existing published, normal GitHub release.
Recovery must require its explicit release tag and verify that the corresponding
release exists and is neither a draft nor a prerelease. It is not an alternative
route for publishing an arbitrary branch, an unreleased tag or a different source
commit. Both routes use the same required checks, artifact tests and publishing
authorization. Drafts and GitHub prereleases must not publish.

Remove the TestPyPI publication route. This does not require deleting Freddy's
TestPyPI account, project or settings.

Manual recovery is useful when publication fails and the workflow itself needs a
repair. Allow the repaired workflow to operate on the existing release's exact
tagged source; do not make recovery depend on executing only the old workflow from
that tag. Keep the workflow revision and the package source revision distinct and
explicit. Recovery must not bypass checks or silently substitute a newer package
source commit.

A transient failure can normally be retried by rerunning the existing release run
without increasing the version. Manual recovery does not permit replacing files
already uploaded to PyPI. Handle partial publication without overwriting existing
files or silently treating conflicting artifacts as equivalent. If correcting the
package requires replacing published files, prepare a new version through the
normal release process. Document these recovery limits.

Build the exact release-tagged commit, not the moving tip of `main`. Require a tag
such as `v0.1.0` to match distribution version `0.1.0`. Reject mismatches before
upload. Do not silently change a version to make a mismatched release pass.

Use uv for environment setup, version management, building and uploading. Publish
with `uv publish --trusted-publishing always`, using short-lived GitHub OIDC
credentials. Do not introduce long-lived PyPI tokens or token fallback. GitHub
Actions for checkout, uv installation and artifact transfer remain appropriate;
using uv does not mean replacing those platform operations.

## Checks and artifacts

Automated checks belong to the release workflow, including its manual recovery
route. Do not add test CI for pull
requests, merges or pushes to `main`, and do not add a merge-approval requirement.
Maintainers are responsible for testing development changes.

The release sequence must:

1. Install the locked development environment with uv.
2. Run formatting checks, lint, `ty check src`, and the source-independent test
   selection supplied by the completed evidence-test design described below.
3. Build the wheel and source distribution with `uv build`.
4. Test the actual release artifacts before upload. Cover clean installation,
   version reporting, packaged catalogue access, and building/installing from the
   source distribution. Reuse the existing packaging assertions where applicable.
5. Transfer the same tested wheel and source distribution to a separate publishing
   job. Only that job receives the production publishing authorization. It uploads
   the tested artifacts without rebuilding them.

Any required check failure stops upload. Existing packaging tests already cover
catalogue inclusion, excluded build inputs and isolated installed imports. Reuse
those safeguards; a new general-purpose sensitive-material scanner is not required.

At discovery, `tests/_distribution.py` builds its own wheel and source-derived wheel
and shares dependency directories from the test environment. Its verifiers use
fresh processes and working directories. Those checks are useful but do not alone
prove that the final upload artifacts install with their declared dependencies.
Adapt or supplement the existing tests to cover the actual release files. Do not
substitute a successful test of a separately rebuilt wheel for testing the uploaded
wheel. Ensure fresh CI can obtain the build backend before existing offline builds;
do not rely on a developer's populated uv cache.

## Integration with the evidence Program

The owner expects [Program #427](https://github.com/RivRetrieve/RivRetrieve/issues/427)
to complete before the first release. Design against its completed contract, not
today's fixture layout or silent skips. In particular,
[#429](https://github.com/RivRetrieve/RivRetrieve/issues/429) separates
source-independent logic checks, archive-backed recording regressions, full source
verification and live observations. Archive-backed checks use explicitly selected,
integrity-checked inputs. Missing mandatory evidence must fail the requested check.

Maintainers run applicable private evidence checks against reviewed code before
publishing a GitHub release. Publication is their confirmation that the required
verification has been completed. The release workflow runs source-independent and
artifact checks without private archive credentials or bodies. A green release job
must not be described as proof that it reran the private evidence checks. Do not add
a new approval system or automated private-evidence execution to this pipeline.

Use #429's final test interface to select release checks. Do not freeze an
unqualified `uv run pytest` command or filter tests by guessed filename patterns
based on the pre-refactor tree. If the final interface is not available when this
vision is implemented, coordinate with that work and report the integration as
blocked rather than inventing a parallel partition or weakening evidence checks.
This vision consumes the evidence design; it does not redesign that system.

The requested [integration comment on #431](https://github.com/RivRetrieve/RivRetrieve/issues/431#issuecomment-5915021390)
asks that Effort to check the completed archive interface, maintainer instructions,
release checks and actual distributions together. Its broader publication-boundary
review remains there. That comment predates the owner's agreement to manual recovery;
its prohibition on manual publishing is superseded by the restricted recovery route
in this vision. This release work neither duplicates that review nor changes
Program membership or delivery state.

## Trusted-publisher evidence

Freddy confirmed in the owner's Slack exchange that trusted publishing is configured
on both production PyPI and TestPyPI, and that the GitHub environments exist. The
observed [manual workflow run](https://github.com/RivRetrieve/RivRetrieve/actions/runs/36709030481)
successfully published to TestPyPI; its production publishing job was skipped.
Treat production configuration as maintainer-confirmed, not as an independently
observed successful production upload. There is no outstanding requirement to ask
Freddy the same setup question again.

Keep project `rivretrieve`, GitHub repository `RivRetrieve/RivRetrieve`, workflow
`publish-pypi.yml` and environment `pypi` consistent with that setup. Switching the
upload command to uv should not require changing these identities. If implementation
finds contrary evidence or needs a material configuration change, report it to the
owner and coordinate with Freddy. Do not silently replace his setup.

## Evidence of completion

- Version metadata and runtime reporting agree on `0.1.0`; obsolete bump tooling is
  removed and uv version preparation is documented accurately.
- Workflow tests or equivalent safe verification demonstrate automatic publication
  from normal releases and manual recovery restricted to an existing published,
  normal release tag. Reject arbitrary branches, unreleased tags, drafts,
  prereleases and tag/version mismatches. Both routes enforce the same checks and
  stop on failure before publishing authorization is used.
- Verify that recovery can use a repaired workflow while building only the selected
  release's tagged source. Cover retry and partial-upload behavior without replacing
  already published files or accepting conflicting artifacts as equivalent.
- Formatting, lint, source type checks and the final source-independent selection
  pass against the implementation. Required unavailable checks remain explicit
  blockers, not a passing or skipped acceptance result.
- The exact wheel and source distribution intended for upload pass the artifact
  checks, including installation with declared dependencies outside the source tree.
- Maintainer instructions explain version preparation, release notes, private
  evidence responsibilities, the automated release sequence, manual recovery and
  their limits.
- The #429 integration is verified against its delivered interface. Coordinate the
  final cross-check with #431 without claiming either Effort delivered by this work.
- Review the workflow's authorization and artifact isolation without uploading to
  PyPI or TestPyPI. State clearly that no production upload was attempted and that
  production trusted-publisher configuration is supported by Freddy's confirmation.

Do not trigger publication as an implementation acceptance test. Keep changes to the
existing documentation deployment workflow outside this scope unless the owner
explicitly approves a necessary interaction change.
