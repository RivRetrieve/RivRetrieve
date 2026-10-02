"""Inspect fresh publisher workbook bytes independently of RivRetrieve parsing."""

import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen  # noqa: TID251 - independent source inspection, not provider transport

import openpyxl

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--out", type=Path, required=True, help="Output directory outside the checkout")
args = parser.parse_args()
root = args.out
root.mkdir(parents=True, exist_ok=True)


def acquire(url, name):
    with urlopen(url, timeout=60) as response:
        body = response.read()
        print(
            json.dumps(
                {
                    "retrieved_at": datetime.now(UTC).isoformat(),
                    "url": url,
                    "status": response.status,
                    "sha256": sha256(body).hexdigest(),
                    "bytes": len(body),
                },
                ensure_ascii=False,
            )
        )
    (root / name).write_bytes(body)
    return body


metadata = json.loads(acquire("https://vodostaji.voda.ba/data/internet/layers/20/index.json", "layer20.json"))
for station, code, workbook in (
    ("2310", "Q", "Q_1Y.xlsx"),
    ("2310", "H", "H_1Y.xlsx"),
    ("4110", "WT", "Tvode_1Y.xlsx"),
):
    (record,) = [row for row in metadata if row["metadata_station_no"] == station]
    print(
        "station",
        station,
        json.dumps({key: value for key, value in record.items() if key.startswith("metadata_")}, ensure_ascii=False),
    )
    group = record["metadata_site_no"]
    url = f"https://vodostaji.voda.ba/data/internet/stations/{group}/{station}/{code}/{workbook}"
    body = acquire(url, f"{station}_{workbook}")
    book = openpyxl.load_workbook(BytesIO(body), read_only=True, data_only=True)
    (sheet,) = book.worksheets
    rows = list(sheet.values)
    print("headers", repr(rows[:8]))
    data = rows[8:]
    print("row_count", len(data), "blank_values", sum(row[1] is None for row in data))
    stamps = [row[0] for row in data]
    print("first", min(stamps).isoformat(), "last", max(stamps).isoformat())
    selected = [row for row in data if datetime(2026, 9, 1) <= row[0] <= datetime(2026, 9, 3, 23, 59, 59)]
    print(
        "example_window",
        len(selected),
        "nulls",
        sum(row[1] is None for row in selected),
        "first_three",
        repr(selected[:3]),
    )
    book.close()
