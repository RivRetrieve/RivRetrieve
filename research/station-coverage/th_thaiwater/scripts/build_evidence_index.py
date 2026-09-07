"""Generate EVIDENCE_INDEX.md: every recording, its integrity fields, and what it establishes."""

from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]
RECORDINGS = HERE / "recordings"

ESTABLISHES = {
    "waterlevel_load_live": "Live catalogue snapshot (1,405 stations, 2026-09-07): population churn against the 825 baseline, and the snapshot fields whose availability signal is tested in FINDINGS section 2.",
    "boundary_1373272_both_products": "A station publishing both value and discharge on a 10-minute grid.",
    "boundary_1035518_stage_only_hourly": "A station publishing stage but no discharge, on an hourly grid.",
    "boundary_1121218_data_in_july": "Station empty in the 7-day window yet publishing 411 stage values in July: evidences why a short window understates coverage.",
    "boundary_11688546_empty_90d": "Complete 90-day time grid with no non-null value for either product: the empty case, still answered with result OK.",
    "churn_removed_1119916_graph": "Baseline station absent from the live snapshot that still publishes values: absence from waterlevel_load is not absence of data.",
    "churn_removed_1121218_graph": "Baseline station absent from the live snapshot; route answers result OK with a null-filled grid.",
    "churn_removed_11568367_graph": "Baseline station absent from the live snapshot; route answers result OK with a null-filled grid.",
    "error_nonexistent_station": "Nonexistent station_id returns HTTP 500 with a Go panic stack trace, not JSON.",
    "error_bad_station_type": "Unknown station_type returns HTTP 500 with a Go panic stack trace, not JSON.",
    "error_missing_station_id": "Missing station_id returns HTTP 200 carrying an error body: a 200 must still be checked.",
    "error_reversed_dates": "end_date before start_date returns HTTP 200, result OK, zero rows - not an error.",
    "limit_three_year_window": "A three-year request returns a one-year span with HTTP 200 and no indication of the clamp.",
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
    lines = [
        "# th_thaiwater — evidence index",
        "",
        "Every recording captured by this survey, with the integrity fields required by issue #224",
        "(exact request URL and parameters, HTTP status, media type, UTC retrieval instant, response bytes,",
        "SHA-256) and the finding it supports. Regenerate any of them with",
        "`scripts/capture.py <recording_id> <url> [key=value ...]`.",
        "",
        "Every route surveyed is public and unauthenticated. No credentials, cookies or tokens were sent",
        "or stored.",
        "",
        "| Recording | Status | Bytes | SHA-256 (first 16) | Retrieved (UTC) | Establishes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for path in sorted(RECORDINGS.glob("*.recording.json")):
        recording_id = path.name.replace(".recording.json", "")
        document = json.loads(path.read_text())
        response, request = document["response"], document["request"]
        size = len(response["content_base64"]) * 3 // 4
        parameters = request.get("parameters") or {}
        detail = " ".join(f"{key}={value}" for key, value in parameters.items() if key != "station_type")
        lines.append(
            f"| [`{recording_id}`](recordings/{path.name})<br><sub>{detail or request['url']}</sub> "
            f"| {response['status_code']} | {size:,} | `{response['sha256'][:16]}` "
            f"| {response['retrieved_at'][:19]}Z | {ESTABLISHES.get(recording_id, '')} |"
        )
    lines += [
        "",
        "## Derived inventories",
        "",
        "| File | Rows | Contents |",
        "| --- | --- | --- |",
        "| [`inventory/station_product_evidence.csv`](inventory/station_product_evidence.csv) | 1,650 | Final inventory: every station x product with status, basis and linked recording. |",
        "| [`STATION_TABLE.md`](STATION_TABLE.md) | 825 | Readable station list, one row per station. |",
        "| [`inventory/graph_sweep.csv`](inventory/graph_sweep.csv) | 825 | First pass: per-station non-null counts over the 7-day window. |",
        "| [`inventory/widened_90d.csv`](inventory/widened_90d.csv) | 549 | Re-probe over 90 days of every station with an empty product. |",
        "| [`inventory/widened_empty.csv`](inventory/widened_empty.csv) | 26 | Earlier re-probe of stations empty for both products. |",
        "| [`inventory/window_limit_probe.csv`](inventory/window_limit_probe.csv) | 7 | Requested vs returned spans establishing the 365-day clamp. |",
        "| [`inventory/window_truncation_observation.json`](inventory/window_truncation_observation.json) | - | The clamp's measured consequence at the public surface. |",
        "",
        "## Reproduction",
        "",
        "```bash",
        "uv run python research/station-coverage/th_thaiwater/scripts/sweep_availability.py",
        "uv run python research/station-coverage/th_thaiwater/scripts/widen_all_empty.py",
        "uv run python research/station-coverage/th_thaiwater/scripts/probe_window_limit.py",
        "uv run python research/station-coverage/th_thaiwater/scripts/reproduce_window_truncation.py",
        "uv run python research/station-coverage/th_thaiwater/scripts/build_inventory.py",
        "uv run python research/station-coverage/th_thaiwater/scripts/build_station_table.py",
        "uv run python research/station-coverage/th_thaiwater/scripts/build_evidence_index.py",
        "```",
        "",
        "`verify_evidence.py` re-hashes every recording and re-checks the inventory's completeness",
        "assertions without touching the network.",
    ]
    (HERE / "EVIDENCE_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote EVIDENCE_INDEX.md covering {len(list(RECORDINGS.glob('*.recording.json')))} recordings")


if __name__ == "__main__":
    main()
