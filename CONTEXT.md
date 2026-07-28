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

**Source coordinates**:
How one source names and locates the thing a canonical product id names: its parameter
code, endpoint, table, workbook, column or field. Declared per product in a
[[provider]]'s `config.py`, and read by fetch to address the source and by parse to pick
the right value out of what comes back. Every source names its products its own way, so
this is a fact about the source rather than behaviour, which is why it is declared
rather than coded.
_Avoid_: product policy (the pre-redesign name, one private variant per provider),
parameter code, native field (both name only one coordinate of several)

### Time

**Native time**:
A timestamp exactly as the provider published it. It is returned as a naive `time`
column holding the source's own wall-clock value, paired with a `time_zone` column
stating that row's zone, or `unknown` where the source does not establish one. The two
columns travel together and neither is meaningful alone. The pairing exists because one
dataframe timestamp column carries a single zone for all its rows, while one result may
span stations in different zones.
_Avoid_: raw time (collides with [[raw]], the untouched payload), local time
(ambiguous between the gauge's own zone and a provider-wide national zone)

**Best-effort UTC**:
Conversion of [[native-time]] to UTC, offered where the source zone is documented and
withheld where it is not. It is an offer, never a guarantee, and sits in the same tier
of promise as the [[best-effort]] catalogue columns.
_Avoid_: UTC guarantee, UTC-in/UTC-out

**Station timezone**:
The zone a station's timestamps are counted in, taken only from what its source
publishes. Where a source publishes none, the station timezone is [[unknown]] and is not
derived from the station's coordinates: a coordinate lookup is a third party's assertion
about a political boundary rather than the source's statement about its own data, and in
a result it would be indistinguishable from a zone the source did establish.
_Avoid_: provider timezone (a zone is a per-station fact wherever a country spans
several), inferred timezone

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

**User cache**:
Retrieved data a user keeps on their own disk so that asking for the same data again is
served locally instead of re-fetched. It is the user's, on the user's machine, for the
user's own reuse, so no redistribution question arises. Distinct from the [[cache]],
which belongs to the library and is disposable, and from an [[archive]], which is a
collection prepared for publication.
_Avoid_: archive, our cache

**Archive**:
A collection of retrieved river data assembled in order to publish or redistribute it.
RivRetrieve cannot ship one, because we do not hold redistribution rights to the sources.
The distinction from a [[user-cache]] is about distribution rights rather than about
storage: a user keeping their own retrieved data on their own disk raises no such
question, and both may sit in the same layout on disk.
_Avoid_: user cache, cache, bundled dataset
