# Netherlands Rijkswaterstaat (`nl_rws`) — station catalogue and metadata

Complete [Effort #1049](https://github.com/RivRetrieve/RivRetrieve/issues/1049)
with a reproducible offline station catalogue builder and approved packaged
catalogue artifacts for the Netherlands hydrometric provider (`nl_rws`) on
branch `port/nl-rws`. Verified completion of this vision completes `#1049`;
publishing this vision alone does not.

This Effort builds on completed Step 1
([#1048](https://github.com/RivRetrieve/RivRetrieve/issues/1048), vision
[`2026-11-25-nl-rws-source-scope-and-access.md`](2026-11-25-nl-rws-source-scope-and-access.md)),
coordination issue [#355](https://github.com/RivRetrieve/RivRetrieve/issues/355),
and the continuing private research record
`research/nl-rws-source-access.md` plus retained collection
`nl_rws-access-2026-11-25-v1` (release `458265071`) in
`RivRetrieve/verification-evidence`. Follow
[provider-port step 2](../../docs/maintenance/provider-ports.md) and the
[evidence guide](../../docs/maintenance/evidence.md). Keep all work on
`port/nl-rws` — never merge into `main` before final review
[#1055](https://github.com/RivRetrieve/RivRetrieve/issues/1055) is approved.

## Outcome

A reproducible catalogue builder (`src/rivretrieve/_internal/providers/nl_rws/generate_catalogue.py`
or equivalent) plus provenance/metadata declarations (`origins.py` /
`station_metadata.py` or equivalent) and packaged catalogue artifacts under
`src/rivretrieve/_internal/providers/nl_rws/catalogue/` that populate, via
RivRetrieve's shared
[catalogue schemas](../../src/rivretrieve/_internal/catalogues/schemas.py) and
[publication path](../../src/rivretrieve/_internal/catalogues/publication.py):

- `StationCatalog`
- `ProductCatalog`
- `StationProductCatalog`
- `ProviderInfoCatalog`
- `SOURCE_METADATA_SCHEMA` (station descriptive metadata projection and source
  view)

Step 2 does not implement series parsing, observation retrieval, or built-in
provider manifest registration (`BUILTIN_PROVIDER_IDS`); those belong to
Steps 3–5 (`#1050`–`#1052`).

## Source input

- **Endpoint:** `POST https://ddapi20-waterwebservices.rijkswaterstaat.nl/METADATASERVICES/OphalenCatalogus`
- **Required `CatalogusFilter` flags:** `Compartimenten`, `Eenheden`,
  `Grootheden`, `Hoedanigheden`, `Parameters`, `Groeperingen`, `ProcesTypes`,
  `WaardeBepalingsMethoden`, and `WaardeBewerkingsMethoden` all set to `true`.
  `ProcesTypes = true` and `WaardeBewerkingsMethoden = true` are mandatory so
  measured series (`ProcesType = "meting"`) and aggregations (`NVT`, `GEM24H`)
  can be filtered accurately without mixing forecasts (`verwachting`),
  astronomical tides (`astronomisch`), or out-of-scope aggregations.
- **Retained genuine baseline:** `01b_catalogus_extended.json` in
  `nl_rws-access-2026-11-25-v1` (2026-11-25 UTC, 14,865,263 bytes, SHA-256
  prefix `80db05e8f6fd3dbf`, 2,494 locations).

## Settled scope

### Station scope and identity

- **All in-scope `Compartiment = OW` stations, no heuristic filtering:** Include
  every `LocatieLijst` entry linked via `AquoMetadataLocatieLijst` to at least
  one admitted product below. In the 2026-11-25 snapshot this yields **1,706
  unique stations**, spanning rivers, canals, lakes, estuaries, coastal/offshore
  gauges, and 3 Caribbean Netherlands (Bonaire) gauges (`hato.kayatilburg`,
  `hato.marinakralendijk`, `kralendijk.plazabeachterminal`).
- **Station identifier:** `station_id = Code` (100% unique across all 2,494
  locations, 0 duplicates; used directly by `OphalenWaarnemingen`).
- **Coordinates and CRS:** All 2,494 locations carry non-null, non-zero `Lat`
  and `Lon` with `Coordinatenstelsel = "ETRS89"` in geographic decimal degrees.
  No projected-CRS reprojection is needed; record the ETRS89 geographic CRS
  honestly (e.g. `EPSG:4258`, matching RivRetrieve's native-geographic EPSG
  convention in `au_bom` rather than silently relabelling ETRS89 as WGS84).

### Product scope and granularity (10 products)

Admit only `Compartiment = "OW"`, `ProcesType = "meting"`, `Groepering = ""`,
and `WaardeBewerkingsMethode` in `{"NVT", "GEM24H"}` across `Q`, `WATHTE`, and
`T`. Key `ProductCatalog` at the physical/aggregation grain
`(Grootheid, Eenheid, Hoedanigheid, WaardeBewerkingsMethode)`:

| `Grootheid` | `Eenheid` | `Hoedanigheid` | `WaardeBewerkingsMethode` | Observed property | Snapshot stations |
|---|---|---|---|---|---:|
| `Q` | `m3/s` | `NVT` | `NVT` | `discharge` | 187 |
| `Q` | `m3/s` | `NVT` | `GEM24H` | `discharge` | 34 |
| `Q` | `m3/d` | `NVT` | `NVT` | `discharge` | 5 |
| `WATHTE` | `cm` | `NAP` | `NVT` | `stage` | 640 |
| `WATHTE` | `cm` | `NAP` | `GEM24H` | `stage` | 67 |
| `WATHTE` | `cm` | `PLAATSLR` | `NVT` | `stage` | 22 |
| `WATHTE` | `cm` | `MSL` | `NVT` | `stage` | 18 |
| `WATHTE` | `cm` | `TAW` | `NVT` | `stage` | 8 |
| `T` | `oC` | `NVT` | `NVT` | `water_temperature` | 1,096 |
| `T` | `oC` | `NVT` | `GEM24H` | `water_temperature` | 24 |

- **Preserve `WaardeBepalingsMethode` for Steps 3–4, not as catalogue products:**
  Do not split `ProductCatalog` into ~60+ rows per `WaardeBepalingsMethode`
  (`other:F006`, `other:F216`, `other:F230`, etc.). Multiple calculation-method
  series for the same physical product are preserved as distinct `SourceSeries`
  identities during parsing/retrieval in `#1050`–`#1051`.
- **Keep the four `WATHTE` vertical references distinct:** `NAP`, `PLAATSLR`,
  `MSL`, and `TAW` are separate products; never collapse or fall back across
  vertical references.
- **Canonical frequency and honest unknowns:** Align `ProductCatalog`
  `frequency`, `statistic`, `period_type`, and `period_anchor` with
  RivRetrieve's canonical ISO 8601 frequency schema (`#1032`). For `GEM24H`,
  daily mean (`P1D`, `mean`) is established by Aquo's *Etmaalgemiddelde*
  definition while `period_anchor` remains honest `unknown` until `#1050`
  establishes day-boundary semantics. For `NVT` (unaggregated), keep
  `frequency`, `statistic`, `period_type`, and `period_anchor` honest where
  `OphalenCatalogus` itself does not declare a single fixed cadence across all
  stations (e.g. 10-minute vs daily `m3/d`).

### Explicit exclusions / deferrals

- `ProcesType` `verwachting` (forecasts) and `astronomisch` (astronomical tide).
- Non-`OW` compartments (`LT`, `BS`, `GW`, etc.) and other `OW` quantities
  outside `Q`, `WATHTE`, and `T`.
- Secondary `WaardeBewerkingsMethode` codes: `SOM` (`Q` `m3/d`, 6 locs),
  `GEMH` (`WATHTE` `NAP` 11, `T` 2), `GEM6H` (`T` 7), `GEM` (`T` 2), and
  `other:EXTMND` (`WATHTE` 2).
- Irregular extreme/tidal `Groepering` series: `GETETM2` (199 locs),
  `GETETMSL2` (4 locs), and `EXTMWTHTE2` (21 locs).

### Station metadata and provider info

- **`SOURCE_METADATA_SCHEMA`:**
  - `Naam` (100% non-blank across all 2,494 locations) → `station_name`.
  - Preserve `Omschrijving` (distinct from `Naam` at 396 locations, carrying
    site/structure descriptions) and `Locatie_MessageID` in the source-view
    metadata table.
  - Do not fabricate `water_body`, `drainage_area`, or `elevation` — DDAPI 2.0
    `OphalenCatalogus` does not publish them.
- **`ProviderInfoCatalog`:**
  - `provider_id`: `"nl_rws"`
  - `name`: `"Rijkswaterstaat"`
  - `license`: `"CC0-1.0"` (verified Public Domain Mark 1.0 / CC0 1.0 in Step 1)
  - `citation`: `"Bron: Rijkswaterstaat – Waterwebservices"`
  - `live_stations = False`, `live_products = False`,
    `live_station_products = False`, `bulk_observations = "none"` (offline
    packaged catalogue + `LiveStages` observation retrieval).
- **`StationProductCatalog`:**
  - Mark catalogue-linked pairs `availability = "available"` with
    `published_record_start_date = null` and `published_record_end_date = null`
    (never infer temporal coverage from `OphalenCatalogus`).

## Evidence of completion

1. Reproducible builder and provenance/metadata modules implemented under
   `src/rivretrieve/_internal/providers/nl_rws/` on `port/nl-rws` (passing
   `uv run ruff check`, `uv run ruff format --check`, and `uv run ty check src`).
2. Approved packaged catalogue artifacts generated from genuine retained
   `01b_catalogus_extended.json` (and any corresponding `verification-evidence`
   catalogue declaration / native-input intake if required by the shared
   catalogue provenance pipeline) and validated against all `CatalogueSchema`
   contracts and `SOURCE_METADATA_SCHEMA`.
3. Focused source-independent tests (synthetic `OphalenCatalogus` fixtures)
   verifying:
   - `ProcesType = "meting"` and `Groepering = ""` filtering (excluding
     `verwachting`, `astronomisch`, `GETETM2`, `EXTMWTHTE2`, `SOM`, `GEMH`,
     `GEM6H`, `GEM`, `other:EXTMND`),
   - Exact 10-product admission and distinct `NAP`/`PLAATSLR`/`MSL`/`TAW`
     vertical references,
   - Deduplication of multiple `WaardeBepalingsMethode` links per station into
     a single `(station_id, product_id)` row,
   - `Naam` → `station_name` and `Omschrijving` / `Locatie_MessageID` source
     metadata preservation,
   - ETRS89 CRS preservation and null record start/end dates.
4. `uv run pytest --logic-only` passes on `port/nl-rws` with no regressions.
5. Independent review completed, PR merged into `port/nl-rws` (never `main`),
   and completion summary posted when closing `#1049`.
