# ADR-0018: Raw is what parse read

## Status

Accepted

## Context

RivRetrieve promises a source-call receipt that can reproduce what each provider parsed. The bytes a
provider parses are not always the enclosing bytes received from a network call: CA ECCC reads rows
from a local SQLite database and must encode them for the parse seam, while a future archive-backed
provider may parse one member extracted from a downloaded archive. Retaining the enclosing response
would make the receipt look more original while failing to identify the actual parse input. Retaining
provider-specific decoded objects would make the receipt impossible to compare across providers and
could silently change after parsing code evolves.

## Decision

For every source call, `Payload.content` is immutable bytes and is exactly the bytes handed to the
provider's parse stage. The engine-owned, provider-agnostic `SourceCallOrigin` records the applicable
URL, request parameters, status code, UTC retrieval instant, content type, source path, and executed
query; an inapplicable or unavailable fact is represented by `UnknownOriginFact`. Request headers are
not part of the origin and are never copied into it.

A network provider retains the response body when that body is what parse reads. A local query
provider deterministically encodes its ordered result rows and retains those encoded bytes. A future
archive provider retains the extracted member handed to parse, not the enclosing archive response.

## Consequences

The receipt can reproduce the parse boundary uniformly across HTTP, local-query, and future archive
providers, and credentials carried only in request headers have no route into it. Some retained bytes
are a deterministic local encoding rather than publisher-authored wire bytes, so the origin must state
the source path and exact query that produced them. Reproducing a network download or archive envelope
is a separate concern and is not implied by raw retention.
