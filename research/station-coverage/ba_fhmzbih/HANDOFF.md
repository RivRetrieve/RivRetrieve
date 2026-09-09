# ba_fhmzbih implementation handoff

For the implementing agent. Everything below is established by a recording in `recordings/`
unless it appears under "Not established". Nothing here is inferred from how identifiers look.
Per-station-per-product results are evidenced in `evidence/`, one file per pair.

Baseline commit: `67796ab8d793867aaaaf9c6fb55bec208adaeab8` · native table captured `2026-08-02T12:42:03Z`
· this survey captured `2026-09-09`.

## 1. Population and identity

The publisher exposes per-parameter **layers**. The authoritative list is
`layers/index.json` (`recordings/layers_manifest.recording.json`), which declares ten layers.
The three RivRetrieve products map to exactly three of them:

| Product | Layer | Layer label | Source code |
| --- | --- | --- | --- |
| `discharge_reported` | 20 | Proticaj | `Q` |
| `stage_reported` | 10 | Vodostaj | `H` |
| `water_temperature_reported` | 30 | Temperatura vode | `WT` |

The remaining seven layers are outside the surveyed population:
40 `GroundWaterLevel` and 50 `GroundWaterTemp` carry object type `General;Stanica podzemnih voda`;
60 `Precipitation` and 70 `AirTemp` carry `General;Meteorološka stanica`.
80 `EPPWaterLevel` and 90 `EPPFlow` are the "ekološki prihvatljiv protok" series — note these carry
object type `General;Hidrološka stanica`, the *same* type as the surveyed 99, so object type does
not distinguish them. They are excluded by layer alias. See `UNRESOLVED.md` §7.

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
| `#Rows` | the publisher's count of **timestamped rows** — not of measurements (see §4) |

Units match the committed `config.py` exactly.

## 4. Availability basis

**Availability is established from the measurement cells, not from `#Rows`.** The header's `#Rows`
field counts timestamped rows. A workbook can declare hundreds of rows while every measurement cell
is published empty: 35 of the 297 surveyed pairs are exactly that.

Read the measurement cells from the worksheet XML. A published blank is a cell element with no
value child:

```
<c r="B171" s="3"/>                        no measurement
<c r="B5196" s="5" t="n"><v>1.331</v></c>  a measurement
```

A dataframe loader renders both as `NaN`, so it cannot distinguish a published blank from a decode
failure. `scripts/workbook_evidence.py:read_workbook` is the reference implementation.

| Status | Meaning |
| --- | --- |
| `measurements_present` | at least one populated measurement cell in the download |
| `timestamped_without_measurements` | timestamped rows, every measurement cell published empty |
| `no_data_rows` | no data rows at all; parameter and unit still declared |
| `access_failed` | the route served no workbook (HTTP 404) |

A blank-only or empty download still declares the station's parameter name and unit. That states
what this download contained. It is **not** a statement that the station cannot measure the
parameter, and must not be recorded as one.

HTTP status carries no availability signal: populated, blank-only and empty workbooks all return
200. Only genuinely absent routes return 404.

## 5. Temporal horizon

**Established.** Two workbook periods serve measurements:

- `*_1M.xlsx` — a recent one-month window
- `*_1Y.xlsx` — a recent one-year window; across the 2026-09-09 capture the observed span runs
  2025-09-10 → 2026-09-09

Each pair's own observed window is recorded in the inventory as `observed_window_start` /
`observed_window_end`, tied to that capture's acquisition instant. Treat these as *recent rolling
windows*: the span moves with the capture date, and a later fetch returns a later window.

**Attempted and refused.** 64 attempts across 4 stations and 3 products, each with its own
preserved response under `evidence/horizon/` and recorded in `inventory/horizon_probe.csv`:
`_1D`, `_1W`, `_3M`, `_6M`, `_2Y`, `_5Y`, `_10Y`, `_ALL`, `_COMPLETE`, `_HIST` and the `.csv`,
`.json` and `.zip` variants each returned 404 on every target tried. Directory listing returned
403; recorded, not bypassed.

**Not established.** That no longer-history access method exists. The attempts above establish only
that these filename variants are not served at this route on the stations tried. Whether the
publisher offers an archive by some other means was not investigated — see `UNRESOLVED.md` §6.

**Consequence for the adapter.** The configured route provides a recent rolling window only. That
is a limitation of this route, and it must not be stated as a limitation of every access method the
publisher might offer.

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

- **Do not treat the `#Rows` header as a measurement count.** It counts timestamped rows. 35 of the
  297 surveyed pairs declare rows > 0 with every measurement cell published empty. Read the cells.
- **Do not read measurement cells through a dataframe loader alone.** A published blank and a decode
  failure both surface as `NaN`; only the cell element distinguishes them.
- Do not treat layer membership as availability. Station `4110` is absent from layer 30 yet its WT
  workbook carried 1,827 populated values on the 2026-09-09 capture.
- Do not treat HTTP 200 as availability. 290 of 297 pairs returned 200, across three different
  classifications.
- Do not treat file size as availability. Blank-only and populated workbooks overlap in bytes per row.
- Do not derive `site_no` from the station id.
- Do not convert a blank-only or empty download into "unsupported measurement". It establishes what
  that download contained, nothing about the station's capability.
- **Do not treat an older requested window returning no measurements as evidence that a station
  lacks historical data.** It is a limit of this rolling route.
- Do not state that longer history cannot be retrieved by any means. That was not established.
- Do not infer a timezone, statistic, frequency, or record bound from anything in this survey.
