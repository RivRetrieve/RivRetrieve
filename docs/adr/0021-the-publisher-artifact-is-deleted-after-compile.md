# ADR-0021: The publisher artifact is deleted after compile

## Status

Accepted

## Context

Two of the thirteen providers publish no per-station access at all: Environment Canada
ships a national SQLite database of roughly a gigabyte, and IMGW ships yearly archives of
CSV. ADR 0002 already fixes that anything RivRetrieve stores on disk uses one layout the
engine queries, so both are compiled into a store rather than kept in the shape their
source happened to ship. That leaves the question ADR 0002 did not reach: whether the
downloaded publisher artifact survives the compile that consumed it.

Retaining it preserves byte-level replay. A defect discovered later in how we read the
source could be diagnosed and repaired locally, and a change to our own layout could be
recompiled without the network. The cost is doubling the footprint of the two providers
where footprint is the entire objection, for bytes no supported call ever opens, on a
machine where the peak during compile is already several times the store.

Discarding it makes the store the only surviving copy of those observations, which binds
the compile step to preserve rather than to summarise, and makes any omission permanent
at the moment it happens.

## Decision

The publisher artifact and any intermediate extraction are deleted once compiling
succeeds. What survives is the artifact's identity rather than its bytes: the manifest
records the URL it was retrieved from, the source vintage as the source itself dates it,
a checksum of the artifact compiled from, and a fingerprint of the source schema it was
compiled against.

Because deletion is irreversible, compiling is certified before it publishes. It compiles
into a staging location; an unknown or retyped source column fails the compile rather
than being ignored; rows accepted are reconciled against rows emitted per source unit;
and the completed store is read back through the same shared reader a user query uses and
compared field for field against the native rows produced from the artifact, covering
keys, duplicates, values, quality fields and native value states. Only after that
comparison passes does the staged store atomically replace the previous one and the
artifact get deleted. On malformed input, a full disk, interruption or any verification
failure, the previous store and the artifact both survive untouched.

A store is never migrated in place. A reader that does not recognise a manifest refuses
it and names the rebuild, rather than interpreting it as best it can or downloading
anything on the user's behalf.

## Consequences

Provenance means identifiable, not reproducible, and the guarantee must say so in those
words. The checksum proves precisely which release a value came from; it cannot
reconstruct that release. A defect in how the compile step understood a source, found
after the publisher has stopped serving the release it was compiled from, is not
recoverable from anything on the user's disk. This is the accepted price of the
decision and not an oversight to be closed later.

Changing our own layout costs every user a fresh download rather than a local
recompile. This is accepted because both bulk sources reissue on their own schedule, so
a rebuild usually wants newer data anyway.

Certification is not free: reading the whole store back and comparing it field for field
makes compiling substantially more expensive than writing files, and staging means the
old store, the artifact and the staged store may coexist, raising the peak disk a refresh
requires. The peak is therefore stated to the user before the download starts rather than
discovered when it fails.
