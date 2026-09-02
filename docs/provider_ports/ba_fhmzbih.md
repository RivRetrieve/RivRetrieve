# ba_fhmzbih provider port

The live adapter uses `fetch.py`, `parse.py`, and `config.py`. It was contributed by Thiago von Däniken.

Each request fetches `layers/20/index.json` once. It resolves the exact `metadata_site_no` for each requested station. It then fetches one source-fixed rolling workbook per requested product. No numbered-group probing occurs. The engine renders no window for these calls and clips the parsed rows to the requested closed window.

The source publishes Q in m³/s, H in cm, and WT in °C. Workbook timestamps are naive. No official zone was established, so rows use `unknown`. The shared engine converts stage from cm to m. Publisher receipts retain the exact metadata JSON and workbook bytes.

The certified catalogue is intentionally sparse. It exposes only `4024/Q`, `4024/H`, and `4110/WT`, established by recordings retrieved on 2026-09-02. Published record bounds are unknown. Unsupported cross-products are absent.

Catalogue CRS evidence is the publisher station document with 230 objects; it publishes no horizontal-CRS token. Its gauge-datum fields are vertical metre elevations, not horizontal coordinate systems.
