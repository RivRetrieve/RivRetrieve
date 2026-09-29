# Archive inventory gzip reader

This directory delivers a one-line repair for the privately retained local
`inventory_material.py` tool. The patch opens gzip decoders with `mode="rb"`.
A writable in-memory `SpooledTemporaryFile` otherwise causes Python 3.13.8 to
infer write mode, change the temporary bytes, and fail to inspect the payload.

The full tool, its input specification, and inventory outputs remain private.
This patch does not introduce a library API or certify an inventory. Related bug:
[#435](https://github.com/RivRetrieve/RivRetrieve/issues/435).

## Apply the repair privately

1. Preserve the original script and all four provisional output/specification
   files in a separate private directory. Confirm their sizes and hashes.
2. Copy the script into a new private output directory outside the checkout and
   outside retained inputs. Never import or run it during patch application:
   its module startup truncates its inventory output.
3. Confirm the original script SHA-256 matches the identity below. Apply the
   patch only to the new copy. From the checkout, with `CANDIDATE_SCRIPT` set
   to that copy:

   ```sh
   patch --dry-run "$CANDIDATE_SCRIPT" maintenance/archive_inventory/gzip-read-mode.patch
   patch "$CANDIDATE_SCRIPT" maintenance/archive_inventory/gzip-read-mode.patch
   ```

4. Confirm the candidate SHA-256 matches the identity below. Run the synthetic
   checks, then obtain independent code review before supplying genuine inputs.
   A full inventory needs separate review of failures, limits, newly discovered
   byte identities, and physical-input preservation. Exit status alone is not
   acceptance.

| Script | SHA-256 |
| --- | --- |
| Preserved original | `9c53681e2e431667451c74093bda2eb51deb43275f5d05e622d33510824bba90` |
| Repaired candidate | `67b298970d662ea83643136d447d4a3058e5faaa228c6cca65ebfd0e13c10fe8` |

## Synthetic regression checks

Set these variables privately. Do not commit their values or logs containing
private paths:

- `INVENTORY_ORIGINAL_SCRIPT`: the preserved original script.
- `INVENTORY_CANDIDATE_SCRIPT`: the repaired copy.
- `INVENTORY_SYNTHETIC_ROOT`: an empty writable scratch directory, separate from
  retained source material and inventory outputs.

Run from the project checkout with its environment:

```sh
uv run python maintenance/archive_inventory/test_gzip_reader.py
```

The suite loads only imports and function definitions from the supplied scripts.
It does not execute module-level output setup or read the source specification.
Only run it on reviewed scripts. All inspected archive bytes are synthetic.

The six tests include 14 cases: the old in-memory failure, repaired reads for
both spool states, recursive TAR and ZIP members for both states, a ZIP/TAR/gzip
parent chain, and malformed direct and nested members. They check payload bytes,
size, SHA-256, parent links, absence of warnings for valid data, and unchanged
input streams after repaired reads. Malformed data must remain a reported
inspection failure. The tests retain the tool's existing locator convention.
The old-behavior test targets the observed Python 3.13.8 runtime and intentionally
fails if that regression can no longer be reproduced.

Initial synthetic verification on Python 3.13.8 passed all six tests in 0.019 s.
This result does not accept a genuine inventory, source classifications, or a
collection. The owning maintainer retains the private script and verification
records. Merging this patch does not authorize archive consolidation.

## Controlled inventory verification

On 2026-09-29, the reviewed candidate was applied privately and the full inventory
was rerun against the unchanged original specification. The project-native
command was `uv run python "$INVENTORY_RERUN_VERIFIER"`; the private verifier
executed the exact candidate and retained detailed logs outside the checkout.
The reviewed verifier SHA-256 was
`b2c0c9d913e0f9c303af6c42bc66d8141c8751663ad3bb1df8ba899d4e99bded`.

The command exited 0 in 9.517 s on Python 3.13.8. Verification found:

- All 6,060 physical regular-file inputs matched the rejected inventory
  and their before/after byte sizes and SHA-256 values were unchanged.
- All 81,411 previous inventory rows were identical. Exactly two decompressed
  entries were added, with independently verified bytes, sizes, hashes and parents.
- The new inventory contained 81,413 rows and no inspection warnings or limits.
- The five original diagnostic files remained unchanged.

An initial preflight stopped before inventory execution because the verification
wrapper rejected a retained FIFO. Review confirmed the original reader excludes
that non-file. A separately reviewed wrapper correction records its before/after
membership and exclusion without opening it. No regular input was excluded and
no reader or specification change was added. Both attempts' records remain private.
These checks establish physical membership and byte preservation, not unchanged
filesystem metadata.

The inventory result does not certify source-role proposals, provider claims or a
new collection. Archive consolidation remains paused pending separate owner
authorization.
