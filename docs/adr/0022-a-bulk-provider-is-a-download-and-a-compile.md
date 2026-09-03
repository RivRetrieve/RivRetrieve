# ADR-0022: A bulk provider is a download and a compile

## Status

Accepted

## Context

ADR 0003 states that a provider contributes `fetch.py`, `parse.py` and `config.py` and
nothing else, and ADR 0008 accepts as its cost that "an exotic source must express itself
as fetch and parse rather than as its own pipeline". The two bulk providers are exactly
that exotic source. Once ADR 0002's single layout holds their data, the store already
contains typed rows: a request queries it and there is nothing left to parse. Forcing the
four-stage shape onto them means a provider parse stage that decodes bytes its own fetch
stage serialised a moment earlier, purely to keep a diagram uniform.

The per-source work has not disappeared; it has moved in time. Reading Environment
Canada's wide monthly rows or IMGW's yearly CSV is still irreducibly per-source code, but
it now runs once per download rather than once per request.

## Decision

A bulk provider contributes `config.py` and `bulk.py`, and no `fetch.py` or `parse.py`.
`bulk.py` holds the two things that are true only of that source: how its publisher
artifact is downloaded, and how that artifact is compiled into the store. Retrieval for
such a provider is the engine querying the store and running convert and assemble; no
provider code executes on a request path.

This preserves ADR 0003's naming rule rather than breaking it — a provider file is named
for the work the provider writes code for — and generalises its count from three files to
the files the provider's kind actually needs. It preserves ADR 0008's guarantee for the
same reason it was made: the provider still never holds the sequence, and still cannot
clip, because it is not invoked during a retrieval at all.

## Consequences

Ticket #17's question, whether the thirteen sources reduce to three files each, has the
answer eleven do and two do not, decided here rather than discovered mid-port.

A contributor adding a bulk provider — Austria is expected — writes a download and a
compile, and inherits reading, querying and cache reporting from the shared store engine
without implementing any of them. That was the whole payoff argued for in ADR 0002 and it
is only realised by this decision.

The provider registry must distinguish the two kinds, because the surface differs: only a
bulk provider answers `download`, `cache_status` and `clear_cache`, and only a bulk
provider can refuse a retrieval for want of a local store. Ticket #146, which owns what
declares a built-in provider, inherits that distinction.

`clear_cache(provider)` is the explicit destructive recovery boundary for bulk state. It removes the compiled store and regular files or symlinks in the composition root's exact `publisher-artifact.download` namespace, reports every removed path and total bytes, and does not follow symlinks. It refuses a directory or other unexpected entry in that namespace before deleting anything. Compilation failures preserve publisher artifacts automatically; retry therefore requires an explicit `clear_cache` call rather than silent evidence deletion.
