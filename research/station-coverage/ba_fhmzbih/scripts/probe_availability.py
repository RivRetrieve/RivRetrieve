"""Probe every baseline station x product workbook URL and record the response metadata.

Uses HTTP HEAD so that no observation history is downloaded merely to establish that a
route exists. Content-Length is recorded verbatim; classification into
available/empty happens in a separate, reviewable step against a threshold that is
itself justified by full GET recordings of boundary cases.

Usage: uv run python research/station-coverage/ba_fhmzbih/scripts/probe_availability.py
Output: inventory/workbook_probe.csv  (one row per station x product, no rows omitted)
"""

from __future__ import annotations

import csv
import pathlib
import time
import urllib.error  # noqa: TID251 - research capture tool, not provider runtime code
import urllib.request  # noqa: TID251 - research capture tool, not provider runtime code
from datetime import UTC, datetime

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[3].parent
NATIVE = ROOT / "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet"
OUT = pathlib.Path(__file__).resolve().parents[1] / "inventory" / "workbook_probe.csv"
WORKBOOK_ROOT = "https://vodostaji.voda.ba/data/internet/stations"
USER_AGENT = "RivRetrieve-research/0.1 (station coverage survey; +https://github.com/RivRetrieve/RivRetrieve)"

# (product_id, source code, workbook filename) exactly as declared in the provider config.
PRODUCTS = (
    ("discharge_reported", "Q", "Q_1Y.xlsx"),
    ("stage_reported", "H", "H_1Y.xlsx"),
    ("water_temperature_reported", "WT", "Tvode_1Y.xlsx"),
)
DELAY_SECONDS = 0.25


def probe(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return {
                "http_status": response.status,
                "content_length": response.headers.get("Content-Length", ""),
                "content_type": response.headers.get("Content-Type", ""),
                "last_modified": response.headers.get("Last-Modified", ""),
                "transport_error": "",
            }
    except urllib.error.HTTPError as error:
        return {
            "http_status": error.code,
            "content_length": "",
            "content_type": error.headers.get("Content-Type", "") if error.headers else "",
            "last_modified": "",
            "transport_error": "",
        }
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        # An access failure is recorded as itself. It is never folded into "no data".
        return {
            "http_status": "",
            "content_length": "",
            "content_type": "",
            "last_modified": "",
            "transport_error": f"{type(error).__name__}: {error}",
        }


def main() -> None:
    native = pd.read_parquet(NATIVE)
    stations = [
        (str(row.metadata_station_no), str(row.metadata_site_no), str(row.metadata_station_name))
        for row in native.itertuples()
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, (station_no, site_no, station_name) in enumerate(sorted(stations), start=1):
        for product_id, code, workbook in PRODUCTS:
            url = f"{WORKBOOK_ROOT}/{site_no}/{station_no}/{code}/{workbook}"
            result = probe(url)
            rows.append(
                {
                    "station_no": station_no,
                    "site_no": site_no,
                    "station_name": station_name,
                    "product_id": product_id,
                    "source_code": code,
                    "workbook": workbook,
                    "url": url,
                    "probed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    **result,
                }
            )
            time.sleep(DELAY_SECONDS)
        print(f"  [{index:>2}/{len(stations)}] {station_no} ({station_name})", flush=True)

    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {len(rows)} rows -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
