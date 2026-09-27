# Poland multi-artifact source vintage repair

Related bug: https://github.com/RivRetrieve/RivRetrieve/issues/368

## Outcome

Make `rr.download("pl_imgw")` compile IMGW-PIB's valid, ordered multi-artifact
hydrology history into one certified local store. The store's source vintage is
the latest publisher-labelled coverage end across its artifacts, not the first
artifact's date, the build date, or the latest observation present in the files.
Keep every artifact's ordered URL and exact checksum in store provenance.

This is a standalone bug-repair vision, not a Program Effort.

## Confirmed investigation

Investigation reproduced the reported exception offline on production revision
`6b3cb7a8679527a165105e1648fa7c8da2893eff`. Production `src/` was unchanged on
GitHub `main` at `21a93efb16ac57b9ebae99c64fa1b14d0b339748`.

The failure occurs before archive reading:

- `BulkCompileRequest.source_vintage` in
  `src/rivretrieve/_internal/providers/registration.py` returns the maximum
  supplied artifact vintage. Its singular path and URL refer to the first artifact.
- `_compile` in `src/rivretrieve/_internal/providers/pl_imgw/declaration.py`
  passes those three values to `ImgwCompileRequest`.
- `ImgwCompileRequest.__post_init__` in `pl_imgw/bulk.py` requires the singular
  path, URL, and vintage together to equal the first plural artifact. A valid
  multi-artifact history has different first and maximum vintages, so it raises
  `ValueError: singular IMGW artifact must equal the first plural artifact`.
- `compile_imgw` already computes the maximum artifact vintage for the store.
  The shared maximum convention is not the defect and must not be changed to
  match the first artifact.

The adapter also reconstructs each `DownloadedImgw` from path and URL alone,
discarding the supplied `DownloadedBulkArtifact.source_vintage`. Since
`DownloadedImgw.source_vintage` is derived from its URL label, comparing that
property with the same label-derived date does not validate the discarded input.
A wrong supplied per-artifact date must be rejected, not silently corrected.
This includes a wrong nonfirst date below the true maximum, which an aggregate
comparison alone cannot detect.

The existing multi-artifact tests construct `ImgwCompileRequest` directly with
the first artifact's date. The public recovery test uses only one archive.
Consequently the following existing suites passed (36 tests) despite the defect:

```text
uv run pytest tests/store/test_pl_imgw_multi_artifact.py tests/store/test_bulk_declaration.py tests/store/test_bulk_public_recovery.py -q
```

A minimal offline reproduction builds a `BulkCompileRequest` from the official
1951 monthly URLs for hydrological months 11 and 12, with matching basenames and
label-derived dates, then calls the real Poland declaration's compile operation.
Those dates are `1951-09-30` and `1951-10-31`. No files or network are needed to
reach the failing request validation. The issue contains the complete script.

Existing live evidence is recorded on issue #368 and locally under
`.worktrees/poland-provider-evidence-2026-09-24/`. It reports the same exception
after the publisher downloads. Preserve this evidence; it is not a dependency
for reproducible offline tests.

## Repair boundaries

Separate first-artifact identity from aggregate store vintage without weakening
source validation. Choose the internal request representation from repository
conventions; this vision does not prescribe a particular dataclass change.
Preserve supported single-artifact behavior and the public API.

Keep rejection of conflicting singular/plural identities where both remain,
duplicate paths or URLs, mismatching path/URL basenames, nonofficial URL
templates, wrong publication regimes, disordered or overlapping periods, and
internal period gaps. Validate supplied per-artifact vintages against the
publisher-labelled coverage end. If an aggregate provider-request vintage
remains an explicit input, reject one inconsistent with the artifacts.

No store-format change is needed: `PublisherArtifact` holds URL and SHA256,
while the manifest stores aggregate vintage separately. Do not add per-artifact
date fields to the store format merely to repair input validation.

Preserve existing certification, atomic publication, recovery, and cleanup
semantics. Pre-publication failure must retain the downloaded inputs and any
previous valid store. Do not weaken fatal contract checks, hide failures through
issue policy, or alter the established post-commit cleanup failure behavior.

Do not change catalogue content, hydrological interpretation, source values,
null semantics, time zones, or publication planning. Do not expand this repair
into a shared bulk-system redesign or automatic retry/resume feature.

**PR #291 is explicitly out of scope.** Do not edit, merge, resume, or otherwise
mutate that PR, its branch, its worktree, its documentation files, or its review
state. Reporting the bug repair is not authorization to act on PR #291.

## Evidence required for acceptance

1. Compile at least two tiny, valid, contiguous archives with unequal vintages
   through `BulkCompileRequest` and the real Poland declaration, not only the
   provider compiler directly. Verify the persisted and reloaded maximum
   coverage-end vintage, ordered URLs, exact checksums calculated before
   compilation, and the union of observations for all three native products.
   Confirm successful input cleanup.
2. Exercise public `rr.download("pl_imgw")` offline using the real declaration
   and compiler. Substitute source transfer and bound the history fixture as
   needed, but do not mock compilation. Verify the returned store and
   `rr.cache_status` report the correct vintage.
3. Cover the monthly-to-annual transition (`codz_2022_12.zip` followed by
   `codz_2023.zip`) and retain single-artifact coverage. Keep the established
   hydrological-period meaning of archive labels.
4. Reject wrong supplied dates for first and nonfirst artifacts, including a
   wrong date that leaves the aggregate maximum unchanged. Retain the identity,
   URL, regime, continuity, and uniqueness negatives, with explicit disorder
   and overlap coverage. Verify invalid compilation leaves inputs and any
   previous valid store intact.
5. Run relevant provider, shared bulk, store-provenance, and recovery tests,
   plus repository-standard lint and type checks. Use `uv` for project execution.
   Prefer library-specific assertions for frames and datasets.

The investigation proves the immediate blocker, not successful compilation of
the complete live history after repair. Offline fixtures provide deterministic
regression evidence; do not describe them as a successful full-history live run.
Any later live run must use an isolated destination and leave PR #291 untouched.
Unexpected subsequent source failures must be reported rather than silently
broadening scope or claiming end-to-end success.

The implementation handoff should identify its repair PR or commit and state
which offline and live checks actually ran. Work on PR #291 requires separate
user authorization.
