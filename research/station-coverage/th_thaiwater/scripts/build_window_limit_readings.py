"""Derive unambiguous day counts from the recorded window-limit probe.

    readings : ProbeRow -> (elapsed days, inclusive calendar dates, returned dates, start honoured)

`inventory/window_limit_probe.csv` is kept as acquired on 2026-09-07. Its `requested_span` column is
a label typed into the probe script, and the labels mix two conventions: "90 days" is 90 elapsed days
(91 calendar dates), while "364/365/366 days" count calendar dates inclusively. This derivation
states both counts from the requested and returned dates themselves, so no label is relied on.

Convention used in this research from here on: a window's size is the number of calendar dates it
covers, counting both endpoints ("inclusive dates"). Elapsed days = inclusive dates - 1.

Usage: uv run python research/station-coverage/th_thaiwater/scripts/build_window_limit_readings.py
Output: inventory/window_limit_readings.csv
"""

from __future__ import annotations

import csv
import pathlib
from datetime import date

HERE = pathlib.Path(__file__).resolve().parents[1]
FIELDS = [
    "requested_start",
    "requested_end",
    "requested_elapsed_days",
    "requested_inclusive_dates",
    "returned_first",
    "returned_last",
    "returned_inclusive_dates",
    "rows",
    "rows_per_returned_date",
    "start_honoured",
    "http_status",
    "probed_at",
    "probe_label_as_recorded",
]


def main() -> None:
    with (HERE / "inventory" / "window_limit_probe.csv").open(newline="", encoding="utf-8") as handle:
        probe = list(csv.DictReader(handle))
    out = []
    for row in probe:
        start, end = date.fromisoformat(row["requested_start"]), date.fromisoformat(row["requested_end"])
        first, last = date.fromisoformat(row["returned_first"][:10]), date.fromisoformat(row["returned_last"][:10])
        returned_dates = (last - first).days + 1
        out.append(
            {
                "requested_start": start.isoformat(),
                "requested_end": end.isoformat(),
                "requested_elapsed_days": (end - start).days,
                "requested_inclusive_dates": (end - start).days + 1,
                "returned_first": row["returned_first"],
                "returned_last": row["returned_last"],
                "returned_inclusive_dates": returned_dates,
                "rows": row["rows"],
                "rows_per_returned_date": int(row["rows"]) / returned_dates,
                "start_honoured": "yes" if first == start else "no",
                "http_status": row["http_status"],
                "probed_at": row["probed_at"],
                "probe_label_as_recorded": row["requested_span"],
            }
        )
    path = HERE / "inventory" / "window_limit_readings.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(out)
    for row in out:
        print(
            f"  {row['requested_start']}..{row['requested_end']}  {row['requested_inclusive_dates']:>5} dates "
            f"({row['requested_elapsed_days']} elapsed) -> {row['returned_first'][:10]}..{row['returned_last'][:10]} "
            f"{row['returned_inclusive_dates']} dates  honoured={row['start_honoured']}"
        )
    print(f"wrote {path.name}")


if __name__ == "__main__":
    main()
