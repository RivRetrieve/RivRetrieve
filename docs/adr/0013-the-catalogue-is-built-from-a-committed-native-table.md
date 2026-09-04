# The catalogue is built from a committed native table

Catalogue generation splits in two. `refresh` touches the network and writes a per-provider
native table, one row per station in the source's own column names, values unaltered,
which is committed. `build` is a pure function of that committed table and the provider's
origin declarations, so it runs in CI on every pull request with no network and produces a
byte-identical artefact, `built_at` excepted.

Two facts force this. Ten of the thirteen catalogues are generated from live sources, so
running the current generator again returns a different and equally valid catalogue, and
the shipped one cannot be checked against anything. And the origin rules of ADR 0012 need
something to check against; thirteen transports (JSON, scraped HTML, CSV, an OGC API, a
downloaded SQLite database) have no common notion of a response field, but they all pass
through one moment where the source's records exist in the source's own vocabulary.

The native table is where they converge, which makes it the only place one check can cover
all thirteen. It is also the thing `docs/design/provider-redesign-review.md` §6.4 asks for
under a different name, so the source's own columns become a table to be read rather than
a second feature. It replaces the opaque per-row `metadata` JSON string and the 39
hand-written pydantic models across 13 `metadata.py` files that exist only to serialise
into it. Parquet is self-describing, so no schema is authored per provider; a source adding
a field changes nothing, and a source renaming a field an origin references fails the build
loudly instead of silently nulling a column.

The rejected alternative keeps the native table off the repository and commits only a hash.
The checks would then exist and nothing would run them, which is how `begin_date` reached
26,231 nulls.

A refresh in which some stations fail carries those stations forward from the previous
native table with their own older `retrieved_at`, so staleness is a per-row fact. A station
that fails with no previous value aborts the refresh, because there is nothing honest to
write. Aborting on any failure is unworkable at Japan's 1,029 requests, and writing holes
reintroduces the ambiguity ADR 0012 removes. A failed request is an issue, returned rather
than printed.

## Superseded distribution consequence: native tables are repository inputs

The original decision said native tables would ship in the wheel so source-vocabulary facts remained
available after ADR 0015 reduced the canonical catalogue. The later distribution contract superseded
that consequence: native tables remain committed repository build inputs but are excluded from wheels.
The wheel carries the canonical catalogue and its acquisition-provenance identity. It does not expose
the native table through the public API or package payload.
