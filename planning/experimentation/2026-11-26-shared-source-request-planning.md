# Shared Source Request Planning: Stage 0 Empirical Batching Study

Related vision: [2026-11-26-shared-source-request-planning.md](../visions/2026-11-26-shared-source-request-planning.md)

## Questions

Before implementing multi-station request batching inside `SourceRequestPlanner`, we probed candidate multi-station upstream APIs live to establish:

1. Hard publisher limits (maximum station/series selectors per call, pagination mode, depth caps, HTTP method constraints).
2. Measured cost and exact data equivalence between N single-target requests and batched requests.
3. Out-of-order response ordering and window/page overflow behavior.
4. Partial-failure behavior when a valid selector is batched alongside an invalid, missing, or malformed selector.

Providers whose HTTP routes address single files or single-series path parameters (`ba_fhmzbih`, `cz_chmi`, `th_thaiwater`, `br_ana`, `ar_ina`, and the snapshot-bulletin shape used in synthetic `bg_nimh` tests) share or target fixed files rather than comma-joined server filters and did not require live batching discovery probes (`ar_ina` series observation route `/obs/puntual/series/{series_id}/observaciones` was checked for completeness).

## Summary Decisions

| Provider | Operation | Decision | Limit / Packing Rule | Primary Reason |
| :--- | :--- | :--- | :--- | :--- |
| `fr_hubeau` | `v2/hydrometrie/obs_elab` GET | Adopt | Single-station unchanged (`size=2500`); batch up to 50 `code_entite` values | OpenAPI max 100 codes; cursor pagination passed 40,000 rows without depth failure; exact equivalence verified |
| `fr_hubeau` | `v1/temperature/chronique` GET | Adopt | Single-station unchanged (`size=2500`); workload-aware cap `max(1, min(50, 10_000 // (48 * max(1, days))))` | OpenAPI max 200 codes; hard `page * size <= 20000` depth cap (`ValidatePageDepth` HTTP 400); large batches timeout or exceed 20,000 depth |
| `no_nve` | `GET /api/v1/Series` | Deduplicate only | 1 GET per `(station_id, parameter)` (do not comma-join `StationId`) | HTTP 400 regex rejects comma-separated `StationId`; 0 GETs when versions are explicit |
| `no_nve` | `Observations` retrieval | Adopt | Single target keeps `GET /api/v1/Observations`; 2+ targets batch via `POST /api/v1/Observations` JSON array (max 25 items) | Exact equivalence verified even across mixed `versionNumber` values (33x faster); mixed invalid item omitted cleanly under HTTP 200 |
| `au_bom` | `getTimeseriesList` GET | Adopt | Single station unchanged; batch up to 25 comma-separated `station_no` values | Exact equivalence verified (7.7x faster); invalid `station_no` omitted cleanly under HTTP 200 |
| `au_bom` | `getTimeseriesValues` GET | Adopt (with guard) | Single `ts_id` unchanged; batch up to 20 inventory-validated `ts_id` values sharing `(from, to, returnfields)`; unverified explicit `ts_id` stays size 1 | Exact equivalence verified (6.8x faster); blocks arrive out of order (must route by `ts_id`); invalid `ts_id` fails the entire batch with HTTP 500 `InvalidParameterValue` |
| `ch_foen` | GraphQL `data_10min_mean` / `data_1hour_mean` | Defer | Keep per-station requests | Hard unpaginated 10,000-row limit (`ValidationError` on 10st x 7d `data_10min_mean`) would fail valid multi-station windows |
| `fi_syke` | OData `or` filter | Defer | Keep per-station requests | 500-row `$skip` pagination increases multi-page drift risk for modest call reduction |
| `usgs_nwis` | OGC `continuous/items` | Defer | Follow-up work | Works with comma-separated `monitoring_location_id`; defer pending dedicated pagination and rate/limit audit |
| `ar_ina` | `observaciones` GET | Not supported | Keep per-series requests | Observations route is path-parameterized by a single `series_id` |

## Detailed Measurements and Behavior

### `fr_hubeau`

- **Documented OpenAPI caps**:
  - `GET /api/v2/hydrometrie/obs_elab`: `code_entite` allows comma-separated codes up to **100**; cursor-based pagination (`cursor`).
  - `GET /api/v1/temperature/chronique`: `code_station` allows comma-separated codes up to **200**; page-number pagination (`page`).
- **Measured equivalence and throughput (`size=2500`)**:
  - `obs_elab` (`QmnJ`), 20 stations x 30 days (`2024-06-01`..`2024-06-30`): single = 20 requests, 1.068 s, 96,369 B, 240 rows; batched (20) = 1 request, 0.070 s, 91,658 B, 240 rows (`equivalent: true`).
  - `obs_elab` (`QmnJ`), 20 stations x 1 year: batched (20) = 1 request, 0.138 s, 539,098 B, 1,462 rows.
  - `obs_elab` (`QmnJ`), 50 stations x 30 days: batched (50) = 1 request, 4.343 s, 161,348 B, 420 rows (HTTP 200).
  - `temperature`, 15 stations x 7 days: single = 15 requests, 0.956 s, 1,442,983 B, 1,692 rows; batched (15) = 1 request, 0.193 s, 1,439,729 B, 1,692 rows (`equivalent: true`).
  - `temperature`, 15 stations x 30 days: batched (15) = 3 pages (HTTP 206), 0.843 s, 5.21 MB, 6,128 rows.
- **Depth limits and timeouts**:
  - `obs_elab` with `size=5000` over 100 stations x 7 years completed 8 consecutive HTTP 206 cursor pages (40,000 rows, `has_more: true`) with no server error.
  - `temperature` with `size=5000` over 30 stations x 3 years returned HTTP 206 on pages 1..4 (20,000 rows) and **HTTP 400** (`ValidatePageDepth`: `page * size` cannot exceed 20,000) on page 5. Large unbudgeted queries (for example 50 stations x 90 days in initial probing) also timed out at 20 s. Both endpoints accept `size=20000` for small windows, while `size=2500` avoids per-page transfer spikes and matches existing single-station paging.
- **Partial failure behavior**:
  - Mixing an absent code (`ZZZZ999999`) or malformed token (`NOT_VALID_!@#`) in `code_entite` / `code_station` returned **HTTP 200** containing rows for valid stations and omitting the absent/malformed codes cleanly (no partial HTTP 4xx/5xx error contamination).
  - Because absent or empty stations yield no rows on intermediate pages, batched `EMPTY` conclusions must only be recorded after the final pagination page completes cleanly with zero errors. Any late-page failure leaves every station-product in that paginated batch `UNRESOLVED`.

### `no_nve`

- **`GET /api/v1/Series`**:
  - OpenAPI regex requires a single station pattern (`^([0-9]+)\.([0-9]+)\.(\*|[0-9]+)|([0-9]+)\.(\*)\.(\*)$`).
  - Comma-joining 5 `StationId` values returned **HTTP 400** (`One or more validation errors occurred`).
  - Single-station paced lookups: 5 requests, 1.99 s, 4,935 B.
  - Decision: deduplicate `/api/v1/Series` lookups by `(station_id, parameter)` across resolution products (3->1 lookups per station for stage/discharge/daily products; 0 lookups when versions are explicit).
- **`POST /api/v1/Observations` vs `GET /api/v1/Observations`**:
  - Swagger `ObservationsRequestPost` schema accepts a JSON array of objects with string `stationId`, `parameter`, `resolutionTime`, optional integer `versionNumber`, and optional string `referenceTime`. (PascalCase keys with integer `parameter`/`resolutionTime` failed HTTP 400 validation; camelCase/string `parameter` & `resolutionTime` succeeded.)
  - 5 stations across mixed versions (`1.10.0` v1, `1.14.0` v1, `1.15.0` v2, `1.167.0` v1, `1.198.0` v1), 30 days daily (`ResolutionTime=1440`):
    - Single `GET`: 5 requests, 1.638 s (incl. 0.25 s pacing), 5,063 B, 30 rows.
    - Single `POST /api/v1/Observations` JSON array: 1 request, 0.049 s, 3,522 B, 30 rows, HTTP 200 (`equivalent: true`, 33.4x faster).
    - `GET /Observations` comma-separated across the 4 v1 stations: HTTP 200, 0.049 s, 1,204 B (`equivalent: true`), limited to requests sharing `parameter`, `resolutionTime`, and `versionNumber`.
  - **Partial failure behavior**:
    - `POST /api/v1/Observations` with one valid station (`1.10.0`) and one nonexistent station (`9999.9999.0`) returned **HTTP 200** with 1 data entry for `1.10.0` and omitted `9999.9999.0`. Comma-separated `GET /Observations` behaved identically.
  - **Pacing note**: Rapid unpaced bursts can return HTTP 429 on HydAPI. Batching 2+ observation targets into `POST /api/v1/Observations` (up to 25 targets per POST while keeping single-target requests on `GET /api/v1/Observations` to preserve recorded single-series call shapes) cuts both request count and rate-limit pressure substantially.

### `au_bom`

- **`getTimeseriesList` (KiWIS)**:
  - 8 stations: single = 8 requests, 2.593 s, 47,486 B -> comma batch = 1 request, 0.338 s, 46,989 B (`equivalent: true`, 7.7x faster).
  - 30 stations: comma batch = 1 request, 0.468 s, 149,959 B, 1,807 rows (HTTP 200).
  - Mixed invalid `station_no` (`410730,INVALID_NO_SUCH,138020A`): **HTTP 200**, 236 rows for valid stations, invalid station cleanly omitted.
- **`getTimeseriesValues` (KiWIS)**:
  - 8 `ts_id`s: single = 8 requests, 2.599 s, 3,346 B -> comma batch = 1 request, 0.384 s, 3,339 B (`equivalent: true`, 6.8x faster).
  - **Out-of-order blocks**: Requested `ts_id` order `[454627010, 454584010, ...]` came back ordered differently (`14838010, 454719010, 14776010, ...`). Consumer routing must match each block's own `ts_id` metadata rather than positional index.
  - 25 `ts_id`s over 15 days: 1 request, 0.632 s, 12,552 B, 25 blocks (HTTP 200).
  - **Mixed invalid `ts_id` caveat**: Batching `454627010,999999999` returned **HTTP 500** (`InvalidParameterValue`: "One or more of the entered timseries ids could not be found."), failing the entire batch. Therefore `au_bom` only batches `ts_id`s established by `getTimeseriesList` inventory (capped at 20 per call), and isolates unverified explicit caller `ts_id` selectors as singletons.

### `ch_foen`

- `data_1hour_mean` (5 stations x 2 days): single = 5 requests, 15.592 s, 38,442 B, 240 rows -> batch = 1 request, 3.785 s, 38,214 B, 240 rows (`equivalent: true`).
- `data_10min_mean` (10 stations x 2 days): single = 10 requests, 30.143 s, 456,312 B, 2,880 rows -> batch = 1 request, 4.443 s, 455,799 B, 2,880 rows (`equivalent: true`).
- `data_10min_mean` (10 stations x 7 days): single = 10 requests, 32.442 s, 1,595,242 B, 10,080 rows -> batch = **HTTP 200 GraphQL error** (`ValidationError`: "Query returned more than 10000 rows. Please narrow your query using filters or specify a limit."), `data: null`, 0 rows (`equivalent: false`).
- Decision: defer `ch_foen` batching because combining stations without pagination hits the hard 10,000-row limit on windows that succeed per station.

### `fi_syke`, `usgs_nwis`, and `ar_ina`

- **`fi_syke`**: Multi-station OData `(Paikka_Id eq ... or ...)` returned HTTP 200 and paginated at 500 rows with `odata.nextLink` (`$skip=500`). Deferred due to small 500-row page size and `$skip` offset pagination.
- **`usgs_nwis`**: Continuous OGC `monitoring_location_id` comma batch (5 stations x 7 days): single = 5 requests, 2.60 s, 1,665,218 B, 3,360 features -> batch = 1 request, 0.663 s, 1,659,699 B, 3,360 features (`has_next: false`). Deferred to a follow-up effort focused on OGC paging/limits.
- **`ar_ina`**: Observations route embeds one integer `series_id` in the path (`/a5/obs/puntual/series/{id}/observaciones`); verified `skip_nulls=true` and `skip_nulls=false` on series `10` (both returned 5 rows). Batching is not supported by the upstream route shape.
