"""Compose the station x product evidence inventory for th_thaiwater from acquisition receipts.

    inventory = map(row_from(governing receipt)) over (baseline station x product)

Every field of a row - window, grid rows, non-null count, HTTP status, media type, acquisition
instant, byte size, digest - is copied from the one receipt the row cites. Nothing is combined across
requests. A single graph response serves both products, so both rows of a station cite the same
receipt; the response is receipted once.

Governing receipt per station: the 91-date request (2026-06-08 .. 2026-09-06) when the 7-date request
(2026-08-31 .. 2026-09-06) left either product without a non-null value; otherwise the 7-date request.

Status vocabulary (non-interchangeable, per issue #224):
  available              - the cited response published at least one non-null value for the field
  empty_in_tested_window - the cited response is a complete time grid with no non-null value for it
  access_failed          - the cited request did not return a readable graph; NOT evidence of absence
  uninvestigated         - not probed by this survey

There is deliberately no "unsupported" status: no recorded evidence states that a station cannot
supply a measurement.

Availability comes from the graph route's published values, never from catalogue metadata; see
build_metadata_comparison.py.
"""

from __future__ import annotations

import collections
import csv
import json
import pathlib
from datetime import date

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = pathlib.Path(__file__).resolve().parents[3].parent
NATIVE = ROOT / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
RECEIPTS = HERE / "evidence" / "graph_receipts.csv"
SNAPSHOT = HERE / "recordings" / "waterlevel_load_live.stations.csv"
SHORT_START, WIDE_START = "2026-08-31", "2026-06-08"
PRODUCTS = (("stage_reported", "value"), ("discharge_reported", "discharge"))


def read_csv(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def dates(receipt: dict[str, str]) -> int:
    return (date.fromisoformat(receipt["window_end"]) - date.fromisoformat(receipt["window_start"])).days + 1


def succeeded(receipt: dict[str, str]) -> bool:
    return not receipt["request_error"] and receipt["http_status"] == "200" and receipt["result"] == "OK"


def status_of(receipt: dict[str, str], field: str) -> tuple[str, str]:
    window = f"{receipt['window_start']}..{receipt['window_end']} ({dates(receipt)} dates)"
    if receipt["request_error"]:
        return "access_failed", f"request {receipt['request_id']} did not return a graph: {receipt['request_error']}"
    if receipt["http_status"] != "200" or receipt["result"] != "OK":
        return "access_failed", f"HTTP {receipt['http_status']}, result '{receipt['result']}' from the graph route"
    count = int(receipt[f"nonnull_{field}"])
    if count > 0:
        return "available", (
            f"graph route published {count} non-null '{field}' values in {receipt['grid_rows']} grid rows over {window}"
        )
    return "empty_in_tested_window", (
        f"graph route answered with {receipt['grid_rows']} grid rows over {window} carrying no non-null "
        f"'{field}' value; the source states nothing about support"
    )


def write_summary(frame: pd.DataFrame, receipts: list[dict[str, str]]) -> None:
    """Every number the prose quotes about the sweep, derived here so the prose cannot drift."""
    ok = [r for r in receipts if not r["request_error"]]
    short = {r["station_id"]: r for r in ok if r["window_start"] == SHORT_START}
    wide = {r["station_id"]: r for r in ok if r["window_start"] == WIDE_START}

    def count(receipt: dict[str, str], field: str) -> int:
        return int(receipt[f"nonnull_{field}"])

    both_empty = [s for s, r in short.items() if count(r, "value") == 0 and count(r, "discharge") == 0]
    status = frame.pivot(index="station_id", columns="product_id", values="status")
    stage, discharge = status["stage_reported"] == "available", status["discharge_reported"] == "available"
    bundle = HERE / "evidence" / "graph_bodies_without_observations.zip"
    summary = {
        "acquired_between": [min(r["retrieved_at"] for r in receipts), max(r["retrieved_at"] for r in receipts)],
        "receipts": len(receipts),
        "failed_attempts": len(receipts) - len(ok),
        "short_window_requests": len(short),
        "wide_window_requests": len(wide),
        "products": {
            product: {k: int(v) for k, v in frame[frame.product_id == product].status.value_counts().items()}
            for product in ("stage_reported", "discharge_reported")
        },
        "series_available": int((frame.status == "available").sum()),
        "stations_stage_and_discharge": int((stage & discharge).sum()),
        "stations_stage_only": int((stage & ~discharge).sum()),
        "stations_discharge_only": int((~stage & discharge).sum()),
        "stations_neither": int((~stage & ~discharge).sum()),
        "rows_resting_on_91_dates": int((frame.window_start == WIDE_START).sum()),
        "short_both_empty": len(both_empty),
        "short_both_empty_recovered_on_wide": sum(
            1 for s in both_empty if s in wide and (count(wide[s], "value") > 0 or count(wide[s], "discharge") > 0)
        ),
        "short_stage_empty_recovered_on_wide": sum(
            1 for s, r in short.items() if count(r, "value") == 0 and s in wide and count(wide[s], "value") > 0
        ),
        "short_discharge_empty_recovered_on_wide": sum(
            1 for s, r in short.items() if count(r, "discharge") == 0 and s in wide and count(wide[s], "discharge") > 0
        ),
        "short_grid_rows_per_date": {
            str(k): v for k, v in sorted(collections.Counter(int(r["grid_rows"]) // 7 for r in short.values()).items())
        },
        "response_bytes_total": sum(int(r["response_bytes"]) for r in ok),
        "response_gzip6_bytes_total": sum(int(r["response_gzip6_bytes"]) for r in ok),
        "response_bytes_carrying_observations": sum(
            int(r["response_bytes"]) for r in ok if r["body_retained"] != "True"
        ),
        "response_gzip6_bytes_carrying_observations": sum(
            int(r["response_gzip6_bytes"]) for r in ok if r["body_retained"] != "True"
        ),
        "bodies_retained": sum(r["body_retained"] == "True" for r in receipts),
        "bodies_not_retained": sum(r["body_retained"] != "True" for r in ok),
        "bundle_bytes": bundle.stat().st_size,
        "receipts_bytes": RECEIPTS.stat().st_size,
    }
    (HERE / "inventory" / "inventory_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


def main() -> None:
    receipts = read_csv(RECEIPTS)
    by_station: dict[tuple[str, str], list[dict[str, str]]] = {}
    for receipt in receipts:
        by_station.setdefault((receipt["station_id"], receipt["window_start"]), []).append(receipt)

    def best(station: str, start: str) -> dict[str, str] | None:
        attempts = by_station.get((station, start), [])
        ok = [r for r in attempts if not r["request_error"]]
        return (ok or attempts or [None])[-1]

    snapshot = {row["station_id"]: row for row in read_csv(SNAPSHOT)}
    native = pd.read_parquet(NATIVE)
    meta = {
        str(row[0]): row[1:]
        for row in native[
            ["station.id", "station.tele_station_name.th", "river_name", "agency.agency_name.en", "basin.basin_name.en"]
        ].itertuples(index=False)
    }

    records = []
    for station in sorted(meta, key=lambda value: (len(value), value)):
        short = best(station, SHORT_START)
        if short is None:
            raise SystemExit(f"station {station} has no receipt; run acquire_graph_evidence.py")
        needs_wide = succeeded(short) and any(int(short[f"nonnull_{field}"]) == 0 for _, field in PRODUCTS)
        wide = best(station, WIDE_START) if needs_wide else None
        if needs_wide and wide is None:
            raise SystemExit(f"station {station} needs a 91-date receipt; run acquire_graph_evidence.py")
        name_th, river, agency, basin = meta[station]
        live = snapshot.get(station)
        for product_id, field in PRODUCTS:
            governing = short
            if wide is not None:
                # An available product never needs the wider window; an empty one must rest on it.
                governing = wide if succeeded(wide) or int(short[f"nonnull_{field}"]) == 0 else short
            status, basis = status_of(governing, field)
            records.append(
                {
                    "station_id": station,
                    "station_name_th": name_th,
                    "river_name": river,
                    "agency": agency,
                    "basin": basin,
                    "product_id": product_id,
                    "native_field": field,
                    "status": status,
                    "evidence_basis": basis,
                    "nonnull_observations": governing[f"nonnull_{field}"],
                    "grid_rows": governing["grid_rows"],
                    "window_start": governing["window_start"],
                    "window_end": governing["window_end"],
                    "window_dates": dates(governing),
                    "request_id": governing["request_id"],
                    "http_status": governing["http_status"],
                    "content_type": governing["content_type"],
                    "retrieved_at": governing["retrieved_at"],
                    "response_bytes": governing["response_bytes"],
                    "response_sha256": governing["response_sha256"],
                    "response_body_retained": governing["body_retained"],
                    "evidence_ref": f"evidence/graph_receipts.csv#{governing['request_id']}",
                    "in_live_snapshot_2026_09_07": live is not None,
                    "snapshot_discharge_state": live["discharge_state"] if live else "absent",
                }
            )

    frame = pd.DataFrame(records).sort_values(["station_id", "product_id"])
    path = HERE / "inventory" / "station_product_evidence.csv"
    frame.to_csv(path, index=False)
    assert len(frame) == len(meta) * 2, f"expected {len(meta) * 2} rows, got {len(frame)}"
    write_summary(frame, receipts)
    print(f"wrote {len(frame)} rows / {frame.station_id.nunique()} stations -> {path.name}\n")
    print(pd.crosstab(frame.product_id, frame.status).to_string())
    print(pd.crosstab(frame.product_id, frame.window_dates).to_string())


if __name__ == "__main__":
    main()
