"""Enumerate every station added to or removed from the source list since the baseline capture.

Issue #224 requires that a changed station list be shown station by station rather than silently
replacing the committed baseline. This lists each added and removed id with the identity the source
publishes for it, so the difference is inspectable rather than a count.

The live list is read from recordings/waterlevel_load_live.stations.csv - the per-station identity
fields of the 2026-09-07 waterlevel_load response, whose observation-bearing bytes are not retained
(see strip_observation_bytes.py).

Usage: uv run python research/station-coverage/th_thaiwater/scripts/build_churn_reconciliation.py
Output: inventory/population_churn.csv
"""

from __future__ import annotations

import csv
import pathlib

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = pathlib.Path(__file__).resolve().parents[3].parent
NATIVE = ROOT / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"


def main() -> None:
    with (HERE / "recordings" / "waterlevel_load_live.stations.csv").open(newline="", encoding="utf-8") as handle:
        live = {row["station_id"]: row for row in csv.DictReader(handle)}

    native = pd.read_parquet(NATIVE)
    baseline_meta = {
        str(row.station_id): row
        for row in native[
            [
                "station.id",
                "station.tele_station_name.th",
                "station.tele_station_name.en",
                "river_name",
                "agency.agency_name.en",
            ]
        ]
        .rename(
            columns={
                "station.id": "station_id",
                "station.tele_station_name.th": "name_th",
                "station.tele_station_name.en": "name_en",
                "river_name": "river",
                "agency.agency_name.en": "agency",
            }
        )
        .itertuples()
    }
    baseline = set(baseline_meta)
    records = []

    for station_id in sorted(live.keys() - baseline, key=lambda value: (len(value), value)):
        row = live[station_id]
        records.append(
            {
                "station_id": station_id,
                "change": "added_since_baseline",
                "name_th": row["name_th"],
                "name_en": row["name_en"],
                "river": row["river_name"],
                "agency": row["agency_en"],
                "basin": row["basin_en"],
                "latest_reading_at": row["waterlevel_datetime"],
                "note": "present in the 2026-09-07 waterlevel_load response, absent from the 2026-08-02 baseline capture",
            }
        )

    for station_id in sorted(baseline - live.keys(), key=lambda value: (len(value), value)):
        meta = baseline_meta[station_id]
        records.append(
            {
                "station_id": station_id,
                "change": "absent_from_latest_snapshot",
                "name_th": meta.name_th,
                "name_en": meta.name_en,
                "river": meta.river,
                "agency": meta.agency,
                "basin": "",
                "latest_reading_at": "",
                "note": (
                    "in the committed baseline, absent from the 2026-09-07 waterlevel_load response; "
                    "the graph route still answers for these stations, so this is not evidence the "
                    "station is gone or dataless"
                ),
            }
        )

    frame = pd.DataFrame(records)
    path = HERE / "inventory" / "population_churn.csv"
    frame.to_csv(path, index=False)
    added = int((frame.change == "added_since_baseline").sum())
    removed = int((frame.change == "absent_from_latest_snapshot").sum())
    assert added + removed == len(frame)
    assert len(baseline) - removed + added == len(live), "reconciliation does not close"
    print(f"wrote {len(frame)} rows -> {path.name}")
    print(f"  baseline {len(baseline)} - {removed} absent + {added} added = {len(live)} live  (reconciliation closes)")


if __name__ == "__main__":
    main()
