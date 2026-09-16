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
[[store]]. A store excerpt contains exactly the selected rows the [[store]] holds, whether compiled
or accumulated, and never reconstructs a value the store does not hold.
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
another. It takes one of five forms: a column of that provider's [[native table]], with a
named typed conversion where needed; an [[authored]] provider identity; a [[documented]]
constant; the evidenced statement that this source publishes nothing for that column; or
[[withheld]]. Source-specific converters and source vocabulary stay in the provider
module and are reused by its generator; the generic gate only invokes the conversion
interface. Every canonical column carries one for every provider in
`ORIGIN_GATE_ENROLLED_PROVIDERS`; an unenrolled provider is explicitly outside origin
certification rather than treated as compliant. Missing declarations or rows, extra rows,
absent native fields, conversion disagreements, invalid authored identity, contradicted
constants, unevidenced claims, and non-unknown values under `NotPublished` each fail the
build rather than shipping.
_Avoid_: mapping, provenance (which names the receipt travelling with a result, not the
per-column declaration), nullable

**Authored**:
The [[origin]] used only for canonical `provider_id`, which RivRetrieve owns rather than
copies from a source. Its exact value and every emitted row must equal the provider
identity supplied to the origin gate. It cannot stand in for source [[evidence]] on any
other column.
_Avoid_: hard-coded, field


**Withheld**:
A catalogue fact or row RivRetrieve does not expose because its acquisition record is
not established. It records our evidence gap, not a claim that the source publishes
nothing. A [[catalogue absence]] carries the recorded reason; an [[origin]] may retain
the `unknown` carrier marker without turning this gap into source silence.
_Avoid_: native-only (the retired origin name), not published (a different claim), rejected

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
carried alongside the value, and never a reason to discard the rows that did arrive. The
[[engine]] isolates each requested series at its one source-call boundary: a 404 is a
`warning`, while timeout, retry exhaustion, terminal sender failure, refused redirect,
credential rejection, and every other non-success HTTP status are `error` issues for that
series. Other series still run, and an all-failed request is an empty five-column frame
whose issues state why. An exception is the other thing entirely — a violation of the
contract between [[stage]]s, such as a parse handing back a frame with the wrong columns,
where there is no result worth assembling. Severity is `info | warning | error`; `info`
records what merely deserves saying, like a unit having been converted, and never activates
the caller's issue policy.
_Avoid_: error, warning, failure (each names one severity, not the category)

### Structure

**Engine**:
The shared core every provider sits on. It owns the contracts between stages and
performs the [[stage]]s that are the same for everyone. Its call of a provider's fetch
stage for one requested series is the observation pipeline's sole failure-isolation point:
a source failure becomes an [[issue]] there and cannot cancel independent series.
_Avoid_: core, framework, base

**Provider**:
An adapter over the [[engine]] for one national source. It contributes only what is
true about that source. An HTTP provider contributes `fetch.py`, `parse.py`, and
`config.py`; a bulk provider contributes `config.py` and `bulk.py`.
_Avoid_: source, backend, plugin

**Stage**:
One of fetch, parse, convert, and assemble. A live source retrieval passes through all
four. Held rows from either kind of [[store]] pass through convert and assemble without
provider fetch or parse; a mixed retrieval merges held and newly parsed rows before
convert. A bulk retrieval uses only that store path. A provider file is named for a stage
only when the provider writes code for that stage, so convert and assemble have no
provider file.
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
[[engine]] needs to make that source usable: where its packaged catalogue sits, which
[[provider-kind]] it is, and the names of any credential variables observation access
requires. A header-authenticated provider also declares the header name and exact source
origin without carrying a credential value. A credential-exchange provider instead
declares the exchange specification and its input header bindings; public retrieval
and maintainer recording compose the shared exchange transport from those facts. It is the only file a new source must write
beyond its stage code, and it is read once, at registration. Everything else a provider used to state
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
calendar each station's own source publishes. `start` is always stated by the caller.
When `end` is omitted, it is the caller machine's local calendar date expanded to that
bare date's last instant; provenance records this actual endpoint. A stated future end is
kept unchanged and carries one `info` [[issue]] saying it extends past the caller's local
date. The engine never clips it by assuming what "today" means at a station. The window
is never an absolute interval on the world's timeline: asking for one day across two
stations in different zones asks each gauge for its own day, not for one shared 24 hours. An endpoint carrying a zone is
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

**Catalogue descriptor**:
The Croissant 1.0 JSON-LD description shipped beside each [[provider]]'s four canonical
catalogue tables and five normalized evidence relations, read offline by
`describe(provider)`. The same reproducible build derives it from the tables,
[[origin]] declarations, and acquisition evidence. It identifies files by digest,
declares typed extraction and exact evidence joins, carries established [[license]]
and [[citation]] words verbatim, and records each [[catalogue absence]]. Individual
fact lineage is resolved explicitly from the local evidence relations, not repeated
as a national graph inside the descriptor. Its version and publication date are the
catalogue's recorded date, when established; its schemaVersion separately identifies
the versioned evidence profile.
_Avoid_: data card (broader than this catalogue contract), observation descriptor

**Catalogue absence**:
A deliberate lack of catalogue facts, expressed by the descriptor's sole extension
property `rr:absence`. A field's extraction source locates its packaged column, even
when an absence explains why the source fact is unavailable. The `not_published`
kind names source silence with an [[evidence]] link; the `withheld` kind names our
acquisition gap with its recorded reason. At record-set grain, withheld rows carry their
count rather than a list of identifiers. An absent value alone establishes neither kind.
The `rr:` namespace is
`https://github.com/RivRetrieve/RivRetrieve/blob/main/docs/catalogue-absence.md#`.
_Avoid_: null reason (a null alone is insufficient), missingness (conflates the two kinds)

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
The user's local observations for reuse on their own machine, populated in two ways:
a bulk provider's national dataset is compiled by an explicit `download()`, and a live
provider's parse output accumulates when retrieval requests `reuse` or `refresh`.
Both use one root, one [[store]] format family, and one shared reader. Live retrieval
bypasses the cache by default; reuse serves held [[coverage]] and fetches its remainder,
while refresh replaces the requested interval with the source's current answer.
`cache_status` reports either kind and `clear_cache` removes it only when asked.
_Avoid_: user cache (the retired separate lifecycle), archive, our cache

**Archive**:
A collection of retrieved river data assembled in order to publish or redistribute it.
RivRetrieve cannot ship one, because we do not hold redistribution rights to the sources.
The distinction from a [[cache]] is about distribution rights rather than storage:
a user keeping retrieved data on their own disk for their own reuse is not publishing it.
_Avoid_: cache, bundled dataset

**Store**:
Native observations at rest in RivRetrieve's own layout, together with the [[manifest]]
describing them. A [[cache]] holds a compiled store or an accumulated store. Compiled
stores use revision `2` and retain the source columns declared by [[compile]]; accumulated
stores use revision `4` and hold live parse output with [[coverage]]. Both hold native
values and native wall-clock timestamps. The shared reader supplies the same convert
[[stage]] for unit conversion and clipping, so a cached value is never converted twice.
The format is authored by RivRetrieve and versioned; an unrecognised revision is refused
before any observation file is opened, with its path and the explicit recovery action.
_Avoid_: database, local format

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
What a [[store]] says about a published observation: a value, a published null, or a
published blank. Absence of a row represents no published record. Compiled stores retain
all three published states because [[compile]] sees the source before deleting its
[[publisher-artifact]]. Accumulated stores retain values and nulls only: live parse output
has already collapsed blanks into nulls and the store cannot reconstruct the distinction.
For an accumulated store, [[coverage]] distinguishes an interval never retrieved from an
interval whose source answer contained no records.
_Avoid_: null handling, missing value, sentinel

**Source vintage**:
Which release of a bulk source a [[store]] was compiled from, as the source itself dates
it, recorded in the [[manifest]] and travelling in provenance on every result the store
answers. An accumulated store has no bulk release: retrieval instants on its [[coverage]]
provide the corresponding traceability, and each served interval carries its own instant.
Both are date stamps rather than verdicts. RivRetrieve computes no freshness threshold,
age field, or expiry; a caller wanting current source values explicitly refreshes them.
_Avoid_: stale, freshness, age, cache expiry

**Coverage**:
A series and closed native wall-clock interval successfully retrieved from its source,
paired with the UTC instant of retrieval. It records that the source was asked, not that
observations exist throughout the interval; a successful empty answer is covered too.
An accumulated [[store]] uses coverage to serve held intervals and fetch only the remainder.
Retrieval instants travel with served intervals in provenance without a freshness verdict.
_Avoid_: published record (a source-stated envelope, not a record of retrieval), continuity

**Manifest**:
The machine-readable record beside a [[store]], stating its format version and build
instant. For a compiled store it identifies the [[publisher-artifact]] and [[source-vintage]];
for an accumulated store it records each series' [[coverage]] and retrieval instants.
Both record partition row counts. A reader validates it before scanning observations,
so an incompatible or malformed store is refused and every served value remains traceable.
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
