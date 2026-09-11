"""Generate EVIDENCE_INDEX.md: the evidence package, every recording, and what each establishes."""

from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]
RECORDINGS = HERE / "recordings"

ESTABLISHES = {
    "waterlevel_load_live": "Live catalogue snapshot (1,405 stations, 2026-09-07): population churn against the 825 baseline, and the snapshot discharge field compared in FINDINGS §2. Per-station identity and field states in `waterlevel_load_live.stations.csv`.",
    "boundary_1373272_both_products": "A station publishing both value and discharge on a 10-minute grid.",
    "boundary_1035518_stage_only_hourly": "A station publishing stage but no discharge, on an hourly grid.",
    "boundary_1121218_data_in_july": "Station publishing 411 stage values over 2026-07-01..2026-07-03 though absent from the later snapshot.",
    "boundary_11688546_empty_90d": "Complete 91-date time grid with no non-null value for either product: the empty case, still answered with result OK.",
    "churn_removed_1119916_graph": "Baseline station absent from the live snapshot that still publishes values: absence from waterlevel_load is not absence of data.",
    "churn_removed_1121218_graph": "Baseline station absent from the live snapshot; route answers result OK with a null-filled grid.",
    "churn_removed_11568367_graph": "Baseline station absent from the live snapshot; route answers result OK with a null-filled grid.",
    "error_nonexistent_station": "Nonexistent station_id returns HTTP 500 with a Go panic stack trace, not JSON.",
    "error_bad_station_type": "Unknown station_type returns HTTP 500 with a Go panic stack trace, not JSON.",
    "error_missing_station_id": "Missing station_id returns HTTP 200 carrying an error body: a 200 must still be checked.",
    "error_reversed_dates": "end_date before start_date returns HTTP 200, result OK, zero rows - not an error.",
    "limit_three_year_window": "A 1,097-date request (2023-09-06..2026-09-06) returns 2025-09-06..2026-09-06 (366 dates) with HTTP 200 and no indication of the shortening.",
}
for station in ("3085", "1095877", "1161516", "3122"):
    ESTABLISHES[f"hypo_withD_{station}"] = (
        "Snapshot discharge present; graph route publishes discharge (hypothesis sample)."
    )
for station in ("395", "575566", "575568", "595"):
    ESTABLISHES[f"hypo_noD_{station}"] = (
        "Snapshot discharge null; graph route publishes no discharge (hypothesis sample, later shown insufficient across the population)."
    )


def main() -> None:
    sweep = json.loads((HERE / "inventory" / "inventory_summary.json").read_text())
    lines = [
        "# th_thaiwater — evidence index",
        "",
        "Every route surveyed is public and unauthenticated. No credentials, cookies or tokens were sent",
        "or stored.",
        "",
        "**Retention.** This project does not redistribute source observations. Every response keeps its",
        "exact request URL, HTTP status, media type, UTC acquisition instant, byte size and the SHA-256 of",
        "the full response, plus derived readings (grid rows, non-null counts, grid endpoints). A response",
        "carrying no observation value — an all-null grid, an error body — is kept whole. A response",
        "carrying observations is not kept; its digest cannot be recomputed from this repository. See",
        "UNRESOLVED.md §7.",
        "",
        "## Availability evidence package",
        "",
        "| File | Size | Contents |",
        "| --- | --- | --- |",
        f"| [`evidence/graph_receipts.csv`](evidence/graph_receipts.csv) | {sweep['receipts_bytes']:,} B "
        f"| {sweep['receipts']} receipts, one per graph request: {sweep['short_window_requests']} over "
        f"7 dates, {sweep['wide_window_requests']} over 91 dates, {sweep['failed_attempts']} failed attempts. "
        "Every inventory row cites one by `request_id`. |",
        f"| [`evidence/graph_bodies_without_observations.zip`](evidence/graph_bodies_without_observations.zip) "
        f"| {sweep['bundle_bytes']:,} B | {sweep['bodies_retained']} whole response bodies carrying no "
        "observation value, one member per `request_id`. |",
        "",
        f"Acquired {sweep['acquired_between'][0]} .. {sweep['acquired_between'][1]}. The "
        f"{sweep['bodies_not_retained']} responses carrying observations total "
        f"{sweep['response_bytes_carrying_observations']:,} B ({sweep['response_gzip6_bytes_carrying_observations']:,} B "
        "gzip-6); only their receipts are committed.",
        "",
        "## Recordings",
        "",
        "Recordings of distinct response shapes and boundary cases, in the repository's recording",
        "convention. `Body` says whether the response bytes are kept.",
        "",
        "| Recording | Status | Bytes | Body | SHA-256 (first 16) | Retrieved (UTC) | Establishes |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for path in sorted(RECORDINGS.glob("*.recording.json")):
        recording_id = path.name.replace(".recording.json", "")
        document = json.loads(path.read_text())
        response, request = document["response"], document["request"]
        parameters = request.get("parameters") or {}
        detail = " ".join(f"{key}={value}" for key, value in parameters.items() if key != "station_type")
        lines.append(
            f"| [`{recording_id}`](recordings/{path.name})<br><sub>{detail or request['url']}</sub> "
            f"| {response['status_code']} | {response['response_bytes']:,} "
            f"| {'kept' if response['body_retained'] else 'not kept'} | `{response['sha256'][:16]}` "
            f"| {response['retrieved_at'][:19]}Z | {ESTABLISHES.get(recording_id, '')} |"
        )
    lines += [
        "",
        "## Derived inventories",
        "",
        "| File | Contents |",
        "| --- | --- |",
        "| [`inventory/station_product_evidence.csv`](inventory/station_product_evidence.csv) | Final inventory: 1,650 station × product rows, each copying its cited receipt. |",
        "| [`inventory/inventory_summary.json`](inventory/inventory_summary.json) | Every sweep number quoted in the prose, generated. |",
        "| [`inventory/metadata_vs_graph.csv`](inventory/metadata_vs_graph.csv) | Per-station snapshot discharge state vs graph discharge status; absent kept distinct from null. |",
        "| [`inventory/metadata_vs_graph_summary.json`](inventory/metadata_vs_graph_summary.json) | Counts, denominators, snapshot instant and graph windows of that comparison. |",
        "| [`STATION_TABLE.md`](STATION_TABLE.md) | Readable station list, one row per station. |",
        "| [`inventory/population_churn.csv`](inventory/population_churn.csv) | Every station added to or absent from the source list since the baseline capture. |",
        "| [`inventory/window_limit_probe.csv`](inventory/window_limit_probe.csv) | Window-limit probe as acquired 2026-09-07 (its `requested_span` labels mix conventions). |",
        "| [`inventory/window_limit_readings.csv`](inventory/window_limit_readings.csv) | The same probe with elapsed days and inclusive dates derived from the recorded dates. |",
        "| [`inventory/window_truncation_observation.json`](inventory/window_truncation_observation.json) | The shortening's measured consequence at the public surface. |",
        "",
        "## Reproduction",
        "",
        "```bash",
        "uv run python research/station-coverage/th_thaiwater/scripts/acquire_graph_evidence.py   # network",
        "uv run python research/station-coverage/th_thaiwater/scripts/build_inventory.py",
        "uv run python research/station-coverage/th_thaiwater/scripts/build_metadata_comparison.py",
        "uv run python research/station-coverage/th_thaiwater/scripts/build_churn_reconciliation.py",
        "uv run python research/station-coverage/th_thaiwater/scripts/build_window_limit_readings.py",
        "uv run python research/station-coverage/th_thaiwater/scripts/build_station_table.py",
        "uv run python research/station-coverage/th_thaiwater/scripts/build_evidence_index.py",
        "uv run python research/station-coverage/th_thaiwater/scripts/verify_evidence.py          # offline",
        "```",
        "",
        "`probe_window_limit.py`, `reproduce_window_truncation.py` and `capture.py` are the network scripts",
        "that produced the probe table, the public-surface observation and the recordings;",
        "`strip_observation_bytes.py` removed observation-bearing bytes from those recordings.",
    ]
    (HERE / "EVIDENCE_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote EVIDENCE_INDEX.md covering {len(list(RECORDINGS.glob('*.recording.json')))} recordings")


if __name__ == "__main__":
    main()
