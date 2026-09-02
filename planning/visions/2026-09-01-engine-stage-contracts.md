# Vision: engine stage contracts

Program: https://github.com/RivRetrieve/RivRetrieve/issues/6
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/7

## Goal / Why

Every retrieval passes through four stages — fetch, parse, convert, assemble — but today
each provider runs all four itself. `ProviderModule.observations(request)` hands the whole
pipeline to the provider and the engine only dispatches. The result is thirteen private
answers to questions that have one answer: when to clip, how to resolve a zone, which unit
factor applies, how to report a station that returned nothing.

The Program Map records what that costs. Eleven of thirteen providers carry a boundary
defect, and the shared root cause is that no single place owns the order of operations:
the fetch window is expressed in the source's calendar while the clip window is expressed
in UTC, with no padding anywhere. `ba_fhmzbih` returns a daily mean of 61.858 where the
true value is 157.738, and the test that issues exactly that request passes.

This vision makes the engine the caller. It fixes the types that cross each stage
boundary, so that the ordering guarantee is structural rather than remembered: a provider
cannot clip before aligning because it never clips, and cannot clip to the user's window
because it is never handed one. A provider contributes only what is true about its source;
everything else has exactly one authoritative representation in the engine.

Success changes what a defect costs. Under the current arrangement a boundary bug is
thirteen bugs found one at a time; under this contract it is one bug in one place, and
several classes of it stop being expressible at all.

## Scope — In

1. **The pipeline driver.** The engine invokes a provider's `fetch` and `parse`, and
   performs `convert` and `assemble` itself. A provider package exposes `fetch`, `parse`
   and `config`, and no `observations`. Recorded in ADR 0008.

2. **The boundary types**, as the real specification of the library:

   ```text
   ObservationRequest ≔ { provider, stations, products, window : RequestedWindow }

   fetch   : (stations, products, FetchWindow, config) -> WithIssues<Payload[]>
   parse   : (Payload, config)                         -> WithIssues<Rows>
   convert : (Rows, config, RequestedWindow)           -> WithIssues<CanonicalRows>
   assemble: (CanonicalRows, provenance, issues, raw)  -> Result

   Rows          ≔ station_id | product_id | time | value | time_zone
   CanonicalRows ≔ time | time_zone | station_id | product_id | value
   WithIssues<A> ≔ { value : A, issues : Issue[] }
   ```

3. **`RequestedWindow` and `FetchWindow` as distinct types.** The requested window is the
   user's, closed at both ends, and is what convert clips to and provenance records. The
   fetch window is padded outward by the engine and is the only window a provider sees.
   Clipping to the padded window must be a type error.

4. **`Payload` as a tagged, opaque unit.** Tagged with the call that produced it — source
   coordinates used, station-product pairs asked for, window as sent — and free to answer
   several stations and several products at once. Its content is opaque to the engine and
   may be bytes, text, or an object a local source produced. Only parse opens it.

5. **`WithIssues<A>` at every provider-facing seam.** A Writer, not an `Either`: nothing
   short-circuits, issue lists concatenate across stages, partial success survives, and an
   all-fail request returns an empty frame with issues rather than raising. Issues are
   facts about data; exceptions are broken seams. Recorded in ADR 0009.

6. **`ProviderConfig` keyed by product.** One record per product holding its source
   coordinates, its native unit from the engine's `Unit` enum, and its time semantics
   including the day definition. Provider-wide `zone` at the top, optional `cache` for the
   two bulk providers. Recorded in ADR 0010.

   ```text
   ProviderConfig ≔ { zone, products : Map<ProductId, ProductConfig>, cache : CacheConfig | none }
   ProductConfig  ≔ { coordinates : SourceCoordinates, unit : Unit, semantics : Instant | Daily }
   ```

7. **The `time_zone` value domain**, enforced at the boundary: an IANA identifier, an
   ISO-8601 offset `±HH:MM`, or the literal `unknown`, never null, with no promotion
   between kinds and abbreviations rejected. Recorded in ADR 0007.

8. **The day label.** A daily row's `time` is the day the source named, written as that
   date at `00:00:00`. What 24 hours it covers comes only from the declared day
   definition, never from the timestamp.

9. **Engine helpers, offered rather than passed.** An HTTP client with retry, backoff,
   timeout, user-agent and rate limiting, mandatory for anything touching the network and
   enforced by a lint rule forbidding direct `httpx`/`requests`/`urllib` imports under
   `providers/**`. Common-format decoders for JSON and CSV, genuinely optional.

10. **Boundary validation.** The engine validates the parsed-row schema where parse hands
    back, and the canonical schema where convert hands back. A malformed frame raises
    rather than flowing onward.

11. **Two providers ported as proof the contract holds**, one HTTP source that stamps a
    per-row offset and one bulk source whose fetch reads a local file. These exist to
    falsify the contract, not to start the port.

## Scope — Out (explicit non-goals)

- **Window representation and padding arithmetic** — how far to pad, in whose calendar the
  ends are expressed, and whether padding is per-product or per-plan. Owned by #10. This
  vision fixes that there are two window types and who receives which, not what is in them.
- **The result object's fields** — what `assemble` produces and what leaves it. Owned by
  #11. This vision fixes assemble's role, not its output shape.
- **The `Issue` taxonomy** and the failure and `on_issue` policy. Owned by #15.
- **How a port is proved correct**, including how the mandatory HTTP client is substituted
  in tests. Owned by #13.
- **Porting all thirteen providers.** Owned by #17.
- **On-disk layout** (#12), **user caching** (#16), **public API surface** (#14),
  **catalogue guarantees** (#8), **CI, build and release** (#9), **documentation site** (#18).
- **Aggregation of any kind.** Banned Program-wide; the derived-daily products of
  `ba_fhmzbih`, `th_thaiwater` and `ch_foen` are dropped rather than fixed.
- **Deriving a station's zone from its coordinates**, or from a zone abbreviation.
- **Filling the five unknown provider zones.** That is the team survey, not this work.

## Constraints

- **Binding ADRs.** 0001 (native time by default), 0003 (a provider is three files),
  0005 (unknown is first-class), 0006 (time and zone are two columns), and the four
  written for this ticket: 0007, 0008, 0009, 0010.
- **`CONTEXT.md` is the authority on language**, over the design documents where they
  collide. Two collisions already reconciled: the review's `time_raw`/`value_raw` column
  naming, and its stage-keyed configuration layout.
- **Polars DataFrames at the row-carrying boundaries**, so a column holds one dtype. `time`
  is a naive `pl.Datetime` throughout; `time_zone` is a string.
- **`unknown` is a value, never null and never a silent default.** A fact is filled only
  where the source states it. A value written from an author's reasonable inference is the
  failure this library exists to prevent, because in a result it is indistinguishable from
  one the source established.
- **Five providers ship `zone = unknown`** — `jp_mlit`, `th_thaiwater`, `ba_fhmzbih`,
  `za_dws`, `br_ana` — replacing the IANA constants currently hardcoded in their runtime
  code, until the survey can cite where each source states its zone.
- **Nothing transport-specific in the contract.** `ca_eccc` and `pl_imgw` read local files;
  a contract they satisfy by ignoring part of it is the wrong contract.
- **DRY applies to knowledge, not to code text.** Retry policy is one piece of knowledge
  and gets one representation; thirteen parsers encode thirteen different pieces of
  knowledge and stay thirteen.

## Acceptance criteria (vision-level "done")

1. No provider module exposes `observations`. The engine holds the sequence.
2. No file under `providers/**` performs timezone arithmetic, unit conversion, window
   clipping, or a retry loop. Checkable by grep: today there are two dozen such lines in
   `parser.py` and `transform.py` files alone.
3. The lint rule forbidding direct HTTP library imports under `providers/**` passes.
4. A function that clips takes a `RequestedWindow`, so passing a `FetchWindow` fails type
   checking rather than returning plausible numbers.
5. A `ProductConfig` cannot be constructed without coordinates, unit and semantics, so a
   product is either fully declared or absent from the provider.
6. A request for five stations where one 404s returns four stations' rows plus one issue —
   not four silent rows, and not an exception.
7. A request where every station 404s returns an empty frame with issues and intact
   provenance, and raises nothing.
8. `time_zone` never holds a value outside IANA, `±HH:MM`, and `unknown`. Asserted against
   USGS specifically, whose catalogue supplies `EST`/`CST`/`MST`/`PST`/`AKST`/`HST` for
   26,231 stations and whose payload supplies the offset that is used instead.
9. A daily row from a date-only payload carries the date at `00:00:00` with the day
   definition recorded separately, and no parser fabricates midnight UTC.
10. Both proof providers satisfy the contract without either one requiring a change to it.

## Decomposition hints

Risky-first ordering, since the types are what everything else is built against:

1. **The contract types first**, in one engine module: `ObservationRequest`,
   `RequestedWindow`, `FetchWindow`, `Payload`, `WithIssues`, `ProviderConfig`,
   `ProductConfig`, `Unit`, `Instant` and `Daily`. Nothing else can be built honestly
   before these exist. The window endpoint type can start opaque, since #10 fixes it.

2. **The pipeline driver next**, with convert and assemble as engine code, against a
   throwaway fake provider. This is where the ordering guarantee either holds or does not,
   and it should be provable before any real source is involved.

3. **`WithIssues` threading through all four stages.** Worth doing as its own slice rather
   than as a side effect of the driver: the accumulation across stages is the part that
   quietly goes wrong.

4. **Helpers after the stages**, not before. The HTTP client's shape should follow from
   what two real `fetch` implementations needed, rather than being designed in advance.

5. **The two proof providers last**, one of each archetype. Pick the HTTP one from those
   whose payload stamps a per-row offset — `usgs_nwis` or `no_nve` — since that exercises
   the zone precedence rule. Pick the bulk one from `ca_eccc` or `pl_imgw`, since that
   exercises a payload whose content is not bytes.

Two dependencies worth watching. #10 fixes the window endpoint type and can change
`FetchWindow`'s shape; keep it opaque until then. #11 fixes the result fields and therefore
assemble's output; keep assemble's internals shallow until that lands.

## Open questions / risks

- **The window endpoint type is unresolved** (#10). `T` and `U` are placeholders. If #10
  concludes the two windows carry the same representation, the nominal distinction between
  `RequestedWindow` and `FetchWindow` still pays for itself inside the engine, but the case
  is weaker and should be revisited there rather than defended here.
- **Whether padding is one window per plan or one per product** (#10). A daily product and
  an instantaneous product may need different margins.
- **Substituting the mandatory HTTP client in tests** (#13). The current suite injects fake
  transports for `no_nve`, `jp_mlit` and `th_thaiwater`, and an imported client is harder
  to substitute than a passed one. This is a real cost of the offered-not-passed rule and
  it has no answer yet.
- **`assemble`'s output depends on #11.** Its role is settled — packaging, no arithmetic —
  but its fields are not.
- **Five providers return `time_zone = unknown` until the survey.** Best-effort UTC is
  unavailable for them in v0.1.0. This needs the team conversation with Frederik, Simon and
  Thiago, and it decides what those providers return in the meantime rather than what gets
  built.
- **`_coerce_datetime` normalises nothing today** (`_internal/observations.py:290`), and
  two providers crash from the public API on a plain string date — `za_dws` with a polars
  `SchemaError`, `br_ana` with a `TypeError`. The request type has to fix this at
  construction, and the fix belongs with #10's representation decision.
- **`jp_mlit` encodes hour 24** in its `.dat` column headers (`1時` through `24時`), and the
  current parser maps hour *n* to *n-1*. Whether `1時` means the instant 01:00 or the hour
  ending at 01:00 is unresolved and changes every timestamp by an hour.
- **The audit grounding several of these decisions was run directly**, not by the four
  subagents spawned for it, which returned no reports. The findings cite fixtures and line
  numbers and are reproducible, but they had no second reader.
