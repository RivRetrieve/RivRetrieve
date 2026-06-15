# RivRetrieve redesign review: necessary complexity

## How to read this document

We agreed on a way of working. I built the harness. I ported one provider as a
proof of concept and wrote down the pain points. Thiago then ported twelve more.
We now have thirteen providers. That was the plan: build enough before we judge
the design, so that we are reflecting on evidence rather than on a guess.

This document is that reflection. The team has asked for a simpler codebase, and
I agree with the goal. But "simpler" is not free. RivRetrieve makes promises to
its users, and some of the complexity in the code exists to keep those promises.
The question worth asking is therefore:

> **Given what RivRetrieve promises, what complexity is irreducible, and what is
> complexity we added before we had the evidence to know better?**

So the structure of this document is deliberate. It first states the promise,
because every later judgement depends on it. Then, for each part of the system,
it asks the same two questions: what does the promise force us to keep, and what
can we remove without breaking it. Opinions are mine and are marked as
recommendations. Questions I do not think I should decide alone are marked as
open for the team.

This is a companion to `provider-redesign.md`. That document proposed the shape
of the package. This one revisits it with thirteen providers in hand.

## 1. The promise

Everything below depends on one decision, so I want it stated plainly and put to
the team before anything else.

**Open question for the team.** *What is the single promise RivRetrieve cannot
break?* My answer, and the assumption the rest of this document is built on:

> RivRetrieve gives you **faithful, traceable access** to river data, presented
> through **one consistent shape** across every provider.

Two halves. *Faithful and traceable* means a user can trust a number and follow
it back to its source: the value is the source's value, correctly converted,
with a record of where it came from and what was done to it. *One consistent
shape* means that once you have learned how to read data from one provider, you
can read it from all of them: the same columns, the same units, the same time
representation.

These two halves pull in different directions, and that tension is the source of
most of the complexity in the codebase. Faithfulness wants to preserve every
provider's quirks; consistency wants to erase them. The rest of this document is
mostly about drawing that line carefully: harmonise enough to keep the second
promise, preserve enough to keep the first, and treat everything else as
removable.

If the team prefers a different promise, much of what follows should change. That
is why this is the first question.

## 2. Where harmonisation stops

If "one consistent shape" has no boundary, it becomes an infinite obligation:
every provider quirk turns into something we are expected to smooth over. So the
boundary has to be explicit. The rule I propose is short:

> **We harmonise identity and physics. We never harmonise judgement.**

Identity and physics are objective. A discharge of 35,400 cubic feet per second
is the same physical quantity as 1,002 cubic metres per second; a timestamp in
one timezone names the same instant as in another. Converting these is not
interpretation, so we do it, and the consistency promise depends on it. What we
harmonise:

- the column shape of the data,
- units (discharge to m³/s, stage to m),
- time (everything to UTC),
- product identity, through a shared vocabulary, so that `discharge_daily_mean`
  means the same kind of thing in Brazil and in Norway.

Judgement is not objective. A quality flag of "A" means different things at
different agencies. Whether two gauges near a border are "the same station" is a
modelling choice. Which river a gauge sits on can be a naming dispute. We do not
adjudicate these. What we deliberately do **not** harmonise:

- quality and QC codes (they stay exactly as the provider gave them),
- station identity across providers (a border gauge listed by two agencies is
  two records; we never merge),
- river and basin naming semantics.

This line is also the simplicity lever. A large share of the per-provider code in
the current implementation exists because this boundary was never written down,
so each port invented its own partial harmonisation. With the rule stated, that
work has a clear home or no home at all.

**Note on v2.** Whether a future version should offer a harmonised quality flag
(for example a simple good/suspect/missing tri-state) is a real question, but it
is out of scope here. We have not planned it, and v1 should not pretend to.

## 3. The shape of the code

Currently, to port a new provider to the design we have, an implementer must
provide seven functions: `info`, `products`, `stations`, `station_products`,
`observations`, `row_annotation_schema`, and `series_annotation_schema`. In
practice these end up spread across seven or more files per provider (`module.py`,
`retrieval.py`, `parser.py`, `transform.py`, `metadata.py`, `issue_codes.py`,
`observation_client.py`). As Freddy pointed out, this can feel confusing: with that
many files it is not obvious where the core logic lives, and the main entry point
is unclear.

So I suggest we rethink this. The workflow every provider goes through has four
stages: `fetch`, `parse`, `convert`, `assemble`. A provider writes a small file for
each of the first three (`fetch.py`, `parse.py`, `convert.py`) and the engine owns
the fourth, so there is no per-provider assemble file. All of it is backed by a
shared engine. The stage names are the workflow, so they are also the map: a reader
knows what each file is for and where to start.

By "engine" I mean the shared RivRetrieve core that every provider sits on top of,
living in one place such as `src/rivretrieve/_engine/`. It covers two things at
once. First, the shared implementation of everything that is the same for every
provider: unit conversion, timezone handling, UTC clipping, de-duplication,
provenance, issues, raw-payload handling, and result assembly. Second, the
contracts that define what a provider must hand back at each step. A
provider is an adapter around this engine: it contributes the parts that are
genuinely specific to its source and inherits everything else. The whole point of
the redesign is to make the engine the single home of the shared logic, so a reader
asking "where does the real work happen" has one answer, and a reader asking "what
does Norway do differently" has only a provider's three small files to read.

### 3.1 A pipeline of four stages

Every provider, no matter how different its source, does the same four things in
the same order:

1. **fetch**: get the raw bytes from the source.
2. **parse**: turn those bytes into rows (a timestamp and a number).
3. **convert**: turn the rows into the canonical form (UTC, canonical units),
   and clip to the requested window.
4. **assemble**: package the result handed to the user.

Today's code is hard to inspect because the files are organised by processing
step, while a reader thinks by provider: "show me everything Norway does." To
answer that question you have to open many files and gather the Norway pieces
scattered across all of them. The same organisation hides duplication: when the
same window-splitting helper lives inside five different files, nobody notices it
is the same function.

### 3.2 The engine owns the contracts

I propose treating these four stages as a pipeline connected by **fixed
contracts**. The engine owns the contracts and the two stages that are the same
for everyone. Each provider is an *adapter* that satisfies the contracts for its
source.

That last sentence is the whole idea behind how the code is organised, so I will
say it again and put it in bold this time: **each provider is an adapter that
satisfies the contracts for its source.** Almost every structural simplification in
this document, the files we delete, the helpers we move into the engine, the
shrinking of a provider to three small files, is a consequence of that one sentence.
(The other big simplifications, dropping the annotation tables, banning
aggregation, the catalogue tiers, come from the promise in section 1 and the
harmonisation boundary in section 2, not from this. Three foundations, not one.)
Good, I said it twice. We can move on.

The contracts are the real specification of the library, and there are only a
handful:

```text
user's request   →  a normalised request (validated, dates normalised)
fetch returns    →  raw payloads, tagged with which (station, product, window) they are
parse returns    →  rows: station_id | product_id | time_raw | value_raw   (still native units, still naive time)
convert returns  →  canonical rows: time | station_id | product_id | value   (UTC, canonical units, clipped)
assemble returns →  the result object (data + provenance + issues + raw)
```

**The convert and assemble logic is shared across every provider.** This follows
from what the first two steps do. By the time parse finishes, every provider, no
matter how different its source, has produced the same thing: rows of a timestamp
and a number. The only differences left are which timezone that timestamp is in and
which units that number is in. From there, convert and assemble are pure mechanics:
shift to UTC, multiply by a unit factor, clip to the window, package the result. The
only thing that varies is data (a timezone, a unit), not behaviour, so the provider
declares those facts and the engine does the work.

That is what makes units, UTC, clipping, and provenance impossible to get subtly
different from one provider to the next: there is only one place each of them
happens. To add a provider, you satisfy the contracts; you do not touch the engine.

### 3.3 What is genuinely per-provider, and what is not

With thirteen providers as evidence, the split is clear. Harmonisation is
strongest at the end of the pipeline and weakest at the start.

- **assemble** is entirely the engine. Building the result object, sorting,
  attaching the receipt, this was ~95% identical across the thirteen, and the
  remainder was nothing a provider needs to vary. So there is no per-provider
  assemble file at all; the engine assembles.
- **convert** is the engine plus a small typed declaration. The engine ships a
  `ConvertConfig` dataclass and a provider's `convert.py` does nothing but fill it
  in. It declares three things: the source timezone (a default zone, which the
  catalogue overrides per station for providers like USGS and Canada that span
  several zones), the source units per product (chosen from a `Unit` enum the engine
  owns, so the engine knows the conversion factor and the canonical target), and the
  time semantics per product (whether a value is an instant or a daily-anchored
  value). The engine performs the conversion; `convert.py` is that declaration, not
  logic.
- **parse** is where the genuine, irreducible mess lives, and that is expected:
  the raw bytes arrive in wildly different shapes (nested JSON, Excel, an HTML
  page, a CSV with foreign-language marker lines, an encoding that changed in
  2024). The engine offers helpers for the common formats; a provider writes a
  small parse function only when its format demands it.
- **fetch** is the least shared, and we should not pretend otherwise. The HTTP
  call itself was 100% identical across the eleven live providers, that is real
  duplication a shared client removes. But the *flow* (how many endpoints, auth,
  pagination, window sizes) is genuinely per-provider. So fetch is a small set of
  shared tools plus a short per-provider function. What is standardised is fetch's
  two edges (the request it receives, the tagged payloads it returns), not its
  middle. Between those edges, the code is free, which is what lets an exotic
  source (a bulk download, an object store) write whatever it needs.

So a provider's real code lives in two files: `fetch.py` (its endpoints, auth,
windowing, or bulk download) and `parse.py` (decoding its format). A third file,
`convert.py`, is a short typed declaration rather than code. The fourth stage,
assemble, has no provider file at all, because the engine does it. So the workflow
is four stages but a provider authors three files: two of code and one of
configuration. They are uniform across every provider, which is what makes them
inspectable: the structure is identical everywhere, and the names say what each file
holds. The core logic lives in the engine. The rule for what goes in a provider:
**a provider's files contain only what is true about that provider; anything the
engine could do generically does not belong there.**

### 3.4 Why small Python files, and not a configuration form

It is tempting to push this further and make a provider pure configuration, a
form to fill in, no code. I recommend against it. The irreducible part of parsing
(Excel, HTML, the 2024 encoding change, foreign-language marker lines) cannot be
expressed as configuration. If we forbid code in a provider, those cases need
escape hatches, and the moment we add escape hatches the "configuration" has
quietly become a second-rate programming language. Small honest Python files are
simpler than a form pretending to be code.

### 3.5 The file layout

**Recommendation.** The engine holds the shared logic for all four stages. A
provider has three files, named for the three stages where it has something to
declare (fetch, parse, convert); the fourth stage, assemble, is entirely the
engine's. Every provider looks identical and the entry point is always obvious.

```text
src/rivretrieve/_engine/
    fetch.py        # http client, retries, windowing, bulk-cache machinery
    parse.py        # helpers for the common formats (json, csv)
    convert.py      # units, timezone, window clipping
    assemble.py     # builds the result object
    contracts.py    # ProviderConfig, ConvertConfig, CacheConfig, Unit enum
    ...
src/rivretrieve/providers/no_nve/
    fetch.py            # how Norway gets its bytes: endpoint, auth, windowing
    parse.py            # how Norway decodes its format into rows
    convert.py          # Norway's ConvertConfig: timezone, units, time semantics
    catalogue/          # packaged catalogue artefacts (see Section 6)
    generate_catalogue.py   # maintainer-only, runs live, not imported at runtime
```

The config types are the contract made concrete. The engine ships them; a provider
fills them in. `convert.py` is the whole of one provider's conversion declaration:

```python
from rivretrieve._engine import ConvertConfig, Unit

CONFIG = ConvertConfig(
    timezone="Europe/Oslo",                       # default; catalogue overrides per station
    units={"discharge": Unit.M3_S, "stage": Unit.M},
    time_semantics={"discharge_daily_mean": "daily"},
)
```

A top-level `ProviderConfig` holds the per-stage configs (the `ConvertConfig` above,
and a `CacheConfig` only for bulk providers), so each stage's contract is its own
type but a provider assembles one object.

A reader who asks "where is the core logic" has one answer: the engine. A reader
who asks "what does Norway do" opens three files whose names already say what each
one holds.

## 4. What we should remove

These are the places where, with the evidence in front of us, I think we built
more than the promise requires.

### 4.1 The per-observation annotation system

The current result object carries, alongside the data, two open-ended annotation
tables, one per observation, one per series, into which each provider writes
provider-specific fields. This is the single largest piece of removable
complexity, and the thirteen providers are the evidence: across all of them, only
three per-row and five per-series annotation *concepts* are universal. Everything
else is either a value that is constant for the whole series (so it does not
belong on every row), or a debugging breadcrumb, or the same concept wearing a
different field name in each provider (`provider_endpoint` versus
`provider_endpoints`; `requested_windows` versus `requested_years` versus
`query_years`). No two providers emit the same set.

**Recommendation.** Remove the open annotation tables. The current
`ObservationResult` already carries `provenance`, `issues`, and `raw` alongside the
two annotation tables, so this deletes a redundant older mechanism rather than
adding a new one. The faithfulness promise does not require the annotation tables;
it requires that the relevant facts be *recoverable*, which the smaller fixed
structure already provides:

- **provenance**: the receipt for the request: which provider, which
  endpoint(s), retrieval time, the native unit, and the conversion applied. One
  fixed shape for all providers.
- **issues**: structured warnings and anomalies (see Section 9). A shared
  vocabulary, not thirteen private ones.
- **raw**: the untouched provider payload, kept when practical.

Nothing traceable is lost. It is simply stored once, in a fixed shape, instead of
per-row in thirteen bespoke shapes.

### 4.2 No quality-flag column

A natural next step would be to promote the provider's quality code to a real
column called `quality_flag`. I recommend against it, on the rule from Section 2:
a column named `quality_flag` implies a shared meaning that does not exist
("A" is not the same judgement at two agencies). The quality code stays in `raw`,
where an interested user can read it for what it actually is. We surface it; we do
not relabel it as if it were harmonised.

### 4.3 No aggregation

This one we confirmed in the meeting. Two providers currently compute daily values
by averaging sub-daily data the source did not publish as daily. Averaging is
analysis, and we are an interface to data, not an analyst of it.

**Decision (agreed).** RivRetrieve exposes the products the source publishes. It
never computes a product the source does not. The two affected providers should
drop their derived-daily products and expose the data at the granularity the
source actually serves. The clean test for a future contributor: *who did the
maths?* If the source did it, surface it; if we would have to, do not.

A consequence: the product schema's `derived` and `derivation_method` fields were
built to support exactly the derivation we are now banning. Since we never derive,
and we usually cannot reliably know whether the *source* derived a value, these
fields are speculative.

**Recommendation.** Remove `derived` and `derivation_method`. The information a
user actually needs ("is this a daily mean or an instantaneous reading") is
already carried by `statistic` and `frequency`.

## 5. The data a user gets

### 5.1 The observation table

**Recommendation.** Keep the canonical table minimal:

```text
time | station_id | product_id | value
```

`value` is always canonical (m³/s, m) and `time` is always UTC. Native values,
quality codes, and original field names live in `raw`; the conversion is recorded
in `provenance`. This keeps the table that most users touch clean, while keeping
everything faithful and recoverable.

### 5.2 Asking for a time window

A user asks for a date range. We have to decide what the dates *mean*.

**Recommendation.** `start` and `end` are interpreted in UTC by default, and the
output `time` is always UTC. So a request for "12 December to 16 December" is the
UTC window, and the returned timestamps are UTC. This is the only globally
well-defined choice: "provider-local" is undefined for a country spanning several
timezones (the United States spans six), and UTC-in/UTC-out is reproducible across
providers.

Because thinking in UTC is not always what a hydrologist wants, we expose a simple
flag rather than asking users to construct timezone-aware objects:

```python
p.observations(..., start="2024-12-12", end="2024-12-16")                    # default: UTC
p.observations(..., start="2024-12-12", end="2024-12-16", time_zone="local") # the station's own local days
```

- `time_zone="utc"` (default): the dates mean UTC.
- `time_zone="local"`: the dates mean the station's own local calendar days,
  which we look up. For a provider spanning several zones, "local" is each
  station's own zone.

The output stays UTC in both cases; the flag only changes how the input is read.

**Recommendation on boundaries.** The window is closed, `[start, end]`, both ends
included. This matches the plain reading of "12 to 16".

**Recommendation on daily values.** A daily value describes a whole calendar day in
the station's local time, so it does not correspond to a single measurement moment.
To keep the `time` column a column of real UTC instants (never a mix of plain dates
and datetimes), we store a daily value at the UTC instant when that local day began.

For example, South Africa is UTC+2. The daily value for `2024-01-10` is the value
for the local South African day that starts at `2024-01-10 00:00` local time, which
is `2024-01-09 22:00 UTC`. So the stored `time` is `2024-01-09 22:00:00Z`. The UTC
date can therefore look like the previous calendar day. That is not an error: it is
the real UTC instant at which the local day begins. A user who wants the local date
back asks with `time_zone="local"`, or converts the UTC timestamp to the station's
zone.

### 5.3 Correct boundaries, in one place

The meeting flagged a real bug: when results are clipped to the requested window
in the provider's local time *before* conversion to UTC, hourly data near the
boundary comes out wrong, with strange values or gaps (this was seen with Norway
and South Africa). The cause is comparing timestamps in two different
representations.

This bug class disappears structurally under the pipeline contract, because there
is exactly one place that does timezone work and clipping:

- **parse never does timezone or unit maths.** It only decodes the format.
- **convert owns all of it**, and clipping is its *last* step, performed on UTC
  timestamps.
- **fetch over-fetches.** When it translates the requested window into the
  source's own terms, it pads outward (a full day each side is a safe margin), so
  no boundary row is missing before the precise clip trims the excess. Where fetch
  splits a request into chunks, the chunks overlap slightly and the engine
  de-duplicates the seams, so chunk boundaries never create a gap or a duplicate.

The checks the meeting asked for then become concrete: a cheap runtime invariant
(after clipping, every timestamp lies within the window, or it is an engine bug),
and a per-provider regression test that requests an hourly window crossing local
midnight and asserts the boundary rows are present and correctly placed. The
important point for this document: this is necessary complexity, and centralising
`convert` is what lets us pay for it once instead of thirteen times.

## 6. The catalogue a user gets

The catalogue is the offline description of what exists, shipped with the library.
`provider-redesign.md` already established the two-tier idea, the catalogue is the
contract, the response is the receipt, and that the catalogue is packaged, not
fetched live. Here I refine what it promises.

### 6.1 Three tiers of guarantee

A finding worth stating bluntly: several columns the meeting asked to "add" already
exist in the schema, `country`, `start_date`, `end_date`, they are simply not
filled in for every provider. A catalogue that declares a column it does not fill
is itself a small breach of the faithfulness promise. So the real question is not
which columns exist, but what each column *guarantees*. I propose three explicit
tiers.

- **Guaranteed**: never null, for every station of every provider, enforced as a
  check when the catalogue is built: `provider_id`, `station_id`, `name`,
  `latitude`, `longitude`, `country`. The promise: every gauge we list, you can
  find and locate. Following the convention used by datasets like EStreams,
  `country` is an ISO country code; sub-national region, where it exists, is a
  best-effort or native field, not a second guaranteed column.
- **Best-effort**: nullable, filled when the source provides it, *never*
  fabricated. A null means "we genuinely do not have this", not "zero":
  `elevation_m`, `drainage_area_km2`, `river_name`, `start_date`, `end_date`,
  `status` (active or closed).
- **Generated convenience**: `observed_properties`, a short list of what is
  measured at a station (for example `["discharge", "stage"]`), generated from the
  station-product catalogue so it cannot drift. This answers the meeting's request
  for a column that tells a user, at a glance, what they can get at a station. The
  authoritative per-product detail still lives in the station-product table.

### 6.2 Start and end dates: the pros and cons

The meeting asked for the pros and cons of storing measurement start and end dates,
so I will state them rather than just decide.

The pro is real: knowing a station's period of record is genuinely useful for
discovery and filtering, and we should try hard to populate it.

The con is specific to `end_date`. A station's `start_date` is stable, its first
observation does not change. But the `end_date` of an *active* station advances
every day, so any fixed value shipped in a packaged catalogue is stale the moment
it ships. Storing it as if it were current would be a faithfulness breach by
construction.

**Recommendation.** Pursue both dates hard, keep them best-effort (some sources
genuinely do not expose them), and define `end_date` in the packaged catalogue
honestly as *"the last observation as of the catalogue version"*, a snapshot, not
a live claim. A user who needs the true current end uses the live path (6.4). The
`status` field (active or closed) carries the real-time-versus-historical signal
the meeting also asked for: a closed station's `end_date` is a fixed truth; an
active station's is a snapshot.

### 6.3 License, citation, and source links

The meeting was emphatic that license is one of the most important things we
surface, and it asked for citation as well. Today there is no structured license
field; only one provider records it, inside its opaque metadata. What a user most
often needs to know about a license is **whether the data may be redistributed**,
and that is something they will want to filter providers on. A bare URL cannot be
filtered, so I propose recording a license *status* alongside the link.

**Recommendation.** Add the following provider-level fields to the provider
information. They describe a data source as a whole, which is why I propose them at
the provider level rather than copied onto every station row.

- `license`: a short, structured status (for example `open`, `attribution`,
  `restricted`), **guaranteed**. This is the filterable fact: it lets a user ask
  "which providers may I redistribute?" before building on the data.
- `license_url`: the link to the actual terms, **guaranteed**. We should not ask
  scientists to use data whose license we cannot show.
- `citation`: how to credit the source (a citation string or DOI), **best-effort
  but high-effort**; not every agency offers one.
- `notes`: a short free-text field for provider caveats (for example "real-time
  values lag by a few days", "file format changed in 2024", "redistribution
  restricted"). This is the natural home for the per-provider caveats the generated
  docs page (Section 10) will surface, and it costs almost nothing. It is the one
  piece of free-text we keep, deliberately at the provider level and not per
  observation, unlike the open annotation tables we removed in Section 4.1.
- source links, `website`, and where they differ, a data URL and a metadata URL,
  **best-effort**. Useful provenance back to the source at low cost.

**Open question for the team.** Thiago's note leans towards surfacing license (and
citation) in the stored station columns as well. My recommendation is to keep them
at the provider level, stamping the same license onto ten thousand identical
station rows is redundant, and it is one call away on the provider. But this is a
genuine preference question, so I am flagging it rather than deciding it.

### 6.4 Native and canonical, packaged and live

Two independent choices, both raised in the meeting.

*How the data is represented.* We are a tunnel, so the source's own column names
must be available, not only our renamed canonical ones. The clean way to honour
this is to **store the native data and derive the canonical columns from it**, the
canonical table is then a renamed view over the stored native data, not a separate
dataset.

```python
rr.provider("no_nve").stations()                     # default: canonical columns
rr.provider("no_nve").stations(metadata="native")    # the source's original column names
```

(The word "native" is just terminology; "raw" or "source" would do. What matters
is that the original is a first-class table, not buried in a blob.)

*Where the data comes from.* Packaged is the default and the guarantee, it works
offline, it is fast, it is reproducible. Live is opt-in and explicitly best-effort:
it gives the current truth (fresh `end_date`, newly added stations) but it is slow
and not every provider supports it.

```python
rr.provider("no_nve").stations(source="packaged")    # default
rr.provider("no_nve").stations(source="live")         # current truth, may be slow
```

**Recommendation on the live path.** A live fetch is allowed to be slow, but it
must never appear to hang. It must signal that it is working and time out rather
than freeze silently. (This is the South Korea case from the meeting: a slow query
that looks dead loses the user's trust.) I am deliberately not stating how slow any
provider is, because we do not know.

### 6.5 What this looks like to a user

Putting the tiers together, `rr.provider("no_nve").stations()` returns something
like this (values illustrative):

```text
provider_id  station_id  name      latitude  longitude  country  river_name  ...  start_date  end_date    status   observed_properties
no_nve       2.32.0      Bjørnå    60.12     6.45       NO       Bjørnå      ...  1985-03-01  2026-06-07  active   ["discharge","stage"]
no_nve       12.209.0    Lillestrøm 59.95    11.05      NO       Nitelva     ...  1971-01-01  2003-09-30  closed   ["stage"]
```

The guaranteed columns are always present; the best-effort ones may be null; the
active stations show an `end_date` that is a snapshot as of the catalogue version,
while the closed station's is fixed. The same clean shape holds for every provider.

## 7. Bulk providers

Three providers (Canada, Poland, and Austria when it arrives) have no "fetch one
station" option. The source only offers the whole national dataset as one large
download. This only changes the *fetch* stage; parse, convert, and assemble are
unchanged.

### 7.1 Consent

RivRetrieve is a library, not an application, so there is no reliable place to ask
"download a gigabyte? yes/no", it might run in a notebook, a script, or a server.

**Recommendation.** A bulk provider does not download silently on first use. With
no local cache, an observation request fails with a clear, actionable message
telling the user the size and what to run. The expensive step only happens when
the user explicitly asks for it (by calling the download/refresh method, or
passing an explicit consent flag for non-interactive scripts). This follows the
general rule from Section 9: never do something expensive silently.

### 7.2 A uniform cache interface

The cache-management methods the meeting sketched belong only on bulk providers,
since a cache status on a live-API provider is meaningless, but they should be
*identical* across all bulk providers:

```python
ca = rr.provider("ca_eccc")
ca.cache_status()    # exists, path, age, size, stale
ca.refresh_cache()   # force re-download, returns any issues
```

The provider's information already tells a user whether it is a bulk provider, so
the methods appear where they apply and nowhere else.

### 7.3 One cache format

Today the two bulk providers store their cache differently (one as a database, one
as a single columnar file), so they have two separate query paths. This is the
last piece of unshared bulk machinery.

**Recommendation (mine; open for the team).** Standardise the cache as one format
for all bulk providers: a hive-partitioned columnar store (Parquet), partitioned
by product and year, with rows sorted by station so that per-station reads prune
cheaply, plus a small manifest that records the format version, when it was built,
and the source vintage. Each bulk provider then contributes only a download step
and a small "compile this source into the standard cache" function; everything
after that, reading, querying, reporting cache status, is one shared
implementation.

I want to address the principled objection directly, because Thiago raised it and
I agree with the principle: *we are an interface to data and make no claim to treat
it perfectly.* Standardising the cache **format** does not violate this. It
re-encodes the same values into a better container, the way we already re-encode
the transport, and it changes no numbers. We already harmonise units,
names, and time; harmonising the storage layout is the same kind of act. The payoff
is that "bulk" stops being several different backends and becomes one engine. The
cache stores the *native* values; conversion happens on read, through the same
`convert` stage every other provider uses.

## 8. The public API surface

The meeting noted that the core provider API is standardised but the top-level and
provider-specific surfaces are not, and that some functions take a `provider_id`
argument while others do not. That inconsistency is structural, and one rule fixes
it.

> **The provider handle operates on one provider. The bare top-level functions
> operate across all providers, and exist only for discovery.**

- Everything you do to a single provider hangs off the handle:
  `provider.stations()`, `.products()`, `.observations()`, `.info()`, and (for
  bulk) the cache methods. The handle already knows its provider, so **no handle
  method ever takes a `provider_id` argument**.
- The bare functions are the cross-provider ones: `rr.providers()`,
  `rr.stations()`, `rr.products()`, `rr.map_stations()`, `rr.provider_info()`.
  They return the union across providers, so `provider_id` appears as a *column*,
  never as an argument.

```python
rr.providers(); rr.stations(); rr.map_stations()        # cross-provider discovery
p = rr.provider("usgs_nwis")                             # then everything hangs off the handle
p.info(); p.stations(); p.observations(stations=..., products=..., start=..., end=...)
```

**Recommendation.** This implies dropping the top-level `rr.observations(provider=...)`
wrapper. It is the one function that forces the `provider_id`-as-argument
inconsistency, and fetching observations is inherently single-provider. Losing the
one-liner is a small price for a rule a user (or an LLM) can hold in their head.
Redundant aliases (a separate `product_info` that equals `products`) should also
go, and the catalogue methods should share one keyword set (`source`, `on_issue`,
and where relevant `metadata`).

**Discovery filters.** The bare discovery functions take three filters and no more:
`providers`, `country`, and `bbox`. These map to guaranteed columns, and `bbox` is
the answer to the meeting's out-of-memory worry: it is pushed down to the catalogue
read so a regional query never loads the global table into memory. Anything richer
than these three, a user does on the returned table themselves; we should not grow
a query language. A `bbox` is `(west, south, east, north)`, the standard
geographic order, and must be documented with the cardinal names wherever it
appears.

With the annotation tables removed (4.1), the two annotation-schema methods on the
handle disappear as well.

## 9. Failure and validation

A promise worth stating in one line: **RivRetrieve never fails silently, and never
does something expensive silently.** Concretely:

- **Unknown station or product.** Requested IDs are checked against the catalogue
  *before* fetching. An unknown ID produces a clear, named warning and is skipped;
  valid IDs still return. This is important because the dangerous failure is
  silent: a mistyped station ID that returns "no data" looks exactly like a real
  station with no data, and the user wrongly concludes the gauge is empty. A named
  warning removes that trap. The existing `on_missing`/`on_issue` policy lets a
  user escalate this to an exception.
- **Dates.** `end` defaults to today, and a future `end` is clipped to today (with
  a note). `start` is required, we do not guess it, because guessing it can
  trigger a multi-decade or multi-gigabyte pull the user never asked for.
- **Source failure.** A network or server failure returns whatever partial data
  succeeded, with error-level issues describing what did not. We never return a
  half-result that looks complete.

## 10. Documentation

The meeting asked for documentation that is professional in the manner of
NeuralHydrology, and raised the idea of human-optimised and LLM-optimised docs. The
canonical scientific-Python stack is already settled by what NeuralHydrology and
scikit-learn use.

**Recommendation.** Mirror that stack: Sphinx, hosted on ReadTheDocs, with the API
reference auto-generated from NumPy-style docstrings, the same way NeuralHydrology
does it. Since we use `uv`, the docs dependencies sit in a `docs` group exactly as
in NeuralHydrology. For now, scope is small and API-first: an install page, one
concepts page (the promise, the canonical shape, the pipeline), the auto-generated
API reference, and a generated provider table. No tutorials yet.

On the human/LLM split, my recommendation is **not** to maintain two sets of docs;
they drift and double the work. Instead, one source with two renderings:

- Write the small amount of prose in Markdown (via MyST), which is both pleasant to
  author and what an LLM reads best.
- Generate the structured pages, the API reference, and the provider coverage
  table (license, citation, country, products) built from the provider information
  so it cannot drift from reality.
- Assemble an LLM entry point (a single flat `llms.txt`) from those same sources,
  rather than authoring it separately.

The LLM optimisation comes from disciplined docstrings and generated structured
artefacts, which serve humans and machines equally; the tool itself matters far
less.

## 11. Testing

The current tests were written by the agents that wrote the code, with no
direction on what or how to test. That, more than any single test, is the problem:
undirected tests tend to check mocked stand-ins rather than the real path, which
passes forever and proves little. The meeting also surfaced a disagreement worth
resolving: I argued we should only test that our own code is correct, while Thiago,
not trusting the providers, wanted to test those too.

These are not in conflict. They are two different activities, and the confusion is
calling both "testing".

> **A test answers "is our code correct?". A monitor answers "is the outside world
> still what we assumed?".**

- **Offline tests gate every commit.** They are deterministic and use no network.
  The engine (convert, clipping, units, timezones, assembly) is tested once,
  deeply, the payoff of the shared contract. Each provider tests only its fetch
  and parse, against a committed *real captured* response, never a hand-mocked
  stand-in.
- **A live conformance monitor runs on a schedule and only alerts.** It makes one
  small real request per provider and checks that the round-trip still works and
  the catalogue is not stale. Provider drift (the Poland 2024 format change is the
  example) opens an alert; it does not turn the build red, because we do not
  control thirteen foreign uptimes. This is the only mechanism that catches drift
  *before* a user reports it.

The two connect through a workflow that is also our regression-proof rule: when the
monitor fires, capture the new payload, add it as a fixture, write the failing test
that reproduces the break, then fix it.

**Recommendation.** Write this as a short testing policy in the design spec and in
`AGENTS.md`, so it actually binds the agents writing the next ports, the root
cause here is that no one told the test-writers what testing means for this
library. And, as table stakes for a canonical tool: stand up CI and re-enable the
type checker. There is currently neither, and that is the real gap.

## 12. Summary: what is necessary, and what we are cutting

The promise (Section 1) forces a specific and short list of necessary complexity:

- **Unit, time, and product-identity harmonisation**, plus the shared product
  vocabulary, without it, "one consistent shape" is not true.
- **One shared `convert` and `assemble`**, including window clipping done after
  conversion in UTC, with over-fetching, this is what makes correctness and
  consistency hold identically across providers, and it is where the boundary bug
  is paid for once.
- **A small, fixed receipt**: provenance, issues, raw, the minimum that makes a
  value traceable.
- **The two-tier catalogue** with explicit guaranteed/best-effort tiers, a
  structured license (including redistribution status) plus citation, and an honest
  snapshot `end_date`.
- **The bulk-download machinery** with consent and a uniform cache interface.
- **Faithful surfacing of the native data** alongside the canonical view.

And it lets us cut, without breaking anything:

- the open per-observation and per-series **annotation tables** (replaced by the
  fixed receipt),
- a harmonised **quality-flag column** (kept native, in `raw`),
- **aggregation** and the `derived`/`derivation_method` fields (we never derive),
- the **horizontal seven-file-per-provider** layout (replaced by one provider file
  plus the engine),
- the duplicated **HTTP, windowing, timezone, and unit code** across providers
  (moved into the engine),
- the redundant **top-level `observations` wrapper** and aliases.

The shape of the conclusion is the thing I want the team to take away: the
complexity we remove is the complexity that served no promise, and the complexity
we keep is the complexity the promise requires. Compactness is bought by being
clear about what we are for.

## 13. Open questions for the team

1. **The promise (Section 1).** Is "faithful, traceable access through one
   consistent shape" the promise we cannot break? Everything else depends on this.
2. **License and citation placement (6.3).** Provider-level only (my
   recommendation), or also surfaced in the stored station columns?
3. **The bulk cache format (7.3).** Do we adopt one standardised hive-partitioned
   Parquet cache across bulk providers? (My recommendation is yes.)
4. **The guaranteed tier (6.1).** Is the guaranteed, never-null set exactly
   `station_id, name, latitude, longitude, country` plus provider-level
   `license_url`? Should `start_date` be promoted into it, accepting that some
   providers cannot supply it?
