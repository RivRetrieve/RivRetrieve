# Context

Project-specific domain language for RivRetrieve. Glossary only.

## Language

### Core

**Unknown**:
A representable state meaning the source does not tell us. Distinct from zero, from
empty, and from a default. Never resolved by assumption, and never filled by computing
a value the source did not publish.
_Avoid_: missing, N/A, not available, default

**Raw**:
The untouched provider payload, kept alongside the returned data.

**Best-effort**:
A field or behaviour that is filled when the source provides what it needs, and
[[unknown]] otherwise. Never fabricated.

### Structure

**Engine**:
The shared core every provider sits on. It owns the contracts between stages and
performs the [[stage]]s that are the same for everyone.
_Avoid_: core, framework, base

**Provider**:
An adapter over the [[engine]] for one national source. It contributes only what is
true about that source, as three files: `fetch.py`, `parse.py`, and `config.py`.
_Avoid_: source, backend, plugin

**Stage**:
One of the four steps every retrieval passes through: fetch, parse, convert, assemble.
A provider file is named for a stage only when the provider writes code for that
stage, which is why convert and assemble have no provider file.
_Avoid_: step, phase

### Time

**Native time**:
A timestamp exactly as the provider published it, carrying whatever zone information
the source itself supplied. This is what RivRetrieve returns by default.
_Avoid_: raw time (collides with [[raw]], the untouched payload), local time
(ambiguous between the gauge's own zone and a provider-wide national zone)

**Best-effort UTC**:
Conversion of [[native-time]] to UTC, offered where the source zone is documented and
withheld where it is not. It is an offer, never a guarantee, and sits in the same tier
of promise as the [[best-effort]] catalogue columns.
_Avoid_: UTC guarantee, UTC-in/UTC-out

**Day definition**:
The 24 hours a daily product actually covers, declared per provider-product. It is not
assumed: where a source does not state which 24 hours its daily value spans, the day
definition is [[unknown]] rather than midnight-to-midnight.
_Avoid_: day start, daily anchor, day boundary

### Measurement

**Datum**:
The reference height a stage measurement is counted from, either mean sea level or a
marker at the gauge itself. Two stage values in metres are not comparable unless they
share a datum, and a gauge's datum can change over time.
_Avoid_: reference level, zero point

### Provenance

**License**:
A source's own terms, surfaced as a link and, where the source publishes one, its
verbatim text. RivRetrieve never classifies, summarises or interprets what a licence
permits.
_Avoid_: license status, redistribution status, open/attribution/restricted

### Stored data

**Cache**:
Our local copy of a bulk provider's whole national dataset, downloaded because the
source offers no per-station access. It belongs to the library, is tied to a source
vintage, and is disposable: refreshing it means downloading the source again.
_Avoid_: archive, local store

**Archive**:
A store of retrieved data that the user builds and owns, accumulated across requests
and across any provider, not only bulk ones. RivRetrieve cannot distribute an archive
itself, because we do not hold redistribution rights to the sources, but nothing
prevents a user from building their own.
_Avoid_: cache, our archive, bundled dataset
