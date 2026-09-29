# Archive inventory gzip reader

## Outcome

Make the retained-material inventory read nested gzip content correctly without
changing its inputs. Produce a new, reviewed inventory before maintainers rely on
its results to consolidate the source archive.

Related bug: https://github.com/RivRetrieve/RivRetrieve/issues/435

This is a standalone bug-repair vision. The defect blocks the shared source archive
work in https://github.com/RivRetrieve/RivRetrieve/issues/428, under the stop rule
of https://github.com/RivRetrieve/RivRetrieve/issues/427. This document does not
replace that Effort's vision, authorize its other implementation work, or authorize
resumption. The owner must explicitly authorize resumption after this repair is
verified.

## Established evidence

The investigation inspected the preserved local `inventory_material.py` and its
provisional `source-spec.json`, `inventory.jsonl`, `inspection-warnings.json`, and
`summary.json`. These remain private. Obtain their location from the paused
implementation owner; do not publish their paths or source contents. If the exact
script or genuine inputs cannot be located, report the missing prerequisite rather
than recreate an acquisition or substitute synthetic data for acceptance.

The script calls `gzip.GzipFile(fileobj=f)` without an explicit mode. Nested archive
members are copied into `tempfile.SpooledTemporaryFile` streams. Such a stream can
remain in memory or move to disk when it grows. On the tested Python 3.13.8 runtime,
the in-memory stream caused gzip to infer write mode. The read attempt then raised
`OSError`, emitted a `FutureWarning`, and changed the ephemeral stream's bytes.
The disk-backed spool did not reproduce this failure. Retained physical files are
opened with `rb`; writable streams in this path are temporary copies.

Synthetic probes executed the preserved function definitions with `uv run python`.
Gzip inside both TAR and ZIP reproduced the missing decompressed entry. An in-memory
candidate change to `gzip.GzipFile(fileobj=f, mode="rb")` produced the expected
payload hashes and removed those inspection failures. Direct gzip checks passed
with the candidate for both spool states, without changing the input bytes. XZ
checks passed unchanged for both states. No preserved script was edited during
these probes, and no genuine inventory rerun was performed.

The saved inventory contains exactly two container-inspection failures, both
nested gzip members. Their shared retained outer container still matched its
saved byte size and SHA-256 when checked during investigation. This is specific
integrity evidence, not a claim that all retained files were independently audited.
All declared code input files and retained root directories were present; directory
presence alone does not prove every retained descendant is unchanged.

The incomplete inventory is rejected. Its record counts and proposed source-role
classifications are not acceptance evidence. The issue reports no publication,
retained-material deletion, or genuine collection acceptance from the failed run.

## Repair and verification

Keep the repair focused on the inventory reader. Make gzip reads explicitly binary
and read-only, independent of the underlying stream's mode. Preserve the failed
script and provisional inventory as private diagnostic evidence before modifying or
rerunning anything. The existing script opens its inventory output for writing at
startup, so a rerun must not overwrite the rejected record.

Provide focused, reproducible regression coverage using synthetic bytes:

- The old behavior fails for an in-memory writable spool containing gzip data.
- The repaired reader returns the expected decompressed bytes, size, and hash for
  both in-memory and disk-backed spools.
- Gzip nested in TAR and ZIP reaches the decompressed entry through the actual
  recursive inspection path, with the expected parent/member relationships.
- Input bytes remain unchanged, and the mode warning and inspection failure are
  absent for valid gzip data.
- Malformed gzip remains a visible inspection failure, never a successful complete
  inventory. Preserve existing failure reporting; do not suppress errors to pass.

Choose the smallest maintainable test location and execution method consistent
with the script's actual ownership. Do not build a new archive framework merely
to repair this local tool. Keep executable tests and synthetic data separate from
private source material. Use `uv` for project execution. Record commands, runtime,
outcomes, and the exact repaired script identity so the result can be reproduced.

After synthetic verification, rerun the complete inventory against the original
declared inputs in a private environment. Preserve original bytes, acquisition
identities, and known gaps. Compare physical-input fingerprints and review the
new inventory against the rejected one. Confirm that both previously failed gzip
members are inspected and that the newly discovered entries have correct byte
identities. Review all inspection failures or limits before accepting the inventory;
a process exit code alone is not sufficient. Missing mandatory inputs remain
blocked. Any new defect must be reported under the existing stop-and-report rule,
not repaired incidentally or silently worked around.

The repair is verified only when regression coverage passes, the genuine full
rerun has been reviewed, the two failures are accounted for, and input preservation
has been checked. Keep detailed evidence private and provide a safe summary of
commands and outcomes. Inventory success does not certify provider claims,
source-role classifications, or a new collection. If governing claims, source
bindings, verifiers, or collections change, the applicable full checks in
`docs/maintenance/evidence.md` remain mandatory.

## Boundaries

Do not change provider behavior, catalogue claims, acquisition identities, or
source vocabulary. Do not collect replacement data, publish archive releases,
delete retained material, or resume unrelated archive consolidation as part of
this repair. Preserve unrelated work in the paused implementation checkout.

Restricted bytes, paths, request details, and credentials must stay out of public
code, issues, documentation, logs, caches, CI artifacts, and distributions. Do not
run unreviewed code with private evidence access. Review the repaired reader before
giving it genuine inputs. Publish only safe verification summaries.

The implementing agent owns the technical details. The owner need not choose
Python APIs or test mechanics. Fix verification and the owner's later explicit
permission to resume the blocked Effort are separate steps.
