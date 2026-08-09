# ADR-0019: The public surface is functions over a selection

## Status

Accepted

## Context

The pre-v0.1.0 surface exposed four catalogue tables (`stations`, `products`, `provider_info`,
`station_products`) and left callers to join them, alongside a `ProviderHandle` protocol whose five
methods duplicated the top-level functions with the provider argument pre-bound. Answering "which
gauges publish daily mean discharge, and over what period" required fetching three tables and joining
them by hand, and `observations` then took seven arguments, three of which — provider, stations,
products — restated what the caller had just derived from those tables.

The four tables are a storage decision. The question a user asks is which series exist and which of
them to retrieve, and the engine can route that question across the tables itself.

Two alternatives were rejected. Keeping the handle alongside top-level functions preserves two
parallel families of every catalogue method, held apart only by a convention that handle methods never
take a provider argument, with each family needing its own documentation and each drifting from the
other. Returning bare frames and asking callers to pass them back loses the ability to attach
diagnostics to an empty answer.

A result cannot span providers. `ObservationProvenance` carries a single `provider_id`, `license` and
`citation`, and one licence field cannot truthfully describe data from several agencies. The
observation frame carries no `provider_id`, and 225 station ids are in use by more than one provider,
so a merged frame would be ambiguous for real rows rather than only in principle.

## Decision

The public surface is nine functions and no user-facing objects with behaviour:

```
providers()  products(provider=None)
find(provider=, station=, product=)  pick(selection, ...)  fetch(selection, start=, end=)
fetch_by_provider(selection, start=, end=)
as_frame(selection)  from_frame(frame)  source_metadata(provider)  map(selection)  to_utc(result)
```

`find` and `pick` return a selection: an immutable value at series grain that prints as a table and
is passed between functions. It exposes no methods and no chained query language. `as_frame` and
`from_frame` are the escape hatch to Polars for filtering the surface does not provide.

`find` is total over valid vocabulary and its behaviour does not vary with argument count. Naming a
provider, product or provider-scoped station that does not exist raises; naming valid identifiers with
no catalogue edge between them returns an empty selection retaining a machine-readable reason. No
fuzzy correction is performed, though an error may name the nearest valid identifier. `fetch` rejects
an empty selection before any network access and reports the retained reason.

`fetch` requires a single-provider selection and returns one result; `fetch_by_provider` accepts a
mixed selection and returns one result per provider.

`ProviderHandle`, `provider()`, the top-level `observations()` wrapper, the table-shaped `stations()`,
`products()` and `provider_info()` accessors, and the `product_info` alias are deleted.

## Consequences

The tutorial path is three calls, and no identifier is typed twice. A user who moves from one provider
to two changes function name and return type rather than passing a larger selection, which is the cost
of refusing to merge provenance. Catalogue predicates beyond provider, station and product require the
Polars escape hatch, and there is deliberately no harmonised name or river search, because ADR-0015
removed those columns from the canonical catalogue. `source_metadata` depends on the per-provider
native table being readable at runtime, which is still open on the packaging ticket. Selections are
constructed only by `find`, `pick` and `from_frame`, so any future discovery capability enters through
those three points rather than by adding methods to a returned object.
