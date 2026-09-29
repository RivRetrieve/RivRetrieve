# Remediate the existing dependency vulnerabilities

Related issue: https://github.com/RivRetrieve/RivRetrieve/issues/358

## Outcome and agreed scope

Remediate the 14 existing Dependabot alerts in RivRetrieve's dependency lockfile,
preserve application behaviour, and close issue #358 after verifying completion.
This is narrow dependency maintenance in a currently private repository.

The maintainer narrowed the original issue during discovery. This vision supersedes
its requests for automatic security-update PR configuration and future-update
instructions. Do not add or change CI workflows, Dependabot configuration, GitHub
security settings, or automatic merging. The maintainer will respond to future
vulnerability notifications and run checks manually. Do not publish a PyPI release;
publication is planned separately for the future. Do not expand this work into a
security overhaul, provider redesign, or unrelated dependency refresh.

## Evidence to refresh before implementation

Discovery confirmed 14 open alerts, all concerning `uv.lock`:

| Dependency | Alert numbers | Locked version | Minimum patched version covering the listed alerts |
| --- | --- | --- | --- |
| `pypdf` | 5, 7–16 | 6.13.1 | 6.16.1 |
| `anyio` | 17–18 | 4.12.1 | 4.14.2 |
| `pydantic-settings` | 6 | 2.13.0 | 2.14.2 |

Alert numbers are security alert identifiers, not issue numbers. Reload the
[alerts](https://github.com/RivRetrieve/RivRetrieve/security/dependabot) and their
advisories before choosing versions. Record advisory links, affected and patched
ranges, dependency paths, and exposure for each of the original alerts. These
alerts establish known dependency flaws, not evidence of exploitation.

`pypdf` is a direct runtime dependency with a declared minimum of `>=6.13.1` in
`pyproject.toml`. PDF extraction is used in
`src/rivretrieve/_internal/acquisition_provenance.py` and
`src/rivretrieve/_internal/providers/za_dws/generate_catalogue.py`.
The inspected development graph contains `bump-my-version → httpx → anyio` and
`bump-my-version → pydantic-settings`; confirm current paths and actual use of the
affected functionality. Development-tool exposure still matters, but should not
be described as runtime exposure without evidence.

## Expected changes

Use the repository's `uv` workflow to update the affected locked dependencies and
only other dependencies required for those updates. Raise the declared `pypdf`
minimum to cover its listed advisories, so the eventual published package carries
the corrected requirement. Do not add development-only transitive dependencies
to the runtime requirements solely to pin them.

A dependency-only change is expected. Change application code only if investigation
or tests demonstrate a compatibility need caused by the patched versions. Preserve
existing behaviour and source fidelity. Bring a necessary breaking change back to
the maintainer before proceeding. Do not claim repository changes update existing
installations; developers must sync their environments to receive the patched
versions.

## Manual verification

Run the full test suite before the updates to identify existing failures, then run
it again with the patched dependencies. Use `uv run pytest`, along with repository
lint and type checks (`uv run ruff check` and `uv run ty check src`). Identify any
relevant PDF-processing and release-tooling behaviour not exercised by the suite
and check it directly without publishing, tagging, or releasing anything. Review
the final dependency diff for unrelated churn.

Follow `docs/maintenance/evidence.md` and the provider evidence index for applicable
source checks. Do not change source claims or evidence collections as part of this
maintenance. Where mandatory checks require unavailable credentials or original
material, report the checks as blocked. Do not weaken tests, substitute derived
inputs for originals, or claim an incomplete run passed. Keep controlled material
and credentials out of repository changes, logs, and artifacts.

Report commands, results, any baseline failures, and any blocked checks in the
implementation PR or completion record. No new CI pipeline is part of this work.

## Completion and issue closure

Completion requires the targeted updates and applicable declared requirements to
be merged into `main`, relevant checks to pass, and every original alert to have
advisory and remediation evidence. After merge and GitHub dependency scanning,
verify GitHub reports each of the 14 alerts as fixed. Do not infer this from a
successful update command or dismiss alerts to clear the counter.

If a safe fix is unavailable, required checks remain blocked, or scanning has not
confirmed remediation, report the remaining risk or verification gap and leave the
issue open. Newly discovered unrelated alerts should be reported separately rather
than silently broadening this effort.

Once completion is verified, post concise remediation and validation evidence on
issue #358 and close it. This closure is explicitly authorized as part of implementing
this standalone vision. Publishing this document alone must leave the issue open.
There is no Program or Effort workflow attached to this issue.
