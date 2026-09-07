"""Read the source-declared '#Rows' header for EVERY station x product in the population.

This removes inference from the evidence inventory: availability for every pair is taken
from the publisher's own '#Rows' statement rather than from Content-Length. Workbooks are
fetched once, the header block is read, and the body is discarded - no observation history
is retained.

Usage: uv run python research/station-coverage/ba_fhmzbih/scripts/read_all_declared_rows.py
Output: inventory/declared_rows_population.csv (one row per probed pair, none omitted)
"""

from __future__ import annotations

import io
import pathlib
import time
import urllib.error  # noqa: TID251 - research capture tool, not provider runtime code
import urllib.request  # noqa: TID251 - research capture tool, not provider runtime code
import warnings
from datetime import UTC, datetime

import pandas as pd

warnings.filterwarnings("ignore")
HERE = pathlib.Path(__file__).resolve().parents[1]
PROBE = HERE / "inventory" / "population_probe.csv"
OUT = HERE / "inventory" / "declared_rows_population.csv"
USER_AGENT = "RivRetrieve-research/0.1 (station coverage survey; +https://github.com/RivRetrieve/RivRetrieve)"


def read_header(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        return {
            "http_status": error.code,
            "declared_rows": "",
            "declared_unit": "",
            "declared_parameter": "",
            "timeseries_name": "",
            "read_error": "",
        }
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {
            "http_status": "",
            "declared_rows": "",
            "declared_unit": "",
            "declared_parameter": "",
            "timeseries_name": "",
            "read_error": f"{type(error).__name__}: {error}",
        }
    try:
        frame = pd.read_excel(io.BytesIO(raw), header=None)
    except Exception as error:  # noqa: BLE001
        return {
            "http_status": status,
            "declared_rows": "",
            "declared_unit": "",
            "declared_parameter": "",
            "timeseries_name": "",
            "read_error": f"decode_error: {type(error).__name__}: {error}",
        }
    labels = frame[0].astype(str)

    def field(name: str) -> str:
        found = frame.loc[labels == name, 1]
        return str(found.iloc[0]) if len(found) else ""

    return {
        "http_status": status,
        "declared_rows": field("#Rows"),
        "declared_unit": field("#Unit Symbol"),
        "declared_parameter": field("#Station Parameter Name"),
        "timeseries_name": field("#Timeseries Name"),
        "read_error": "",
    }


def main() -> None:
    probe = pd.read_csv(PROBE, dtype=str)
    print(f"reading #Rows for all {len(probe)} station x product pairs")
    records = []
    for count, row in enumerate(probe.itertuples(), start=1):
        result = read_header(str(row.url))
        records.append(
            {
                "station_no": row.station_no,
                "product_id": row.product_id,
                "in_baseline": row.in_baseline,
                "url": row.url,
                "probe_content_length": row.content_length,
                **result,
                "read_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }
        )
        if count % 25 == 0:
            print(f"  {count}/{len(probe)}", flush=True)
        time.sleep(0.2)
    pd.DataFrame(records).to_csv(OUT, index=False)
    print(f"wrote {len(records)} rows -> {OUT.name}")


if __name__ == "__main__":
    main()
