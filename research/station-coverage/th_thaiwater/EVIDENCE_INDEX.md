# th_thaiwater — evidence index

Every recording captured by this survey, with the integrity fields required by issue #224
(exact request URL and parameters, HTTP status, media type, UTC retrieval instant, response bytes,
SHA-256) and the finding it supports. Regenerate any of them with
`scripts/capture.py <recording_id> <url> [key=value ...]`.

Every route surveyed is public and unauthenticated. No credentials, cookies or tokens were sent
or stored.

| Recording | Status | Bytes | SHA-256 (first 16) | Retrieved (UTC) | Establishes |
| --- | --- | --- | --- | --- | --- |
| [`boundary_1035518_stage_only_hourly`](recordings/boundary_1035518_stage_only_hourly.recording.json)<br><sub>station_id=1035518 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 5,871 | `047997c9546d6b80` | 2026-09-07T15:37:31Z | A station publishing stage but no discharge, on an hourly grid. |
| [`boundary_1121218_data_in_july`](recordings/boundary_1121218_data_in_july.recording.json)<br><sub>station_id=1121218 start_date=2026-07-01 end_date=2026-07-03</sub> | 200 | 35,082 | `6b0f82d7b6cf6032` | 2026-09-07T15:37:32Z | Station empty in the 7-day window yet publishing 411 stage values in July: evidences why a short window understates coverage. |
| [`boundary_11688546_empty_90d`](recordings/boundary_11688546_empty_90d.recording.json)<br><sub>station_id=11688546 start_date=2026-06-08 end_date=2026-09-06</sub> | 200 | 172,668 | `710e5649afedcd48` | 2026-09-07T15:37:34Z | Complete 90-day time grid with no non-null value for either product: the empty case, still answered with result OK. |
| [`boundary_1373272_both_products`](recordings/boundary_1373272_both_products.recording.json)<br><sub>station_id=1373272 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 36,087 | `8d7b46daee8d5f66` | 2026-09-07T15:37:30Z | A station publishing both value and discharge on a 10-minute grid. |
| [`churn_removed_1119916_graph`](recordings/churn_removed_1119916_graph.recording.json)<br><sub>station_id=1119916 start_date=2026-09-05 end_date=2026-09-06</sub> | 200 | 3,939 | `7bfd8c0949ea6beb` | 2026-09-07T15:09:32Z | Baseline station absent from the live snapshot that still publishes values: absence from waterlevel_load is not absence of data. |
| [`churn_removed_1121218_graph`](recordings/churn_removed_1121218_graph.recording.json)<br><sub>station_id=1121218 start_date=2026-09-05 end_date=2026-09-06</sub> | 200 | 22,884 | `24bdfcd86a87caec` | 2026-09-07T15:09:34Z | Baseline station absent from the live snapshot; route answers result OK with a null-filled grid. |
| [`churn_removed_11568367_graph`](recordings/churn_removed_11568367_graph.recording.json)<br><sub>station_id=11568367 start_date=2026-09-05 end_date=2026-09-06</sub> | 200 | 22,884 | `e54ce47034ae37e3` | 2026-09-07T15:09:35Z | Baseline station absent from the live snapshot; route answers result OK with a null-filled grid. |
| [`error_bad_station_type`](recordings/error_bad_station_type.recording.json)<br><sub>station_id=1373273 start_date=2026-09-05 end_date=2026-09-06</sub> | 500 | 2,109 | `5d31e069957d3b95` | 2026-09-07T15:35:44Z | Unknown station_type returns HTTP 500 with a Go panic stack trace, not JSON. |
| [`error_missing_station_id`](recordings/error_missing_station_id.recording.json)<br><sub>start_date=2026-09-05 end_date=2026-09-06</sub> | 200 | 45 | `fc48a1f0efaa7efd` | 2026-09-07T15:35:43Z | Missing station_id returns HTTP 200 carrying an error body: a 200 must still be checked. |
| [`error_nonexistent_station`](recordings/error_nonexistent_station.recording.json)<br><sub>station_id=999999999 start_date=2026-09-05 end_date=2026-09-06</sub> | 500 | 2,121 | `23e97944b0130224` | 2026-09-07T15:35:41Z | Nonexistent station_id returns HTTP 500 with a Go panic stack trace, not JSON. |
| [`error_reversed_dates`](recordings/error_reversed_dates.recording.json)<br><sub>station_id=1373273 start_date=2026-09-06 end_date=2026-09-05</sub> | 200 | 135 | `e2c75871803ee927` | 2026-09-07T15:35:42Z | end_date before start_date returns HTTP 200, result OK, zero rows - not an error. |
| [`hypo_noD_395`](recordings/hypo_noD_395.recording.json)<br><sub>station_id=395 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 35,049 | `ee0a309442c5852a` | 2026-09-07T15:10:36Z | Snapshot discharge null; graph route publishes no discharge (hypothesis sample, later shown insufficient across the population). |
| [`hypo_noD_575566`](recordings/hypo_noD_575566.recording.json)<br><sub>station_id=575566 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 34,332 | `36f6f01670950fe6` | 2026-09-07T15:10:40Z | Snapshot discharge null; graph route publishes no discharge (hypothesis sample, later shown insufficient across the population). |
| [`hypo_noD_575568`](recordings/hypo_noD_575568.recording.json)<br><sub>station_id=575568 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 34,332 | `cbf412a8748161f1` | 2026-09-07T15:10:31Z | Snapshot discharge null; graph route publishes no discharge (hypothesis sample, later shown insufficient across the population). |
| [`hypo_noD_595`](recordings/hypo_noD_595.recording.json)<br><sub>station_id=595 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 34,263 | `0961b42613950667` | 2026-09-07T15:10:33Z | Snapshot discharge null; graph route publishes no discharge (hypothesis sample, later shown insufficient across the population). |
| [`hypo_withD_1095877`](recordings/hypo_withD_1095877.recording.json)<br><sub>station_id=1095877 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 6,153 | `4e9c875f2c9f2137` | 2026-09-07T15:10:26Z | Snapshot discharge present; graph route publishes discharge (hypothesis sample). |
| [`hypo_withD_1161516`](recordings/hypo_withD_1161516.recording.json)<br><sub>station_id=1161516 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 5,940 | `9dd5e1745666b803` | 2026-09-07T15:10:28Z | Snapshot discharge present; graph route publishes discharge (hypothesis sample). |
| [`hypo_withD_3085`](recordings/hypo_withD_3085.recording.json)<br><sub>station_id=3085 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 5,967 | `7942f87ba9e38fb5` | 2026-09-07T15:10:23Z | Snapshot discharge present; graph route publishes discharge (hypothesis sample). |
| [`hypo_withD_3122`](recordings/hypo_withD_3122.recording.json)<br><sub>station_id=3122 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 5,952 | `fb60e6396dcc85d1` | 2026-09-07T15:10:29Z | Snapshot discharge present; graph route publishes discharge (hypothesis sample). |
| [`limit_three_year_window`](recordings/limit_three_year_window.recording.json)<br><sub>station_id=1373273 start_date=2023-09-06 end_date=2026-09-06</sub> | 200 | 4,346,430 | `f43099da644dd21b` | 2026-09-07T15:35:47Z | A three-year request returns a one-year span with HTTP 200 and no indication of the clamp. |
| [`waterlevel_load_live`](recordings/waterlevel_load_live.recording.json)<br><sub>https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_load</sub> | 200 | 2,384,841 | `c6de458722531801` | 2026-09-07T15:08:00Z | Live catalogue snapshot (1,405 stations, 2026-09-07): population churn against the 825 baseline, and the snapshot fields whose availability signal is tested in FINDINGS section 2. |

## Derived inventories

| File | Rows | Contents |
| --- | --- | --- |
| [`inventory/station_product_evidence.csv`](inventory/station_product_evidence.csv) | 1,650 | Final inventory: every station x product with status, basis and linked recording. |
| [`STATION_TABLE.md`](STATION_TABLE.md) | 825 | Readable station list, one row per station. |
| [`inventory/graph_sweep.csv`](inventory/graph_sweep.csv) | 825 | First pass: per-station non-null counts over the 7-day window. |
| [`inventory/widened_90d.csv`](inventory/widened_90d.csv) | 549 | Re-probe over 90 days of every station with an empty product. |
| [`inventory/widened_empty.csv`](inventory/widened_empty.csv) | 26 | Earlier re-probe of stations empty for both products. |
| [`inventory/window_limit_probe.csv`](inventory/window_limit_probe.csv) | 7 | Requested vs returned spans establishing the 365-day clamp. |
| [`inventory/window_truncation_observation.json`](inventory/window_truncation_observation.json) | - | The clamp's measured consequence at the public surface. |

## Reproduction

```bash
uv run python research/station-coverage/th_thaiwater/scripts/sweep_availability.py
uv run python research/station-coverage/th_thaiwater/scripts/widen_all_empty.py
uv run python research/station-coverage/th_thaiwater/scripts/probe_window_limit.py
uv run python research/station-coverage/th_thaiwater/scripts/reproduce_window_truncation.py
uv run python research/station-coverage/th_thaiwater/scripts/build_inventory.py
uv run python research/station-coverage/th_thaiwater/scripts/build_station_table.py
uv run python research/station-coverage/th_thaiwater/scripts/build_evidence_index.py
```

`verify_evidence.py` re-hashes every recording and re-checks the inventory's completeness
assertions without touching the network.
