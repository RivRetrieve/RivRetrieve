# Context

Project-specific domain language for RivRetrieve. Glossary only.

## Language

### Core

**Unknown**:
A fact without an established value. Physical facts distinguish `source_silent` (the
source does not state it) from `not_established` (RivRetrieve has not established it).
Neither means zero, an empty answer, or a default. A known fact carries a value and evidence.
A license or citation not yet established is absent, not a claim of source silence.
_Avoid_: default, assumed

**Receipt**:
What a [[provider]]'s parse [[stage]] was handed, kept alongside the returned result so a
user can audit a value against what the source actually said, and only when the caller
asks for it ; unasked, the slot exists and is empty and no response bytes are reachable
from the result. It is bytes and stays bytes: sources answer in JSON, CSV, HTML
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
_Avoid_: raw, untouched payload (a store excerpt is authored by RivRetrieve), response, blob

**Native table**:
One [[provider]]'s station metadata in the source's own vocabulary: its column names,
its spellings, its units, its values unaltered. Every provider produces one, whatever
shape its source arrives in, and it is the single point where thirteen unlike transports
become one thing. The canonical station catalogue is built from it rather than beside
it, which is why the source's own columns are a table to be read rather than a blob to
be parsed.
_Avoid_: opaque metadata, raw table (collides with
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
_Avoid_: not published (a different claim), rejected

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
still retrievable. A bound is populated only where established by source evidence.
An absent bound does not establish source silence and is never used to prevent a fetch. The name carries `published` because a
bound RivRetrieve established by asking rather than by reading is a weaker and different claim
— bounded by how we asked — and would need its own column and its own [[origin]] form rather
than this one.
_Avoid_: start_date, end_date (bare, they invite an observed value into a published column),
period of record (does not say who established it), coverage (implies continuity)

**Issue**:
A source or data condition retained alongside a result, with severity
`info | warning | error`. Recoverable failures retain their identity and reason while
independent series can return rows. The caller's `on_issue` policy can warn, raise, or
ignore warning and error issues; informational issues do not activate it. Empty answers,
failed requests and published null values are distinct. An all-failed result has the
same ten-column observation schema as a successful result. Invalid internal stage output
raises a fatal contract error outside this policy.
_Avoid_: exception (a different control path), silent failure

**Source series**:
A concrete source identity at a station, with a source namespace, published identifier
when supplied, and evidence. `series_id` is RivRetrieve's key for that identity;
`variant` exposes an optional source-specific selector. Brazil ANA's Bruto (raw) and
Consistido (quality-checked) series remain separate. ANA performs that checking, not
RivRetrieve. Source-series identity is not a harmonised quality score.
_Avoid_: preferred series, quality tier

**Physical facts**:
Independently evidenced statements about quantity, source unit, frequency, statistic,
temporal support, day definition, timestamp anchor, time zone or vertical reference.
A `facts_id` identifies a segment of these facts within a [[source series]]. A daily
frequency does not establish a mean statistic or which hours the value covers. Temporal
support describes the measurement interval, not how often the agency updates its service.
_Avoid_: inferred product, update cadence

**Inventory**:
An acquired statement about source-series membership within a stated scope, access path
and optional window. It records evidence and completeness, not successful retrieval.
`complete`, `incomplete`, and `unresolved` describe that bounded claim. A static catalogue
does not establish all identities a response may publish.
_Avoid_: coverage, exhaustive census

**Retrieval outcome**:
The recorded result of asking for a series and window: `success`, `empty`, `failed`,
`unsupported`, `unresolved`, or `no_match`. A successful outcome identifies concrete
source-series facts. Other outcomes retain a reason, and can retain the requested
selector without pretending that it names a published series.
_Avoid_: null value, missing row

### Structure

**Engine**:
The shared core every provider uses. It owns stage contracts, request planning,
source-series selection, unit conversion, clipping and result assembly. Supported source
failures become [[issue]]s at their established isolation boundaries without cancelling
independent series. Invalid internal stage output remains fatal.
_Avoid_: framework, base

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
How a [[provider]] addresses a source: parameter code, endpoint, table, workbook,
column or field. Internal product routes select these access coordinates and window
rules. A route is not itself evidence of quantity, statistic, frequency or source-series
identity. Response and catalogue evidence establish those facts separately.
_Avoid_: physical classification, quality rank

**Catalogue-only**:
A [[provider]] registered without observation [[stage]]s. South Africa DWS is the
catalogue-only provider. Its packaged catalogue can be read, but observation retrieval
raises because that provider has no observation port. The other twelve providers support
observation retrieval through live access or compiled bulk stores.
_Avoid_: disabled, broken

**Provider declaration**:
The statement in a [[provider]] directory of its packaged catalogue, provider kind,
observation configuration and credential requirements. Header authentication declares
the header name and source origin without a credential value. Credential exchange
declares the exchange specification and input header bindings. Public retrieval and
maintainer recording compose transport from these declarations. Registration reads them;
lower-level operations receive resolved dependencies.
_Avoid_: credential storage, provider instance

**Provider kind**:
Which of exactly three shapes a [[provider]] takes, declared in its
[[provider-declaration]] and dispatched on by the [[engine]] rather than inferred from its
id: [[catalogue-only]], an HTTP source contributing fetch and parse [[stage]]s, or a bulk
source contributing a download and a [[compile]]. The set is closed. A source fitting none
of the three is an engine change argued once and applied to every provider, not a fourth
architecture a single provider invents — which is the distinction between adding a
provider, which touches one directory, and adding a kind of provider, which is a design
decision. Dispatch uses the declared kind rather than provider identity.
_Avoid_: provider type, capability, variant, strategy

**Selection**:
An immutable requested scope plus acquired source-series evidence, produced by `find`
and narrowed by `pick`. The scope holds physical filters and optional explicit variant
or series restrictions. It is not just a list of currently known members: an unrestricted
selection can admit matching source identities discovered in a response. Packaged
inventory is not an exhaustive current or historical census. An empty selection retains
its reason. `no_match` means established facts show nothing matches; `unresolved_inventory`
means the available evidence cannot establish whether the requested series is available.
_Avoid_: result (what `fetch` returns), frozen inventory

**Shows rather than decides**:
A capability may display source facts and unknowns without choosing a scientific
interpretation for the caller. Physical filters require established facts; matching
physical facts do not establish scientific interchangeability. Source alternatives
remain visible unless the caller restricts them explicitly.
_Avoid_: quality ranking, preferred variant

### Time

**Native time**:
A timestamp in the source's published wall-clock calendar. The returned observation
columns are `time`, `time_zone`, `station_id`, `product_id`, `series_id`, `facts_id`,
`quantity`, `source_unit`, `unit`, and `value`, in that order. `time` is naive and paired
with the source-established zone or `unknown`. A result can contain different zones,
source identities and physical-fact segments. Its converted values use `unit`; its
`source_unit` records the source spelling rather than the converted scale.
_Avoid_: inferred local time, UTC timestamp

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
placed against an established [[station-timezone]]. A station or series may lack that
evidence. Wall-clock windows make clipping possible for a station
whose zone is [[unknown]]: wall clock compares to wall clock without needing a zone on
either side. A caller wanting an absolute interval converts the returned [[native-time]]
afterwards.
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
by the [[engine]] from the [[window-granularity]] a provider-product declares. Some sources cannot answer an arbitrary window in one request. Granularity states
the source constraint; the engine performs the interval arithmetic.
_Avoid_: chunk, window split, decomposition (which names the act, not the piece)

**Window granularity**:
The declaration keyed by provider-product that tells the [[engine]] whether a
[[fetch-window]] is unsplit as an ISO instant or date pair, split by year, split by
year-month, split into N-year chunks, split into capped inclusive-date spans, split into fixed backward
inclusive-date spans, or has no
requested-window parameters. Drive selects one declaration for each requested `ProductId`
before planning the authoritative fetch window. It names source request boundaries;
post-hoc result filtering is not a granularity. Fixed backward spans each contain exactly
the declared number of whole dates, are disjoint and end at the final fetch date.
Only the earliest span may extend before the fetch start date, by fewer than that
number of days; convert still clips to the requested window.

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
bypasses the cache by default. Reuse serves held rows only when inventory evidence and
[[coverage]] satisfy the requested scope and interval. Otherwise it reacquires the full
requested scope and interval for that station and internal product route, not just the
uncovered dates. Refresh requests a current answer and replaces successful series
intervals; failures preserve held rows and coverage.
`cache_status` reports either kind and `clear_cache` removes it only when asked.
_Avoid_: archive, our cache

**Archive**:
A collection of retrieved river data assembled in order to publish or redistribute it.
RivRetrieve cannot ship one, because we do not hold redistribution rights to the sources.
The distinction from a [[cache]] is about distribution rights rather than storage:
a user keeping retrieved data on their own disk for their own reuse is not publishing it.
_Avoid_: cache, bundled dataset

**Store**:
Native observations at rest in RivRetrieve's own layout, together with the [[manifest]]
describing them. A [[cache]] holds a compiled store or an accumulated store. Compiled
stores use revision `5` and retain the source columns declared by [[compile]]; accumulated
stores use revision `7` and hold live parse output with [[coverage]]. Both hold native
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
source vintage and its checksum. These identify the compiled bytes but do not guarantee
that the publisher will serve the same release again.
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
A successfully retrieved concrete source series, physical-fact scope and closed native
wall-clock interval, linked to its successful outcome and retrieval instant when known.
It records that the source was asked, not that observations exist throughout the interval;
a successful empty answer is covered too. An accumulated [[store]] combines coverage
with inventory evidence to decide whether the requested scope can be served locally.
An incomplete request is reacquired for the full requested interval, not only its gaps.
Coverage for one identity or fact segment cannot
stand in for another. Failed outcomes remain separate and do not create coverage.
_Avoid_: inventory, published record, continuity

**Manifest**:
The machine-readable record beside a [[store]], stating its format version and build
instant. For a compiled store it identifies the [[publisher-artifact]] and [[source-vintage]];
for an accumulated store it records each series' [[coverage]] and retrieval instants.
Both record partition row counts, concrete source-series definitions, physical-fact
segments, scoped inventories, retrieval outcomes, issues and source-call provenance. A reader validates it before scanning observations,
so an incompatible or malformed store is refused and every served value remains traceable.
_Avoid_: metadata, header, index

### Proof

**Recording**:
A saved interaction with a real source: the exact request, response bytes, retrieval
instant and digest. Replay matches the request through the transport seam and refuses
requests for which no recording exists. A recording establishes what the source returned
at capture time, not present-day service availability. A [[receipt]] exposes bytes to a
caller; a recording supplies source evidence to a test.
_Avoid_: mock, stub, invented payload

**Invented payload**:
An author-created response used to exercise a structural or failure condition. It can
test software behavior but is not a [[recording]] and cannot establish a publisher's
physical meaning, values or availability. Tests must distinguish these controls from
real source evidence.
_Avoid_: source evidence, recording

**Boundary probe**:
A test of clipping against a [[recording]] with observations around a requested
boundary. Counts and first/last native time labels are checked directly against the
source bytes, including calendar and time-zone meaning where established.
_Avoid_: inferred timezone, computed source truth

**Independent expectation**:
An expected value grounded in source bytes and publisher definitions rather than the
implementation's own output. Exact receipt identity, source values, units and native
time labels provide independent checks of retrieval and conversion.
_Avoid_: implementation-as-oracle
