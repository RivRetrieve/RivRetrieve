"""Compare the catalogue snapshot's discharge field with graph-route discharge, per baseline station.

    comparison : (Snapshot 2026-09-07 x Inventory) -> per-station class + counts with denominators

The two sides answer different time questions. The snapshot (`waterlevel_load`, acquired
2026-09-07T15:08:00Z) carries each station's latest reading at that instant. The graph side is the
inventory's discharge status over a 7- or 91-date window ending 2026-09-06. A disagreement means the
snapshot field does not predict the window's availability; it is not evidence that either is wrong.

Stations are split by presence first, because a baseline station absent from the snapshot response
is a different case from one present with a null discharge field:

  absent   - baseline station not in the snapshot response; the snapshot says nothing about it
  present  - in the response; its `discharge` field is `value` (set) or `null`. No blank string occurs;
             a blank would be kept as its own class.

Usage: uv run python research/station-coverage/th_thaiwater/scripts/build_metadata_comparison.py
Output: inventory/metadata_vs_graph.csv, inventory/metadata_vs_graph_summary.json
"""

from __future__ import annotations

import collections
import csv
import json
import pathlib

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = pathlib.Path(__file__).resolve().parents[3].parent
NATIVE = ROOT / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
CLASS = {
    ("value", "available"): "agree_snapshot_value_graph_available",
    ("null", "empty_in_tested_window"): "agree_snapshot_null_graph_empty",
    ("null", "available"): "snapshot_null_graph_available",
    ("value", "empty_in_tested_window"): "snapshot_value_graph_empty",
    ("blank", "available"): "snapshot_blank_graph_available",
    ("blank", "empty_in_tested_window"): "snapshot_blank_graph_empty",
    ("absent", "available"): "absent_graph_available",
    ("absent", "empty_in_tested_window"): "absent_graph_empty",
}


def read_csv(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    inventory = read_csv(HERE / "inventory" / "station_product_evidence.csv")
    snapshot = {row["station_id"]: row for row in read_csv(HERE / "recordings" / "waterlevel_load_live.stations.csv")}
    recording = json.loads((HERE / "recordings" / "waterlevel_load_live.recording.json").read_text())
    by = {(row["station_id"], row["product_id"]): row for row in inventory}
    stations = sorted({row["station_id"] for row in inventory}, key=lambda value: (len(value), value))

    rows = []
    for station in stations:
        live = snapshot.get(station)
        state = live["discharge_state"] if live else "absent"
        discharge = by[(station, "discharge_reported")]
        rows.append(
            {
                "station_id": station,
                "snapshot_presence": "present" if live else "absent",
                "snapshot_discharge_state": state,
                "graph_discharge_status": discharge["status"],
                "graph_stage_status": by[(station, "stage_reported")]["status"],
                "window_start": discharge["window_start"],
                "window_end": discharge["window_end"],
                "comparison": CLASS.get((state, discharge["status"]), f"unclassified_{state}_{discharge['status']}"),
            }
        )
    with (HERE / "inventory" / "metadata_vs_graph.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    counts = collections.Counter(row["comparison"] for row in rows)
    present = [row for row in rows if row["snapshot_presence"] == "present"]
    agree = counts["agree_snapshot_value_graph_available"] + counts["agree_snapshot_null_graph_empty"]
    disagree_present = counts["snapshot_null_graph_available"] + counts["snapshot_value_graph_empty"]
    native = pd.read_parquet(NATIVE)
    windows = collections.Counter(f"{row['window_start']}..{row['window_end']}" for row in rows)
    summary = {
        "snapshot_route": recording["request"]["url"],
        "snapshot_acquired_at": recording["response"]["retrieved_at"],
        "graph_windows_for_discharge": dict(sorted(windows.items())),
        "graph_acquired_between": [
            min(by[(s, "discharge_reported")]["retrieved_at"] for s in stations),
            max(by[(s, "discharge_reported")]["retrieved_at"] for s in stations),
        ],
        "baseline_stations": len(rows),
        "present_in_snapshot": len(present),
        "absent_from_snapshot": len(rows) - len(present),
        "counts": dict(sorted(counts.items())),
        "present_agree": agree,
        "present_disagree": disagree_present,
        "present_agreement_rate": round(agree / len(present), 4),
        "absent_with_graph_discharge": counts["absent_graph_available"],
        "absent_without_graph_discharge": counts["absent_graph_empty"],
        "missing_as_null_disagreements_over_baseline": disagree_present + counts["absent_graph_available"],
        "snapshot_waterlevel_m_null_live": sum(r["waterlevel_m_state"] == "null" for r in snapshot.values()),
        "snapshot_stations_live": len(snapshot),
        "baseline_capture_waterlevel_m_null": int(native["waterlevel_m"].isna().sum()),
        "baseline_capture_stations": len(native),
    }
    (HERE / "inventory" / "metadata_vs_graph_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
