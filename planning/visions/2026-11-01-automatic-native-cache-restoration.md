# Automatic native cache restoration

A complete accumulated native cache copied to another directory, disk or machine
should work through ordinary RivRetrieve operations. Users should not need a restore
command, an opt-in flag, source access or edits to internal seals. The restored copy
is a normal working cache: it supports offline reuse and later acquisition updates.

This vision addresses [#651](https://github.com/RivRetrieve/RivRetrieve/issues/651).
Implementing and verifying this outcome completes that issue. Publishing this document
does not complete it.

## Agreed behavior

When local filesystem identities differ from those recorded in a saved cache,
RivRetrieve automatically verifies the complete cache before accepting its new local
identities. It checks every managed file against the original saved content digest,
the closed file inventory, and all observation and metadata consistency rules.
Only successful complete verification permits recording new filesystem witnesses
and continuing the original operation.

This applies to ordinary local access, including reuse, audit and subsequent updates.
The first access after copying may require a full-cache scan. Subsequent operations
use the normal validation path; relocation must not impose a full scan on every read.
Document the first-access cost and automatic local metadata update where users need
to understand them. No separate restoration API is required.

Preserve observation bytes, the manifest, coverage, acquisition provenance, original
content digests and the content-based generation identity. Only local filesystem
witnesses change. A copy does not make observations newly acquired.

Changed, missing or extra managed content, invalid metadata, unsupported formats,
or an invalid seal still cause refusal. Do not repair content, accept new digests
computed from replacement bytes, silently discard data, or fetch from the source to
hide a failed restoration. Verification must complete before new witnesses become
authoritative. Failure must leave the original saved content identities intact.

A filesystem mismatch alone cannot establish that the user deliberately copied the
cache. Automatic acceptance therefore depends on complete validation against saved
content identities, not on guessing why the filesystem changed. Digests detect
corruption and ordinary replacement. They do not authenticate a party able to rewrite
both the data and its seal.

## Repository context and implementation boundaries

The report at `b361e2bdb2f0faeaa730ff65432db527a65eab2a` describes a byte-identical
restore refused with `integrity.file_identity:manifest.json`. Its later comment
confirms remote S3 audit and reuse as a workaround, not a local restore solution.
See the issue for the downstream acquisition evidence.

In `src/rivretrieve/_internal/store/integrity.py`, local inspection checks filesystem
witnesses before a complete audit hashes the files. That ordering currently prevents
an ordinary copied cache from reaching full verification. `refresh_witnesses` is
restricted to owned change-time transitions; it is not a general relocation operation.
The seal's generation identity already binds content digests and sizes rather than
filesystem location.

Use the existing shared store integrity and publication lifecycle. Preserve its
exclusive ownership, managed-path and symlink checks, generation consistency, and
interruption guarantees. Automatic restoration must not treat unfinished publication,
ambiguous ownership or pending seal metadata as evidence of a complete copied snapshot.
Keep existing explicit recovery semantics for unfinished work. Safe witness replacement
and locking are implementation choices, not a second publication protocol.

The [store contract](../../docs/design/observation-store-layout.md) currently describes
inspection as checking file identities without hashing observation bytes. Update the
contract and affected API documentation to explain the automatic full-validation
exception and its metadata side effect. Decide the internal factoring and exact
entry-point wiring during implementation; no new public controls are requested.

Scope is complete accumulated local cache snapshots. Cache merging, salvage of
incomplete copies, new backup formats, remote-cache redesign, source recertification,
and stronger hostile-user or host/power-loss guarantees are excluded. Preserve existing
compiled-store and remote-store behavior where shared code changes touch those paths.

## Evidence of completion

Use source-independent synthetic fixtures and temporary cache roots to demonstrate:

- A complete cache copied to a fresh location, with changed filesystem identities,
  passes public audit and returns equivalent observations and provenance through
  ordinary reuse with source HTTP denied. Neither path needs a prior restore call.
- The restored cache supports a later normal accumulation update while preserving
  the existing retained-data and provenance rules.
- Complete verification precedes acceptance, including for partitions outside the
  first requested scope. Changed bytes and malformed or incomplete snapshots are
  refused without blessing new content identities or falling back to source access.
- Successful restoration retains the content-based generation identity. Later access
  follows the ordinary path rather than repeating relocation verification.
- Failed or interrupted witness replacement preserves the established lifecycle
  safety guarantees and does not make an incompletely verified cache usable.

Extend existing shared integrity and lifecycle coverage at the simplest sufficient
level. Run affected source-independent tests and broader checks required by the shared
boundaries changed. Leave reversible internal mechanisms to the implementing agent.
