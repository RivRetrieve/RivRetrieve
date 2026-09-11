"""Remove publisher observation values from the committed recordings, keeping receipts and readings.

    strip : Recording -> Recording   (idempotent; a recording already stripped is left unchanged)

This project does not redistribute source observations. A recording whose body carries no
observation value (an all-null grid, an error body, an empty result) keeps its bytes whole. A
recording whose body carries observations keeps its exact request, HTTP status, media type, UTC
acquisition instant, byte size and SHA-256 of the full bytes, plus derived readings, and loses the
bytes. The stored digest is checked against the bytes before they are removed.

The waterlevel_load snapshot carries a latest reading per station, so it is stripped too; its
per-station identity fields and the populated/null state of each measurement field are written to
recordings/waterlevel_load_live.stations.csv. No field value is copied, only whether it was set.

Usage: uv run python research/station-coverage/th_thaiwater/scripts/strip_observation_bytes.py
"""

from __future__ import annotations

import base64
import csv
import hashlib
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]
RECORDINGS = HERE / "recordings"
SNAPSHOT_MEASUREMENTS = (
    "discharge",
    "waterlevel_m",
    "waterlevel_msl",
    "waterlevel_msl_previous",
    "flow_rate",
    "storage_percent",
    "diff_wl_bank",
)
STATION_FIELDS = [
    "station_id",
    "name_th",
    "name_en",
    "river_name",
    "agency_en",
    "basin_en",
    "waterlevel_datetime",
    *(f"{field}_state" for field in SNAPSHOT_MEASUREMENTS),
]


def state(row: dict, field: str) -> str:
    if field not in row:
        return "missing_key"
    value = row[field]
    if value is None:
        return "null"
    if isinstance(value, str) and not value.strip():
        return "blank"
    return "value"


def graph_reading(document: dict) -> dict[str, object] | None:
    data = document.get("data")
    if not isinstance(data, dict) or "graph_data" not in data:
        return None
    graph = data["graph_data"] or []
    return {
        "result": document.get("result", ""),
        "grid_rows": len(graph),
        "nonnull_value": sum(1 for row in graph if row.get("value") is not None),
        "nonnull_discharge": sum(1 for row in graph if row.get("discharge") is not None),
        "nonnull_value_out": sum(1 for row in graph if row.get("value_out") is not None),
        "grid_first": graph[0]["datetime"] if graph else "",
        "grid_last": graph[-1]["datetime"] if graph else "",
    }


def snapshot_reading(document: dict, path: pathlib.Path) -> dict[str, object]:
    rows = document["waterlevel_data"]["data"]
    stations = []
    for row in rows:
        station = row.get("station") or {}
        name = station.get("tele_station_name") or {}
        stations.append(
            {
                "station_id": str(station["id"]),
                "name_th": name.get("th", ""),
                "name_en": name.get("en", ""),
                "river_name": row.get("river_name", ""),
                "agency_en": ((row.get("agency") or {}).get("agency_name") or {}).get("en", ""),
                "basin_en": ((row.get("basin") or {}).get("basin_name") or {}).get("en", ""),
                "waterlevel_datetime": row.get("waterlevel_datetime", ""),
                **{f"{field}_state": state(row, field) for field in SNAPSHOT_MEASUREMENTS},
            }
        )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=STATION_FIELDS)
        writer.writeheader()
        writer.writerows(sorted(stations, key=lambda s: (len(s["station_id"]), s["station_id"])))
    populated = sum(any(state(row, f) == "value" for f in SNAPSHOT_MEASUREMENTS) for row in rows)
    return {
        "result": document["waterlevel_data"].get("result", ""),
        "stations": len(rows),
        "stations_with_a_populated_measurement_field": populated,
        "station_readings": path.name,
    }


def main() -> None:
    for path in sorted(RECORDINGS.glob("*.recording.json")):
        document = json.loads(path.read_text())
        response = document["response"]
        if "content_base64" not in response:
            print(f"  already stripped  {path.name}")
            continue
        raw = base64.b64decode(response["content_base64"])
        if hashlib.sha256(raw).hexdigest() != response["sha256"]:
            raise SystemExit(f"{path.name}: stored SHA-256 does not match stored bytes; refusing to strip")
        try:
            body = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = None

        reading: dict[str, object] | None = None
        carries = False
        if isinstance(body, dict) and "waterlevel_data" in body:
            reading = snapshot_reading(body, RECORDINGS / f"{path.name.removesuffix('.recording.json')}.stations.csv")
            carries = bool(reading["stations_with_a_populated_measurement_field"])
        elif isinstance(body, dict):
            reading = graph_reading(body)
            if reading is not None:
                carries = any(
                    isinstance(n := reading[f"nonnull_{f}"], int) and n > 0 for f in ("value", "discharge", "value_out")
                )

        stripped = {
            "status_code": response["status_code"],
            "content_type": response["content_type"],
            "retrieved_at": response["retrieved_at"],
            "response_bytes": len(raw),
            "sha256": response["sha256"],
            "body_retained": not carries,
        }
        if not carries:
            stripped["content_base64"] = response["content_base64"]
        if reading is not None:
            stripped["reading"] = reading
        document["response"] = stripped
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  {'KEPT WHOLE' if not carries else 'stripped  '}  {path.name}  ({len(raw):,} B)")


if __name__ == "__main__":
    main()
