"""Probe every hydrological station x product workbook across the full published population.

Population = union of the three surface-water layers the provider's products map to:
  layer 10 Vodostaj (H), layer 20 Proticaj (Q), layer 30 Temperatura vode (WT).

Each row is marked `in_baseline` so the committed 60-station baseline stays distinguishable
from the additional stations the publisher lists. Nothing is merged silently.

HEAD only: no observation history is downloaded to establish that a route exists.
Usage: uv run python research/station-coverage/ba_fhmzbih/scripts/probe_population.py
"""

from __future__ import annotations

import base64
import csv
import json
import pathlib
import time
import urllib.error  # noqa: TID251 - research capture tool, not provider runtime code
import urllib.request  # noqa: TID251 - research capture tool, not provider runtime code
from datetime import UTC, datetime

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = pathlib.Path(__file__).resolve().parents[3].parent
NATIVE = ROOT / "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet"
OUT = HERE / "inventory" / "population_probe.csv"
WORKBOOK_ROOT = "https://vodostaji.voda.ba/data/internet/stations"
USER_AGENT = "RivRetrieve-research/0.1 (station coverage survey; +https://github.com/RivRetrieve/RivRetrieve)"
PRODUCTS = (
    ("discharge_reported", "Q", "Q_1Y.xlsx"),
    ("stage_reported", "H", "H_1Y.xlsx"),
    ("water_temperature_reported", "WT", "Tvode_1Y.xlsx"),
)
DELAY_SECONDS = 0.25


def layer(number: int) -> list[dict]:
    path = HERE / "recordings" / f"layer_{number}.recording.json"
    document = json.loads(path.read_text())
    return json.loads(base64.b64decode(document["response"]["content_base64"]))


def probe(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return {
                "http_status": response.status,
                "content_length": response.headers.get("Content-Length", ""),
                "content_type": response.headers.get("Content-Type", ""),
                "transport_error": "",
            }
    except urllib.error.HTTPError as error:
        return {"http_status": error.code, "content_length": "", "content_type": "", "transport_error": ""}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {
            "http_status": "",
            "content_length": "",
            "content_type": "",
            "transport_error": f"{type(error).__name__}: {error}",
        }


def main() -> None:
    rows_by_station: dict[str, dict] = {}
    membership: dict[str, set[str]] = {}
    for number, code in ((10, "H"), (20, "Q"), (30, "WT")):
        for row in layer(number):
            station = row["metadata_station_no"]
            rows_by_station.setdefault(station, row)
            membership.setdefault(station, set()).add(code)

    baseline = set(pd.read_parquet(NATIVE).metadata_station_no.astype(str))
    print(
        f"population: {len(rows_by_station)} hydrological stations ({len(baseline)} baseline, "
        f"{len(set(rows_by_station) - baseline)} additional)"
    )

    records = []
    for index, station in enumerate(sorted(rows_by_station), start=1):
        meta = rows_by_station[station]
        site_no = meta["metadata_site_no"]
        for product_id, code, workbook in PRODUCTS:
            url = f"{WORKBOOK_ROOT}/{site_no}/{station}/{code}/{workbook}"
            result = probe(url)
            records.append(
                {
                    "station_no": station,
                    "site_no": site_no,
                    "station_name": meta.get("metadata_station_name", ""),
                    "river_name": meta.get("metadata_river_name", ""),
                    "object_type": meta.get("metadata_object_type", ""),
                    "in_baseline": station in baseline,
                    "declared_in_layer": code in membership[station],
                    "product_id": product_id,
                    "source_code": code,
                    "workbook": workbook,
                    "url": url,
                    "probed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    **result,
                }
            )
            time.sleep(DELAY_SECONDS)
        if index % 10 == 0:
            print(f"  {index}/{len(rows_by_station)}", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    print(f"wrote {len(records)} rows -> {OUT.name}")


if __name__ == "__main__":
    main()
