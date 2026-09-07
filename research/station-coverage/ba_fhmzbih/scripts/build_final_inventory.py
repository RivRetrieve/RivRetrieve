"""Compose the final station x product evidence inventory.

Availability comes from the publisher's own '#Rows' header field for every pair. Content-Length
is retained as a recorded observation but is NOT used to classify: reading '#Rows' everywhere
showed the size heuristic misclassifying 7 low-row-count workbooks as empty.

Status vocabulary (non-interchangeable, per issue #223):
  available                        - publisher declares #Rows > 0
  declared_empty_in_rolling_window - publisher declares #Rows = 0, parameter and unit still declared
  access_failed                    - route did not serve the workbook (HTTP 404); NOT evidence of absence
  uninvestigated                   - not probed by this survey

There is no "unsupported" status: no recorded evidence states that a station cannot measure a
parameter.
"""

from __future__ import annotations

import base64
import json
import pathlib

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = pathlib.Path(__file__).resolve().parents[3].parent
NATIVE = ROOT / "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet"
CRS = ROOT / "tests/test_data/ba_fhmzbih_crs_evidence_stations.json"


def layer(number: int) -> list[dict]:
    document = json.loads((HERE / "recordings" / f"layer_{number}.recording.json").read_text())
    return json.loads(base64.b64decode(document["response"]["content_base64"]))


def main() -> None:
    probe = pd.read_csv(HERE / "inventory" / "population_probe.csv", dtype=str)
    declared = pd.read_csv(HERE / "inventory" / "declared_rows_population.csv", dtype=str)
    frame = probe.merge(
        declared[
            [
                "station_no",
                "product_id",
                "declared_rows",
                "declared_unit",
                "declared_parameter",
                "timeseries_name",
                "read_error",
            ]
        ],
        on=["station_no", "product_id"],
        how="left",
        validate="one_to_one",
    )
    frame["declared_rows_n"] = pd.to_numeric(frame.declared_rows, errors="coerce")

    crs_ids = {row["station_no"] for row in json.loads(CRS.read_text())}
    frame["in_station_document"] = frame.station_no.isin(crs_ids)

    def classify(row: pd.Series) -> tuple[str, str]:
        if pd.notna(row.read_error) and str(row.read_error).strip():
            return "access_failed", f"workbook could not be read: {row.read_error}"
        if str(row.http_status) == "404":
            return "access_failed", "HTTP 404 - the publisher serves no workbook at this route"
        if pd.isna(row.declared_rows_n):
            return "uninvestigated", "no #Rows statement obtained by this survey"
        count = int(row.declared_rows_n)
        if count == 0:
            return (
                "declared_empty_in_rolling_window",
                f"publisher declares #Rows = 0 while still declaring parameter "
                f"{row.declared_parameter!r} and unit {row.declared_unit!r} for this station",
            )
        return "available", f"publisher declares #Rows = {count}"

    results = frame.apply(classify, axis=1, result_type="expand")
    frame["status"], frame["evidence_basis"] = results[0], results[1]
    frame["evidence_recording"] = frame.status.map(
        {
            "access_failed": "recordings/absent_4228_H_404.recording.json",
            "declared_empty_in_rolling_window": "recordings/boundary_4060_WT_headeronly.recording.json",
            "available": "recordings/boundary_1020_WT_populated.recording.json",
        }
    ).fillna("")
    frame["layer_recording"] = frame.source_code.map(
        {
            "Q": "recordings/layer_20.recording.json",
            "H": "recordings/layer_10.recording.json",
            "WT": "recordings/layer_30.recording.json",
        }
    )

    columns = [
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
        "declared_unit",
        "declared_parameter",
        "timeseries_name",
        "content_length",
        "http_status",
        "url",
        "probed_at",
        "evidence_recording",
        "layer_recording",
    ]
    out = frame[columns].sort_values(["in_baseline", "station_no", "product_id"], ascending=[False, True, True])
    path = HERE / "inventory" / "station_product_evidence.csv"
    out.to_csv(path, index=False)

    stations = out.station_no.nunique()
    assert len(out) == stations * 3, f"expected {stations * 3} rows, got {len(out)}"
    assert out.status.isin(
        {"available", "declared_empty_in_rolling_window", "access_failed", "uninvestigated"}
    ).all(), "unknown status value"
    baseline = set(pd.read_parquet(NATIVE).metadata_station_no.astype(str))
    covered = set(out[out.in_baseline == "True"].station_no)
    assert covered == baseline, f"baseline not fully accounted for: {baseline ^ covered}"

    print(f"wrote {len(out)} rows / {stations} stations -> {path.name}")
    print(f"every one of the {len(baseline)} baseline stations accounted for: True\n")
    print(pd.crosstab([out.in_baseline, out.product_id], out.status).to_string())


if __name__ == "__main__":
    main()
