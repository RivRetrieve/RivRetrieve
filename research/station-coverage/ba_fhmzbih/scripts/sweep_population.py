"""Re-sweep every station x product, classifying on measurement cells rather than '#Rows'.

Supersedes read_all_declared_rows.py, which classified on the publisher's declared row count
alone. That count includes timestamped rows whose measurement cells are published empty, so it
overstated numerical availability.

The population comes from the committed layer recordings, so the station list, site numbers and
layer membership are reproducible offline; only the workbooks require network access.

Usage: uv run python research/station-coverage/ba_fhmzbih/scripts/sweep_population.py
Writes: evidence/<station>_<product>.evidence.json  (one per pair, none omitted)
        inventory/population_sweep.csv              (one row per pair)
"""

from __future__ import annotations

import base64
import csv
import json
import pathlib
import sys
import time
import urllib.error  # noqa: TID251 - research capture tool, not provider runtime code
import urllib.request  # noqa: TID251 - research capture tool, not provider runtime code

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from workbook_evidence import read_workbook, utc_now, write_evidence  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = pathlib.Path(__file__).resolve().parents[3].parent
BASE = "https://vodostaji.voda.ba/data/internet/stations"
USER_AGENT = "RivRetrieve-research/0.1 (station coverage survey; +https://github.com/RivRetrieve/RivRetrieve)"
DELAY_SECONDS = 0.25

# product_id -> (source code, layer carrying it, workbook filename)
PRODUCTS = {
    "discharge_reported": ("Q", 20, "Q_1Y.xlsx"),
    "stage_reported": ("H", 10, "H_1Y.xlsx"),
    "water_temperature_reported": ("WT", 30, "Tvode_1Y.xlsx"),
}


def layer(number: int) -> list[dict]:
    document = json.loads((HERE / "recordings" / f"layer_{number}.recording.json").read_text())
    return json.loads(base64.b64decode(document["response"]["content_base64"]))


def build_population() -> list[dict]:
    """Union of the three hydrological layers, with site numbers taken from layer metadata.

    site_no is never derived from the station id: the publisher's own metadata_site_no is the
    only source for it, and the two do not correspond.
    """
    stations: dict[str, dict] = {}
    membership: dict[str, set[int]] = {}
    for number in (10, 20, 30):
        for row in layer(number):
            station_no = row["metadata_station_no"]
            membership.setdefault(station_no, set()).add(number)
            stations.setdefault(
                station_no,
                {
                    "station_no": station_no,
                    "site_no": row.get("metadata_site_no", ""),
                    "station_name": row.get("metadata_station_name", ""),
                    "river_name": row.get("metadata_river_name", ""),
                    "object_type": row.get("metadata_object_type", ""),
                },
            )
    baseline = {row["metadata_station_no"] for row in layer(20)}
    population = []
    for station_no, station in sorted(stations.items()):
        station["in_baseline"] = station_no in baseline
        station["layers"] = membership[station_no]
        population.append(station)
    return population


def fetch(url: str) -> tuple[int | str, str, bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read(), ""
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read(), ""
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return "", "", b"", f"{type(error).__name__}: {error}"


def main() -> None:
    population = build_population()
    print(
        f"population: {len(population)} stations x {len(PRODUCTS)} products = {len(population) * len(PRODUCTS)} pairs"
    )
    rows = []
    for index, station in enumerate(population, start=1):
        for product_id, (code, layer_number, workbook) in PRODUCTS.items():
            url = f"{BASE}/{station['site_no']}/{station['station_no']}/{code}/{workbook}"
            retrieved_at = utc_now()
            status_code, content_type, raw, transport_error = fetch(url)
            reading = read_workbook(raw) if status_code == 200 else None
            if transport_error:
                note = f"transport error, not a publisher response: {transport_error}"
            elif status_code != 200:
                note = f"publisher served no workbook at this route (HTTP {status_code})"
            else:
                note = ""
            document = write_evidence(
                HERE / "evidence" / f"{station['station_no']}_{product_id}.evidence.json",
                url=url,
                method="GET",
                status_code=status_code,
                content_type=content_type,
                retrieved_at=retrieved_at,
                raw=raw,
                station_no=station["station_no"],
                product_id=product_id,
                reading=reading,
                note=note,
            )
            rows.append(
                {
                    "station_no": station["station_no"],
                    "station_name": station["station_name"],
                    "river_name": station["river_name"],
                    "site_no": station["site_no"],
                    "object_type": station["object_type"],
                    "in_baseline": station["in_baseline"],
                    "declared_in_layer": layer_number in station["layers"],
                    "product_id": product_id,
                    "source_code": code,
                    "workbook": workbook,
                    "status": document.get("reading", {}).get("status", "access_failed"),
                    "evidence_basis": document.get("reading", {}).get("evidence_basis", note),
                    "declared_rows": (reading.declared_rows if reading else ""),
                    "data_rows": (reading.data_rows if reading else ""),
                    "populated_measurements": (reading.populated_measurements if reading else ""),
                    "declared_unit": (reading.declared_unit if reading else ""),
                    "declared_parameter": (reading.declared_parameter if reading else ""),
                    "timeseries_name": (reading.timeseries_name if reading else ""),
                    "observed_window_start": (reading.observed_window_start if reading else ""),
                    "observed_window_end": (reading.observed_window_end if reading else ""),
                    "byte_size": len(raw),
                    "http_status": status_code,
                    "url": url,
                    "retrieved_at": retrieved_at,
                    "response_sha256": document["response"]["response_sha256"],
                    "evidence_ref": f"evidence/{station['station_no']}_{product_id}.evidence.json",
                    "layer_recording": f"recordings/layer_{layer_number}.recording.json",
                    "transport_error": transport_error,
                }
            )
            time.sleep(DELAY_SECONDS)
        if index % 10 == 0:
            print(f"  {index}/{len(population)} stations")

    path = HERE / "inventory" / "population_sweep.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {len(rows)} rows -> {path.name}")
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    for status, count in sorted(counts.items()):
        print(f"  {status:<34} {count}")


if __name__ == "__main__":
    main()
