# uv releases through GitHub

## Outcome and agreed scope

Use uv consistently for version preparation, building and uploading, and prepare
package version `0.1.0`. This is a focused maintenance change to Freddy's existing
publishing setup from [PR #454](https://github.com/RivRetrieve/RivRetrieve/pull/454),
not a release-process redesign. The upload workflow already uses `uv build` and
already publishes on GitHub release publication. Resetting the package version and
replacing the old version tool are separate from changing the upload command.

The owner narrowed this vision after clarifying the agreed changes with Freddy.
This revision supersedes the broader requirements in the versions published through
PRs #462 and #463. Implement only the scope below. Do not restore those earlier
requirements as incidental improvements or infer broader approval from the original
proposal in [#441](https://github.com/RivRetrieve/RivRetrieve/issues/441).

This remains a standalone vision, not implementation of the historical Effort #9 or
an Effort in the evidence Program. Material scope or release-policy changes need
separate owner agreement. Coordinate with the owner before implementation if Freddy
is working on the same changes; publication of this vision is not evidence that he
has confirmed the work is available to take over.

## Version preparation

- Reset the stale `0.1.49` development version to `0.1.0`.
- Use `uv version` to manage the version in `pyproject.toml`. Have
  `rivretrieve.__version__` read installed distribution metadata rather than maintain
  a second version literal. Preserve that public version attribute.
- Remove the obsolete `bump-my-version` development dependency and its configuration.
  Update the lockfile and keep installed metadata and runtime reporting consistent.
- Maintainers prepare and commit version changes before release. Do not add automatic
  version bumps, tag creation or release-note generation to the publishing workflow.
- Keep the agreed pre-1.0 convention: breaking changes increment the minor version;
  compatible improvements and fixes increment the patch version. Release notes in
  GitHub releases explain relevant changes and adaptation for breaking changes.
- Preserve the completed stale-tag cleanup. PR #446 published that cleanup's vision;
  issue #444 records deletion of the old tags without changing package metadata.
  Do not recreate those tags or rewrite history.

## Upload-tool change

Keep `.github/workflows/publish-pypi.yml`, the existing build job and artifact
handoff. Replace the PyPA publishing action with uv in both publishing jobs. Each
publishing job runs separately from the build job, so install uv in each job that
uses it.

Use `uv publish --trusted-publishing always` with short-lived GitHub OIDC credentials.
Preserve environment names `pypi` and `testpypi`, the project name `rivretrieve`, and
repository identity `RivRetrieve/RivRetrieve`. Do not introduce long-lived tokens or
token fallback. Keep production uploads directed to PyPI and sandbox uploads directed
to TestPyPI; explicitly preserve the sandbox destination when replacing the action's
`repository-url` configuration.

Preserve the current trigger and routing behavior:

- `release: types: [published]` remains unchanged, including its existing behavior
  for published GitHub prereleases. Do not introduce a new prerelease filter.
- Manual dispatch remains available with the existing `pypi` / `testpypi` target
  selector and current default. Do not restrict dispatch to recovery of an existing
  release tag or introduce new branch/tag eligibility rules.
- Keep both publishing jobs and their existing environment/permission isolation.
  uv installation, checkout and artifact-transfer Actions remain appropriate.

Freddy confirmed that trusted publishers and GitHub environments are set up for
both production PyPI and TestPyPI. The observed
[manual run](https://github.com/RivRetrieve/RivRetrieve/actions/runs/36709030481)
successfully published to TestPyPI and skipped production publishing. Treat production
configuration as maintainer-confirmed, not as an observed production upload. There
is no need to ask him the same setup question again. Report any discovered identity
mismatch to the owner instead of silently replacing his setup.

## Verification and completion

Test these changes without uploading packages or changing release behavior:

- Check that `pyproject.toml`, the lockfile, installed package metadata and
  `rivretrieve.__version__` agree on `0.1.0`. Verify uv version preparation and removal
  of obsolete bump tooling.
- Build wheel and source distribution with uv. Use existing relevant package/version
  tests and verify installed version reporting outside the source checkout. Choose
  focused regression coverage for the changed behavior; do not create a new release
  gate or general package-scanning system.
- Validate the workflow and its command/configuration wiring: both publishing jobs
  install uv, require trusted publishing, use the existing environments, and send
  uploads to the intended index. Check that triggers, target selection and job
  conditions retain their existing behavior.
- Run applicable formatting, lint and type checks for changed files. Follow the
  repository's verification rules and report unavailable required checks honestly.
  These are implementation checks, not authorization to add recurring test CI.
- Update relevant maintainer guidance to explain `uv version`, the version source
  and the upload-tool change. Keep guidance consistent with the actual unchanged
  release and manual-dispatch behavior.

A successful focused implementation does not certify the whole release process or
establish launch readiness. State what was checked and that no production or sandbox
upload was attempted.

## Explicit boundaries

Do not add release-time test gates, tag/version enforcement, new artifact-testing
pipeline stages, PR/merge/main test CI, or a recovery-policy redesign in this change.
Do not remove TestPyPI or manual dispatch. Do not alter documentation deployment.
The earlier vision's broader release-check and evidence-integration requirements
are no longer implementation requirements here.

Evidence Program #427, including #429 and #431, remains separate. This maintenance
change does not redesign archive access or depend on #429 providing a new release
check selection. Apply the repository's evidence rules if relevant changes arise;
do not weaken source verification or expose private inputs. The earlier
[integration comment on #431](https://github.com/RivRetrieve/RivRetrieve/issues/431#issuecomment-5915021390)
records a broader release plan that this vision has since narrowed. Do not treat its
old release-policy bullets as authorization to expand this implementation. #431's
own publication-boundary review remains its responsibility.

Actual launch is outside this work. Do not publish to PyPI or TestPyPI, create a
release or release tag, or change repository visibility to verify the implementation.
The repository remains private during this work. Opening it and making the first
release are separate owner actions for another day.
