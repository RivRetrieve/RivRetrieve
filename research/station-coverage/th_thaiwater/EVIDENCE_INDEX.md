# th_thaiwater — evidence index

Every route surveyed is public and unauthenticated. No credentials, cookies or tokens were sent
or stored.

**Retention.** This project does not redistribute source observations. Every response keeps its
exact request URL, HTTP status, media type, UTC acquisition instant, byte size and the SHA-256 of
the full response, plus derived readings (grid rows, non-null counts, grid endpoints). A response
carrying no observation value — an all-null grid, an error body — is kept whole. A response
carrying observations is not kept; its digest cannot be recomputed from this repository. See
UNRESOLVED.md §7.

## Availability evidence package

| File | Size | Contents |
| --- | --- | --- |
| [`evidence/graph_receipts.csv`](evidence/graph_receipts.csv) | 576,984 B | 1377 receipts, one per graph request: 825 over 7 dates, 549 over 91 dates, 3 failed attempts. Every inventory row cites one by `request_id`. |
| [`evidence/graph_bodies_without_observations.zip`](evidence/graph_bodies_without_observations.zip) | 129,554 B | 39 whole response bodies carrying no observation value, one member per `request_id`. |

Acquired 2026-09-11T07:55:50.882871Z .. 2026-09-11T09:38:16.858951Z. The 1336 responses carrying observations total 500,847,708 B (25,874,399 B gzip-6); only their receipts are committed.

## Recordings

Recordings of distinct response shapes and boundary cases, in the repository's recording
convention. `Body` says whether the response bytes are kept.

| Recording | Status | Bytes | Body | SHA-256 (first 16) | Retrieved (UTC) | Establishes |
| --- | --- | --- | --- | --- | --- | --- |
| [`boundary_1035518_stage_only_hourly`](recordings/boundary_1035518_stage_only_hourly.recording.json)<br><sub>station_id=1035518 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 5,869 | not kept | `047997c9546d6b80` | 2026-09-07T15:37:31Z | A station publishing stage but no discharge, on an hourly grid. |
| [`boundary_1121218_data_in_july`](recordings/boundary_1121218_data_in_july.recording.json)<br><sub>station_id=1121218 start_date=2026-07-01 end_date=2026-07-03</sub> | 200 | 35,081 | not kept | `6b0f82d7b6cf6032` | 2026-09-07T15:37:32Z | Station publishing 411 stage values over 2026-07-01..2026-07-03 though absent from the later snapshot. |
| [`boundary_11688546_empty_90d`](recordings/boundary_11688546_empty_90d.recording.json)<br><sub>station_id=11688546 start_date=2026-06-08 end_date=2026-09-06</sub> | 200 | 172,668 | kept | `710e5649afedcd48` | 2026-09-07T15:37:34Z | Complete 91-date time grid with no non-null value for either product: the empty case, still answered with result OK. |
| [`boundary_1373272_both_products`](recordings/boundary_1373272_both_products.recording.json)<br><sub>station_id=1373272 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 36,086 | not kept | `8d7b46daee8d5f66` | 2026-09-07T15:37:30Z | A station publishing both value and discharge on a 10-minute grid. |
| [`churn_removed_1119916_graph`](recordings/churn_removed_1119916_graph.recording.json)<br><sub>station_id=1119916 start_date=2026-09-05 end_date=2026-09-06</sub> | 200 | 3,938 | not kept | `7bfd8c0949ea6beb` | 2026-09-07T15:09:32Z | Baseline station absent from the live snapshot that still publishes values: absence from waterlevel_load is not absence of data. |
| [`churn_removed_1121218_graph`](recordings/churn_removed_1121218_graph.recording.json)<br><sub>station_id=1121218 start_date=2026-09-05 end_date=2026-09-06</sub> | 200 | 22,883 | kept | `24bdfcd86a87caec` | 2026-09-07T15:09:34Z | Baseline station absent from the live snapshot; route answers result OK with a null-filled grid. |
| [`churn_removed_11568367_graph`](recordings/churn_removed_11568367_graph.recording.json)<br><sub>station_id=11568367 start_date=2026-09-05 end_date=2026-09-06</sub> | 200 | 22,883 | kept | `e54ce47034ae37e3` | 2026-09-07T15:09:35Z | Baseline station absent from the live snapshot; route answers result OK with a null-filled grid. |
| [`error_bad_station_type`](recordings/error_bad_station_type.recording.json)<br><sub>station_id=1373273 start_date=2026-09-05 end_date=2026-09-06</sub> | 500 | 2,108 | kept | `5d31e069957d3b95` | 2026-09-07T15:35:44Z | Unknown station_type returns HTTP 500 with a Go panic stack trace, not JSON. |
| [`error_missing_station_id`](recordings/error_missing_station_id.recording.json)<br><sub>start_date=2026-09-05 end_date=2026-09-06</sub> | 200 | 44 | kept | `fc48a1f0efaa7efd` | 2026-09-07T15:35:43Z | Missing station_id returns HTTP 200 carrying an error body: a 200 must still be checked. |
| [`error_nonexistent_station`](recordings/error_nonexistent_station.recording.json)<br><sub>station_id=999999999 start_date=2026-09-05 end_date=2026-09-06</sub> | 500 | 2,121 | kept | `23e97944b0130224` | 2026-09-07T15:35:41Z | Nonexistent station_id returns HTTP 500 with a Go panic stack trace, not JSON. |
| [`error_reversed_dates`](recordings/error_reversed_dates.recording.json)<br><sub>station_id=1373273 start_date=2026-09-06 end_date=2026-09-05</sub> | 200 | 133 | kept | `e2c75871803ee927` | 2026-09-07T15:35:42Z | end_date before start_date returns HTTP 200, result OK, zero rows - not an error. |
| [`hypo_noD_395`](recordings/hypo_noD_395.recording.json)<br><sub>station_id=395 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 35,047 | not kept | `ee0a309442c5852a` | 2026-09-07T15:10:36Z | Snapshot discharge null; graph route publishes no discharge (hypothesis sample, later shown insufficient across the population). |
| [`hypo_noD_575566`](recordings/hypo_noD_575566.recording.json)<br><sub>station_id=575566 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 34,332 | not kept | `36f6f01670950fe6` | 2026-09-07T15:10:40Z | Snapshot discharge null; graph route publishes no discharge (hypothesis sample, later shown insufficient across the population). |
| [`hypo_noD_575568`](recordings/hypo_noD_575568.recording.json)<br><sub>station_id=575568 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 34,332 | not kept | `cbf412a8748161f1` | 2026-09-07T15:10:31Z | Snapshot discharge null; graph route publishes no discharge (hypothesis sample, later shown insufficient across the population). |
| [`hypo_noD_595`](recordings/hypo_noD_595.recording.json)<br><sub>station_id=595 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 34,261 | kept | `0961b42613950667` | 2026-09-07T15:10:33Z | Snapshot discharge null; graph route publishes no discharge (hypothesis sample, later shown insufficient across the population). |
| [`hypo_withD_1095877`](recordings/hypo_withD_1095877.recording.json)<br><sub>station_id=1095877 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 6,151 | not kept | `4e9c875f2c9f2137` | 2026-09-07T15:10:26Z | Snapshot discharge present; graph route publishes discharge (hypothesis sample). |
| [`hypo_withD_1161516`](recordings/hypo_withD_1161516.recording.json)<br><sub>station_id=1161516 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 5,940 | not kept | `9dd5e1745666b803` | 2026-09-07T15:10:28Z | Snapshot discharge present; graph route publishes discharge (hypothesis sample). |
| [`hypo_withD_3085`](recordings/hypo_withD_3085.recording.json)<br><sub>station_id=3085 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 5,967 | not kept | `7942f87ba9e38fb5` | 2026-09-07T15:10:23Z | Snapshot discharge present; graph route publishes discharge (hypothesis sample). |
| [`hypo_withD_3122`](recordings/hypo_withD_3122.recording.json)<br><sub>station_id=3122 start_date=2026-09-04 end_date=2026-09-06</sub> | 200 | 5,951 | not kept | `fb60e6396dcc85d1` | 2026-09-07T15:10:29Z | Snapshot discharge present; graph route publishes discharge (hypothesis sample). |
| [`limit_three_year_window`](recordings/limit_three_year_window.recording.json)<br><sub>station_id=1373273 start_date=2023-09-06 end_date=2026-09-06</sub> | 200 | 4,346,430 | not kept | `f43099da644dd21b` | 2026-09-07T15:35:47Z | A 1,097-date request (2023-09-06..2026-09-06) returns 2025-09-06..2026-09-06 (366 dates) with HTTP 200 and no indication of the shortening. |
| [`waterlevel_load_live`](recordings/waterlevel_load_live.recording.json)<br><sub>https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_load</sub> | 200 | 2,384,841 | not kept | `c6de458722531801` | 2026-09-07T15:08:00Z | Live catalogue snapshot (1,405 stations, 2026-09-07): population churn against the 825 baseline, and the snapshot discharge field compared in FINDINGS §2. Per-station identity and field states in `waterlevel_load_live.stations.csv`. |

## Derived inventories

| File | Contents |
| --- | --- |
| [`inventory/station_product_evidence.csv`](inventory/station_product_evidence.csv) | Final inventory: 1,650 station × product rows, each copying its cited receipt. |
| [`inventory/inventory_summary.json`](inventory/inventory_summary.json) | Every sweep number quoted in the prose, generated. |
| [`inventory/metadata_vs_graph.csv`](inventory/metadata_vs_graph.csv) | Per-station snapshot discharge state vs graph discharge status; absent kept distinct from null. |
| [`inventory/metadata_vs_graph_summary.json`](inventory/metadata_vs_graph_summary.json) | Counts, denominators, snapshot instant and graph windows of that comparison. |
| [`STATION_TABLE.md`](STATION_TABLE.md) | Readable station list, one row per station. |
| [`inventory/population_churn.csv`](inventory/population_churn.csv) | Every station added to or absent from the source list since the baseline capture. |
| [`inventory/window_limit_probe.csv`](inventory/window_limit_probe.csv) | Window-limit probe as acquired 2026-09-07 (its `requested_span` labels mix conventions). |
| [`inventory/window_limit_readings.csv`](inventory/window_limit_readings.csv) | The same probe with elapsed days and inclusive dates derived from the recorded dates. |
| [`inventory/window_truncation_observation.json`](inventory/window_truncation_observation.json) | The shortening's measured consequence at the public surface. |

## Reproduction

```bash
uv run python research/station-coverage/th_thaiwater/scripts/acquire_graph_evidence.py   # network
uv run python research/station-coverage/th_thaiwater/scripts/build_inventory.py
uv run python research/station-coverage/th_thaiwater/scripts/build_metadata_comparison.py
uv run python research/station-coverage/th_thaiwater/scripts/build_churn_reconciliation.py
uv run python research/station-coverage/th_thaiwater/scripts/build_window_limit_readings.py
uv run python research/station-coverage/th_thaiwater/scripts/build_station_table.py
uv run python research/station-coverage/th_thaiwater/scripts/build_evidence_index.py
uv run python research/station-coverage/th_thaiwater/scripts/verify_evidence.py          # offline
```

`probe_window_limit.py`, `reproduce_window_truncation.py` and `capture.py` are the network scripts
that produced the probe table, the public-surface observation and the recordings;
`strip_observation_bytes.py` removed observation-bearing bytes from those recordings.
