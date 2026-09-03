# za_dws Provider Port Notes

These notes record evidence and decisions for the South African Department of Water and
Sanitation (DWS) Verified Hydrology provider. Provider-specific pain stays here; shared
architecture changes need an ADR. The provider is a `LiveStages` adapter (`config.py`,
`fetch.py`, `parse.py`) over the shared engine. Contributed by: Thiago von Däniken.

## Source Endpoints

| Endpoint | Role | Auth | Notes |
|---|---|---|---|
| `https://www.dws.gov.za/Hydrology/Verified/HyData.aspx` | Observation retrieval: one HTML page per (station, DataType, window) carrying a `<pre>` block of fixed-format rows | None | Query parameters `Station=<id>100.00`, `DataType=Daily\|Point`, `StartDT=YYYY-MM-DD`, `EndDT=YYYY-MM-DD`, `SiteType=RIV`. The literal `100.00` suffix addresses the station's "Variable 100.00 Surface Water Level" and is required. |
| `https://www.dws.gov.za/hydrology/Verified/HyCatalogue.aspx` | Catalogue generation (maintainer-only) | None | Index of eight WMA River PDFs; see the attestation section. |

The adapter sends only through the engine `HttpClient`, so every request carries the repository's
fixed `User-Agent` and no other header.

## Products and source coordinates

| Product ID | DataType | Column read | Native unit | Semantics | Window declaration |
|---|---|---|---|---|---|
| `discharge_daily_mean` | `Daily` | `D AVG F/R` | m³/s | `Daily(DayDefinition("unknown"), DailyLabelTime("00:00"))` | `n-year-chunk`, size 20, date rendering, exclusive stop |
| `discharge_instantaneous` | `Point` | `COR.FLOW` | m³/s | `Instant` | `n-year-chunk`, size 1, date rendering, exclusive stop |
| `stage_instantaneous` | `Point` | `COR.LEVEL` | m | `Instant` | `n-year-chunk`, size 1, date rendering, exclusive stop |

The Daily legend wording is "Daily avg flow rate in cubic metres/sec", which is the source's
statement that the value is a mean. It states no day definition, so the day definition is
`unknown`. Units are the source's own (m³/s, m); the engine performs no conversion.

## Coalesced calls

`fetch` issues exactly one request per (station, DataType, rendered window). Both Point
products are tagged on the same payload and read from the same bytes, and a product repeated in
the request never issues a second identical call. `parse` reads every tagged product's column
out of one payload. This is the pattern the vision names for South Africa ("several requested
products in one source response, never duplicate identical calls"); it is expressed with the
existing `Payload.station_products` tags and needed no engine change.

## Response format (from the real 2020 legacy responses and the portal's own legend)

A `<pre>` block holds a format legend (`POS. a-b = ...` lines), the station id on its own line,
the line `Variable 100.00 Surface Water Level`, a header row (`DATE     D AVG F/R  QUAL` or
`DATE     TIME             COR.LEVEL QUA           COR.FLOW  QUA`), whitespace-delimited data
rows and the terminator `ZZZZZZZZZZZZ`. `parse` requires the legend, the requested station line,
the variable line, the column labels it needs in the header row, and the terminator; a block that
lacks any of these, a row whose token count differs from the header, or a non-numeric value
raises rather than being repaired.

The Point legend's `POS.` columns for `COR.FLOW` are one character to the right of where the
values actually sit in the real 2020 response, so rows are tokenised by whitespace rather than
sliced by the legend's positions. A Point row with a missing value cannot be attributed to one
column by whitespace alone; the adapter refuses such a row loudly until a recording shows how the
source publishes one.

Timestamps are the row's `CCYYMMDD` date (Daily, labelled `00:00`) or `CCYYMMDD HHMMSS`
(Point) exactly as published, with `time_zone="unknown"` on every row.

## Time zone

Neither the HyData.aspx page, its legend, nor the archived Verified Hydrology pages recorded in
`catalogue/provenance.json` state a time standard for the published dates and times. Under ADR
0007 the zone is what the source publishes or `unknown`; it is not derived from the country. The
retired port's SAST assumption is therefore not carried forward, and `to_utc` refuses this
provider's rows until the source states its zone.

## Stop convention

The two real 2020 responses kept as legacy reference both end one day before their `EndDT`:
`Daily` with `EndDT=2020-01-31` ends at row `20200130`, and `Point` with `EndDT=2020-01-03` ends
at `20200102 233600`. The rendered stop is therefore declared exclusive; the engine advances it by
one day. The engine's two-day padding covers the request either way, so the declaration decides
only how much of the padding the source answers; the boundary recordings confirm it.

## Window sizes (unverified)

The retired port claimed the source accepts about 20 years per `Daily` request and about one year
per `Point` request. Neither claim has been verified against the source; the declarations restate
them as chunk sizes so that a long request is split conservatively. A request the source refuses
surfaces as an unexpected HTTP status or as a no-data statement rather than as silent truncation.

## Issues surfaced, never interpreted

| Code | Severity | Meaning |
|---|---|---|
| `http_not_found` | warning | HTTP 404 for one station-window request. |
| `source_request_failed` | warning | Transport retries exhausted for one request. |
| `no_data_for_period` | warning | The portal answered with a plain-text no-data statement (`No data for requested period.` or `There is no row at position 0.`, both taken from the retired port and not yet observed through this adapter). |
| `sentinel_missing_value` | info | Rows whose value field is the `99999.999` marker the Daily legend names; the rows are returned with a null value and the count, first and last time are reported. |
| `source_quality_code` | info | One per (product, quality code): the count, first and last time carrying that code. The code's meaning is source judgement and is not read. |

## Evidence state

Observation evidence for this adapter is a set of recordings captured through the engine
transport (ADR 0024). The DWS host answers HTTP 403 ("You don't have permission to access this
resource") to every request from the porting network, including one sent through the engine
`HttpClient` on 2026-09-03; the catalogue attestation below records the same refusal from two
other egress points. No recording exists yet, so:

- `tests/test_za_dws_boundary_probe.py` and `tests/test_za_dws_live.py` fail (they never skip)
  and name the missing files and the capture commands;
- the boundary literal slots in `tests/test_za_dws_boundary_probe.py` are `None`, to be authored
  independently from the recording bytes and the legend once the files exist;
- the legacy subtree `reference/legacy_observations/za_dws/` remains until the replacement is
  proven; its two 2020 text files are real responses and were used only as reading material.

### Capture commands

Run from a network the source accepts. Each command drives the adapter exactly as a public
`rr.fetch` would and writes what it exchanged:

```
uv run python -m rivretrieve._internal.record_observations --provider za_dws --station X3H001 \
  --product discharge_daily_mean --start 2019-12-30 --end 2020-01-02 \
  --out-dir tests/test_data --name za_dws_X3H001_Daily_2019-12-28_2020-01-05

uv run python -m rivretrieve._internal.record_observations --provider za_dws --station X3H001 \
  --product discharge_instantaneous --product stage_instantaneous --start 2020-01-05 --end 2020-01-06 \
  --out-dir tests/test_data --name za_dws_X3H001_Point_2020-01-03_2020-01-09
```

The Daily request straddles the year edge (`StartDT=2019-12-28`, `EndDT=2020-01-05`); the Point
request spans several local midnights (`StartDT=2020-01-03`, `EndDT=2020-01-09`). Each command
issues exactly one source call, so each writes exactly one `<name>.recording.json`. Then author
the three literals per product in `tests/test_za_dws_boundary_probe.py` from the recording bytes
without running the adapter, run `uv run pytest`, and delete the legacy subtree together with its
entry in `tests/test_legacy_observation_reference_m7_s4.py`.

## Native Catalogue Attestation

Direct DWS requests returned HTTP 403 from two independent egress points. The accepted acquisition is
eight Internet Archive captures of the WMA PDFs linked by an archived `HyCatalogue.aspx`, retrieved
between `2026-08-02T18:47:00Z` and `2026-08-02T18:47:09Z`. Exact archived and origin URLs, snapshots,
byte sizes, SHA-256 values, and retrieval instants are declared in `generate_catalogue.py` and checked
by `tests/test_za_dws_generate_catalogue.py`.

Deterministic PDF parsing produces 544, 210, 417, 702, 406, 567, 19, and 40 rows: 2,905 rows with
2,905 unique station codes. It repairs 40 standard-code rows whose drainage region is blank and the
suffixed codes `A2H090Q` and `B6H018M01`. Native rows preserve source DMS, catchment strings, null
drainage regions, exact source PDF identity, and each PDF's retrieval instant. The semantic native-frame
digest and source bindings are held by `catalogue/provenance.json`.

The canonical catalogue is built only from committed `catalogue/native.parquet` plus origins. DMS is
converted deterministically to decimal degrees; no live or fixture response directly generates the
canonical artefacts. All 8,715 station-products carry `availability="unknown"` because the PDFs do
not say which products a station reports, so every station is publicly selectable and a station
that publishes nothing for a window answers with an issue rather than an error.

## Surprises and Pain Points

| Issue | Detail |
|---|---|
| `100.00` suffix on station IDs | The `Station=` parameter requires `<id>100.00`; the page itself names the variable as "Variable 100.00 Surface Water Level". |
| PDF-only catalogue | Station metadata lives in eight WMA PDFs; no JSON or CSV catalogue exists. |
| Legend positions drift | The Point legend's column positions do not match the real row layout by one character; rows are tokenised, not sliced. |
| Exclusive `EndDT` | Both real responses stop one day short of `EndDT`; declared exclusive, awaiting recorded confirmation. |
| Host refuses the porting network | HTTP 403 for every request; evidence capture needs another egress. |
