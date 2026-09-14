# ba_fhmzbih provider port

The stable provider key is `ba_fhmzbih`. The evidenced publisher is **Agencija za vodno područje rijeke Save (AVP Sava)**, through `vodostaji.voda.ba`. This corrects the institutional display name; it does not migrate station or provider identifiers. The live adapter uses `fetch.py`, `parse.py`, and `config.py`. It was contributed by Thiago von Däniken.

## Selectable baseline

| Account | Before | After |
| --- | ---: | ---: |
| Original stations selectable for observations | 2 | 60 |
| Applicable station/product pairs selectable | 3 | 180 |
| Available pairs | 3 | 132 |
| Unknown-availability pairs selectable | 0 | 48 |

All 60 original stations have numerical Q and H evidence. Twelve have numerical WT evidence. The other 48 WT acquisitions are valid station/parameter/unit-matched workbooks with zero data rows. Those pairs remain **unknown and selectable**, not unsupported or permanently empty. Availability does not promise a numerical value for every source row or requested window. Timestamped blank measurement cells remain source records, distinct from numerical measurements.

The machine-readable reviewed account is [`baseline_workbook_access.json`](../../research/station-coverage/ba_fhmzbih/inventory/baseline_workbook_access.json). Its 180 entries identify each exact request, retrieval date, response digest and byte count, observed window, numerical/blank counts, and availability conclusion. Governing acquisitions have mixed dates: three pairs on September 2, three on September 7, 48 on September 9, and 126 on September 13, 2026. This is not a simultaneous snapshot. The original native table is unchanged. The additional 39 surveyed stations, EPP layers, and other objects in the 230-object document are outside this baseline.

## Retrieval and fidelity

Each request fetches `layers/20/index.json` once. It resolves the exact string `metadata_station_no` to its `metadata_site_no`, then fetches one source-fixed rolling workbook per requested product. For example, `2101-B` uses site `3`, not a group guessed from its identifier. No numbered-group probing occurs. The engine renders no window for these calls and clips the parsed rows to the requested closed window.

The configured yearly workbooks and the known monthly example establish rolling access. They do not establish a historical archive, an exhaustive list of supported date methods, or a source-wide maximum history. Failed guessed filenames do not prove that a longer-history method does not exist. An old requested window can return no rows from a rolling download. Observed capture windows are not published record bounds; both published-bound columns remain unknown.

The source publishes Q in m³/s, H in cm, and WT in °C. It does not establish temporal support, frequency, statistic, period type, or period anchor, so the products are `discharge_reported`, `stage_reported`, and `water_temperature_reported` with all temporal catalogue fields `unknown`. Workbook timestamps are naive. No official zone was established, so rows use `unknown`. The shared engine converts stage from cm to m. Publisher receipts retain the exact metadata JSON and workbook bytes.

## Rebuild and acquisition account

The catalogue generator takes the native table and reviewed workbook ledger as explicit build inputs. Runtime discovery loads only packaged catalogue artifacts; it does not open research paths or the private verification corpus.

```console
uv run python -m rivretrieve._internal.providers.ba_fhmzbih.generate_catalogue \
  --native src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet \
  --workbook-access-ledger research/station-coverage/ba_fhmzbih/inventory/baseline_workbook_access.json \
  --out src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue
```

The offline build keeps normal origin, native-byte and genuine public-recording checks. Workbook acquisitions identify the private source bodies through `MaterialIdentity` and exact request/date facts; they are not fake repository recording references. Rebuilding the reviewed public account is distinct from certifying all private bodies. The research verifier requires an explicit authorized evidence root for the latter. Missing private bodies must fail that source-certification mode. The complete corpus is not published or included in distribution artifacts.

The publisher attribution establishes who supplied the material. It does not establish every original measurer, historical operator, or a dataset-author citation. Source terms remain verbatim in provenance. The licence and citation fields remain unset where not established; no redistribution or legal classification is inferred.

Catalogue CRS evidence is the publisher station document with 230 objects; it publishes no horizontal-CRS token. Its gauge-datum fields are vertical metre elevations, not horizontal coordinate systems.
