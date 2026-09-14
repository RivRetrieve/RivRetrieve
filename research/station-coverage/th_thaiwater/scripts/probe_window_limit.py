"""Establish the publisher's effective window limit on the graph route.

The port notes state that no publisher cap is claimed. This probe records what the route actually
returns for progressively longer requested windows, so the limit is established from responses
rather than assumed. Only requested/returned spans and row counts are retained; the bodies are not
stored (a one-year grid is several MB).

Usage: uv run python research/station-coverage/th_thaiwater/scripts/probe_window_limit.py
Output: inventory/window_limit_probe.csv
"""

from __future__ import annotations

import json
import pathlib
import time
import urllib.error  # noqa: TID251 - research capture tool, not provider runtime code
import urllib.parse  # noqa: TID251 - research capture tool, not provider runtime code
import urllib.request  # noqa: TID251 - research capture tool, not provider runtime code
from datetime import UTC, datetime

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
GRAPH = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_graph"
USER_AGENT = "RivRetrieve-research/0.1 (station coverage survey; +https://github.com/RivRetrieve/RivRetrieve)"
STATION = "1373273"
WINDOWS = [
    ("2026-08-31", "2026-09-06", "7 days"),
    ("2026-06-08", "2026-09-06", "90 days"),
    ("2025-09-08", "2026-09-06", "364 days"),
    ("2025-09-07", "2026-09-06", "365 days"),
    ("2025-09-06", "2026-09-06", "366 days"),
    ("2025-06-06", "2026-09-06", "15 months"),
    ("2023-09-06", "2026-09-06", "3 years"),
]


def probe(start: str, end: str) -> dict[str, object]:
    params = {"station_type": "tele_waterlevel", "station_id": STATION, "start_date": start, "end_date": end}
    request = urllib.request.Request(f"{GRAPH}?{urllib.parse.urlencode(params)}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            document = json.loads(response.read())
            status = response.status
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        return {
            "http_status": "",
            "rows": "",
            "returned_first": "",
            "returned_last": "",
            "request_error": f"{type(error).__name__}: {error}",
        }
    graph = (document.get("data") or {}).get("graph_data") or []
    return {
        "http_status": status,
        "rows": len(graph),
        "returned_first": graph[0]["datetime"] if graph else "",
        "returned_last": graph[-1]["datetime"] if graph else "",
        "request_error": "",
    }


def main() -> None:
    records = []
    for start, end, label in WINDOWS:
        result = probe(start, end)
        records.append(
            {
                "station_id": STATION,
                "requested_span": label,
                "requested_start": start,
                "requested_end": end,
                **result,
                "probed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }
        )
        print(
            f"  {label:>10}: requested {start}..{end} -> rows={result['rows']} "
            f"returned {result['returned_first']}..{result['returned_last']}",
            flush=True,
        )
        time.sleep(1.0)
    pd.DataFrame(records).to_csv(HERE / "inventory" / "window_limit_probe.csv", index=False)
    print("wrote window_limit_probe.csv")


if __name__ == "__main__":
    main()
