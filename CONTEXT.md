# Context

Project-specific domain language for RivRetrieve. Glossary only.

## Language

### Core

**Unknown**:
A representable state meaning the source does not tell us. Distinct from zero, from
empty, and from a default. Never resolved by assumption, and never filled by computing
a value the source did not publish. A license or citation RivRetrieve has not yet
established is absent, not [[unknown]]: that is RivRetrieve's pre-research state, not
source silence.
_Avoid_: missing, N/A, not available, default

**Receipt**:
What a [[provider]]'s parse [[stage]] was handed, kept alongside the returned result so a
user can audit a value against what the source actually said, and only when the caller
asks for it — unasked, the slot exists and is empty and no response bytes are reachable
from the result. It is bytes and stays bytes: thirteen sources answer in JSON, CSV, HTML
and spreadsheets, and modelling that would be parsing. Each entry carries a uniform
envelope naming where the bytes came from, with the fields that do not apply left
[[unknown]] and request headers excluded entirely so a credential has no route in. It is
deliberately what parse read rather than what came off the wire: a zip explains no value,
and a bulk provider never touches the network on a request. Every receipt declares its
authorship, because the two are not the same kind of thing and only the reader can tell
which matters: a **publisher payload** is untouched bytes the source itself served, and a
**store excerpt** is bytes RivRetrieve produced by encoding rows read out of its own
[[store]]. A store excerpt is exactly as complete as [[compile]] made the store and never
reconstructs a value the store does not hold.
_Avoid_: raw (the former name; it presented RivRetrieve's own encoding as the source's own
words), untouched payload (one unzipping step removes it from what the server sent),
response, blob

**Native table**:
One [[provider]]'s station metadata in the source's own vocabulary: its column names,
its spellings, its units, its values unaltered. Every provider produces one, whatever
shape its source arrives in, and it is the single point where thirteen unlike transports
become one thing. The canonical station catalogue is built from it rather than beside
it, which is why the source's own columns are a table to be read rather than a blob to
be parsed.
_Avoid_: metadata (the opaque per-row JSON string it replaces), raw table (collides with
[[receipt]], the exact bytes handed to a [[provider]]'s parse [[stage]] and retained only when
requested), source table

**Origin**:
How one [[provider]] fills one catalogue column. Declared per provider rather than per
column, so the same canonical column is filled one way by one source and left empty by
another. It takes one of four forms: a column of that provider's [[native table]]; a
[[documented]] constant; the statement that this source publishes nothing for that
column, carrying [[evidence]]; or [[native-only]]. Every canonical column carries one for
every provider in `ORIGIN_GATE_ENROLLED_PROVIDERS`; an unenrolled provider is explicitly
outside origin certification rather than treated as compliant. The ways to breach it are
an undeclared column, an origin naming a native column that was never fetched, a null where
the native column held a value, a documented constant differing from the emitted value,
and a documented or not-published claim carrying no evidence. Each fails the build rather
than shipping.
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

**Documented**:
The [[origin]] for a constant the source states in its documentation rather than carrying
in every row of its [[native table]]. It pairs the exact value with [[evidence]], so the
generator cannot silently emit a different constant and the declaration does not pretend
that a native column contains it or that the source is silent.
_Avoid_: hard-coded, assumed, field

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
What a not-published or [[documented]] [[origin]] must carry: a reference to the source's
own documentation stating that it publishes nothing for that column or stating the
documented constant. It exists because absence from a payload proves only how we asked.
USGS returns no period of record from the site service called with default output, and
publishes one from the same service asked differently, so a payload-only check would have
certified the false claim. Evidence is read by a person once, and is the one part of an
origin no machine can settle.
_Avoid_: citation (which credits a source for its data, not its documentation), proof,
justification

**Best-effort**:
A field or behaviour that is filled when the source provides what it needs, and
[[unknown]] otherwise. Never fabricated. In the catalogue this is enforced rather than
intended: a best-effort column still carries an [[origin]] for every [[provider]] in
`ORIGIN_GATE_ENROLLED_PROVIDERS`, so being empty is a declared claim and not permission to
leave it unfilled.

**Published record**:
The period a source itself states a series covers, carried as
`published_record_start_date` and `published_record_end_date`. It is a nominal envelope and
nothing more: it does not establish continuity, absence of gaps, quality, or that the data is
still retrievable. Twelve of the thirteen sources publish none, so it is [[unknown]] for most
of the catalogue and is never used to prevent a fetch. The name carries `published` because a
bound RivRetrieve established by asking rather than by reading is a weaker and different claim
— bounded by how we asked — and would need its own column and its own [[origin]] form rather
than this one.
_Avoid_: start_date, end_date (bare, they invite an observed value into a published column),
period of record (does not say who established it), coverage (implies continuity)

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
true about that source. An HTTP provider contributes `fetch.py`, `parse.py`, and
`config.py`; a bulk provider contributes `config.py` and `bulk.py`.
_Avoid_: source, backend, plugin

**Stage**:
One of fetch, parse, convert, and assemble. An HTTP retrieval passes through all four.
A bulk retrieval queries the [[store]] and then passes through convert and assemble; it
passes through neither provider fetch nor provider parse, and no provider code executes
on its retrieval path. A provider file is named for a stage only when the provider writes
code for that stage, which is why convert and assemble have no provider file.
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

**Provider declaration**:
The single statement, living in a [[provider]]'s own directory, of everything the
[[engine]] needs to make that source usable: where its packaged catalogue sits and which
[[provider-kind]] it is. It is the only file a new source must write beyond its stage
code, and it is read once, at registration. Everything else a provider used to state
about itself — the catalogue-reading functions each of the thirteen copied verbatim — was
never called, because the engine reads the catalogue from the artifact directly.
_Avoid_: registration block, provider module (the pre-registry file, whose catalogue
functions no runtime path reached), config (which declares [[source-coordinates]] per
product, a different fact), plugin

**Provider kind**:
Which of exactly three shapes a [[provider]] takes, declared in its
[[provider-declaration]] and dispatched on by the [[engine]] rather than inferred from its
id: [[catalogue-only]], an HTTP source contributing fetch and parse [[stage]]s, or a bulk
source contributing a download and a [[compile]]. The set is closed. A source fitting none
of the three is an engine change argued once and applied to every provider, not a fourth
architecture a single provider invents — which is the distinction between adding a
provider, which touches one directory, and adding a kind of provider, which is a design
decision. Dispatching on kind rather than on provider id is what removes the last
hand-written per-provider branch.
_Avoid_: provider type, capability, variant, strategy

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

**Selection**:
The set of series a caller has settled on, at the grain of one
`(provider_id, station_id, product_id)` triple, produced by `find` or narrowed by `pick` and
handed to `fetch`. It is a value rather than an object: immutable, printable as a table, and
carrying no methods, no chaining and no query language, so every capability enters through a
function rather than by growing the thing a user is holding. An empty selection is an ordinary
answer and retains a machine-readable reason for being empty, which `fetch` reports when it
refuses to retrieve nothing.
_Avoid_: query, queryset, handle (which named the deleted per-provider object), result (which
is what `fetch` returns), filter

**Shows rather than decides**:
The test that admits a capability the catalogue cannot fully support. A capability that decides
on the caller's behalf and does not record what it dropped turns an [[unknown]] into a silent
exclusion, so it does not ship — this is what removed the bounding box, `record_covers` and the
live catalogue argument. A capability that displays every row and leaves the judgement to a
person makes the same [[unknown]] visible rather than operative, which is why a map renders
unstated-frame coordinates while a bounding box may not compare them.
_Avoid_: best-effort filtering, graceful degradation, partial support

### Time

**Native time**:
A timestamp exactly as the provider published it. The complete returned observation
frame is `time | time_zone | station_id | product_id | value`, in that order. Its `time`
column holds the source's naive wall-clock value, paired on every row with the
source-published `time_zone`, or `unknown` only where the source establishes no zone.
All five columns travel together as the observation frame; `time` and `time_zone` are
not meaningful alone. The pairing exists because one dataframe timestamp column carries
a single zone for all its rows, while one result may span stations in different zones.
_Avoid_: raw time (collides with [[receipt]], the exact bytes handed to a [[provider]]'s parse
[[stage]] and retained only when requested), local time (ambiguous between the gauge's
own zone and a provider-wide national zone)

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
a result it would be indistinguishable from a zone the source did establish. Neither is
one kind of zone promoted to the other: a published fixed offset stays an offset and is
never upgraded to a named identifier, because several identifiers share any given offset
and choosing among them is a derivation. Converting [[native-time]] to absolute time
therefore reads each row's own published zone rather than one zone per station, which is
what lets a station whose offset shifts across a daylight-saving boundary convert at all.
_Avoid_: provider timezone (a zone is a per-station fact wherever a country spans
several), inferred timezone, promoted timezone

**Requested window**:
The interval a caller asks for, closed at both ends, expressed as wall-clock time in the
calendar each station's own source publishes. It is never an absolute interval on the
world's timeline: asking for one day across two stations in different zones asks each
gauge for its own day, not for one shared 24 hours. An endpoint carrying a zone is
refused rather than reinterpreted, because a window that means an instant can only be
placed against a [[station-timezone]], and five of the thirteen sources publish none — the
capability would evaporate by country. This is what makes clipping possible for a station
whose zone is [[unknown]]: wall clock compares to wall clock without needing a zone on
either side. A caller wanting an absolute interval converts the returned [[native-time]]
afterwards, as ADR 0006 intends.
_Avoid_: date range, time range, requested period, UTC window

**Fetch window**:
The [[requested-window]] widened outward by a fixed two days at each end, and the only
window a [[provider]] ever sees. The pad is uniform rather than computed per source
because the widest disagreement between any two calendars on Earth is 26 hours, so a
fixed two days cannot fail to contain the request whatever calendar the source's date
parameters turn out to be in — which leaves no per-provider padding for a port to get
wrong. It is always a superset of the requested window; the extra rows are removed when
[[convert]] clips.
_Avoid_: query window, padded window, over-fetch window

**Sub-window**:
One piece of a [[fetch-window]] a [[provider]] can actually ask its source for, computed
by the [[engine]] from the [[window-granularity]] a provider-product declares. Six of the
thirteen sources cannot answer an arbitrary window in one request, and each expressed
that with its own private splitting code; the granularity is a fact about the source,
the splitting is arithmetic, and the two are separated so that only the engine performs
the arithmetic.
_Avoid_: chunk, window split, decomposition (which names the act, not the piece)

**Window granularity**:
The declaration keyed by provider-product that tells the [[engine]] whether a
[[fetch-window]] is unsplit as an ISO instant or date pair, split by year, split by
year-month, split into N-year chunks, split into capped inclusive-date spans, or has no
requested-window parameters. Drive selects one declaration for each requested `ProductId`
before planning the authoritative fetch window. It names source request boundaries;
post-hoc result filtering is not a granularity.

**Stop convention**:
Whether a rendered source-request stop includes its displayed boundary or excludes it.
The [[requested-window]] remains closed; the [[engine]] advances an exclusive rendered
stop by the rendering's smallest boundary unit. The provider receives the already-adjusted
rendering for its requested `ProductId` and performs no stop arithmetic.

**Window rendering**:
The immutable product-keyed mapping of source-vocabulary string tuples the [[engine]]
produces from a [[fetch-window]] or [[sub-window]] according to each
[[window-granularity]] and [[stop-convention]]: an ISO instant, a date, a year, a
year-month, or nothing where the source accepts no date parameter. A [[provider]] consumes
only the tuple for the requested `ProductId` as source-request bounds and cannot add to,
shift, or split it. The separate `FetchWindow` is only the payload tag.
_Avoid_: window formatting, window translation, window conversion

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
verbatim text. RivRetrieve never classifies, summarises or interprets what a license
permits. A license RivRetrieve has not yet established is absent, not [[unknown]];
[[unknown]] would mean the source does not tell us.
_Avoid_: license status, redistribution status, open/attribution/restricted

**Citation**:
The credit a source requests for its data, surfaced verbatim rather than rewritten or
inferred. A citation RivRetrieve has not yet established is absent, not [[unknown]];
[[unknown]] would mean the source does not tell us.

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

**Store**:
Retrieved observations at rest in RivRetrieve's own layout, together with the
[[manifest]] describing them. It is the single form ADR 0002 fixes for anything held on
disk, so a [[cache]] and a [[user-cache]] are both stores. Revision `1` of the compiled-
store manifest contract is reserved for a store produced by compiling a
[[publisher-artifact]]. A user-cache store uses a distinct later format revision and does
not use a reduced revision-`1` manifest. A store holds the source's native values and
native wall-clock timestamps; unit conversion and clipping happen on read through the
same convert [[stage]] every provider uses, so standardising the container is not the
same act as changing the numbers. The layout is authored by RivRetrieve rather than
owned by a publisher, which is why it carries a format version and why reading one is a
compatibility obligation rather than an implementation detail.
_Avoid_: cache (one kind of store, not the category), database, local format

**Publisher artifact**:
The file a bulk source actually ships — a national database or a set of yearly archives —
downloaded whole because that source offers no per-station access. It is the input to
[[compile]] and not a queryable thing: it is deleted once compiling succeeds, so a
[[store]] is the only surviving copy of the observations. What survives of it is its
identity rather than its bytes, recorded in the [[manifest]] as the URL it came from, its
source vintage and its checksum, which names precisely which release a value was compiled
from and allows that exact release to be fetched again.
_Avoid_: raw download, source file, bulk payload

**Compile**:
The step turning one [[publisher-artifact]] into a [[store]], run once per download rather
than once per request. It is where a bulk provider's source-specific work lives, which is
why a bulk provider contributes a download step and a compile step rather than the fetch
and parse [[stage]]s an HTTP provider contributes. It preserves by default: every cell the
source published about an observation is carried across, including values RivRetrieve never
reads, because deleting the [[publisher-artifact]] makes any omission permanent. Whatever it
does drop is declared and argued in the layout specification rather than left to what the
library happens to consume.
_Avoid_: ingest, import, transform, ETL

**Value state**:
Which of four distinct things a [[store]] says about one station-product-day: that the
source published no record for it at all, that it published a record whose value is null,
that it published a record whose value field is blank, or that it published a value. A
typed numeric column collapses the first three into one, so the layout carries the state
beside the value rather than encoding it in the value. The distinction is not decoration:
"we hold no record" and "the source told us there is nothing here" are different claims
about the world, and [[compile]] is the last moment either can be observed, because the
[[publisher-artifact]] is gone afterwards.
_Avoid_: null handling, missing value, sentinel

**Source vintage**:
Which release of a bulk source a [[store]] was compiled from, as the source itself dates
it, recorded in the [[manifest]] and travelling in provenance on every result the store
answers. It is a date stamp and never a verdict: RivRetrieve does not compute whether a
store is old, because a threshold would be a number nobody derived and would replace a
precise fact — this answer came from that release — with an opinion we invented. A user
comparing two runs sees the release change; nothing nudges them, by design.
_Avoid_: stale, freshness, age, cache expiry

**Manifest**:
The machine-readable record written beside a [[store]] stating the layout's format version,
when the store was built, and the [[publisher-artifact]] it was compiled from. It exists so
a store describes itself to a reader that did not build it, so a version mismatch is
detected rather than misread, and so a value can be traced to a specific source release
after the artifact itself is gone.
_Avoid_: metadata, header, index

### Proof

**Recording**:
A saved interaction with a real source: the exact request that was issued, the exact
response bytes that came back, the instant it was made, and a digest. It is the only
admissible observation fixture. Every [[provider]] already sends through one injectable
transport seam, so there is exactly one point at which a recording is made and exactly one
at which it is replayed, and replay resolves a request rather than answering
unconditionally — a replay handed a request it holds no recording for fails instead of
returning something. That is what makes a fake that ignores the [[requested-window]]
unconstructible, and it is why a wrong [[window-rendering]] declaration is caught by a
missed lookup rather than by a reviewer. A recording is repeatable by construction: it
carries what to ask and when it was last asked, so drift is detectable later without being
detected now. Distinct from a [[receipt]], which is the same bytes travelling out with a
result for a user to audit; a recording is the same bytes travelling in, so a test can be
about the source rather than about us.
_Avoid_: fixture (the repository's nine invented observation payloads were also called
fixtures, which is how a belief passed for an observation), mock, stub, cassette, sample

**Invented payload**:
An observation payload written by an author from what they believed a source returns. It
proves a port reproduces its author's belief, which is how eleven providers held a
boundary defect while their tests passed. It is never a [[recording]] and never grounds an
expectation; the nine committed under `reference/legacy_observations/` remain as
[[legacy-reference]] reading material, because what a previous author believed the shape
was is worth reading, and are not promoted into a live fixture or a baseline.
_Avoid_: synthetic fixture, toy fixture, minimal fixture (all three describe the size
rather than the defect, and the defect is the authorship)

**Boundary probe**:
The one audited defect a single provider-product is shown not to have, converted from the
charting audit's prose into an executable claim about what its source published. Its input
is a [[recording]] whose readings straddle local midnight in the source's own calendar; its
assertion is three literals — how many readings returned, the wall-clock time of the first,
the wall-clock time of the last — chosen to be checkable by eye against the recorded bytes
in under a minute, because an expectation nobody can audit is indistinguishable from one
nobody wrote. Everything beyond those three is engine business already carried by the
always-on window invariants. It does not re-run the retired implementation: the audit
established that the old code was wrong, and the open question is whether the new code is
right.
_Avoid_: regression test (nothing regressed; the behaviour never worked), edge case test,
timezone test

**Independent expectation**:
A [[boundary-probe]]'s three literals, authored from a [[recording]] and the source's own
documentation by an author with no access to the port's code or its output. The separation
is the entire content: an author who can run the port will write down what the port does,
whichever answer that is. This is a rule about how the work is done rather than about what
the code contains, so it lives in `AGENTS.md` and binds whoever reads it.
_Avoid_: golden value, expected output, baseline (which named the retired practice of
comparing two implementations over an [[invented-payload]])
