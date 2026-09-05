# Vision: one cache serves the second request

Program: https://github.com/RivRetrieve/RivRetrieve/issues/6
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/16

## Goal / Why

A user who asks a live provider for the same data twice pays for the source twice. Every
one of the eleven live providers goes to the network on every `fetch()`, and nothing the
user retrieved is kept. The two bulk providers are the opposite case: `ca_eccc` and
`pl_imgw` are answered from a compiled store on disk, built once by an explicit
`download()`, and never touch the network on a request.

This vision makes the cache one thing for all thirteen providers. For a bulk provider it
is the compiled national store #12 built. For a live provider it accumulates from what
the user retrieves. Both live under one root, are written in one format family, are read
through the one shared store reader, and are reported and cleared by the same verbs. The
user turns it on with one keyword per call, and a second request for held data is
answered from disk with no source call.

Success is observable in four ways. A repeat request with `cache="reuse"` makes no
network call. An overlapping request fetches only the remainder. Every served interval
says when it was retrieved from the source. And `cache_status` and `clear_cache` answer
for every provider, not only the two bulk ones.

## What the user sees

```python
import rivretrieve as rr

sel = rr.pick(rr.find(provider="usgs_nwis", product="discharge_daily_mean"), station="09380000")

rr.fetch(sel, start="2020-01-01", end="2020-12-31")                   # bypass: source only, cache untouched (default)
rr.fetch(sel, start="2020-01-01", end="2020-12-31", cache="reuse")    # serve held, fetch the rest, write the rest
rr.fetch(sel, start="2024-01-01", end="2024-03-31", cache="refresh")  # source for the whole window, replace held

rr.cache_status("usgs_nwis")   # path, bytes, coverage per station and product with retrieval instants
rr.clear_cache("usgs_nwis")    # delete that provider's store; the user asking is the consent
rr.download("ca_eccc")         # unchanged, bulk only
```

The root defaults to the operating-system cache directory through platformdirs, which is
where the bulk stores already live (`~/Library/Caches/rivretrieve` on macOS, the XDG
cache directory on Linux). `RIVRETRIEVE_CACHE_DIR` relocates it. `cache_status` prints
the resolved path so it is always discoverable.

## Settled decisions

1. **The cache is one thing.** One root, one format family, one reader, three verbs.
   A bulk provider's cache is its compiled store; a live provider's cache accumulates.
   The glossary's separate "user cache" that RivRetrieve never deletes is retired. The
   surviving rule is that nothing is deleted unasked, and `clear_cache` is the user asking.
2. **Off by default, one keyword to turn on.** `fetch()` and `fetch_by_provider()` gain a
   `cache` keyword with three named modes. The keyword is a per-call instruction, never a
   state of the directory:
   - `bypass` (the default): the source is asked, nothing is read from the cache, nothing
     is written, and what is held stays exactly as it was. A user with a decade cached
     who wants one live answer omits the keyword.
   - `reuse`: every held interval is served from disk; only the remainder of the requested
     window is fetched from the source, written, and returned together with the held rows
     as one result.
   - `refresh`: the whole requested window is fetched from the source and replaces what
     was held for those series in that window. The source's current answer wins even when
     it has fewer rows than were held.
   The mode is a named literal, not a boolean, per the project's enum rule.
3. **Everything held is served.** The library never computes whether a held interval is
   old. There is no horizon, threshold, or freshness verdict of any kind. The ticket's
   premise that a historical window cannot change is false for the sources: USGS publishes
   provisional values it later revises, and every bulk vintage replaces earlier data.
   Provenance states, for each served interval, when it was retrieved from the source; a
   user who wants the source's current answer passes `refresh`.
4. **One root, resolved at the composition root.** The default is the platformdirs user
   cache directory already used at `_internal/providers/registration.py:278`.
   `RIVRETRIEVE_CACHE_DIR` overrides it, resolved from the process environment and then
   `./.env`, by the public entry points only, using the same resolver credentials use
   (`_resolve_credentials` in `_internal/discovery.py`). No provider, engine, or store
   module reads the environment.
5. **The three verbs cover every provider.** `cache_status(provider)` and
   `clear_cache(provider)` stop refusing live providers. For a live provider, status
   reports the resolved path, bytes on disk, and coverage per station and product with
   retrieval instants; clear deletes that provider's accumulated store and reports what it
   removed. `download(provider)` stays bulk-only and unchanged.
6. **Bulk providers under the keyword.** On a bulk provider, `bypass` and `reuse` both
   read the compiled store, as today, because the store is its only data path. `refresh`
   refuses and names `download`, because a gigabyte never lands from a keyword.
7. **A mixed result is one result.** When part of a window is held and part is fetched
   now, the caller receives one observation frame. Provenance lists the held intervals
   with their retrieval instants and the source calls made now. With receipts requested,
   the fresh calls appear as `publisher_payload` entries and the held rows as a
   `store_excerpt`, so a reader can always tell whose words they hold.
8. **Failure keeps what succeeded.** If the source fails for the remainder, the held rows
   are still returned together with the `error` issue #15 defines, and only successful
   series are written. Under `on_issue="raise"`, successful series are written before the
   raise.
9. **A new format revision for accumulated stores**, specified the way revision 2 was: a
   normative section in `docs/design/observation-store-layout.md`, the manifest schema at
   `src/rivretrieve/_internal/store/manifest.schema.json`, and valid and intentionally
   invalid conformance stores under `tests/test_data/observation_store_conformance/`.
   Revision 2 stays reserved for compiled stores. The reader refuses any revision it does
   not recognise, as today.
10. **The accumulated store holds parse output.** Native units and native wall-clock
    timestamps, exactly what a live provider's parse stage returns before convert
    (`RowsSchema` at `_internal/engine.py:318`: `station_id`, `product_id`, `time`,
    `value`, `time_zone`). Conversion and clipping happen on read through the same convert
    stage every provider uses, so a value is never converted twice.
11. **The manifest records coverage.** Which station, product, and interval was asked of
    the source, and the instant it was retrieved. Coverage is what lets "we hold nothing
    here" differ from "the source said there is nothing here", and it is how the remainder
    of a partially held window is computed. A source answer with zero rows is covered.
    Retrieval instants are the accumulated store's date stamp, in the role source vintage
    plays for a compiled store.
12. **Doctrine corrected in the same change.** `CONTEXT.md` defines one cache with two
    ways of being populated; the "User cache" entry is retired and the "Cache", "Store",
    "Manifest", and "Source vintage" entries are reworded to cover both. The layout
    document's clause reserving a distinct future revision for a user cache is fulfilled
    rather than reserved. `tests/test_domain_context.py` follows.

## Scope — In

- The `cache` keyword on `fetch()` and `fetch_by_provider()`, with the three modes above.
- Root resolution with `RIVRETRIEVE_CACHE_DIR`, for bulk stores and accumulated stores
  alike, at the public entry points.
- The accumulated-store format revision: normative section, manifest schema, conformance
  stores, coverage record.
- Writing parse output and coverage on retrieval; computing the remainder of a partially
  held window; replacing a window on `refresh`.
- Reading an accumulated store through the shared reader and merging held rows with
  freshly fetched rows before convert.
- Provenance and receipt behaviour for served, fresh, and mixed results.
- `cache_status` and `clear_cache` for every provider; `refresh` refusal on a bulk
  provider.
- `CONTEXT.md`, the layout document, and the domain-context test.

## Scope — Out (explicit non-goals)

- **An archive.** RivRetrieve holds no redistribution rights, and a collection prepared
  for publication is a different product. The cache is the user's own reuse on the user's
  own machine.
- **Any freshness threshold, staleness verdict, or expiry.**
- **Holding publisher payload bytes in the cache.** Held rows are re-encoded from the
  store and declared as such; the cache is not a recording store.
- **Caching for bulk providers beyond what #12 built.** No second copy of a compiled
  store, no writing bulk results into an accumulated store.
- **Quality codes or provider-native columns for live providers.** They are gone at parse
  and are not reconstructed.
- **A default of `reuse`.** Caching changes answers silently, and a slow request is not
  consequential in the way a stale value is.
- **Documentation pages.** #18 owns them. This vision touches `CONTEXT.md` and the layout
  document only.
- **A per-call cache path.** Considered and rejected in favour of one root, because a
  second location would make two caches.
- **Automatic rebuild or migration** of an accumulated store the reader does not
  recognise. Refuse, name the path, and let the user clear it.

## Constraints

- The public surface stays functions over a selection (#14). The new keyword is a keyword;
  no user-facing object grows behaviour or holds cache state.
- The result stays exactly frame, provenance, issues, receipts (#11, #12). A served row is
  a `store_excerpt`; a freshly fetched row is a `publisher_payload`.
- The store holds native values (#12). No conversion on write.
- AGENTS.md §2.2: only public entry points read `RIVRETRIEVE_CACHE_DIR`. The architecture
  test banning `os.environ`, `getenv`, and `dotenv` inside providers stays in force.
- AGENTS.md §2.4: source failure for the remainder is isolated once, at the engine's
  per-series call that #15 established, and never inside cache code.
- The shared reader validates before it scans (`_internal/store/reader.py`). An
  accumulated store is validated the same way, and an unknown revision cannot open a
  Parquet file.
- A compiled store's revision-2 manifest and reader behaviour are unchanged. Existing
  Canada and Poland stores remain readable.
- Nothing is published to PyPI, so adding a keyword to `fetch()` and widening
  `cache_status` and `clear_cache` breaks no released user.
- `CONTEXT.md` is the glossary of record. Cite code and `CONTEXT.md`, not ADR numbers.

## Repository facts the implementer needs

- Live retrieval runs in `drive()` at `_internal/driver.py`: a per-series fetch loop with
  the #15 isolation point, then parse per payload, concatenation, convert, and assemble.
  Bulk retrieval runs in `drive_store()` in the same module: one `StoreQuery` padded by
  the fixed two-day fetch padding, then the same convert and assemble.
- Registry dispatch is in `_ProviderHandle.observations` at `_internal/registry.py:100`
  onward: `_drive_engine` for live stages, `_drive_store` for a compiled store. The store
  root is bound per provider at registration (`registration.py:304`,
  `<root>/<provider_id>/store`).
- The bulk composition root is `_internal/bulk.py`: `download`, `cache_status`,
  `clear_cache`, disk admission, and the `publisher-artifact.download` pending namespace.
  `_bulk_registration` is where the bulk-only refusal lives today.
- The revision-2 reader, `StoreQuery`, `StoreReadResult`, and `StoreStatus` are in
  `_internal/store/reader.py`; validation and `StoreManifest` in
  `_internal/store/validation.py`; the store-excerpt receipt in `_internal/store/receipts.py`.
- Revision 2 pins one Parquet file per partition, rows nondecreasing by `station_id`, and
  a `value_state` column with three tokens. Parse output cannot distinguish a published
  blank from a published null, so accumulated rows carry `published_value` and
  `published_null` only. This loses nothing the user is handed today.
- The requested window is normalised in `_normalize_window` in `_internal/discovery.py`,
  including the defaulted `end` and the future-date `info` issue from #15. Coverage is
  recorded against the normalised window that was actually asked.
- `ObservationProvenance` in `_internal/observations.py` already carries
  `source_vintage`, `publisher_artifact_*`, `calls_made`, and `time_windows`; the
  accumulated case adds what a served interval needs rather than a second provenance type.

## Acceptance criteria (vision-level "done")

```json
{
  "criteria": [
    {
      "name": "The second request is local",
      "input": "With an empty cache, fetch one usgs_nwis station-product for 2020 with cache='reuse' through a transport that records every call; then repeat the identical call",
      "observation": "The first call records source requests and writes the store; the second call records zero transport calls and returns a frame equal to the first"
    },
    {
      "name": "Only the remainder is fetched",
      "input": "After holding January to June 2020 for one series, fetch January to December 2020 with cache='reuse' through the recording transport",
      "observation": "The recorded source requests cover only July to December (plus the engine's fixed padding), the returned frame covers the whole year, and the store afterwards covers the whole year"
    },
    {
      "name": "Bypass touches nothing",
      "input": "With an interval held, fetch the same interval with no cache keyword through the recording transport",
      "observation": "The source is called, the store's bytes and manifest are unchanged, and the result carries no store_excerpt receipt"
    },
    {
      "name": "Refresh replaces",
      "input": "Hold a window whose source recording returns ten rows; change the recording to return eight rows; fetch the window with cache='refresh'",
      "observation": "The source is called for the whole window, the frame holds eight rows, and a subsequent cache='reuse' call returns eight rows with no transport call"
    },
    {
      "name": "Held nothing differs from source said nothing",
      "input": "Fetch a series and window for which the recording returns zero rows with cache='reuse'; then repeat the call",
      "observation": "The second call makes no transport call, returns an empty frame, and cache_status shows the interval as covered"
    },
    {
      "name": "Every served interval says when it was retrieved",
      "input": "Hold January 2020 at instant T1 and February 2020 at instant T2 for one series, then fetch January to February with cache='reuse'",
      "observation": "Provenance lists two served intervals carrying T1 and T2 respectively, and no freshness or age field of any kind"
    },
    {
      "name": "A mixed result declares authorship",
      "input": "Hold January to June, then fetch January to December with cache='reuse' and receipts=True",
      "observation": "Receipts hold publisher_payload entries for the July to December calls and one store_excerpt for the held rows; provenance lists both the held intervals and the calls made"
    },
    {
      "name": "Failure keeps what is held",
      "input": "Hold January to June, then fetch January to December with cache='reuse' through a transport that answers HTTP 503 for the remainder",
      "observation": "The frame holds the January to June rows, issues hold one error issue for the failed remainder, and the store afterwards still covers exactly January to June"
    },
    {
      "name": "Native values on disk",
      "input": "Fetch with cache='reuse' a series whose source publishes 12.4 in the source's own unit and whose config converts it",
      "observation": "The accumulated store holds 12.4 in the native unit and a naive native wall-clock time; the converted value appears only in the returned frame"
    },
    {
      "name": "One root, relocatable",
      "input": "Set RIVRETRIEVE_CACHE_DIR to a fresh directory in ./.env with nothing in the environment, then fetch with cache='reuse' and call cache_status for that provider and for ca_eccc",
      "observation": "Both stores are located under that directory, cache_status reports that path, and no module under providers/ or store/ reads the variable"
    },
    {
      "name": "Verbs answer for every provider",
      "input": "Call cache_status and clear_cache on usgs_nwis after holding data, then call cache_status again",
      "observation": "The first status reports the path, bytes, and per-series coverage with retrieval instants; clear_cache reports the removed paths and bytes; the second status reports the store absent"
    },
    {
      "name": "Refresh refuses on a bulk provider",
      "input": "Fetch a ca_eccc series with cache='refresh'",
      "observation": "The call refuses before any transfer, names rivretrieve.download('ca_eccc'), and the compiled store is unchanged"
    },
    {
      "name": "Unrecognised revision is refused",
      "input": "Hand-edit an accumulated store's manifest to a format version the reader has never seen, then fetch with cache='reuse'",
      "observation": "The call refuses naming the store path and the revision, opens no Parquet file, and makes no source call"
    },
    {
      "name": "Compiled stores are unchanged",
      "input": "Run the revision-2 conformance and certification suites and the Canada and Poland bulk evidence",
      "observation": "All pass unchanged"
    }
  ]
}
```

## Decomposition hints

1. **The format revision first.** Write the normative section, the manifest schema, and the
   conformance stores, including the coverage record and at least one intentionally
   invalid store, before any code writes a row. This is the HFX pattern #12 followed and
   the reason its reader refuses cleanly.
2. **Reader and status for the new revision** against the conformance stores, with no
   network in the loop. Coverage arithmetic, meaning the remainder of a requested window
   given held intervals, belongs here and should be exercised on fixtures alone.
3. **The write path** from parse output plus the asked window, with atomic partition
   replacement. Prove `refresh` replacement and `reuse` accumulation on fixtures before
   wiring a provider.
4. **The keyword and root resolution** at the public entry points, then the registry
   dispatch that merges held and fresh rows before convert. Provenance and receipts land
   with this step.
5. **The verbs**: widen `cache_status` and `clear_cache`, add the `refresh` refusal for
   bulk providers.
6. **Doctrine**: `CONTEXT.md`, the layout document, and the domain-context test.

Steps 1 to 3 build nothing a user can see and carry most of the risk; resist folding them
into step 4.

## Open questions / risks

- **Two processes writing one provider's store at once.** Bound it with atomic partition
  replacement and a documented single-writer assumption; do not build a lock server. The
  layout revision may allow more than one Parquet file per partition so a write does not
  rewrite a decade, and revision 2's one-file rule stays revision 2's.
- **Coverage and the fixed two-day padding.** The engine asks the source for a padded
  window and clips on read. Whether coverage records the padded or the requested interval
  is the implementer's call; it must be one of them consistently, and the remainder
  computation must not re-fetch an interval the padding already covered.
- **Duplicate rows across writes.** A source may return the same row in two overlapping
  retrievals. Revision 2 preserves duplicates and never deduplicates in the writer; an
  accumulated store replacing a window on `refresh` avoids the question for that mode, and
  `reuse` never asks for a held interval, so duplicates arise only from the source itself.
- **Defaulted `end`.** A `reuse` call with no `end` covers through the caller's local date,
  and tomorrow's identical call has a one-day remainder. That is correct and should be
  visible in coverage rather than special-cased.
- **The domain-context test** asserts the glossary's current wording about a user cache
  and will fail until the glossary is rewritten; that failure is the intended signal, not
  a test to relax.
