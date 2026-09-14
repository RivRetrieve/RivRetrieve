"""Graph evidence certification : pair ledger × native station agencies × private acquisitions → verified pair counts.

The ledger-only check certifies public metadata consistency, not private response bytes.
The CLI requires the controlled evidence root and performs complete body verification.
It never contacts a source or rewrites the acquired corpus.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlparse  # noqa: TID251 - offline request inspection only

import polars as pl

FIELDS = {"stage_reported": "value", "discharge_reported": "discharge"}
GRAPH_URL = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_graph"


def read_ledger(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def station_agencies(native_path: Path) -> dict[str, str]:
    native = pl.read_parquet(native_path)
    agencies = {}
    for station, agency, station_agency in native.select("station.id", "agency.id", "station.agency_id").iter_rows():
        if agency != station_agency or agency not in {8, 9, 12, 91} or not isinstance(station, str):
            raise ValueError(f"unverified native station agency: {station}")
        if station in agencies:
            raise ValueError(f"duplicate native station: {station}")
        agencies[station] = f"th_agency_{agency}"
    return agencies


def verify_ledger(rows: list[dict[str, str]], agencies: dict[str, str]) -> None:
    pairs = Counter((row["station_id"], row["product_id"]) for row in rows)
    if set(pairs) != {(station, product) for station in agencies for product in FIELDS} or set(pairs.values()) != {1}:
        raise ValueError("governing ledger does not match the exact native station/product population")
    station_requests = {}
    for row in rows:
        station, product = row["station_id"], row["product_id"]
        if row["native_field"] != FIELDS[product] or row["source_id"] != agencies[station]:
            raise ValueError(f"wrong graph field or supplying agency: {station}/{product}")
        parsed = urlparse(row["request_url"])
        if f"{parsed.scheme}://{parsed.netloc}{parsed.path}" != GRAPH_URL:
            raise ValueError(f"wrong graph endpoint: {station}")
        if parse_qs(parsed.query) != {
            "station_type": ["tele_waterlevel"],
            "station_id": [station],
            "start_date": [row["window_start"]],
            "end_date": [row["window_end"]],
        }:
            raise ValueError(f"wrong graph request identity or window: {station}")
        days = (date.fromisoformat(row["window_end"]) - date.fromisoformat(row["window_start"])).days + 1
        count, grid = int(row["nonnull_observations"]), int(row["grid_rows"])
        if (
            days not in (7, 91)
            or int(row["window_dates"]) != days
            or grid not in (days * 24, days * 144)
            or not 0 <= count <= grid
        ):
            raise ValueError(f"invalid graph grid/count/window: {station}/{product}")
        status = "available" if count else "empty_in_tested_window"
        availability = "available" if count else "unknown"
        if row["status"] != status or row["availability"] != availability or row["http_status"] != "200":
            raise ValueError(f"invalid availability conclusion: {station}/{product}")
        instant = datetime.fromisoformat(row["retrieved_at"])
        if instant.tzinfo is None or instant.utcoffset() != timedelta(0):
            raise ValueError(f"acquisition instant is not UTC: {station}")
        if int(row["response_bytes"]) <= 0 or len(row["response_sha256"]) != 64:
            raise ValueError(f"invalid material identity: {station}")
        int(row["response_sha256"], 16)
        for key in ("evidence_body", "evidence_receipt"):
            path = Path(row[key])
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"evidence material path escapes its supplied root: {station}")
        identity = tuple(
            row[key]
            for key in (
                "request_id",
                "request_url",
                "retrieved_at",
                "response_bytes",
                "response_sha256",
                "evidence_body",
                "evidence_receipt",
                "content_type",
                "grid_rows",
                "grid_first",
                "grid_last",
                "acquisition_mode",
            )
        )
        previous = station_requests.setdefault(station, identity)
        if previous != identity:
            raise ValueError(f"station product facts mix different acquisitions: {station}")


def verify_response(row: dict[str, str], receipt: dict[str, object], raw: bytes) -> dict[str, int]:
    """Read actual publisher fields, not a receipt's derived measurements."""
    station = row["station_id"]
    if len(raw) != int(row["response_bytes"]) or hashlib.sha256(raw).hexdigest() != row["response_sha256"]:
        raise ValueError(f"source body digest/size mismatch: {station}")
    if receipt["body_path"] != row["evidence_body"]:
        raise ValueError(f"receipt names a different body: {station}")
    if row["acquisition_mode"] == "reused":
        original = receipt["original_receipt"]
        if not isinstance(original, dict) or any(not isinstance(key, str) for key in original):
            raise ValueError(f"invalid original receipt: {station}")
        original = cast("dict[str, object]", original)
        url, instant, status, media, size, sha = (
            original[key]
            for key in (
                "request_url",
                "retrieved_at",
                "http_status",
                "content_type",
                "response_bytes",
                "response_sha256",
            )
        )
    elif row["acquisition_mode"] == "new":
        if receipt["body_complete"] is not True or "error" in receipt:
            raise ValueError(f"incomplete acquisition: {station}")
        request, response = receipt["request"], receipt["response"]
        if not isinstance(request, dict) or not isinstance(response, dict):
            raise ValueError(f"invalid request/response receipt: {station}")
        if any(not isinstance(key, str) for item in (request, response) for key in item):
            raise ValueError(f"invalid request/response keys: {station}")
        request, response = cast("dict[str, object]", request), cast("dict[str, object]", response)
        url, instant, status, media, size, sha = (
            request["url"],
            receipt["retrieved_at"],
            response["status"],
            response["content_type"],
            receipt["body_bytes"],
            receipt["body_sha256"],
        )
    else:
        raise ValueError(f"unknown acquisition mode: {station}")
    actual = (str(url), str(instant), str(status), str(media), str(size), str(sha))
    expected = tuple(
        row[key]
        for key in ("request_url", "retrieved_at", "http_status", "content_type", "response_bytes", "response_sha256")
    )
    if actual != expected:
        raise ValueError(f"receipt acquisition facts disagree with ledger: {station}")
    document = json.loads(raw)
    if document["result"] != "OK":
        raise ValueError(f"source did not return a successful graph: {station}")
    graph = document["data"]["graph_data"]
    if len(graph) != int(row["grid_rows"]):
        raise ValueError(f"source graph row count disagrees: {station}")
    days = int(row["window_dates"])
    step = timedelta(minutes=1440 // (len(graph) // days))
    start = datetime.fromisoformat(row["window_start"])
    for index, item in enumerate(graph):
        if item["datetime"] != (start + index * step).strftime("%Y-%m-%d %H:%M"):
            raise ValueError(f"source graph grid contains an offset/gap: {station}")
        for field in FIELDS.values():
            if field not in item or (item[field] is not None and type(item[field]) not in (int, float)):
                raise ValueError(f"invalid required source measurement field: {station}/{field}")
    if (graph[0]["datetime"], graph[-1]["datetime"]) != (row["grid_first"], row["grid_last"]):
        raise ValueError(f"source grid endpoints disagree: {station}")
    return {field: sum(item[field] is not None for item in graph) for field in FIELDS.values()}


def verify_bodies(rows: list[dict[str, str]], evidence_root: Path) -> None:
    verified = {}
    for row in rows:
        key = row["evidence_body"]
        if key not in verified:
            receipt = json.loads((evidence_root / row["evidence_receipt"]).read_text())
            verified[key] = verify_response(row, receipt, (evidence_root / key).read_bytes())
        if verified[key][row["native_field"]] != int(row["nonnull_observations"]):
            raise ValueError(
                f"source measurement count disagrees with conclusion: {row['station_id']}/{row['product_id']}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--native", required=True, type=Path)
    parser.add_argument(
        "--evidence-root",
        required=True,
        type=Path,
        help="Controlled baseline-capture directory; required, never downloaded",
    )
    args = parser.parse_args()
    rows = read_ledger(args.ledger)
    verify_ledger(rows, station_agencies(args.native))
    verify_bodies(rows, args.evidence_root)
    print(
        json.dumps(
            {
                "verified_stations": len({r["station_id"] for r in rows}),
                "verified_pairs": len(rows),
                "available": sum(r["availability"] == "available" for r in rows),
                "unknown": sum(r["availability"] == "unknown" for r in rows),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
