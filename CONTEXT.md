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

**Native table**:
One [[provider]]'s station metadata in the source's own vocabulary: its column names,
its spellings, its units, its values unaltered. Every provider produces one, whatever
shape its source arrives in, and it is the single point where thirteen unlike transports
become one thing. The canonical station catalogue is built from it rather than beside
it, which is why the source's own columns are a table to be read rather than a blob to
be parsed.
_Avoid_: metadata (the opaque per-row JSON string it replaces), raw table (collides with
[[raw]], the untouched observation payload), source table

**Origin**:
How one [[provider]] fills one catalogue column. Declared per provider rather than per
column, so the same canonical column is filled one way by one source and left empty by
another. It takes one of three forms: a column of that provider's [[native table]]; the
statement that this source publishes nothing for that column, carrying [[evidence]]; or
[[native-only]]. Every column carries one for every provider, so an empty cell is a claim
rather than an absence that could equally mean we never asked. The four ways to breach it
are an undeclared column, an origin naming a native column that was never fetched, a null
where the native column held a value, and a not-published claim carrying no evidence.
Each fails the build rather than shipping.
_Avoid_: mapping, provenance (which names the receipt travelling with a result, not the
per-column declaration), nullable

**Native-only**:
The [[origin]] for a column this source does publish and we decline to promote, because
the value cannot be admitted to the column's domain. It is distinct from publishing
nothing: the cell is empty for a reason that is ours rather than the source's, and the
source's value remains readable in the [[native table]]. It names the decision that
withheld it rather than restating the argument, so reversing that decision is one edit.
_Avoid_: rejected, excluded (both read as a verdict on the source's data), unrepresentable
(which implies a technical limit rather than a choice), withheld

**Canonical column**:
A catalogue column carried in RivRetrieve's own vocabulary, filled through an [[origin]]
by every [[provider]] that can. A column earns canonical status only where it harmonises
identity or physics; anything resting on judgement stays in the [[native table]] in the
source's own words. This is why the station catalogue holds identity and geometry and
nothing else, and why a gauge's name, its river, its elevation and its country are native
facts rather than canonical ones. Grain is a separate question: canonical says whose
vocabulary, not what a row is about.
_Avoid_: harmonised column, standard column, core column

**Evidence**:
What a not-published [[origin]] must carry: a reference to the source's own documentation
stating that it publishes nothing for that column. It exists because absence from a
payload proves only how we asked. USGS returns no period of record from the site service
called with default output, and publishes one from the same service asked differently, so
a payload-only check would have certified the false claim. Evidence is read by a person
once, and is the one part of an origin no machine can settle.
_Avoid_: citation (which credits a source for its data, not its documentation), proof,
justification

**Best-effort**:
A field or behaviour that is filled when the source provides what it needs, and
[[unknown]] otherwise. Never fabricated. In the catalogue this is enforced rather than
intended: a best-effort column still carries an [[origin]] for every [[provider]], so
being empty is a declared claim and not permission to leave it unfilled.

**Issue**:
A fact about the data, returned rather than raised. A station answering 404, a window
holding no observations, a zone that could not be established are all issues: non-fatal,
carried alongside the value, and never a reason to discard the rows that did arrive. An
exception is the other thing entirely — a violation of the contract between [[stage]]s,
such as a parse handing back a frame with the wrong columns, where there is no result
worth assembling. Severity is `info | warning | error`, so an issue also records what
merely deserves saying, like a unit having been converted.
_Avoid_: error, warning, failure (each names one severity, not the category)

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

**Catalogue-only**:
A [[provider]] registered with no observation [[stage]]s. Its packaged catalogue is read
normally, while asking it for observations raises rather than returning an empty result,
because the source is reachable and the question is answerable — the port simply has not
been written. Eleven of the thirteen are catalogue-only, so this is the ordinary state of
a provider rather than an exceptional one.
_Avoid_: unported, disabled, stub, broken

**Legacy reference**:
The pre-engine implementation of a [[catalogue-only]] provider, kept readable under
`reference/legacy_observations/<provider>/` with the tests and payload fixtures it was
written against. It exists so that porting a provider can start from how that source
actually behaves — its endpoints, request construction, headers and response shapes —
rather than from reconstruction. It is excluded from lint, typecheck, test collection and
both distributions, and is deleted per provider as that provider is ported. It is
evidence, not runtime code and not a live test suite.
_Avoid_: dead code, backup, vendored, archive (which is a collection prepared for
publication)

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
