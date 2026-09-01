# Vision: the store is the only copy

Program: https://github.com/RivRetrieve/RivRetrieve/issues/6
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/12

## Goal / Why

Two of the thirteen providers publish no per-station access at all. Environment Canada
ships a national SQLite database of roughly a gigabyte; IMGW ships yearly archives of CSV.
Today each keeps its data in whatever shape its source happened to ship, so each needs its
own read, query and status implementation. `ca_eccc` queries HYDAT SQLite directly.
`pl_imgw` reads a single flat parquet whole-nation file into memory before filtering
(`pl_imgw/observation_client.py:255`) and is switched off entirely — asking it for
observations raises.

ADR 0002 already decided that anything RivRetrieve stores on disk uses one layout the
engine queries, and explicitly left the layout itself and the interface it is queried
through unspecified. That is this vision's body: specify the layout following the HFX
pattern — a normative document, a machine-readable manifest schema, and conformance
fixtures both valid and intentionally invalid — build the one shared reader, and prove it
by compiling two sources that agree about nothing into the same store.

Success changes four things. A bulk download is asked for by name and never arrives any
other way. Poland answers observations for the first time. Every returned value names the
source release it was compiled from. And a contributor adding a bulk provider — Austria is
expected — writes a download and a compile and inherits reading, querying and cache
reporting without implementing any of them, which was the entire payoff argued for in
ADR 0002 and is unrealised until a second source lives in the store.

The binding constraint that shapes everything else: the downloaded publisher artifact is
deleted once compiling succeeds (ADR 0021), so the store is the only surviving copy of
those observations and any omission at compile time is permanent.

## Scope — In

1. **The normative storage layout specification**, in this repository following the HFX
   pattern: a normative document, a machine-readable manifest schema, and conformance
   fixtures both valid and intentionally invalid, so a store is validated rather than
   assumed. Hive-partitioned parquet is the starting point from the review document's
   §7.3, not the conclusion; the partition scheme and the expression of predicate pushdown
   are settled during design against both sources.
2. **The value-state representation.** The layout distinguishes four things a source can
   say about one station-product-day: no record at all, a record whose value is null, a
   record whose value field is blank, and a record carrying a value. A typed numeric column
   collapses three of these into one, so the state is carried beside the value.
3. **The manifest**, recording the layout's format version, the compiler version, when the
   store was built, the source vintage as the source itself dates it, the URL and checksum
   of the publisher artifact compiled from, a fingerprint of the source schema it was
   compiled against, and per-partition row counts.
4. **The shared store reader**, implementing reading, querying and cache status once for
   every bulk provider, with predicate pushdown replacing `pl_imgw`'s eager whole-nation
   `read_parquet`. No provider code executes on a bulk retrieval path.
5. **Certified compilation.** Compile into a staging location; fail the compile on a source
   column that is unknown or has changed type rather than ignoring it; reconcile rows
   accepted against rows emitted per source unit; read the completed store back through the
   same shared reader a user query uses and compare it field for field against the native
   rows produced from the artifact, covering keys, duplicates, values, quality fields and
   value states. Only on success does the staged store atomically replace the previous one
   and the artifact get deleted.
6. **`ca_eccc` ported onto the store**, replacing HYDAT SQLite as the queried thing:
   `config.py` plus `bulk.py`, with `fetch.py` and `parse.py` deleted.
7. **`pl_imgw` ported onto the store**, replacing its flat parquet and making it answer
   observations for the first time: `config.py` plus `bulk.py`, retiring the private
   `ImgwCacheClient` and `parser.py` retrieval path.
8. **The consent gate and the bulk surface.** A retrieval with no local store returns an
   issue naming the exact command and downloads nothing. Three public functions are added —
   `download(provider)`, `cache_status(provider)`, `clear_cache(provider)` — taking the
   shipped surface from ten names to thirteen, available only on bulk providers.
9. **`raw` renamed to `receipts`**, with every entry declaring its authorship:
   `publisher_payload` for untouched bytes the source served, `store_excerpt` for bytes
   RivRetrieve encoded from rows read out of its own store, the latter carrying the store
   path, the executed query, the format version and the source vintage.
10. **Refusal on an unrecognised manifest.** A reader that does not recognise a store's
    manifest refuses it and names the rebuild; it never interprets it as best it can,
    never migrates in place, and never downloads anything on the user's behalf.
11. **Disk-peak refusal.** The space a compile requires is stated and checked before the
    download begins rather than discovered when it fails mid-compile.
12. **Documentation of the amendments**: ADR 0021, ADR 0022 and ADR 0023 moved from
    `Proposed` to `Accepted`, and ADR 0003's three-file claim amended to a per-kind count.
13. **Deletion of `reference/legacy_observations/ca_eccc` and
    `reference/legacy_observations/pl_imgw`** per ADR 0011, since porting a provider is
    what retires its legacy subtree.

## Scope — Out (explicit non-goals)

- **The user cache.** #16 owns it and is an option under consideration, not a v0.1.0
  commitment. This vision leaves the layout usable by it and builds none of it. No HTTP
  provider writes a store.
- **Austria, or any provider beyond the existing thirteen.** Austria is the reason the
  layout must generalise, not a provider ported here.
- **An archive.** RivRetrieve holds no redistribution rights; §7.4 defers it and #16 owns
  what survives of it.
- **Surfacing quality codes as native annotations in a returned result.** That reopens #11,
  which deleted the annotation tables deliberately. The codes are preserved in the store and
  reachable through a receipt; they do not enter the observation frame.
- **Porting the eleven HTTP providers.** #17 owns them; this vision touches only the two
  bulk providers.
- **What proves a port correct in general.** #13 owns that question. This vision lands two
  ports and carries its own falsification for them.
- **Retaining the publisher artifact for replay or local repair.** Rejected in ADR 0021 with
  the irrecoverability accepted in writing.
- **A staleness threshold, freshness verdict or cache expiry of any kind.** The 90-day
  `stale` rule in `ca_eccc/observation_client.py` is deleted, not replaced. RivRetrieve date
  stamps and never judges.
- **Automatic rebuild or migration of an incompatible store.** Refuse and instruct.
- **A root-digest chain, declared permitted reader-version ranges, or a native-state
  encoding version separate from the format version.** Considered and trimmed; a reader that
  refuses any manifest it does not recognise gets the same protection without a version
  algebra to maintain.
- **Computing, aggregating or interpreting any value the source did not publish**, per the
  Program's standing out-of-scope list.

## Constraints

- **ADR 0002 is binding and not reopened.** One layout for anything stored on disk, queried
  by the engine rather than in the shape a source shipped. Thiago's preference for keeping
  each source's native format is on record as overruled, not as agreed.
- **ADR 0021 governs the artifact.** Deleted after a certified compile; only its identity
  survives. Provenance therefore means identifiable, not reproducible, and the guarantee
  must be worded that way wherever it is stated to a user. A defect in how the compile step
  understood a source, discovered after the publisher stops serving that release, is not
  recoverable from anything on the user's disk. This is an accepted price, stated in the
  ADR, and must not be quietly re-described as a gap to close.
- **ADR 0022 governs the provider shape.** A bulk provider contributes `config.py` and
  `bulk.py` and no `fetch.py` or `parse.py`. This preserves ADR 0003's naming rule — a file
  is named for the work the provider writes code for — and generalises its count. It
  preserves ADR 0008's guarantee for the reason that guarantee was made: the provider never
  holds the sequence and cannot clip, because it is not invoked during a retrieval at all.
- **ADR 0023 governs receipts.** What ADR 0018 decided is unchanged — retained bytes are
  exactly what the parse boundary consumed, retention is opt-in and empty unless asked for,
  request headers never enter an origin. Only the name and the authorship declaration are
  added. The rename is free now and breaking after v0.1.0; the package is unpublished and
  unregistered on PyPI.
- **The store holds native values.** Source units, source wall-clock timestamps. Conversion
  and clipping happen on read through the same convert stage every provider uses
  (ADR 0016, ADR 0017). Standardising the container is not the same act as changing the
  numbers.
- **Compile preserves by default.** Every cell the source published about an observation is
  carried across, including values RivRetrieve never reads. An omission is declared and
  argued in the layout specification, never inferred from what the library happens to
  consume. This is enforced the way the origin gate in #8 is enforced: the build fails.
- **The result stays four members** (#11): observation frame, provenance, issues, receipts.
  The rename does not add a fifth.
- **The public surface stays functions over a selection** (ADR 0019). The three cache verbs
  are module-level functions taking a provider id; no user-facing object grows behaviour, and
  `ProviderHandle` stays deleted.
- **ADR 0020 applies to the bulk surface.** A capability whose behaviour is determined by
  which country was asked about does not ship; the bulk verbs are legitimate because they
  refuse explicitly on a non-bulk provider rather than degrading silently.
- **Peak disk during a refresh may hold the previous store, the artifact and the staged
  store at once.** Poland's yearly archives permit compiling one year at a time; Canada's
  single database does not, and its peak must be bounded deliberately.
- **The engine's `CacheConfig`** (`_internal/engine.py:384`) is an empty placeholder today
  and is where a provider's store declaration lands.
- **`ORIGIN_GATE_ENROLLED_PROVIDERS` and the catalogue build are untouched.** Both providers
  are already certified; this vision changes observations, not catalogues.

## Acceptance criteria (vision-level "done")

```json
{
  "criteria": [
    {
      "name": "Four value states survive compile",
      "input": "Compile a fixture station-month holding a day with no record at all, a day whose value the source published as null, a day whose value field the source left blank, and a day carrying a value with the quality flag E",
      "observation": "Reading those four days back through the shared store reader returns four distinguishable states, with the E flag attached to that day and to no other"
    },
    {
      "name": "Undeclared source column stops the compile",
      "input": "A publisher artifact carrying one source column that the layout specification does not declare as retained, reconstructible or deliberately discarded",
      "observation": "Compiling refuses, no staged store is published, and both the previous store and the publisher artifact remain present on disk"
    },
    {
      "name": "No plausible prefix is published",
      "input": "A publisher artifact whose 1997 member is truncated mid-record, with valid 1998 records following it",
      "observation": "No store is published and no 1998 row is readable through the store reader"
    },
    {
      "name": "Verification catches a mutated store",
      "input": "Run a compile whose writer deliberately alters one value after staging and before verification",
      "observation": "The field-for-field read-back comparison fails, the atomic swap does not occur, and the publisher artifact is not deleted"
    },
    {
      "name": "Unrecognised manifest is refused",
      "input": "Hand-edit a valid store's manifest so it declares a format version the reader has never seen, then query that store",
      "observation": "The read refuses and names the rebuild command; no download begins and no partial interpretation of the store is returned"
    },
    {
      "name": "The gigabyte never lands unasked",
      "input": "Call fetch for a ca_eccc station on a machine with no local store",
      "observation": "The result carries an issue naming the download command, no bytes are written to the cache directory, and no request reaches the source host"
    },
    {
      "name": "Two unlike sources read through one path",
      "input": "Compile Canada's HYDAT SQLite and Poland's yearly ZIP archives, then fetch one station-year from each",
      "observation": "Both are served by the same store reader with no provider-specific branch on the request path, and no provider code executes during either retrieval"
    },
    {
      "name": "A value names the release it came from",
      "input": "Fetch any ca_eccc value from a compiled store",
      "observation": "Provenance carries the source vintage and the checksum of the publisher artifact the store was compiled from"
    },
    {
      "name": "Native values are unchanged on disk",
      "input": "Compile a fixture whose source publishes the value 12.4 in the source's own unit",
      "observation": "The store holds 12.4 in that unit, and any unit conversion appears only in the returned observation frame"
    },
    {
      "name": "A receipt declares its authorship",
      "input": "Fetch a ca_eccc value and a usgs_nwis value in one session with receipt retention requested",
      "observation": "The ca_eccc entry is marked store_excerpt and carries the store path, executed query, format version and source vintage; the usgs_nwis entry is marked publisher_payload and holds the untouched response body"
    },
    {
      "name": "Insufficient disk refuses before downloading",
      "input": "Invoke download for ca_eccc with less free space reported than the compile requires",
      "observation": "It refuses before any bytes are downloaded, naming the space required and the space available"
    }
  ]
}
```

## Decomposition hints

Risky-first ordering, since the irreversible act is the artifact deletion and everything
protective must exist before it does:

1. **The layout specification and its conformance fixtures**, including the four value
   states and at least one intentionally invalid store. Nothing compiles until the shape
   and its refusals are written down and validated. This is the HFX pattern's whole point
   and it precedes code.
2. **The manifest schema and the reader's refusal path.** Build the "refuse a manifest I do
   not recognise" behaviour before any store exists to be misread, using a hand-authored
   fixture store rather than a compiled one.
3. **The shared store reader against fixture stores.** Reading, querying with predicate
   pushdown, and cache status, exercised against committed fixtures with no download
   anywhere in the loop.
4. **The certification harness**: staging, column-closure check, count reconciliation,
   field-for-field read-back, atomic swap, and the on-failure guarantee that the previous
   store and the artifact both survive. Prove it with a deliberately faulty writer before
   any real compile deletes anything.
5. **`ca_eccc` as `config.py` plus `bulk.py`**, compiling HYDAT and deleting its
   `fetch.py`, `parse.py` and the 90-day staleness rule. This is where the layout meets a
   real source for the first time and where a layout defect is cheapest to fix.
6. **`pl_imgw` as `config.py` plus `bulk.py`**, compiling yearly archives one year at a
   time. This is the falsifier for the whole vision: if the layout only fits Canada, it
   fails here, and Poland's per-year archives also exercise the bounded-peak path Canada
   cannot.
7. **The consent gate and the three public functions**, once both providers can be
   downloaded and compiled.
8. **The receipts rename**, mechanical and independent of the store work; it may run in
   parallel with 3–6 and must land before the surface is documented.
9. **ADR status flips, ADR 0003 amendment, legacy subtree deletion, documentation.**

Steps 1–4 build nothing a user can see and are the majority of the value; resist
compressing them into the provider ports.

## Open questions / risks

- **The disk-peak criterion is not observable from an ordinary test run.** It needs an
  injectable free-space probe or a controlled environment. Decide the mechanism while
  building the download step, not at the end.
- **Poland's port carries defect risk this vision does not own.** The charting audit found
  `pl_imgw` returns the wrong day entirely for a request expressed in `Europe/Warsaw`, and
  #13 owns what proves a port correct in general. The window handling here must go through
  the engine's ADR 0016/0017 machinery like any other provider; do not reproduce the legacy
  behaviour.
- **`pl_imgw`'s legacy cache build parses to canonical columns before writing.** Compiling
  must not inherit that: the store holds native values, so the port is a rewrite of the
  compile step rather than a relocation of the existing one.
- **A layout defect discovered during Poland (step 6) invalidates stores already produced in
  step 5.** That is the intended sequencing and the reason Poland is not last, but it means
  step 5's store format must not be treated as frozen until step 6 passes.
- **The Program's fixture suite cannot currently express non-UTC windows**, per the Map. Any
  conformance fixture asserting boundary behaviour for these two providers must construct
  its own requests rather than reusing existing fakes.
- **Compiling is substantially more expensive than writing files** because certification
  reads the whole store back and compares it field for field. If that cost proves
  prohibitive for Canada at full scale, the response is to bound it explicitly and record
  what is no longer verified — never to silently sample.
