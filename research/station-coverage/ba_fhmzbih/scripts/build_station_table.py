"""Generate STATION_TABLE.md: one row per station in the published list, with per-product status.

This is the readable companion to inventory/station_product_evidence.csv. Every station in the
surveyed population appears exactly once; no row is omitted or summarised away.

Counts shown are populated measurement cells, not the publisher's declared row count: the
declared count includes timestamped rows whose measurement cell is published empty.
"""

from __future__ import annotations

import pathlib

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
SYMBOL = {
    "measurements_present": "yes",
    "timestamped_without_measurements": "blank",
    "no_data_rows": "empty",
    "access_failed": "404",
    "uninvestigated": "?",
}
PRODUCTS = ("discharge_reported", "stage_reported", "water_temperature_reported")


def main() -> None:
    frame = pd.read_csv(HERE / "inventory" / "station_product_evidence.csv", dtype=str)
    frame["values"] = pd.to_numeric(frame.populated_measurements, errors="coerce")
    frame["rows"] = pd.to_numeric(frame.data_rows, errors="coerce")

    def cell(group: pd.DataFrame, product: str) -> str:
        row = group[group.product_id == product]
        if row.empty:
            return "?"
        record = row.iloc[0]
        label = SYMBOL[record.status]
        if record.status == "measurements_present":
            return f"**{label}** ({int(record['values']):,})"
        if record.status == "timestamped_without_measurements":
            return f"{label} ({int(record['rows']):,} rows, 0 values)"
        return label

    lines = [
        "# ba_fhmzbih — station list with established coverage",
        "",
        "One row per station in the surveyed population. Generated from",
        "`inventory/station_product_evidence.csv` by `scripts/build_station_table.py`; every station",
        "appears, none is omitted.",
        "",
        "`yes (n)` = the download carried *n* populated measurement cells.",
        "`blank (n rows, 0 values)` = the download carried *n* timestamped rows with every measurement",
        "cell published empty, **while still declaring the parameter and its unit**. That establishes what",
        "this download contained; it is *not* a statement that the station cannot measure the parameter.",
        "`empty` = no data rows at all, parameter and unit still declared.",
        "`404` = the route serves no workbook; an access failure, never evidence of absence.",
        "",
        "Counts are populated measurement cells, not the publisher's `#Rows` header. The header counts",
        "timestamped rows, including rows whose measurement cell is empty, so it overstates availability.",
        "",
        "**Baseline** marks the 60 stations in the committed `native.parquet` (the publisher's layer-20",
        "membership). The other 39 are published hydrological stations that the layer-20 capture excluded",
        "— see `UNRESOLVED.md` §3; they are not merged into the baseline.",
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
    established = int((frame.status == "measurements_present").sum())
    lines += [
        "",
        f"**{frame.station_no.nunique()} stations · {len(frame)} station × product pairs · "
        f"{established} series carrying measurements.**",
        "",
        "| Product | measurements | timestamped, no values | no data rows | access failed |",
        "| --- | --- | --- | --- | --- |",
    ]
    for product in PRODUCTS:
        lines.append(
            f"| `{product}` | {counts.get((product, 'measurements_present'), 0)} "
            f"| {counts.get((product, 'timestamped_without_measurements'), 0)} "
            f"| {counts.get((product, 'no_data_rows'), 0)} "
            f"| {counts.get((product, 'access_failed'), 0)} |"
        )

    (HERE / "STATION_TABLE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote STATION_TABLE.md — {frame.station_no.nunique()} stations, {established} series with measurements")


if __name__ == "__main__":
    main()
