"""Compose the station x product evidence inventory for th_thaiwater.

Availability comes from the graph route's published values, never from catalogue metadata: the
snapshot `discharge` field disagrees with the route for 19 of 825 stations, and its `waterlevel_m`
field is null everywhere.

Status vocabulary (non-interchangeable, per issue #224):
  available              - the route published at least one non-null value for the product's field
  empty_in_tested_window - the route answered with a complete time grid carrying no non-null value
  access_failed          - the request did not complete; NOT evidence of absence
  uninvestigated         - not probed by this survey

There is deliberately no "unsupported" status: no recorded evidence states that a station cannot
supply a measurement.
"""

from __future__ import annotations

import base64
import json
import pathlib

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = pathlib.Path(__file__).resolve().parents[3].parent
NATIVE = ROOT / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
PRODUCTS = (("stage_reported", "value", "nonnull_value"), ("discharge_reported", "discharge", "nonnull_discharge"))


def _to_float(value: object) -> float | None:
    """Coerce a pandas/itertuples cell to float, treating None, NaN and blanks alike as absent."""
    if value is None:
        return None
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return None if number != number else number  # NaN is the only value unequal to itself


def main() -> None:
    sweep = pd.read_csv(HERE / "inventory" / "graph_sweep.csv", dtype=str)
    for column in ("rows", "nonnull_value", "nonnull_discharge"):
        sweep[column] = pd.to_numeric(sweep[column], errors="coerce")
    # Every station with at least one empty product on the short window was re-probed over 90 days.
    # A negative availability claim always rests on the widest window tested for that station.
    widened = pd.read_csv(HERE / "inventory" / "widened_90d.csv", dtype=str)
    for column in ("rows", "nonnull_value", "nonnull_discharge"):
        widened[column] = pd.to_numeric(widened[column], errors="coerce")
    wide = {
        str(row.station_id): {
            "value": row.nonnull_value,
            "discharge": row.nonnull_discharge,
            "rows": row.rows,
            "start": row.window_start,
            "end": row.window_end,
            "error": row.request_error,
        }
        for row in widened.itertuples()
    }

    snapshot = json.loads(
        base64.b64decode(
            json.loads((HERE / "recordings" / "waterlevel_load_live.recording.json").read_text())["response"][
                "content_base64"
            ]
        )
    )
    live = {str(row["station"]["id"]): row for row in snapshot["waterlevel_data"]["data"]}

    native = pd.read_parquet(NATIVE)
    columns = native[
        [
            "station.id",
            "station.tele_station_name.th",
            "river_name",
            "agency.agency_name.en",
            "basin.basin_name.en",
        ]
    ].copy()
    columns.columns = ["station_id", "name_th", "river", "agency", "basin"]
    meta = {
        str(row.station_id): {"name_th": row.name_th, "river": row.river, "agency": row.agency, "basin": row.basin}
        for row in columns.itertuples()
    }

    records = []
    for row in sweep.itertuples():
        station = str(row.station_id)
        info = meta.get(station, {})
        widened_row = wide.get(station)
        for product_id, field, column in PRODUCTS:
            observed = getattr(row, column)
            window_start, window_end = row.window_start, row.window_end
            basis_window = "7-day"
            if widened_row is not None and pd.notna(widened_row["rows"]):
                # Re-probed over 90 days because at least one product was empty on the short window.
                # The wider window governs both products for this station.
                observed = widened_row["value"] if field == "value" else widened_row["discharge"]
                window_start, window_end = widened_row["start"], widened_row["end"]
                basis_window = "90-day"

            observed_count = _to_float(observed)
            if pd.notna(row.request_error) and str(row.request_error).strip():
                status = "access_failed"
                basis = f"request did not complete: {row.request_error}"
            elif str(row.http_status) != "200":
                status = "access_failed"
                basis = f"HTTP {row.http_status} from the graph route"
            elif observed_count is None:
                status = "uninvestigated"
                basis = "not resolved by this survey"
            elif observed_count > 0:
                status = "available"
                basis = f"graph route published {int(observed_count)} non-null '{field}' values in the {basis_window} window"
            else:
                status = "empty_in_tested_window"
                basis = (
                    f"graph route answered with a complete time grid carrying no non-null '{field}' "
                    f"value in the {basis_window} window; the source states nothing about support"
                )

            records.append(
                {
                    "station_id": station,
                    "station_name_th": info.get("name_th", ""),
                    "river_name": info.get("river", ""),
                    "agency": info.get("agency", ""),
                    "basin": info.get("basin", ""),
                    "product_id": product_id,
                    "native_field": field,
                    "status": status,
                    "evidence_basis": basis,
                    "nonnull_observations": "" if observed_count is None else int(observed_count),
                    "grid_rows": "" if _to_float(row.rows) is None else int(_to_float(row.rows) or 0),
                    "window_start": window_start,
                    "window_end": window_end,
                    "in_live_snapshot_2026_09_07": station in live,
                    "snapshot_discharge_present": (live.get(station, {}).get("discharge") is not None),
                    "http_status": row.http_status,
                    "probed_at": row.probed_at,
                    "evidence_recording": "recordings/boundary_1373272_both_products.recording.json"
                    if status == "available"
                    else "recordings/boundary_11688546_empty_90d.recording.json"
                    if status == "empty_in_tested_window"
                    else "",
                }
            )

    frame = pd.DataFrame(records).sort_values(["station_id", "product_id"])
    path = HERE / "inventory" / "station_product_evidence.csv"
    frame.to_csv(path, index=False)

    baseline = set(native["station.id"].astype(str))
    assert len(frame) == len(baseline) * 2, f"expected {len(baseline) * 2} rows, got {len(frame)}"
    assert set(frame.station_id) == baseline, "every baseline station must appear exactly once per product"
    print(f"wrote {len(frame)} rows / {frame.station_id.nunique()} stations -> {path.name}\n")
    print(pd.crosstab(frame.product_id, frame.status).to_string())


if __name__ == "__main__":
    main()
