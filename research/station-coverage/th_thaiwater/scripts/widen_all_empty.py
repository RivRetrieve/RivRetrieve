"""Re-probe every station x product recorded empty on the short window, over 90 days.

A negative availability claim is only as strong as the window it rests on. Widening recovered 14 of
26 stations in the first pass, so every empty pair - not only stations empty for both products - is
re-probed before the claim is recorded.

One request per station serves both products. Only derived counts are retained.

Usage: uv run python research/station-coverage/th_thaiwater/scripts/widen_all_empty.py
Output: inventory/widened_90d.csv
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
WIDE_START = "2026-06-08"
WIDE_END = "2026-09-06"


def probe(station_id: str) -> dict[str, object]:
    params = {
        "station_type": "tele_waterlevel",
        "station_id": station_id,
        "start_date": WIDE_START,
        "end_date": WIDE_END,
    }
    request = urllib.request.Request(f"{GRAPH}?{urllib.parse.urlencode(params)}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            document = json.loads(response.read())
            status = response.status
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        return {
            "http_status": "",
            "rows": "",
            "nonnull_value": "",
            "nonnull_discharge": "",
            "request_error": f"{type(error).__name__}: {error}",
        }
    graph = (document.get("data") or {}).get("graph_data") or []
    return {
        "http_status": status,
        "rows": len(graph),
        "nonnull_value": sum(1 for row in graph if row.get("value") is not None),
        "nonnull_discharge": sum(1 for row in graph if row.get("discharge") is not None),
        "request_error": "",
    }


def main() -> None:
    sweep = pd.read_csv(HERE / "inventory" / "graph_sweep.csv", dtype=str)
    for column in ("nonnull_value", "nonnull_discharge"):
        sweep[column] = pd.to_numeric(sweep[column], errors="coerce")
    targets = sweep[(sweep.nonnull_value == 0) | (sweep.nonnull_discharge == 0)]
    print(f"re-probing {len(targets)} stations with at least one empty product over {WIDE_START}..{WIDE_END} (90 days)")
    records = []
    for count, row in enumerate(targets.itertuples(), start=1):
        result = probe(str(row.station_id))
        records.append(
            {
                "station_id": row.station_id,
                "window_start": WIDE_START,
                "window_end": WIDE_END,
                **result,
                "probed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }
        )
        if count % 50 == 0:
            print(f"  {count}/{len(targets)}", flush=True)
        time.sleep(0.35)
    pd.DataFrame(records).to_csv(HERE / "inventory" / "widened_90d.csv", index=False)
    print(f"wrote {len(records)} rows -> widened_90d.csv")


if __name__ == "__main__":
    main()
