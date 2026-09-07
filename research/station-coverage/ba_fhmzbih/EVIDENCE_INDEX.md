# ba_fhmzbih — evidence index

Every recording captured by this survey, with the integrity fields required by issue #223
(exact request URL, HTTP status, media type, UTC retrieval instant, response bytes, SHA-256)
and the finding it supports. Recordings are stored in the repository's existing convention;
regenerate any of them with `scripts/capture.py <url> <recording_id>`.

No credentials, cookies or tokens were sent or stored: every route surveyed is public and
unauthenticated.

| Recording | Status | Bytes | SHA-256 (first 16) | Retrieved (UTC) | Establishes |
| --- | --- | --- | --- | --- | --- |
| [`absent_4109_WT_404`](recordings/absent_4109_WT_404.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/stations/4/4109/WT/Tvode_1Y.xlsx</sub> | 404 | 246 | `e1201cb8fc2bd6ed` | 2026-09-07T09:02:59Z | Access block: WT workbook route returns 404. |
| [`absent_4228_H_404`](recordings/absent_4228_H_404.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/stations/4/4228/H/H_1Y.xlsx</sub> | 404 | 240 | `4e7c38fbff5c4286` | 2026-09-07T09:02:58Z | Access block: station declared in the H layer, workbook route returns 404. |
| [`absent_9025_H_404`](recordings/absent_9025_H_404.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/stations/1/9025/H/H_1Y.xlsx</sub> | 404 | 240 | `7e3160c6d6f26ea8` | 2026-09-07T09:02:58Z | Access block: station declared in the H layer, workbook route returns 404. |
| [`boundary_1020_WT_populated`](recordings/boundary_1020_WT_populated.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/stations/1/1020/WT/Tvode_1Y.xlsx</sub> | 200 | 95,022 | `b39b0b0981851ea6` | 2026-09-07T08:46:43Z | Boundary: #Rows = 7251, 7251 data rows verified; one-year span 2025-09-07 to 2026-09-06. |
| [`boundary_4060_WT_headeronly`](recordings/boundary_4060_WT_headeronly.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/stations/4/4060/WT/Tvode_1Y.xlsx</sub> | 200 | 3,642 | `ea267e09c2f28242` | 2026-09-07T08:46:43Z | Boundary: #Rows = 0 with parameter and unit still declared (0 data rows verified). |
| [`boundary_4110_H_smallest`](recordings/boundary_4110_H_smallest.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/stations/4/4110/H/H_1Y.xlsx</sub> | 200 | 74,562 | `7b9e27b02a74b5c1` | 2026-09-07T08:46:45Z | Smallest populated H workbook; 5189 data rows verified; unit cm. |
| [`boundary_4110_Q_smallest`](recordings/boundary_4110_Q_smallest.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/stations/4/4110/Q/Q_1Y.xlsx</sub> | 200 | 76,203 | `c49c1d0753084c70` | 2026-09-07T08:46:44Z | Smallest populated Q workbook; 5189 data rows verified; unit m³/s. |
| [`horizon_4024_Q_1M_exists`](recordings/horizon_4024_Q_1M_exists.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/stations/4/4024/Q/Q_1M.xlsx</sub> | 200 | 13,308 | `aaa542c9f38e8ddf` | 2026-09-07T09:06:43Z | A one-month workbook period exists (span 2026-08-08 to 2026-09-07). |
| [`horizon_4024_Q_5Y_absent`](recordings/horizon_4024_Q_5Y_absent.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/stations/4/4024/Q/Q_5Y.xlsx</sub> | 404 | 240 | `8e8c1904fa54722c` | 2026-09-07T09:06:44Z | No multi-year period: _5Y returns 404 (as do _2Y, _10Y, _ALL and others). |
| [`horizon_directory_listing_403`](recordings/horizon_directory_listing_403.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/stations/4/4024/Q/</sub> | 403 | 234 | `1c8090b99e8d24ac` | 2026-09-07T09:06:45Z | Directory listing refused with 403; recorded, not bypassed. |
| [`layer_10`](recordings/layer_10.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/layers/10/index.json</sub> | 200 | 106,383 | `9ef83a18428beaf2` | 2026-09-07T08:42:16Z | Vodostaj (H) layer membership - 99 hydrological stations. |
| [`layer_20`](recordings/layer_20.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/layers/20/index.json</sub> | 200 | 64,677 | `cf8ce047653a311e` | 2026-09-07T08:42:17Z | Proticaj (Q) layer membership - 60 stations; identical to the committed baseline. |
| [`layer_30`](recordings/layer_30.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/layers/30/index.json</sub> | 200 | 13,779 | `3a30e0660be87667` | 2026-09-07T08:42:18Z | Temperatura vode (WT) layer membership - 13 stations. |
| [`layer_40`](recordings/layer_40.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/layers/40/index.json</sub> | 200 | 29,172 | `8ffe6e3ac6359f5a` | 2026-09-07T08:42:19Z | GroundWaterLevel layer; object type 'Stanica podzemnih voda' - evidences out-of-scope. |
| [`layer_50`](recordings/layer_50.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/layers/50/index.json</sub> | 200 | 24,447 | `7a7d193b4c7d9cd5` | 2026-09-07T08:42:19Z | GroundWaterTemp layer; object type 'Stanica podzemnih voda' - evidences out-of-scope. |
| [`layer_60`](recordings/layer_60.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/layers/60/index.json</sub> | 200 | 24,741 | `4e278220a9d8ec63` | 2026-09-07T08:42:20Z | Precipitation layer; object type 'Meteorološka stanica' - evidences out-of-scope. |
| [`layer_70`](recordings/layer_70.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/layers/70/index.json</sub> | 200 | 24,735 | `a878f8dcfb16746b` | 2026-09-07T08:42:21Z | AirTemp layer; object type 'Meteorološka stanica' - evidences out-of-scope. |
| [`layer_80`](recordings/layer_80.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/layers/80/index.json</sub> | 200 | 86,715 | `ebdf1ffdd9e7147c` | 2026-09-07T08:42:22Z | EPPWaterLevel layer - evidences out-of-scope. |
| [`layer_90`](recordings/layer_90.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/layers/90/index.json</sub> | 200 | 42,528 | `2c53daf49a9f144c` | 2026-09-07T08:42:22Z | EPPFlow layer - evidences out-of-scope. |
| [`layers_manifest`](recordings/layers_manifest.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/layers/index.json</sub> | 200 | 1,884 | `2921b2fd316e4216` | 2026-09-07T08:42:16Z | The publisher's own list of ten layers; the authoritative product-to-layer mapping. |
| [`lowrow_1110_Q_1rows`](recordings/lowrow_1110_Q_1rows.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/stations/1/1110/Q/Q_1Y.xlsx</sub> | 200 | 3,741 | `8c3f8fe19010952f` | 2026-09-07T09:23:47Z | Content-Length 3740 B but publisher declares #Rows = 1: evidences why file size cannot classify availability. |
| [`lowrow_4023_Q_164rows`](recordings/lowrow_4023_Q_164rows.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/stations/4/4023/Q/Q_1Y.xlsx</sub> | 200 | 5,616 | `dfc5e22b834ba220` | 2026-09-07T09:23:48Z | Content-Length 5614 B but publisher declares #Rows = 164: evidences why file size cannot classify availability. |
| [`lowrow_4911_Q_338rows`](recordings/lowrow_4911_Q_338rows.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/stations/1/4911/Q/Q_1Y.xlsx</sub> | 200 | 7,629 | `72113347f1944120` | 2026-09-07T09:23:48Z | Content-Length 7628 B but publisher declares #Rows = 338: evidences why file size cannot classify availability. |
| [`lowrow_9001_Q_1rows`](recordings/lowrow_9001_Q_1rows.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/stations/1/9001/Q/Q_1Y.xlsx</sub> | 200 | 3,759 | `f7602547a1d16a5d` | 2026-09-07T09:23:49Z | Content-Length 3758 B but publisher declares #Rows = 1: evidences why file size cannot classify availability. |
| [`lowrow_9020_Q_1rows`](recordings/lowrow_9020_Q_1rows.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/stations/2/9020/Q/Q_1Y.xlsx</sub> | 200 | 3,741 | `fc7c5bc2e895b4e2` | 2026-09-07T09:23:50Z | Content-Length 3740 B but publisher declares #Rows = 1: evidences why file size cannot classify availability. |
| [`lowrow_9043_Q_1rows`](recordings/lowrow_9043_Q_1rows.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/stations/4/9043/Q/Q_1Y.xlsx</sub> | 200 | 3,744 | `e0baa3bc91005ed2` | 2026-09-07T09:23:50Z | Content-Length 3742 B but publisher declares #Rows = 1: evidences why file size cannot classify availability. |
| [`lowrow_9130_Q_1rows`](recordings/lowrow_9130_Q_1rows.recording.json)<br><sub>https://vodostaji.voda.ba/data/internet/stations/4/9130/Q/Q_1Y.xlsx</sub> | 200 | 3,744 | `eb63e41834a446ef` | 2026-09-07T09:23:51Z | Content-Length 3744 B but publisher declares #Rows = 1: evidences why file size cannot classify availability. |
| [`portal_root`](recordings/portal_root.recording.json)<br><sub>https://vodostaji.voda.ba/</sub> | 200 | 1,959 | `86d62b4fa6067e76` | 2026-09-07T09:00:32Z | Portal identity: page title names Agencija za vodno području rijeke Save. |

## Derived inventories

| File | Rows | Contents |
| --- | --- | --- |
| [`inventory/station_product_evidence.csv`](inventory/station_product_evidence.csv) | 297 | Final inventory: every station x product with status, basis and linked recording. |
| [`STATION_TABLE.md`](STATION_TABLE.md) | 99 | Readable station list: one row per station, per-product status. |
| [`inventory/declared_rows_population.csv`](inventory/declared_rows_population.csv) | 297 | The publisher's `#Rows`, unit, parameter and timeseries name per pair. |
| [`inventory/population_probe.csv`](inventory/population_probe.csv) | 297 | HEAD probe: HTTP status, Content-Length, layer membership, baseline membership. |
| [`inventory/workbook_probe.csv`](inventory/workbook_probe.csv) | 180 | First-pass probe over the committed 60-station baseline only. |
| [`inventory/declared_rows.csv`](inventory/declared_rows.csv) | 48 | First-pass `#Rows` read of the baseline's empty WT candidates. |

## Reproduction

```bash
uv run python research/station-coverage/ba_fhmzbih/scripts/probe_population.py
uv run python research/station-coverage/ba_fhmzbih/scripts/read_all_declared_rows.py
uv run python research/station-coverage/ba_fhmzbih/scripts/build_final_inventory.py
uv run python research/station-coverage/ba_fhmzbih/scripts/build_station_table.py
uv run python research/station-coverage/ba_fhmzbih/scripts/build_evidence_index.py
```

`verify_evidence.py` re-hashes every recording and re-checks the inventory's completeness
assertions without touching the network.
