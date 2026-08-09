# Vision: the surface is three verbs and a selection

## Goal / Why

RivRetrieve's public surface hands back storage tables and asks the caller to join them. To find a
gauge a user fetches `stations()`, `products()` and `station_products()` and joins by hand; to
retrieve it they retype the provider, stations and products they just derived into `observations()`,
a function with seven arguments. A parallel `ProviderHandle` family duplicates every catalogue
method with the provider pre-bound, held apart from the top-level family only by a convention.

Three of the surface's capabilities are backed by nothing:

- `source="live"` is a public argument on three handle methods, implemented by no provider. Every
  `provider_info` row reports `live_stations`, `live_products` and `live_station_products` as false,
  and calling it warns and returns an empty frame.
- A bounding-box filter needs a coordinate reference frame. Nine of thirteen providers state none;
  22,509 of 64,244 stations carry `crs = unknown`.
- A `record_covers` filter needs a published period of record. Twelve of thirteen providers publish
  none; bounds exist for 57,450 of 326,574 series — 17.6 per cent, every one American.

Each of those answers an unanswerable question quietly instead of loudly, which is the failure this
project has already ruled against twice (ADR-0006, ADR-0016).

After this lands a user types three lines — say which series, narrow, retrieve — and never names an
identifier twice. The same four-member result comes back for all thirteen countries. Anything the
library cannot answer for every country is either absent from the surface or visibly `unknown` in a
frame the user filters themselves. Nothing is published to PyPI yet, so every deletion here is free;
after #9 it is not.

## Scope — In

1. Ship the public surface as functions over a selection: `providers()`, `products()`, `find()`,
   `pick()`, `fetch()`, `fetch_by_provider()`, `as_frame()`, `from_frame()`, `source_metadata()`,
   `map()`, `to_utc()`. No user-facing object carries behaviour.
2. Implement the selection: an immutable value at `(provider_id, station_id, product_id)` grain,
   printing as a table, carrying no methods and no chained query language. An empty selection is an
   ordinary answer and retains a machine-readable reason for being empty.
3. Make `find()` total over valid vocabulary, with behaviour independent of argument count. Naming a
   provider, product or provider-scoped station that does not exist raises; naming valid identifiers
   with no catalogue edge between them returns an empty selection. No fuzzy correction; an error may
   name the nearest valid identifier.
4. Make `pick()` validate names against the catalogue scope rather than against its input rows, so a
   station that is real but absent from the current selection yields an empty selection with a
   reason rather than an unknown-name error. A vocabulary error in a list fails the whole call.
5. Make `fetch()` reject an empty selection before any network access, reporting the retained reason.
6. Restrict `fetch()` to a single-provider selection and add `fetch_by_provider()` returning one
   result per provider, because `ObservationProvenance` carries one `provider_id`, `license` and
   `citation`, and 225 station ids are in use by more than one provider.
7. Ship `to_utc()`, which raises on any row whose `time_zone` is `unknown`, naming the provider and
   affected row count rather than relabelling a timestamp.
8. Ship `map()`: plots every station in a selection, renders unstated-frame coordinates as if
   EPSG:4326, distinguishes established from unstated frames by marker colour, states `crs` in every
   popup, and never narrows a selection.
9. Delete `ProviderHandle`, `provider()`, the top-level `observations()` wrapper, the table-shaped
   `stations()`, `products()` and `provider_info()` accessors, the `product_info` alias, and the
   `source="live"` argument with its `CatalogSource` type. Retain the `usgs_nwis` live machinery
   internally.
10. Rename the catalogue period-of-record columns to `published_record_start_date` and
    `published_record_end_date` across the schema, the thirteen `generate_catalogue.py` files, the
    tests, and the regenerated packaged catalogues.

## Scope — Out (explicit non-goals)

- Any search argument whose behaviour depends on which country was asked about: bounding box,
  `record_covers`, `source="live"`. None ships in v0.1.0.
- Building a coverage snapshot, cron-probed or opportunistically recorded, to back a record-window
  filter. Deferred to #92.
- Establishing a record bound by measurement rather than by reading what a source published. It
  would be a distinct claim needing its own column and its own origin form, which the current origin
  vocabulary does not have.
- Harmonised name or river search. ADR-0015 removed those columns from the canonical catalogue.
- A chained query language, click-to-select mapping, or any capability that narrows a selection by
  deciding on the caller's behalf without recording what it dropped.
- Deciding whether native tables ship inside the wheel; that is #51's call and it governs whether
  `source_metadata()` can exist.
- Publishing to PyPI, documentation authoring, and porting providers. Those are #9, #18 and #17.

## Constraints

- The observation frame is fixed by ADR-0006 at `time | time_zone | station_id | product_id | value`
  and cannot gain a `provider_id` column.
- A result is exactly the four members #11 landed: frame, provenance, issues, raw.
- `ObservationProvenance.provider_id`, `license` and `citation` are singular, so one result cannot
  span providers.
- `product_id` is a canonical cross-provider vocabulary of twelve ids over 53 provider-product rows,
  so a product can be named without naming a provider.
- Station identity is `(provider_id, station_id)`; 225 station ids are in use by more than one
  provider.
- ADR-0016 governs the requested window: wall-clock, closed at both ends, zone-carrying endpoints
  refused.
- Nothing is published to PyPI, so deletions are free during this vision and not afterwards.
- Governing principle: harmonise identity and physics, never harmonise judgement, and where
  something is objective but cannot be established, say so rather than assume it.
- ADR-0019 and ADR-0020 were written during the grill and bind this work.

## Acceptance criteria (vision-level "done")

```json
{
  "criteria": [
    {
      "name": "Deleted surface is unreachable",
      "input": "evaluate [n for n in dir(rivretrieve) if not n.startswith('_')] against a freshly installed package",
      "observation": "the list is exactly the shipped public names, and provider, observations, stations, provider_info, product_info, ProviderHandle and CatalogSource are all absent from it"
    },
    {
      "name": "Unknown zone is refused, not guessed",
      "input": "fetch a ch_foen selection, whose rows all carry time_zone unknown, then call to_utc on the returned result",
      "observation": "to_utc raises, naming ch_foen and the count of affected rows; no frame is returned and no timestamp has been relabelled"
    },
    {
      "name": "A typo raises, an absence does not",
      "input": "call find(provider='usgs_nwis', station='0164650'), then call find(provider='usgs_nwis', station='01646500', product='stage_daily_mean')",
      "observation": "the first call raises UnknownStationError; the second returns a zero-row selection whose printed reason lists the products that station does publish"
    },
    {
      "name": "A known station is never called unknown",
      "input": "pick a real usgs_nwis station that exists in the catalogue but lacks the product the selection was built on",
      "observation": "pick returns an empty selection carrying a machine-readable reason and does not raise UnknownStationError"
    },
    {
      "name": "Mixed providers cannot share provenance",
      "input": "pass a selection spanning usgs_nwis and ca_eccc to fetch",
      "observation": "fetch raises, naming both providers and directing the caller to fetch_by_provider, and no source call is made"
    },
    {
      "name": "Nothing fetched makes no request",
      "input": "pass an empty selection to fetch, configured with a transport that records every source call",
      "observation": "the transport records zero source calls, and fetch raises carrying the reason the selection retained from find"
    },
    {
      "name": "Search is nationality-blind",
      "input": "call find(provider='cz_chmi', product='discharge_daily_mean') and find(provider='usgs_nwis', product='discharge_daily_mean'), then inspect the signatures of find and pick",
      "observation": "both calls return non-empty selections, and neither signature accepts a record window, a bounding box, or a catalogue source argument"
    },
    {
      "name": "The map admits its assumption",
      "input": "call map on a ch_foen selection, then read the crs column back from the packaged catalogue",
      "observation": "all 246 stations are rendered, every popup states crs unknown, and the catalogue value read back is still unknown rather than EPSG:4326"
    },
    {
      "name": "Published bounds are named as published",
      "input": "call as_frame on any selection and list its columns",
      "observation": "published_record_start_date and published_record_end_date are present and no bare start_date or end_date column survives anywhere in the catalogue schema"
    }
  ]
}
```

## Decomposition hints

- The column rename is the widest and least risky change: schema, thirteen `generate_catalogue.py`
  files, the tests and regenerated packaged catalogues. It touches roughly 23 files mechanically and
  unblocks nothing, so it can run first or in parallel.
- The selection value and `find`/`pick` semantics are the core. Build the selection type, the
  vocabulary-versus-combination rule, and the retained empty reason together; everything else
  consumes them.
- `fetch` and `fetch_by_provider` are a thin re-parameterisation of the existing observation path —
  the engine work landed in #7, #10 and #11. The new behaviour is the single-provider guard and the
  empty-selection rejection before I/O.
- Deletion is its own slice and should come after the replacements exist, so the test suite is never
  simultaneously without both surfaces.
- `to_utc` is small but touches the one Program-level open question — `usgs_nwis` publishes a fixed
  offset that changes across a DST boundary, so a station that shifts has no single answer. Decide
  its behaviour for that case explicitly rather than by accident.
- `map` is last and independent; it depends only on the selection existing.

## Open questions / risks

- `source_metadata()` may not be buildable. It reads the per-provider native table, and whether that
  ships inside the wheel is undelivered on #51. If native tables do not ship, this function has
  nothing to read and must either be dropped from the surface or restricted to a source checkout.
- `products(provider=None)` is the one surviving table-shaped accessor and was never tested against
  the same objection that removed the others. It may not belong on the surface.
- `raw=` and `on_issue=` on `fetch` were not reached in the grill. `RawMode` is currently a public
  enum; whether it stays one or becomes a boolean is undecided, and it is public surface.
- `to_utc` intersects a Program-level open question: whether an IANA identifier may be promoted from
  a published offset. A `usgs_nwis` station whose offset shifts across a DST boundary has no single
  answer, and this vision does not settle it.
- The name `map()` was chosen by the assistant rather than the user. It shadows the builtin when
  imported bare; reversible if the user disagrees.
- Deleting `source="live"` withdraws a working `usgs_nwis` code path from the public surface. If
  #17's ports want live catalogue reads sooner than #92 lands, the argument returns earlier than
  planned.
