# cz_chmi Provider Port Notes

These notes capture evidence and hand-off context from the `cz_chmi` Czech CHMI provider port. Promote only shared harness commitments to [ADRs](../adr/).

## Source Endpoints

| Endpoint or source | Role | Credential status |
| --- | --- | --- |
| `https://opendata.chmi.cz/hydrology/historical/metadata/meta1.json` | Maintainer-side catalogue input for station metadata. Runtime catalogue calls use packaged artifacts only. | No token. Public CHMI Open Data. |
| `https://opendata.chmi.cz/hydrology/historical/data/daily/H_{id}_DQ_{year}.json` | Observation retrieval for daily discharge (QD), stage (HD), and water temperature (TD). One file per station per year. | No token. Public. |
| `https://opendata.chmi.cz/hydrology/historical/data/hourly/H_{id}_HQ_{year}.json` | Observation retrieval for hourly instantaneous discharge (QH) and stage (HH). One file per station per year. | No token. Public. |
| Legacy `CzechFetcher` in `rivretrieve/czech.py` | Reference for station field normalization and URL templates. | N/A. |

Note: the legacy `CzechFetcher` also defines `TEMP_BASE_URL` pointing to `H_{id}_OT_{year}.json`. However, the legacy implementation routes water temperature via the daily DQ file with `tsConID=TD`. This port follows the legacy routing. The OT file URL is currently unused.

## Metadata JSON Structure

The CHMI metadata endpoint returns a doubly-nested JSON object:

```json
{
  "data": {
    "data": {
      "header": "objID,STATION_NAME,STREAM_NAME,GEOGR1,GEOGR2,PLO_STA",
      "values": [
        ["0-203-1-016000", "Prague - Modřany", "Vltava", "50.0014", "14.4092", "14260.0"],
        ...
      ]
    }
  }
}
```

Access path: `root["data"]["data"]["header"]` and `root["data"]["data"]["values"]`.

## Native Catalogue Attestation

The complete metadata response was retrieved at `2026-08-02T00:14:31Z` with 831 rows and 23 header
columns. Canonicalizing the parsed JSON with sorted keys, compact separators, `ensure_ascii=False`,
and UTF-8 produces SHA-256
`a75f5ae23d8e9108cedb613d320ac3f3daf7be071442a3a91d23b323721cc9e9`. The active three-row fixture
is a verbatim parser subset, not the source of the committed native table. It replaced a source-incorrect
fixture: `0-203-1-016000` and `0-203-1-020000` had wrong coordinates, and `0-204-1-001000` was not
published by the source. The native-frame digest and source-correct coordinate witnesses are enforced
by `catalogue/provenance.json` and the generator tests.

## Observation JSON Structure

Each year file contains a `tsList` array. Each entry has a `tsConID` field and nested `tsData.data.header` / `tsData.data.values` for the actual observations:

```json
{
  "tsList": [
    {
      "tsConID": "QD",
      "tsData": {
        "data": {
          "header": "DT,VAL,Q",
          "values": [["2020-01-01T00:00:00Z", 12.5, 0], ...]
        }
      }
    }
  ]
}
```

The `Q` column is a quality flag. This port parses `DT` (timestamp) and `VAL` (value) only; `Q` is available in the raw payload but not emitted as a row annotation in V1.

## Catalogue Mapping

| Native field | Canonical target | Decision |
| --- | --- | --- |
| `objID` | `provider_id`, `station_id` | Exact hyphen-separated source identity. |
| `GEOGR1`, `GEOGR2` | `latitude`, `longitude` | Direct numeric coercion with no coordinate transformation. |
| Horizontal CRS | `crs` | `unknown`; the captured publisher description does not publish a horizontal CRS. |
| All other 20 source fields | Native only | Names, stream, drainage-area, elevation, and other source vocabulary remain in `native.parquet`. |

## Product Dictionary

All five products map to canonical V1 product IDs. No `cz_chmi`-specific product IDs were needed.

| tsConID | URL template | Native unit | Canonical product_id | Conversion |
| --- | --- | --- | --- | --- |
| QD | daily (`DQ`) | m³/s | `discharge_daily_mean` | none |
| HD | daily (`DQ`) | cm | `stage_daily_mean` | divide by 100 |
| TD | daily (`DQ`) | °C | `water_temperature_daily_mean` | none |
| QH | hourly (`HQ`) | m³/s | `discharge_instantaneous` | none |
| HH | hourly (`HQ`) | cm | `stage_instantaneous` | divide by 100 |

Three products (QD, HD, TD) are retrieved from the same daily URL; two (QH, HH) from the hourly URL. This means a request for multiple daily products for the same station and year results in separate HTTP calls (one per product/tsConID), even though the response file contains all three. Deduplication/caching was not added in V1 to avoid speculative optimization.

## Timezone and Timestamp Handling

CHMI observation timestamps are ISO 8601 with a Z suffix (e.g., `2020-01-01T00:00:00Z`). These are unambiguously UTC. No inference is required. The series annotation `timezone_source` is set to `"provider_timestamp_utc"` and `resolved_timezone` to `"UTC"`.

The parser normalises the Z suffix to `+00:00` before passing to Polars `str.to_datetime(time_zone="UTC")` for robustness. No structured issue is emitted because no inference occurs.

## Windowing

Observations are fetched year by year (annual chunks), matching the legacy `CzechFetcher._download_data` loop. The `_iter_years(start, end)` helper returns `range(start.year, end.year + 1)`. The filter `_filter_date_range` applies an exclusive upper bound of midnight UTC of `(end_date + 1)` — the same pattern as `usgs_nwis` — to correctly include all observations on the last calendar day.

## Station-Product Availability

The CHMI metadata catalogue does not expose per-variable availability. All 831 × 5 = 4155 station-product rows are materialized as `availability=unknown`.

## Pain Points

| Issue | Status | Action |
| --- | --- | --- |
| Doubly-nested metadata JSON | Documented. | Access path `root["data"]["data"]` instead of the more common single level. |
| `TEMP_BASE_URL` in legacy code unused | Documented. | Water temperature is in the daily DQ file with tsConID=TD. The OT endpoint URL exists but was not used by the legacy mapping. Defer verification to future maintenance. |
| `Q` quality flag column in observation data | Not yet used. | Available in raw payload. Not emitted as a row annotation in V1. Defer quality harmonization to post-V1. |
| Stage raw unit is cm | Handled. | Stage observations (HD, HH) are divided by 100 in the transform layer. Raw cm value preserved in `raw_value` row annotation. |
| Elevation not in metadata | Handled. | `elevation_m` is always `None` for `cz_chmi` stations. |
| Station IDs contain hyphens | Documented. | IDs like `0-203-1-016000` are valid station IDs; preserved as-is without normalization. |
| Three daily products share one URL file | Documented. | Each product triggers a separate HTTP call per year even when the response file contains all three. No V1 deduplication. |
