# Mirror-compatible verification and required lockfile checks

Take ownership of the coordinated verification changes in
[RivRetrieve PR #910](https://github.com/RivRetrieve/RivRetrieve/pull/910) and
[verification-evidence PR #106](https://github.com/RivRetrieve/verification-evidence/pull/106).
Finish their review, validation and enforcement details so an authorized maintainer
can run verification independently from a workstation configured with a package
mirror, without depending on another maintainer to execute each provider check.

The associated investigation is
[verification-evidence issue #105](https://github.com/RivRetrieve/verification-evidence/issues/105).
Successful delivery of this work is intended to complete that issue. Publishing
this vision does not complete it. Keep detailed environment diagnostics and
controlled evidence in the private repository.

## Agreed approach

Keep the proposed split: verification uses the reviewed lockfiles with
`uv run --frozen`, while CI uses `uv lock --check` to detect dependency-declaration
and lockfile drift. Preserve public PyPI lockfile sources. Do not replace this
with locally rewritten mirror lockfiles or relax source-evidence checks.

The reported failure is a system-level package-index configuration conflicting
with `--locked`. The issue reports successful installation with `--frozen` using
the verifier's child environment. Confirm that result rather than treating the
report as independent validation. Frozen installation still needs access to the
pinned package artifacts; this work does not promise support for air-gapped
machines or every corporate network policy.

`--frozen` omits the lockfile freshness check. It does not replace the evidence
coordinator, change test selection, or authorize unreviewed dependency changes.
Keep exact reviewed public and private revisions, clean checkouts, external
restricted outputs, exact evidence identities, full-positive prerequisites and
failure/skip handling intact. Follow each repository's current verification and
testing guidance. No private source inputs or credentials belong in public CI.

## Finish the coordinated changes

Review both current PR heads, their surrounding code and documentation, and the
issue's latest discussion before editing. Build on these PRs rather than creating
a competing implementation. Confirm the four child command sites and relevant
outer invocation examples consistently use the intended policy. Fix any defects
found and keep contributor instructions accurate.

Close the gap between moving a check to CI and actually enforcing it. Cover both
repositories and the dependency files used by the exact revisions selected for
verification, including provider development branches. A successful check on an
unrelated or older `main` revision is not enough. Choose a proportionate way to
establish that coverage; this vision does not prescribe a new certification
service or require every local verification to query GitHub.

Prepare required-check and branch-protection changes alongside the workflows.
The proposed private workflow is path-filtered: making its check required without
addressing skipped workflows can strand unrelated PRs waiting for a check that
never runs. The public proposal runs on all PRs and pushes to `main` and `port/**`.
Inspect actual rules and workflow behavior rather than assuming a workflow file
makes checks mandatory. Account for both repositories when choosing rollout and
merge order.

Repository-settings changes and merging either implementation PR require explicit
user approval. Prepare the changes and report the remaining actions if approval
or administrative access is unavailable. Publication of this vision authorizes
neither action. Do not merge one half on the assumption that the other enforcement
half is already active.

## Evidence of completion

- Demonstrate that the reported mirror/index mismatch no longer blocks environment
  setup, while the reviewed lockfiles remain unchanged. Use a source-independent
  reproduction where possible; distinguish it from a run on the affected machine.
- Demonstrate that stale dependency declarations fail the replacement CI check.
  Check the supported public-source policy rather than assuming a job name proves it.
- Verify required-check behavior for dependency changes and unrelated PRs, and show
  how the dependency files used by selected development revisions are covered.
- Run affected source-independent orchestration and documentation checks. Run any
  mandatory genuine-input checks required by the changed boundaries under the
  existing private evidence rules. Report unavailable mandatory evidence as blocked;
  synthetic tooling tests are not genuine-source acceptance.
- Record what was tested directly, what was reported by the contributor, remaining
  limitations, approved settings changes, and the coordinated merge state.

At authoring, both PRs were open and their new lockfile CI jobs had passed. The
prior assessment inspected the diffs and issue report but did not independently
rerun their tests or a genuine-evidence verification. Refresh these facts during
implementation. Completion requires the approved changes to be delivered and
verified, not merely a green workflow on the draft PRs.
