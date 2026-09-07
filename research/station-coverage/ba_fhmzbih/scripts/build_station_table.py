"""Generate STATION_TABLE.md: one row per station in the published list, with per-product status.

This is the readable companion to inventory/station_product_evidence.csv. Every station in the
surveyed population appears exactly once; no row is omitted or summarised away.
"""

from __future__ import annotations

import pathlib

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
SYMBOL = {
    "available": "yes",
    "declared_empty_in_rolling_window": "empty",
    "access_failed": "404",
    "uninvestigated": "?",
}


def main() -> None:
    frame = pd.read_csv(HERE / "inventory" / "station_product_evidence.csv", dtype=str)
    frame["rows"] = pd.to_numeric(frame.declared_rows, errors="coerce")

    def cell(group: pd.DataFrame, product: str) -> str:
        row = group[group.product_id == product]
        if row.empty:
            return "?"
        status = row.iloc[0].status
        label = SYMBOL[status]
        if status == "available":
            return f"**{label}** ({int(row.iloc[0]['rows']):,})"
        return label

    lines = [
        "# ba_fhmzbih — station list with established coverage",
        "",
        "One row per station in the surveyed population. Generated from",
        "`inventory/station_product_evidence.csv` by `scripts/build_station_table.py`; every station",
        "appears, none is omitted.",
        "",
        "`yes (n)` = the publisher declares `#Rows = n` observations in the rolling workbook.",
        "`empty` = the publisher declares `#Rows = 0` **while still declaring the parameter and its unit**",
        "for that station — no observations in the rolling year, *not* a statement that the station cannot",
        "measure it. `404` = the route serves no workbook; an access failure, never evidence of absence.",
        "",
        "**Baseline** marks the 60 stations in the committed `native.parquet` (the publisher's layer-20",
        "membership). The other 39 are published hydrological stations of the identical object type that",
        "the layer-20 capture excluded — see `UNRESOLVED.md` §3; they are not merged into the baseline.",
        "",
        "| Station | Name | River | Site | Baseline | Q | H | WT |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for station, group in sorted(frame.groupby("station_no"), key=lambda kv: kv[0]):
        first = group.iloc[0]
        lines.append(
            f"| `{station}` | {first.station_name} | {first.river_name} | {first.site_no} "
            f"| {'yes' if first.in_baseline == 'True' else '—'} "
            f"| {cell(group, 'discharge_reported')} | {cell(group, 'stage_reported')} "
            f"| {cell(group, 'water_temperature_reported')} |"
        )

    counts = frame.groupby(["product_id", "status"]).size()
    lines += [
        "",
        f"**{frame.station_no.nunique()} stations · {len(frame)} station × product pairs · "
        f"{int((frame.status == 'available').sum())} established series.**",
        "",
        "| Product | available | declared empty | access failed |",
        "| --- | --- | --- | --- |",
    ]
    for product in ("discharge_reported", "stage_reported", "water_temperature_reported"):
        lines.append(
            f"| `{product}` | {counts.get((product, 'available'), 0)} "
            f"| {counts.get((product, 'declared_empty_in_rolling_window'), 0)} "
            f"| {counts.get((product, 'access_failed'), 0)} |"
        )

    (HERE / "STATION_TABLE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote STATION_TABLE.md — {frame.station_no.nunique()} stations")


if __name__ == "__main__":
    main()
