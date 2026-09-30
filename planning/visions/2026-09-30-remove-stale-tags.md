# Remove stale tags

Related issue: https://github.com/RivRetrieve/RivRetrieve/issues/444

## Outcome

Remove the obsolete Git tags left by the old agent workflow from
`RivRetrieve/RivRetrieve` on GitHub and from the local clone used during discovery
(`/Users/nicolaslazaro/Desktop/work/RivRetrieve`). The owner confirmed that all
observed tags are stale and irrelevant, including the local retention tag.

## Agreed scope

Discovery found 32 tags on `origin`, all also present locally:
`v0.1.2` through `v0.1.25` and `v0.1.49` through `v0.1.56`, inclusive.
The clone also has one local-only tag:
`pce-retained/2026-08-19-a-fixture-is-a-recording/assembly-v2-resolution`.
Delete all 32 remote tags and all 33 local tags. This explicitly includes the
retention tag; no replacement tags or bookmarks are needed.

Leave commit history, branches, package version numbers, published packages,
and future release policy unchanged. This is a one-time cleanup, not a redesign
of versioning or release automation. Do not extend cleanup to other clones or
repositories.

## Repository facts and safeguards

No GitHub releases were present during discovery. Package versions are explicit,
not derived from Git tags. `pyproject.toml` configures version-bump tooling with
`tag = false`. No source changes are needed for the agreed outcome.

Refresh the local and remote tag inventory before deletion. If new tags or
changed targets appear, distinguish them from the agreed stale inventory rather
than deleting unrelated concurrent work. Deleting these tags removes their use
as checkout or installation references; this consequence was accepted during
discovery. Do not rewrite commits or delete published package artifacts.

Publishing this vision does not itself execute the cleanup. A later
implementation invocation authorizes the tag deletions specified here.

## Completion evidence

Verify that `git tag --list` in the discovery clone and
`git ls-remote --tags origin` both return no tags after cleanup. Report any
remaining tags or failed deletions rather than claiming completion. If concurrent
new tags prevent an empty inventory, report that scope conflict for a decision.
Record the before-and-after inventories and confirm that issue #444's cleanup
was performed without changes to package versions or commit history.
