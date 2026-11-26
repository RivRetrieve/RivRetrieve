# Netherlands Rijkswaterstaat (`nl_rws`) — retrieval behavior

Complete [Effort #1051](https://github.com/RivRetrieve/RivRetrieve/issues/1051)
by implementing `nl_rws`'s request configuration, window declarations, HTTP
acquisition, and single-pass shared response parsing (`config.py`, `fetch.py`,
`parse.py`) on branch `port/nl-rws`. Verified completion of this vision
completes `#1051`; publishing this vision alone does not.

This Effort builds on completed Steps 1–3
([#1048](https://github.com/RivRetrieve/RivRetrieve/issues/1048),
[#1049](https://github.com/RivRetrieve/RivRetrieve/issues/1049),
[#1050](https://github.com/RivRetrieve/RivRetrieve/issues/1050)),
coordination issue [#355](https://github.com/RivRetrieve/RivRetrieve/issues/355),
and the continuing private research record `research/nl-rws-source-access.md`
plus retained collection `nl_rws-access-2026-11-25-v1` (release `458265071`)
in `RivRetrieve/verification-evidence`. Follow
[provider-port step 4](../../docs/maintenance/provider-ports.md). Keep all
work on `port/nl-rws` — never merge into `main` before final review
[#1055](https://github.com/RivRetrieve/RivRetrieve/issues/1055) is approved.

## Outcome

Implement the runtime retrieval modules under
`src/rivretrieve/_internal/providers/nl_rws/`:

- `src/rivretrieve/_internal/providers/nl_rws/config.py` — `ProviderConfig`,
  typed `SourceCoordinates` for all 10 admitted `nl_rws` products, and
  `ProductWindowDeclarations` with empirically validated chunk spans.
- `src/rivretrieve/_internal/providers/nl_rws/fetch.py` — `fetch()` sending
  `POST /ONLINEWAARNEMINGENSERVICES/OphalenWaarnemingen` with
  `ProcesType = "meting"`, adaptive co-acquisition when both `NVT` and `GEM24H`
  for the same `(Grootheid, Eenheid, Hoedanigheid)` are requested together, and
  clean failure isolation via `attempt_request`.
- `src/rivretrieve/_internal/providers/nl_rws/parse.py` — `parse()` and
  `parse_group()` (`SharedParseProvider` contract) decoding JSON once per
  co-acquired payload into independent per-product `ParsedSeries` results,
  preserving distinct parallel `WaardeBepalingsMethode` streams, published null
  observations (`Kwaliteitswaardecode == "99"` / `9.99999e+37`), and
  `nl_rws.observation` annotations (`statuswaarde`, `kwaliteitswaardecode`).
- Focused source-independent tests in `tests/test_nl_rws_fetch.py` and
  `tests/test_nl_rws_parse.py` (or combined `tests/test_nl_rws_retrieval.py`).

Step 4 does not implement `declaration.py` or built-in provider manifest /
origin-gate registration (`BUILTIN_PROVIDER_IDS`,
`ORIGIN_GATE_ENROLLED_PROVIDERS`); those belong to Step 5 (`#1052`).

## Settled decisions

### 1. Endpoint, request body, and pacing

- **Endpoint:** `POST https://ddapi20-waterwebservices.rijkswaterstaat.nl/ONLINEWAARNEMINGENSERVICES/OphalenWaarnemingen`
  with `Content-Type: application/json`, `Accept: application/json`, and
  `ReplaySafety.SAFE` (read-only query over `POST`, permitting shared transport
  retries on transient failures).
- **Mandatory filter fields on every request:**
  - `Locatie: {"Code": station_id}`
  - `AquoPlusWaarnemingMetadata.AquoMetadata`: `Compartiment: {"Code": "OW"}`,
    `Grootheid`, `Eenheid`, `Hoedanigheid`, and **`ProcesType: "meting"`**
    (always enforced so forecasts `verwachting` and astronomical tides
    `astronomisch` are never requested or returned).
  - `Periode`: `Begindatumtijd` and `Einddatumtijd` rendered from the engine's
    `RenderedWindow` bounds without shifting them, using explicit fixed
    `+01:00` ISO-8601 timestamps (`YYYY-MM-DDTHH:MM:SS.000+01:00`).
- **Pacing:** Use RivRetrieve's shared transport default pacing (≥1 s between
  requests); no custom `ProviderRateLimit` override is needed.

### 2. Window declarations and empirically validated chunk spans

Live multi-gauge benchmarking on 2026-11-26 across 5 gauges
(`lobith.bovenrijn.tolkamer`, `eijsden.grens`, `arnhem.nederrijn`,
`ameland.nes`, `maarssen.kanaal`) established:
- `NVT` at **90 days**: 2.28–4.38 s, 3.79–7.94 MB (even with parallel `F216`+`F230`
  10-minute series at Lobith: 26,208 rows). At 365 days, Lobith reached 16.72 s
  / 31.91 MB (105,408 rows).
- `GEM24H` at **10 years (3,650 days)**: 0.62–1.12 s, 0.66–1.31 MB (even with
  2–3 parallel series at Lobith and Eijsden).

Accordingly:
- `ProviderConfig.zone = ZoneValue("+01:00")`.
- `WindowDeclaration`: `WindowGranularity("iso-instant")`,
  `WindowRenderingVocabulary.ISO_INSTANT`, `StopConvention.INCLUSIVE`.
- **Chunk spans (`max_span`):**
  - **`timedelta(days=90)`** for all 7 `NVT` products (`discharge_m3s_nvt`,
    `discharge_m3d_nvt`, `stage_nap_nvt`, `stage_plaatslr_nvt`, `stage_msl_nvt`,
    `stage_taw_nvt`, `water_temperature_nvt`).
  - **`timedelta(days=3650)`** (~10 years) for all 3 `GEM24H` products
    (`discharge_m3s_gem24h`, `stage_nap_gem24h`, `water_temperature_gem24h`).

### 3. Adaptive co-acquisition and `SharedParseProvider` (`parse_group`)

Live probing confirmed DDAPI 2.0 filters `WaardeBewerkingsMethode` server-side:
- **Joint `NVT` + `GEM24H` request for the same `(Grootheid, Eenheid, Hoedanigheid)`:**
  When `fetch()` receives both the `NVT` and `GEM24H` products for the same
  physical group (`Q`/`m3/s`/`NVT`, `WATHTE`/`cm`/`NAP`, or `T`/`oC`/`NVT`),
  co-acquire them in **one** POST per 90-day chunk by omitting
  `WaardeBewerkingsMethode` from `AquoMetadata`, and attach the shared payload
  to both products so `parse_group()` decodes the JSON once into independent
  per-product `ParsedSeries` results and immediately drops intermediate decoded
  structures.
- **Single-product request (`NVT`-only or `GEM24H`-only):**
  Pass `WaardeBewerkingsMethode: {"Code": "NVT"}` or `{"Code": "GEM24H"}`
  explicitly on the POST body so a 10-year `GEM24H`-only query never downloads
  10-minute `NVT` rows (staying ~1 MB / ~1 s per decade) and an `NVT`-only
  query downloads no extra `GEM24H` rows.
- When `rendered_windows` differ between co-acquired `NVT` (90d) and `GEM24H`
  (3,650d) products, use the 90-day `NVT` chunks to cover the requested window
  for both products (since the union of the 90-day chunks covers the exact same
  requested window for `GEM24H`).

### 4. Empty responses, errors, and parsing semantics

- **Empty windows (`HTTP 204 No Content` / 0-byte body or empty `WaarnemingenLijst`):**
  Return `OutcomeStatus.EMPTY` (not a failure). `fetch.py` must not branch on
  `response.status_code` directly (respecting `test_provider_architecture_contracts.py`):
  `HTTP 204` is a 2xx response whose body is `b""`, which `parse.py` maps to
  `OutcomeStatus.EMPTY`.
- **Errors (`HTTP 400`, `5xx`, transport errors):**
  Surface through `attempt_request` as `FailedSourceRequest` →
  `OutcomeStatus.FAILED` so independent stations/products still return partial
  results.
- **Parsing (`parse()` and `parse_group()`):**
  - Reuse Step 3's `resolve_response_series()`, `parse_tijdstip_offset()`,
    `is_missing_observation_value()`, and `NL_RWS_OBSERVATION_SCHEMA`.
  - Keep parallel `WaardeBepalingsMethode` streams separate without collapsing.
  - Filter out any unexpected out-of-scope series (`resolve_response_series()`
    returning `None`) cleanly without crashing or mixing into admitted products.
  - Emit published null rows (`value = None`) for `Kwaliteitswaardecode == "99"`
    / `9.99999e+37` / `None` / `".999999E+38"` linked in `nl_rws.observation`
    with `measured = True` and `measurement_index = <row_idx>`.
  - Keep `0.0` and negative values (coastal/polder stage, cold water) numeric.
  - Return `OutcomeStatus.EMPTY` for a requested product if the decoded JSON
    contains series only for the *other* co-acquired product (e.g. a 1990 window
    containing `GEM24H` only and no `NVT` rows).

## Evidence of completion

1. `src/rivretrieve/_internal/providers/nl_rws/{config,fetch,parse}.py`
   implemented on `port/nl-rws` (passing `ruff format --check`, `ruff check`,
   and `ty check src`).
2. Focused source-independent tests verifying:
   - `config()` and `window_declarations()` (10 products, `+01:00`, `INCLUSIVE`,
     90d `NVT` vs 3,650d `GEM24H` chunking).
   - `fetch()` enforces `ProcesType = "meting"`, passes `WaardeBewerkingsMethode`
     for single-product calls, co-acquires in a single POST (omitting
     `WaardeBewerkingsMethode`) when both `NVT` and `GEM24H` of a pair are
     requested, and isolates per-station/product transport failures.
   - `parse()` and `parse_group()` decode shared JSON once into independent
     per-product `ParsedSeries`, handle `b""` (`HTTP 204`) and empty
     `WaarnemingenLijst` as `OutcomeStatus.EMPTY`, preserve parallel
     `F216`/`F230` streams, map `9.99999e+37`/`"99"` to published `None` with
     linked `nl_rws.observation` annotations, preserve `0.0`/negative readings,
     and handle a co-acquired response where only one of `NVT`/`GEM24H` has rows.
   - `tests/test_provider_architecture_contracts.py` passes with zero violations.
3. Independent review completed, PR merged into `port/nl-rws` (never `main`),
   and completion summary posted when closing `#1051`.
