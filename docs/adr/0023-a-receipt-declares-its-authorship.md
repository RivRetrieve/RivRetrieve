# ADR-0023: A receipt declares its authorship

## Status

Proposed

## Context

ADR 0018 fixed the retained bytes as exactly what a provider's parse stage was handed,
and named the member `raw`. It already acknowledged that a local-query provider's bytes
are "a deterministic local encoding rather than publisher-authored wire bytes", and
required the origin to state the source path and query that produced them.

That acknowledgement is not enough once ADR 0002's store is a format RivRetrieve authors
and ADR 0021 deletes the publisher artifact behind it. For the eleven HTTP providers the
member holds an untouched response body. For a bulk provider it holds bytes RivRetrieve
serialised out of RivRetrieve's own file. Calling both `raw` presents our own encoding to
a scientist as the source's own words, and the name is the part that misleads: a reader
who checks `result.raw` has no way to learn which of the two they are holding.

The alternative considered was leaving the member empty for bulk providers and offering
only the store path and the executed query. It was rejected because it hands a person
auditing a suspicious number a file path and a SQL string instead of data, and requires
them to bring their own query tooling to answer a question the library could answer.

`evidence` was considered as the replacement name and rejected: `CONTEXT.md` already
defines evidence as the documentation reference an origin carries, and reusing it would
collide with the catalogue's language. ADR 0018 already calls this thing a receipt.

## Decision

The result member is `receipts` rather than `raw`, and every entry declares its
authorship: `publisher_payload` for untouched bytes the source itself served, or
`store_excerpt` for bytes RivRetrieve produced by encoding rows read from its own store.
Both travel in the same envelope, and a `store_excerpt` carries the store path, the
executed query, the store's format version and the source vintage it was compiled from.

What ADR 0018 decided is unchanged: retained bytes are exactly what the parse boundary
consumed, retention stays opt-in and empty unless the caller asks, and request headers are
never copied into an origin. Only the naming and the authorship declaration are added.

## Decision boundary

A `store_excerpt` is a faithful re-encoding of the store's own rows and nothing more. It
never reconstructs, infers or fills a value the store does not hold, so it is exactly as
complete as ADR 0021's compile step made the store, and no more.

## Consequences

A user can tell at a glance whether they are auditing a government's words or ours, which
is the distinction that matters when a number looks wrong.

The rename touches a member fixed by ticket #11 and ADR 0018. It is free now — the package
is unpublished and unregistered on PyPI — and would be a breaking change after v0.1.0, so
it is taken here or not at all.

A future archive-backed provider, which ADR 0018 anticipated, must choose an authorship
rather than inheriting one: an extracted archive member handed to parse is publisher
authored, while rows read back out of a store are not.
