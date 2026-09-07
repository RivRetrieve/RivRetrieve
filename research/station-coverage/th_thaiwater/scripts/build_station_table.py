"""Generate STATION_TABLE.md: one row per baseline station with per-product status."""

from __future__ import annotations

import pathlib

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
LABEL = {"available": "yes", "empty_in_tested_window": "empty", "access_failed": "404", "uninvestigated": "?"}


def main() -> None:
    frame = pd.read_csv(HERE / "inventory" / "station_product_evidence.csv", dtype=str)
    frame["n"] = pd.to_numeric(frame.nonnull_observations, errors="coerce")

    def cell(group: pd.DataFrame, product: str) -> str:
        row = group[group.product_id == product]
        if row.empty:
            return "?"
        status = row.iloc[0].status
        if status == "available":
            return f"**yes** ({int(row.iloc[0]['n']):,})"
        return LABEL[status]

    lines = [
        "# th_thaiwater — station list with established coverage",
        "",
        "One row per station in the committed 825-station baseline. Generated from",
        "`inventory/station_product_evidence.csv` by `scripts/build_station_table.py`; no station is omitted.",
        "",
        "`yes (n)` = the graph route published *n* non-null values for that product's field in the tested",
        "window. `empty` = the route answered with a complete time grid carrying no non-null value — the",
        "source states nothing about whether the station can supply the measurement, and this is never",
        "recorded as unsupported.",
        "",
        "Availability comes from the graph route, never from catalogue metadata: the snapshot `discharge`",
        "field disagrees with the route for 19 of these 825 stations, and its `waterlevel_m` field is null",
        "for every one of them.",
        "",
        "Stations empty over the 7-day window were re-probed over 90 days and the wider window governs;",
        "that recovered 14 of 26. `Live` marks presence in the 2026-09-07 `waterlevel_load` snapshot —",
        "absence there is not evidence of absence of data.",
        "",
        "| Station | Name (th) | River | Agency | Basin | Live | Stage | Discharge |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    short = {
        "Royal Irrigation Department": "RID",
        "Hydro – Informatics Institute (Public Organization)": "HII",
        "Friend in Need (of “Pa”) Volunteers Foundation": "FiN",
        "Electricity Generating Authority of Thailand": "EGAT",
    }
    for station, group in sorted(frame.groupby("station_id"), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        first = group.iloc[0]
        lines.append(
            f"| `{station}` | {first.station_name_th} | {first.river_name} "
            f"| {short.get(first.agency, first.agency)} | {first.basin} "
            f"| {'yes' if first.in_live_snapshot_2026_09_07 == 'True' else '—'} "
            f"| {cell(group, 'stage_reported')} | {cell(group, 'discharge_reported')} |"
        )

    counts = frame.groupby(["product_id", "status"]).size()
    lines += [
        "",
        f"**{frame.station_id.nunique()} stations · {len(frame)} station × product pairs · "
        f"{int((frame.status == 'available').sum())} established series.**",
        "",
        "| Product | available | empty in tested window | access failed |",
        "| --- | --- | --- | --- |",
    ]
    for product in ("stage_reported", "discharge_reported"):
        lines.append(
            f"| `{product}` | {counts.get((product, 'available'), 0)} "
            f"| {counts.get((product, 'empty_in_tested_window'), 0)} "
            f"| {counts.get((product, 'access_failed'), 0)} |"
        )
    (HERE / "STATION_TABLE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote STATION_TABLE.md — {frame.station_id.nunique()} stations")


if __name__ == "__main__":
    main()
