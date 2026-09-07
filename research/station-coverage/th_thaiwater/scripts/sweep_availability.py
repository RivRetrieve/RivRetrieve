"""Establish per-station measurement availability across the baseline population.

One graph request per station over a single shared window. Only derived counts are retained:
the response bodies are not stored, so no observation history is accumulated merely to establish
support. Representative responses are recorded separately by capture.py.

A station with no non-null values in the tested window is recorded as empty *in that window*.
That is never converted into "unsupported" — the source states no such thing.

Usage: uv run python research/station-coverage/th_thaiwater/scripts/sweep_availability.py
Output: inventory/graph_sweep.csv (one row per station, none omitted)
"""

from __future__ import annotations

import csv
import json
import pathlib
import time
import urllib.error  # noqa: TID251 - research capture tool, not provider runtime code
import urllib.parse  # noqa: TID251 - research capture tool, not provider runtime code
import urllib.request  # noqa: TID251 - research capture tool, not provider runtime code
from datetime import UTC, datetime

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = pathlib.Path(__file__).resolve().parents[3].parent
NATIVE = ROOT / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
OUT = HERE / "inventory" / "graph_sweep.csv"
GRAPH = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_graph"
USER_AGENT = "RivRetrieve-research/0.1 (station coverage survey; +https://github.com/RivRetrieve/RivRetrieve)"

START_DATE = "2026-08-31"
END_DATE = "2026-09-06"
DELAY_SECONDS = 0.35


def probe(station_id: str) -> dict[str, object]:
    params = {
        "station_type": "tele_waterlevel",
        "station_id": station_id,
        "start_date": START_DATE,
        "end_date": END_DATE,
    }
    url = f"{GRAPH}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw, status = response.read(), response.status
    except urllib.error.HTTPError as error:
        return {
            "http_status": error.code,
            "result": "",
            "rows": "",
            "nonnull_value": "",
            "nonnull_discharge": "",
            "first_datetime": "",
            "last_datetime": "",
            "request_error": "",
        }
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {
            "http_status": "",
            "result": "",
            "rows": "",
            "nonnull_value": "",
            "nonnull_discharge": "",
            "first_datetime": "",
            "last_datetime": "",
            "request_error": f"{type(error).__name__}: {error}",
        }
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return {
            "http_status": status,
            "result": "",
            "rows": "",
            "nonnull_value": "",
            "nonnull_discharge": "",
            "first_datetime": "",
            "last_datetime": "",
            "request_error": f"decode_error: {error}",
        }

    graph = (document.get("data") or {}).get("graph_data") or []
    return {
        "http_status": status,
        "result": document.get("result", ""),
        "rows": len(graph),
        "nonnull_value": sum(1 for row in graph if row.get("value") is not None),
        "nonnull_discharge": sum(1 for row in graph if row.get("discharge") is not None),
        "first_datetime": graph[0]["datetime"] if graph else "",
        "last_datetime": graph[-1]["datetime"] if graph else "",
        "request_error": "",
    }


def main() -> None:
    native = pd.read_parquet(NATIVE)
    frame = native[["station.id", "station.tele_station_name.en", "agency.agency_name.en"]].copy()
    frame.columns = ["station_id", "station_name", "agency"]
    frame["station_id"] = frame.station_id.astype(str)

    print(f"sweeping {len(frame)} baseline stations, window {START_DATE}..{END_DATE}")
    records = []
    for count, row in enumerate(frame.itertuples(), start=1):
        result = probe(str(row.station_id))
        records.append(
            {
                "station_id": row.station_id,
                "station_name": row.station_name,
                "agency": row.agency,
                "window_start": START_DATE,
                "window_end": END_DATE,
                **result,
                "probed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }
        )
        if count % 50 == 0:
            print(f"  {count}/{len(frame)}", flush=True)
        time.sleep(DELAY_SECONDS)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    print(f"wrote {len(records)} rows -> {OUT.name}")


if __name__ == "__main__":
    main()
