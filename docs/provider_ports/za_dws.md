# za_dws Provider Port Notes

Port of the legacy Python `SouthAfricaFetcher` (`thirdparty/RivRetrieve-Python` @ `rivretrieve/southafrica.py`) and reference for the equivalent R `adapter_ZA_DWS.R` (https://github.com/bafg-bund/hydrodownloadR). Provider ID `za_dws` follows the `<country_code>_<agency>` convention for South Africa's Department of Water and Sanitation (DWS), which operates the Verified Hydrology portal at `www.dws.gov.za`.

## Source Endpoints

| Endpoint | Role | Auth | Notes |
|---|---|---|---|
| `https://www.dws.gov.za/Hydrology/Verified/HyData.aspx` | Observation retrieval — per-station-product HTML page with a `<pre>` block of tabular data | None | Query parameters: `Station={id}100.00`, `DataType=Daily\|Point`, `StartDT=YYYY-MM-DD`, `EndDT=YYYY-MM-DD`, `SiteType=RIV`. The `100.00` suffix is literal and required (R adapter convention). |
| `https://www.dws.gov.za/Hydrology/Verified/HyCatalogue.aspx` | Catalogue generation — index page linking to 8 WMA PDF files | None | Maintainer-only. Each link target is a `*_River.pdf` containing tabular station metadata. |

The observation endpoint was exercised live during the port for station X3H001 in January 2020. The current catalogue acquisition is the 2,905-row archived PDF campaign described below; direct publisher catalogue requests later returned HTTP 403.

## Data Types

DWS exposes two data types, each with a different time granularity and column layout:

| DataType | Time resolution | Relevant columns | Max window per request |
|---|---|---|---|
| `Daily` | Calendar day | `D_AVG_FR` (daily average flow rate, m³/s) | 20 years |
| `Point` | Sub-daily instantaneous | `COR_LEVEL` (m), `COR_FLOW` (m³/s) | 1 year |

The `Daily` endpoint returns date-stamped rows only (no time of day). The `Point` endpoint returns `YYYYMMDD HHMMSS` pairs for both water level and flow in the same row.

## Products

| Product ID | DataType | Column | Native unit | Canonical unit | Conversion |
|---|---|---|---|---|---|
| `discharge_daily_mean` | `Daily` | `D_AVG_FR` | m³/s | m³/s | none |
| `discharge_instantaneous` | `Point` | `COR_FLOW` | m³/s | m³/s | none |
| `stage_instantaneous` | `Point` | `COR_LEVEL` | m | m | none |

The `discharge_instantaneous` and `stage_instantaneous` products share one HTTP request per `(station_id, window)` — a per-call `point_cache` avoids a redundant fetch when both products are requested together.

## Request Window Decomposition

- `discharge_daily_mean`: 20-year aligned windows (e.g. `2000-01-01/2019-12-31`, `2020-01-01/2039-12-31`).
- `discharge_instantaneous` and `stage_instantaneous`: 1-year aligned windows (e.g. `2020-01-01/2020-12-31`).

Windows are year-aligned so that repeat calls with adjacent ranges will not duplicate rows at boundaries.

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

The canonical catalogue is built only from externally retained `catalogue/native.parquet` plus origins. DMS is
converted deterministically to decimal degrees; no live or fixture response directly generates the
canonical artefacts.

## Timestamps and Timezone (South Africa Standard Time)

South Africa Standard Time (SAST) is **UTC+2, no DST**. South Africa does not observe daylight saving. The `Africa/Johannesburg` IANA key is used throughout.

| Product | Raw timestamp | Handling | `timezone_source` |
|---|---|---|---|
| `discharge_daily_mean` | `YYYYMMDD` only — no time component | Parsed as `datetime.strptime(..., "%Y%m%d").replace(tzinfo=UTC)` — i.e. UTC midnight | `date_only_utc_midnight` |
| `discharge_instantaneous` | `YYYYMMDD HHMMSS` SAST local time | `datetime.strptime(..., "%Y%m%d%H%M%S").replace(tzinfo=SAST).astimezone(UTC)` | `local_to_utc_conversion` |
| `stage_instantaneous` | `YYYYMMDD HHMMSS` SAST local time | Same as above | `local_to_utc_conversion` |

For daily data a `date_only_timestamp` warning issue is emitted per series, documenting the UTC-midnight interpretation. For Point data a `timezone_local_to_utc` info issue is emitted per series.

**Live verification of the UTC conversion**: the first row in the January 2020 Point fixture is `20200101 000000` SAST, which converts to `2019-12-31 22:00:00 UTC` — correctly verified in `test_retrieve_stage_instantaneous_sast_to_utc`.

Series annotations always carry: `resolved_timezone`, `timezone_source`, `source_timezone` (only for Point), `returned_time_range_start`, `returned_time_range_end`, `native_unit_returned`, `converted_unit`, `provider_endpoint`.

## "No Data" Responses

When the server has no data for the requested station/window, it returns a plain-text message (`"No data for requested period."` or `"There is no row at position 0."`) before the HTML envelope — no `<pre>` tag is present. The parsers return an empty DataFrame with `has_no_data=True`. The retrieval layer emits a `missing_data` warning issue in this case.

## Sentinel Values

Daily responses encode missing observations as `99999.999` in the `D_AVG_FR` column. Any row with `d_avg_fr >= 99999.0` is dropped by the parser before the DataFrame is returned.

## Surprises and Pain Points

| Issue | Detail |
|---|---|
| `100.00` suffix on station IDs | The `Station=` parameter requires `{id}100.00` appended — this is a quirk of the web form, documented in the R adapter. |
| PDF-only catalogue | No JSON or CSV catalogue exists. Station metadata is embedded in 8 WMA PDF files that must be scraped with `pypdf`. |
| Elevation absent | The WMA PDFs do not include elevation; `elevation_m` is always `None`. |
| Daily max window = 20 years | The server appears to reject ranges longer than ~20 years. The chunking policy hard-caps windows to 20 years. |
| Point max window = 1 year | The server returns at most 1 year of sub-daily data per request. |
| All station-products `availability = unknown` | The PDFs list stations but do not indicate which products each station actually reports. |
| DMS coordinates | Latitude and longitude are in `DD:MM:SS` format; parsed to decimal degrees (`_dms_to_dd`), always negative lat (south), positive lon (east). |

## Live Verification

Per the project convention (to avoid repeating the `th_thaiwater` mistake where downloads were silently not happening), this port was verified against the live DWS portal:

- The historical live catalogue check is superseded by the 2,905-row archived acquisition described above; canonical artefacts now come only from externally retained `native.parquet` plus origins.
- A live `fetch()` for station `X3H001`, `DataType=Daily`, January 2020 returned HTTP 200 and 30 valid rows with values starting at `1.257 m³/s`.
- A live `fetch()` for the same station, `DataType=Point`, January 2020 returned HTTP 200 and sub-daily rows starting at `COR_LEVEL=0.146 m`, `COR_FLOW=1.230 m³/s`.
- The SAST→UTC conversion was confirmed: `20200101 000000` SAST → `2019-12-31T22:00:00Z`.

## Retained inputs and offline checks

Retrieve the exact za_dws inputs using the private source archive instructions
and [verification guide](../maintenance/evidence.md). Keep them outside source
checkouts in their repository-relative layout. Set
`RIVRETRIEVE_TEST_EVIDENCE_ROOT` to that external root before running:

```sh
uv run pytest tests/test_za_dws*.py -q --tb=no -p no:cacheprovider
```

Build the catalogue from the retained native table and verified source recordings:

```sh
uv run python -m rivretrieve._internal.providers.za_dws.generate_catalogue \
  --native "$RIVRETRIEVE_TEST_EVIDENCE_ROOT/src/rivretrieve/_internal/providers/za_dws/catalogue/native.parquet" \
  --evidence-root "$RIVRETRIEVE_TEST_EVIDENCE_ROOT" \
  --out "$CATALOGUE_OUTPUT"
```

Choose `CATALOGUE_OUTPUT` as a separate build output directory. Native tables
and recordings are external build inputs. Packaged catalogue products remain
runtime inputs and do not require archive access. Missing retained inputs block
the corresponding checks. Keep detailed test output private.
