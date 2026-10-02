# cz_chmi Provider Port Notes

These notes capture evidence and hand-off context from the `cz_chmi` Czech CHMI provider port. See [Architecture](../architecture.md) for shared harness contracts.

## Source Endpoints

| Endpoint or source | Role | Credential status |
| --- | --- | --- |
| `https://opendata.chmi.cz/hydrology/historical/metadata/meta1.json` | Maintainer-side catalogue input for station metadata. Runtime catalogue calls use packaged artifacts only. | No token. Public CHMI Open Data. |
| `https://opendata.chmi.cz/hydrology/historical/data/daily/H_{id}_DQ_{year}.json` | Observation retrieval for daily discharge (QD), stage (HD), and water temperature (TD). One file per station per year. | No token. Public. |
| `https://opendata.chmi.cz/hydrology/historical/data/hourly/H_{id}_HQ_{year}.json` | Observation retrieval for hourly hourly mean discharge (QH) and stage (HH). One file per station per year. | No token. Public. |
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
is a verbatim parser subset, not the source of the retained native table. It replaced a source-incorrect
fixture: `0-203-1-016000` and `0-203-1-020000` had wrong coordinates, and `0-204-1-001000` was not
published by the source. The native-frame digest and source-correct coordinate witnesses are enforced
by `catalogue/provenance.json` and the generator tests.

## Observation JSON Structure

Each annual file contains a `tsList` array. Each entry identifies one series with `tsConID`, declares its native unit, and carries a `DataCollection` with the exact `DT,VAL` header. The official schemas and recorded complete annual responses expose no row-quality field. Null `VAL` values remain null; the port does not invent quality.

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
| QH | hourly (`HQ`) | m³/s | `discharge_hourly_mean` | none |
| HH | hourly (`HQ`) | cm | `stage_hourly_mean` | divide by 100 |

Three products (QD, HD, TD) are retrieved from one daily DQ response; two (QH, HH) from one hourly HQ response. Requests are coalesced by station, year, and file family, so all five products require exactly two source calls.

## Timezone and Timestamp Handling

CHMI observation timestamps use an explicit `Z` suffix. The parser preserves each source wall-clock label and emits `time_zone=+00:00`. QH and HH are declared as hourly interval means with unknown interval anchoring because the official source does not establish whether labels mark interval starts or ends.

## Windowing

The provider declares annual source windows. The shared engine plans padded annual fetches and performs final clipping. The provider performs no date arithmetic or clipping.

## Station-Product Availability

The CHMI metadata catalogue does not expose per-variable availability. All 831 × 5 = 4155 station-product rows are materialized as `availability=unknown`.

## Resolved port constraints

| Constraint | Resolution |
| --- | --- |
| Doubly nested metadata JSON | The catalogue generator reads `root["data"]["data"]` explicitly. |
| No observation quality field | Official schemas and complete annual recordings contain exactly `DT,VAL`; the parser emits no quality carrier. |
| Stage native unit is cm | Shared conversion changes HD and HH values from cm to canonical metres. Publisher bytes remain available through opt-in receipts. |
| Station IDs contain hyphens | Source identities such as `0-203-1-000400` are preserved exactly. |
| Three daily and two hourly products share files | Fetch coalesces by station, year, and DQ/HQ family, producing two source calls for all five products. |
| Hourly label anchoring is unpublished | `Hourly(IntervalDefinition("unknown"))` preserves the explicit unknown fact and shared clipping uses only published labels. |

## Retained verification inputs

Obtain the exact inputs from the private source archive as described in the
[verification guide](../maintenance/evidence.md). Tests read the external
repository-relative layout selected by `RIVRETRIEVE_TEST_EVIDENCE_ROOT`. Missing
inputs block verification. Runtime catalogue products remain packaged.

The catalogue generator requires `--native` to select the retained native table
and `--evidence-root` to select the external root for provenance checks. Recorded
paths remain acquisition identities; they are resolved below that root. For example:

```sh
uv run python -m rivretrieve._internal.providers.cz_chmi.generate_catalogue \
  --native "$RIVRETRIEVE_TEST_EVIDENCE_ROOT/src/rivretrieve/_internal/providers/cz_chmi/catalogue/native.parquet" \
  --evidence-root "$RIVRETRIEVE_TEST_EVIDENCE_ROOT" \
  --out catalogue-output
```
