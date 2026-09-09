"""Compose the final station x product evidence inventory from the measurement-cell sweep.

Availability is established from the measurement cells in each workbook, read from the
worksheet XML. The publisher's '#Rows' header is retained as a recorded observation but is NOT
used to classify: it counts timestamped rows, including rows whose measurement cell is
published empty, so it overstates numerical availability.

Status vocabulary (non-interchangeable, per issue #223):
  measurements_present              - at least one populated measurement cell in the download
  timestamped_without_measurements  - timestamped rows present, every measurement cell empty
  no_data_rows                      - no data rows at all; parameter and unit still declared
  access_failed                     - the route did not serve a workbook; NOT evidence of absence
  uninvestigated                    - not probed by this survey

'unsupported' is expressible so the category stays distinguishable, but this survey never
assigns it: no recorded evidence states that a station cannot measure a parameter. A blank-only
or empty download establishes what that download contained, nothing more.

Each row links to its own response evidence. There is deliberately no status-to-example
mapping: an example of a response shape cannot substantiate a different station's result.
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = pathlib.Path(__file__).resolve().parents[3].parent
NATIVE = ROOT / "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet"
CRS = ROOT / "tests/test_data/ba_fhmzbih_crs_evidence_stations.json"

COLUMNS = [
    "station_no",
    "station_name",
    "river_name",
    "site_no",
    "object_type",
    "in_baseline",
    "in_station_document",
    "declared_in_layer",
    "product_id",
    "source_code",
    "workbook",
    "status",
    "evidence_basis",
    "declared_rows",
    "data_rows",
    "populated_measurements",
    "declared_unit",
    "declared_parameter",
    "timeseries_name",
    "observed_window_start",
    "observed_window_end",
    "byte_size",
    "http_status",
    "url",
    "retrieved_at",
    "response_sha256",
    "evidence_ref",
    "layer_recording",
]


def main() -> None:
    frame = pd.read_csv(HERE / "inventory" / "population_sweep.csv", dtype=str)
    crs_ids = {row["station_no"] for row in json.loads(CRS.read_text())}
    frame["in_station_document"] = frame.station_no.isin(crs_ids)

    out = frame[COLUMNS].sort_values(["in_baseline", "station_no", "product_id"], ascending=[False, True, True])
    path = HERE / "inventory" / "station_product_evidence.csv"
    out.to_csv(path, index=False)

    stations = out.station_no.nunique()
    assert len(out) == stations * 3, f"expected {stations * 3} rows, got {len(out)}"
    baseline = set(pd.read_parquet(NATIVE).metadata_station_no.astype(str))
    covered = set(out[out.in_baseline == "True"].station_no)
    assert covered == baseline, f"baseline not fully accounted for: {baseline ^ covered}"
    assert not out.status.eq("unsupported").any(), "no row may claim a measurement is unsupported"

    print(f"wrote {len(out)} rows / {stations} stations -> {path.name}")
    print(f"every one of the {len(baseline)} baseline stations accounted for: True\n")
    print(pd.crosstab([out.in_baseline, out.product_id], out.status).to_string())
    print("\nseries with measurements, by population:")
    present = out[out.status == "measurements_present"]
    print(present.groupby("in_baseline").size().to_string())
    print(f"total: {len(present)}")


if __name__ == "__main__":
    main()
