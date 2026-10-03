# Historical archive inventory repair

This directory retains the patch and verification record for the private,
one-off `inventory_material.py` repair in [#435](https://github.com/RivRetrieve/RivRetrieve/issues/435).
The patch opened gzip decoders with `mode="rb"`. Python 3.13.8 otherwise inferred
write mode for a writable in-memory temporary file and changed its bytes.

The old synthetic harness is retained in Git history. Its six tests covered
14 cases, including the original failure, both temporary-file storage states,
nested archives and malformed gzip. All passed during the original repair.
That historical reader is not a maintained archive interface. Current archive
checks belong to the private verification-evidence repository. They do not
require reproducing the old bug or running the old machine-local scripts.
The original script, inputs and detailed verification records remain private.

| Historical script | SHA-256 |
| --- | --- |
| Preserved original | `9c53681e2e431667451c74093bda2eb51deb43275f5d05e622d33510824bba90` |
| Repaired candidate | `67b298970d662ea83643136d447d4a3058e5faaa228c6cca65ebfd0e13c10fe8` |

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
new collection. At the time of this repair, archive consolidation remained paused pending
separate owner authorization.
