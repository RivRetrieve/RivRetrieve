# Hub’Eau station inventory capture

The 2026-09-21 capture uses Hub’Eau's hydrometry and temperature station routes independently. Both responses used `size=10000&format=json`, returned HTTP 200, and published `count` equal to their row count with `next=null`. No activity or territorial filter was supplied. This is the source-published station inventory at those retrieval instants, not an assertion of observations for every product.

The retained `.json.xz` files are lossless compressed copies of the exact HTTP bodies. Each `.receipt.json` records the original JSON media type, request, retrieval instant, raw byte size and raw SHA-256. `native_capture.json` separately identifies the retained compressed recordings and the native Parquet input. The offline builder verifies decompressed raw bytes before decoding and verifies recording hashes before publication.

## Reconciliation with 2026-08-02

- Hydrometry: 6,475 stations, 21 additions, no removals. Inactive stations remain included.
- Temperature: 872 stations, three additions (`04187710`, `05150900`, `06131550`), no removals.
- Full station identifiers are preserved. The two route populations do not overlap.
- All 54 projection-31 hydrometry rows have the same identifiers and the same four coordinate values as the previous capture. Their original x equals `latitude_station`, and original y equals `longitude_station`. The existing documented transposition and its bounds therefore apply unchanged to these specific rows. This is not a new universal bounding-box assumption. The independent HydroPortail comparison is retained in that provider's coverage evidence.

The old native Parquet is retained as `native-2026-08-02.parquet`. `governing_evidence.json.xz` remains unchanged, including its original mixed-service acquisitions and material identity. It is historical evidence, not the current supported product list. The build reuses only its Hub’Eau daily-hydrometry and temperature evidence. The 66 new station-product pairs are selectable with unknown observation history and no fabricated observation acquisition. Existing positive counts remain dated source witnesses, not continuity claims.

## Rebuild

From the repository root:

```sh
uv run python maintenance/catalogue/fr_hubeau/inventory/build_catalogue.py --revision 4222cfa3226c9aaa0b7e12da596886ab7a68aa1f
```

That revision contains the exact captured source inputs and native table. A later capture must use its own native-input revision, source receipts and coverage reconciliation. The builder does not contact observation services.
