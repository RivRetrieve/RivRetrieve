# ba_fhmzbih implementation handoff

For the implementing agent. Everything below is established by a recording in `recordings/`
unless it appears under "Not established". Nothing here is inferred from how identifiers look.

Baseline commit: `67796ab8d793867aaaaf9c6fb55bec208adaeab8` · native table captured `2026-08-02T12:42:03Z`
· this survey captured `2026-09-07`.

## 1. Population and identity

The publisher exposes per-parameter **layers**. The authoritative list is
`layers/index.json` (`recordings/layers_manifest.recording.json`), which declares ten layers.
The three RivRetrieve products map to exactly three of them:

| Product | Layer | Layer label | Source code |
| --- | --- | --- | --- |
| `discharge_reported` | 20 | Proticaj | `Q` |
| `stage_reported` | 10 | Vodostaj | `H` |
| `water_temperature_reported` | 30 | Temperatura vode | `WT` |

The remaining seven layers are out of scope and evidenced as such:
40 `GroundWaterLevel` and 50 `GroundWaterTemp` carry object type `General;Stanica podzemnih voda`;
60 `Precipitation` and 70 `AirTemp` carry `General;Meteorološka stanica`;
80 `EPPWaterLevel` and 90 `EPPFlow` are the "ekološki prihvatljiv protok" series.

**Identity.** `metadata_station_no` is the public `station_id` (unique, no nulls, 0 duplicates
across the population). `metadata_site_no` is the workbook path group. Both come from the layer
documents. One station id is non-numeric (`2101-B`), so station ids must stay strings.

**Population.** The committed baseline of 60 is exactly the layer-20 membership. The union of
layers 10/20/30 is **99** hydrological stations. See `FINDINGS.md` §2 for the reconciliation and
the scope decision this raises.

## 2. Retrieval route

```
https://vodostaji.voda.ba/data/internet/stations/{site_no}/{station_no}/{code}/{workbook}
```

| Product | code | workbook |
| --- | --- | --- |
| `discharge_reported` | `Q` | `Q_1Y.xlsx` |
| `stage_reported` | `H` | `H_1Y.xlsx` |
| `water_temperature_reported` | `WT` | `Tvode_1Y.xlsx` |

`site_no` must be resolved from a layer document, never derived from the station id. The current
adapter resolves it from `layers/20/index.json` only; that is the mechanism that clipped the
catalogue to 60 stations (see `FINDINGS.md` §2).

## 2a. Request shape, pagination and access requirements

**Access requirements: none.** Every route surveyed is public and unauthenticated. No API key,
token, cookie or session is involved, and none was sent. There is nothing to preflight.

**Pagination: none.** Layer documents are unpaginated JSON arrays returned whole (layer 10 is the
largest at 99 objects / 106 KB). The layer manifest is a single object. Workbooks are single-sheet
XLSX files returned whole. No `Link` header, cursor, offset or page parameter appears on any route.

**Request windows: none.** The workbook route accepts no date parameters of any kind — the period is
fixed in the filename (`_1M` / `_1Y`). This is why the provider declares source-fixed windows and
why the engine renders no window for these calls. The tested windows are therefore exactly the two
the publisher offers; there is no window to vary. Clipping to the user's requested range happens
after parsing, as it does today.

**Distinct response shapes recorded:** unpaginated JSON array (layer documents), JSON object (layer
manifest), XLSX with a populated body, XLSX with a header block and zero data rows, HTTP 404 for an
absent route, HTTP 403 for a refused directory listing.

## 3. Source fields and units

Every workbook begins with an 8-row header block, then `#Timestamp` / `Value` rows.

| Header field | Meaning |
| --- | --- |
| `#Station Name`, `#Station Number` | station identity |
| `#Station Parameter Name` | `Proticaj` / `Vodostaj` / `Temperatura vode` |
| `#Timeseries Name` | `81 Web Kontinuirani` for all three products, at every station observed |
| `#Unit Symbol` | `m³/s` (Q), `cm` (H), `°C` (WT) |
| `#Rows` | **the publisher's own count of observations in the workbook** |

Units match the committed `config.py` exactly. `#Rows` is the availability basis used throughout
this survey: it is a published statement, not a size heuristic.

## 4. Availability basis

`#Rows > 0` means the publisher states the rolling workbook contains observations.
`#Rows = 0` means the publisher states it contains none **while still declaring the parameter and
its unit for that station**. That is not a statement that the station cannot measure the parameter,
and it is not recorded as one.

HTTP status carries no availability signal: every populated and every empty workbook returns 200.
Only genuinely absent routes return 404.

## 5. Temporal horizon

Two workbook periods exist, established by probing and recorded:

- `*_1M.xlsx` — one month (`recordings/horizon_4024_Q_1M_exists.recording.json`, span 2026-08-08 → 2026-09-07)
- `*_1Y.xlsx` — one year (span 2025-09-07 → 2026-09-06 at station 1020)

`_1D`, `_1W`, `_3M`, `_6M`, `_2Y`, `_5Y`, `_10Y`, `_ALL`, `_COMPLETE`, `_HIST` all return 404
(`recordings/horizon_4024_Q_5Y_absent.recording.json`). `.csv`, `.json` and `.zip` variants return 404.
Directory listing is refused with 403 and was not bypassed
(`recordings/horizon_directory_listing_403.recording.json`).

**Consequence: historical requests beyond one year cannot be fulfilled through this route.**
A request for an older window is not evidence that a station lacks data; it is outside the
published horizon. The adapter's source-fixed window declaration is correct.

## 6. Time semantics

Workbook timestamps are naive — the cells carry no zone marker. No official zone statement was
found, so `zone` must stay `unknown`, as it is today.

One adjacent fact, recorded but deliberately **not** promoted to a zone claim: the live layer
documents carry `L1_timestamp` values with a `+02:00` offset. That describes the live snapshot
field, not the workbook timestamps, and the two were not shown to share a zone.

`#Timeseries Name` is `81 Web Kontinuirani` throughout, which names a timeseries but does not state
statistic, frequency, period type or period anchor. Those remain `unknown`.

Station descriptions in the station document give founding and renovation years (e.g. "Stanica
osnovana 1963. godine"). These are **not** published record bounds and must not be used as such.

## 7. Producer

Established: the portal is operated by **Agencija za vodno područje rijeke Save**
(`recordings/portal_root.recording.json` — the page title; the host is a subdomain of the agency's
own `voda.ba`). The committed `origins.py` issuer is therefore correct.

Not established: whether that agency *produces* the observations or republishes them. See
`UNRESOLVED.md` §1 — this is a question for the delivery owner, not something to infer.

## 8. Things that must not be done

- Do not treat layer membership as availability. Station `4110` is absent from layer 30 yet its WT
  workbook declares 2,002 rows.
- Do not treat HTTP 200 as availability. All 297 probed pairs returned 200 except 7 genuine 404s.
- Do not derive `site_no` from the station id.
- Do not convert `#Rows = 0` into "unsupported measurement".
- Do not infer a timezone, statistic, frequency, or record bound from anything in this survey.
