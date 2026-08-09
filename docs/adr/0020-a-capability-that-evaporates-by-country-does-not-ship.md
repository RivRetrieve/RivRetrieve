# ADR-0020: A capability that evaporates by country does not ship

## Status

Accepted

## Context

Three separate conveniences were proposed for the public surface, and each turned out to rest on
metadata that most of the thirteen sources do not publish.

- A bounding-box filter needs a reference frame for the coordinates it compares against. Nine of the
  thirteen providers state none: seven are certified `NotPublished` with evidence, and two are the
  providers deferred from origin certification. 22,509 of 64,244 stations carry `crs = unknown`.
- A `record_covers` filter needs a published period of record. Twelve of the thirteen providers
  publish none. Bounds exist for 57,450 of 326,574 series — 17.6 per cent, every one American.
- A `source="live"` catalogue argument was already present on three handle methods and implemented by
  no provider. Every `provider_info` row reports `live_stations`, `live_products` and
  `live_station_products` as false, and calling it returned a warning and an empty frame.

ADR-0016 had already made this judgement once, refusing a window whose endpoints carry a timezone
because placing an instant requires a station timezone and five of the thirteen sources publish none.
The alternative in each case is to ship the capability and return an empty or partial answer where the
metadata is absent. That answer is indistinguishable from a genuine negative: a user filtering Czech
stations by record window sees nothing and concludes there is no Czech data, rather than that the
question cannot be asked of that source.

A rendered map appeared to fall under the same objection, since plotting a marker on a web tile
asserts a reference frame for coordinates that state none.

## Decision

A capability whose behaviour is determined by which country was asked about does not ship in v0.1.0.
The bounding-box filter, `record_covers`, and the `source="live"` argument with its `CatalogSource`
type are removed. Search vocabulary is limited to provider, product and provider-scoped station, all of
which every provider supplies. Filtering on anything else is performed by the caller in Polars against
the returned frame, where absent metadata is visible as `unknown` rather than silently excluded.

The boundary is what the capability does with an absent fact. A filter decides on the user's behalf and
does not record what it dropped, so an unstated fact silently changes the answer. A rendering shows
every row and leaves the judgement to a person, so an unstated fact is visible rather than operative.
`map` therefore ships: it plots all stations, renders unknown-frame coordinates as if EPSG:4326,
distinguishes established from unstated frames by marker colour, and states the frame in every popup.
The catalogue value remains `unknown`; the rendering assumption exists only for the duration of drawing
and is never written back. `map` returns a rendering and never narrows a selection, because a
click-to-select map would decide rather than show.

Catalogue period-of-record columns are named `published_record_start_date` and
`published_record_end_date` so that a value established by observation cannot later occupy a column
whose name claims the source stated it.

## Consequences

Nine functions ship whose behaviour is the same for all thirteen providers, and no search argument
returns a silently nationality-dependent answer. Users who want date filtering write a null-aware
Polars predicate, which the documentation must demonstrate; this is more work than a keyword for the
17.6 per cent of series where bounds exist. Each removed capability is additive: `record_covers` and a
live catalogue argument can return once the evidence supports them, without changing the signature of
`find`. Working `source="live"` machinery for `usgs_nwis` is retained internally while the public
argument is withdrawn. A capability established by RivRetrieve measuring rather than by a source
publishing needs its own column and its own origin form, which the current origin vocabulary does not
have.
