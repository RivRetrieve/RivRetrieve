# Restore archive tar safety checks

Repair issue: https://github.com/RivRetrieve/RivRetrieve/issues/473

This is a standalone bug-repair vision. It does not replace the vision for
[Effort #429](https://github.com/RivRetrieve/RivRetrieve/issues/429), which is
paused on this bug.

## Outcome

Restore the archive reader's existing safety checks with a small, focused repair
in the private `RivRetrieve/verification-evidence` repository. The checks must run
on supported Python versions before processing oversized archive metadata.

These checks protect the computer opening the archive. Oversized metadata or too
many internal records can consume excessive memory or processing time. The
whole-archive decompression limit still works; this defect bypasses earlier,
per-header checks. There is no evidence here of an attack, disclosure, corrupted
river data or wholly unbounded extraction.

## Cause and code locations

Source inspection used private archive target
`e59eb212146dccaae8721bf4645ce0d97b146831`. At that revision:

- `archive/archives.py`, `_tar_headers` (lines 73–90), installs checks through
  `BoundedTarInfo.frombuf`. It counts headers, rejects counts above
  `3 * member_count + 1`, caps extension metadata at 65,536 bytes, and rejects
  unsupported entry types.
- The same file, `_TarBytes` and the tar extraction loop (lines 93–105 and
  184–206), retains the total decompression limit and checks returned members.
- `tests/test_verification_evidence_acquisition.py` contains
  `test_tar_extension_metadata_is_bounded_before_allocation` and
  `test_gnu_extension_metadata_is_rejected_before_read`.
- `pyproject.toml` declares Python `>=3.13`.

Newer CPython patch releases parse headers through `_frombuf` instead of
`frombuf`, so the override never runs. The change starts at **3.13.13 and
3.14.4**, rather than affecting every 3.14 release or sparing every 3.13 release.
The extractor is byte-identical between the inspected archive target and private
PR #11 head `75430f26b38a4b6b57f9de1bd4464ed279e47404`. The #429 test-access
refactor did not introduce it.

Official upstream evidence:

- [Upstream change](https://github.com/python/cpython/commit/42d754e34c06e57ad6b8e7f92f32af679912d8ab),
  with [3.13 backport](https://github.com/python/cpython/commit/ae99fe3a33b43e303a05f012815cef60b611a9c7)
  and [3.14 backport](https://github.com/python/cpython/commit/7ad3093d76a748af55bdb1d2e8aad3638163b017).
- Compare `Lib/tarfile.py` at
  [3.13.12](https://github.com/python/cpython/blob/v3.13.12/Lib/tarfile.py) and
  [3.13.13](https://github.com/python/cpython/blob/v3.13.13/Lib/tarfile.py), and at
  [3.14.3](https://github.com/python/cpython/blob/v3.14.3/Lib/tarfile.py) and
  [3.14.4](https://github.com/python/cpython/blob/v3.14.4/Lib/tarfile.py).
- The [shared processing step](https://github.com/python/cpython/blob/v3.14.6/Lib/tarfile.py#L1382-L1405)
  runs before extension dispatch. Extension handlers read metadata and recursively
  parse further headers; ordinary file iteration does not expose every header.

Issue #473 reports three failing synthetic regression cases on Python 3.14.6,
including reproduction on the archive target. Small PAX metadata passes;
oversized PAX and GNU longlink metadata are accepted. GNU longname fails later
through path handling, which does not prove the metadata guard ran. Discovery
inspected code and upstream sources; it did not independently execute those tests.

## Focused repair

Move the checks to a parsing step reached by both call paths, before extension
processing. Overriding `TarInfo._proc_member`, checking before delegating to the
base method, is the source-backed candidate. This remains an internal Python
interface and needs compatibility tests. The implementing agent may choose an
equivalent narrow mechanism that proves the same behavior.

Count each parsed header exactly once, including headers consumed inside PAX or
GNU extension handling. Do not leave a second counter in `frombuf`. Cover metadata
extension types recognized by the parser, including global and local PAX, GNU
longname/longlink, and the Solaris PAX type. Preserve all existing decompression,
member-count, extracted-size, path, sparse-entry and special-entry protections.

Do not redesign storage, change source claims or collections, replace recordings,
weaken negative tests, or drop supported Python versions to hide the defect. Do
not replay or overwrite preserved #429 drafts or merge its implementation PRs.

## Acceptance and handoff

Use credential-free synthetic archives to prove:

- Existing regressions pass, and ordinary supported archives still open.
- Metadata at the limit is accepted when otherwise valid; metadata above it is
  rejected before the tar parser requests its body. Eventual filename rejection
  is insufficient. Buffered decompression may read ahead; no zero-read-ahead
  guarantee is required.
- Header counts enforce the exact boundary, including a chain of extension
  headers hidden from ordinary iteration. Separate extractions reset the count.
- Existing total extraction limits and entry restrictions remain effective.

Run focused regressions across the patch boundaries above and current supported
patch releases, with the full source-independent archive suite on maintained
supported interpreters. Reuse existing coverage where it proves the requirement;
avoid multiplying the full suite unnecessarily. Record exact interpreter versions,
commands, results and runtime. Missing required validation is blocked, not passed.

Keep credentials and retained source material out of these synthetic tests.
Genuine-input execution remains gated on independent review of the exact code and
restricted execution. Synthetic results establish archive mechanics, not genuine
collection acceptance. Follow each repository's verification and preservation
rules; retain private review details privately.

The delivery should identify the merged repair and its validation, and provide
the evidence needed to close #473. Publishing this vision does not close the bug.
Effort #429 remains paused until the owner explicitly authorizes resumption after
the repair; its genuine-input acceptance is separate work.
