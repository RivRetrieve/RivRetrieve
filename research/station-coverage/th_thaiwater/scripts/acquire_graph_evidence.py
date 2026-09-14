"""Acquire the graph responses behind every availability conclusion, keeping a receipt for each.

    acquire : BaselineStations -> (Receipt table, Bundle of observation-free bodies)   (network)

The original survey (2026-09-07) retained only derived counts and discarded every response body, so
its conclusions could not be linked to the response that produced them. This script is the
replacement capture: same route, same explicit windows, new acquisition instants recorded as such.

Two passes, as in the original method:
  1. every baseline station over 2026-08-31 .. 2026-09-06 (7 inclusive calendar dates);
  2. every station with a product carrying no non-null value in pass 1, over
     2026-06-08 .. 2026-09-06 (91 inclusive calendar dates).

One request serves both products; each response is receipted once.

Retention. This project does not redistribute source observations. Each response keeps its exact
request URL, HTTP status, media type, UTC acquisition instant, byte size and SHA-256 of the full
bytes, plus derived readings (grid rows, non-null counts per field, grid endpoints). A response
carrying no observation value at all - an all-null grid, an error body - is kept whole in the
bundle, because establishing that it is empty requires every byte. A body carrying observations is
never written to disk.

Resumable: request ids already receipted successfully are skipped; a failed attempt stays in the
receipt table as evidence and the next run makes a new attempt under a new id.

Usage: uv run python research/station-coverage/th_thaiwater/scripts/acquire_graph_evidence.py
Output: evidence/graph_receipts.csv, evidence/graph_bodies_without_observations.zip
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import pathlib
import time
import urllib.error  # noqa: TID251 - research capture tool, not provider runtime code
import urllib.parse  # noqa: TID251 - research capture tool, not provider runtime code
import urllib.request  # noqa: TID251 - research capture tool, not provider runtime code
import zipfile
from datetime import UTC, datetime

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = pathlib.Path(__file__).resolve().parents[3].parent
NATIVE = ROOT / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
RECEIPTS = HERE / "evidence" / "graph_receipts.csv"
BUNDLE = HERE / "evidence" / "graph_bodies_without_observations.zip"
GRAPH = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_graph"
USER_AGENT = "RivRetrieve-research/0.1 (station coverage survey; +https://github.com/RivRetrieve/RivRetrieve)"
SHORT = ("2026-08-31", "2026-09-06")
WIDE = ("2026-06-08", "2026-09-06")
DELAY_SECONDS = 0.35
OBSERVATION_FIELDS = ("value", "discharge", "value_out")
FIELDS = [
    "request_id",
    "station_id",
    "window_start",
    "window_end",
    "request_url",
    "retrieved_at",
    "http_status",
    "content_type",
    "response_bytes",
    "response_sha256",
    "response_gzip6_bytes",
    "result",
    "grid_rows",
    "nonnull_value",
    "nonnull_discharge",
    "nonnull_value_out",
    "grid_first",
    "grid_last",
    "body_retained",
    "request_error",
]


def read(raw: bytes) -> dict[str, object]:
    """Derived readings of one graph response body. Counts only; no observation value survives."""
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"result": "", "parse": "not_json"}
    data = document.get("data") if isinstance(document, dict) else None
    if not isinstance(data, dict) or "graph_data" not in data:
        return {"result": document.get("result", "") if isinstance(document, dict) else "", "parse": "no_graph"}
    graph = data["graph_data"] or []
    return {
        "result": document.get("result", ""),
        "parse": "graph",
        "grid_rows": len(graph),
        "nonnull_value": sum(1 for row in graph if row.get("value") is not None),
        "nonnull_discharge": sum(1 for row in graph if row.get("discharge") is not None),
        "nonnull_value_out": sum(1 for row in graph if row.get("value_out") is not None),
        "grid_first": graph[0]["datetime"] if graph else "",
        "grid_last": graph[-1]["datetime"] if graph else "",
    }


def carries_observations(reading: dict[str, object]) -> bool:
    if reading["parse"] == "graph":
        return any(isinstance(n := reading[f"nonnull_{field}"], int) and n > 0 for field in OBSERVATION_FIELDS)
    return False  # an error or non-graph body carries no observation field


def fetch(request_id: str, station_id: str, window: tuple[str, str], bundle: zipfile.ZipFile) -> dict[str, object]:
    params = {
        "station_type": "tele_waterlevel",
        "station_id": station_id,
        "start_date": window[0],
        "end_date": window[1],
    }
    url = f"{GRAPH}?{urllib.parse.urlencode(params)}"
    receipt: dict[str, object] = dict.fromkeys(FIELDS, "")
    receipt.update(request_id=request_id, station_id=station_id, window_start=window[0], window_end=window[1])
    receipt["request_url"] = url
    retrieved_at = datetime.now(UTC)
    receipt["retrieved_at"] = retrieved_at.isoformat().replace("+00:00", "Z")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            raw, status = response.read(), response.status
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as error:  # the refusal is evidence; keep it
        raw, status = error.read(), error.code
        content_type = error.headers.get("Content-Type", "") if error.headers else ""
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        receipt["request_error"] = f"{type(error).__name__}: {error}"
        receipt["body_retained"] = False
        return receipt

    reading = read(raw)
    receipt.update(
        http_status=status,
        content_type=content_type,
        response_bytes=len(raw),
        response_sha256=hashlib.sha256(raw).hexdigest(),
        response_gzip6_bytes=len(gzip.compress(raw, 6)),
        **{key: value for key, value in reading.items() if key != "parse"},
    )
    if reading["parse"] != "graph":
        receipt["request_error"] = f"response is {reading['parse']}"
    keep = not carries_observations(reading)
    receipt["body_retained"] = keep
    if keep:
        info = zipfile.ZipInfo(f"{request_id}.body", date_time=retrieved_at.timetuple()[:6])
        info.compress_type = zipfile.ZIP_DEFLATED
        bundle.writestr(info, raw)
    return receipt


def main() -> None:
    stations = sorted(pd.read_parquet(NATIVE)["station.id"].astype(str), key=lambda value: (len(value), value))
    RECEIPTS.parent.mkdir(parents=True, exist_ok=True)
    done: dict[str, dict[str, str]] = {}
    attempts: dict[tuple[str, str], int] = {}
    if RECEIPTS.exists():
        with RECEIPTS.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row["station_id"], row["window_start"])
                attempts[key] = attempts.get(key, 0) + 1
                if not row["request_error"]:
                    done[f"{row['station_id']}|{row['window_start']}"] = row
    new_file = not RECEIPTS.exists()
    with RECEIPTS.open("a", newline="", encoding="utf-8") as handle, zipfile.ZipFile(BUNDLE, "a") as bundle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()

        def acquire(station_id: str, window: tuple[str, str]) -> dict[str, str]:
            key = f"{station_id}|{window[0]}"
            if key in done:
                return done[key]
            attempt = attempts.get((station_id, window[0]), 0) + 1
            attempts[(station_id, window[0])] = attempt
            request_id = f"{station_id}_{window[0]}_{window[1]}_a{attempt}"
            receipt = {k: str(v) for k, v in fetch(request_id, station_id, window, bundle).items()}
            writer.writerow(receipt)
            handle.flush()
            time.sleep(DELAY_SECONDS)
            if not receipt["request_error"]:
                done[key] = receipt
            return receipt

        print(f"pass 1: {len(stations)} stations over {SHORT[0]}..{SHORT[1]}", flush=True)
        short = {}
        for count, station_id in enumerate(stations, start=1):
            short[station_id] = acquire(station_id, SHORT)
            if count % 50 == 0:
                print(f"  {count}/{len(stations)}", flush=True)

        widen = [
            station_id
            for station_id, receipt in short.items()
            if not receipt["request_error"]
            and (int(receipt["nonnull_value"]) == 0 or int(receipt["nonnull_discharge"]) == 0)
        ]
        print(f"pass 2: {len(widen)} stations with an empty product over {WIDE[0]}..{WIDE[1]}", flush=True)
        for count, station_id in enumerate(widen, start=1):
            acquire(station_id, WIDE)
            if count % 50 == 0:
                print(f"  {count}/{len(widen)}", flush=True)
    print(f"receipts -> {RECEIPTS.name}; observation-free bodies -> {BUNDLE.name} ({BUNDLE.stat().st_size:,} B)")


if __name__ == "__main__":
    main()
