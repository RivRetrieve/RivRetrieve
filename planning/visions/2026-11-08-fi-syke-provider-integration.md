# Finland SYKE provider integration

Make SYKE observations available through RivRetrieve's public selection,
retrieval and cache interfaces under `fi_syke`. Deliver the agreed scope for
[Effort #757](https://github.com/RivRetrieve/RivRetrieve/issues/757) (step 5
of the [provider-port guide](../../docs/maintenance/provider-ports.md)) and
[Program #353](https://github.com/RivRetrieve/RivRetrieve/issues/353),
combined into one PR, following `au_bom`'s own step-5 precedent (commit
`a516db0c`, itself following `at_ehyd`'s PR #676).

Work targets `port/fi-syke` and leaves `main` unchanged until final review.
Full-provider verification against genuine retained public-API captures
stays a later step (#758); the dedicated provider documentation page stays
in #759. This step does not defer the checks needed to establish correct
public integration itself.

## Build on the delivered provider work

Steps 1-4 are complete: the packaged catalogue supports offline discovery of
2,543 river-gauge stations across 3 admitted products; `series.py` resolves
series identity (station_id/`Paikka_Id` witnesses exactly one product) and
stage's `vertical_reference`; `config.py`/`fetch.py`/`parse.py` implement
the real OData request/response handling, including `odata.nextLink`
pagination. `declaration.py` still declares `CatalogueOnly()`, leaving
public observation retrieval disabled — switching that is this step's
actual work.

## Deliver working public retrieval

Connect `config()`, `window_declarations()`, `fetch` and `parse` to
`LiveStages` in `declaration.py`, with `required_credentials=()`, mirroring
`au_bom`/`lt_lhmt`/`cz_chmi`'s own `_Stages` class shape. No
`shared_acquisition_products` is needed or declared: unlike `au_bom`'s
shared `getTimeseriesList` lookup, fi_syke has no prerequisite call to
coalesce across products — each station-product's native table is already
pinned by the catalogue (step 2), and `fetch.py` issues one independent,
self-paginating request per pair.

Update the repository-wide capability contracts so they reflect live
`fi_syke` retrieval:

- `docs/_generated/reference-tables.md` (`scripts/generate_reference.py`):
  `fi_syke`'s observation kind changes from `catalogue-only` to `live`.
- `docs/scripts/coverage_map.py` and `docs/assets/coverage-map.png`:
  `fi_syke` moves from `PLANNED_COUNTRY` (`"FIN"`) to `PROVIDER_COUNTRY`
  (`"fi_syke": "FIN"`), and the map regenerates to show Finland implemented
  rather than planned (confirmed live via the real Natural Earth boundaries
  download: 15 providers, 14 countries, 80,900 unique provider-station
  records).
- Root `README.md`'s provider table: adds Finland / Finnish Environment
  Institute (Syke), Hydrologiarajapinta / `fi_syke` / 2,543 stations / Open
  access, and updates the count sentence from "fourteen different providers
  in thirteen countries" to "fifteen different providers in fourteen
  countries." Like `au_bom`'s row, fi_syke's packaged `stations.parquet` is
  already the fully-selectable 2,543-station set — no narrowing caveat
  sentence is needed.

Also corrects a now-stale claim: step 2's packaged `catalogue/provider.json`
states `"bulk_observations": "unknown: fi_syke is CatalogueOnly; retrieval
behavior is not yet implemented"`. That claim is false once this step ships.
`generate_catalogue.py`'s `build_provider_info()` and the already-published
`catalogue/provider.json` both get corrected text, describing the real
mechanism steps 3-4 actually built: one Hydrologiarajapinta OData request
per station-product, paginated via `odata.nextLink` (never `$top`, which
would suppress it), with no shared or batched request across products.
`live_stations`/`live_products`/`live_station_products` stay `False` — these
describe whether the catalogue itself was built from a live query, not
whether retrieval is live, matching `au_bom`'s own flip leaving them `False`
too.

Unlike `au_bom`'s step 5, no `PRODUCT_DEFINITIONS`-relocation fix is needed:
fi_syke's `ProductDefinition`/`PRODUCT_DEFINITIONS` already lived in
`series.py`, not `generate_catalogue.py` (a `MAINTAINER_ROLES` module
`declaration.py`'s runtime import graph must never reach), from the very
first catalogue PR.

The catalogue artifact is rebuilt from the exact same retained evidence used
in steps 3-4 — no new captures, no re-selection. Only `provider.json` (new
text), `croissant.json` and `provenance.json` (code-revision bump) change;
`products.parquet`/`stations.parquet`/`station_products.parquet`/
`station_metadata.parquet`/`series_claims.parquet`/`format.json`/
`source_series.json` are confirmed byte-identical to what steps 3-4 already
shipped.

## Tests

`tests/test_fi_syke_public.py` (new): public `rr.find`/`rr.fetch` tests
through `monkeypatch.setattr(discovery, "HttpClient", _Transport)`, mirroring
`tests/test_au_bom_public.py`'s shape but exercising fi_syke's own OData JSON
shape. Covers: unit conversion (stage's cm-to-m, the one real conversion
fi_syke has — `Arvo=11017` cm -> `110.17` m), a `Lippu_id` flag surfacing as
an info-severity `Issue` without dropping the value, an empty-range `EMPTY`
outcome, and a reported transport failure. `tests/test_reference_contracts.py`
and `tests/test_boundary_probe_harness.py` updated for the new live-provider
counts and fi_syke's 3 product obligations.

## Completion

Full suite stays green. Post a concise status update on #757 referencing
this vision; keep #757 open until the implementation PR merges.
