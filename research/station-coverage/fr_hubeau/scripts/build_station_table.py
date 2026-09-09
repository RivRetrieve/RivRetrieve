"""Generate STATION_TABLE.md: one row per baseline station with per-product status."""

from __future__ import annotations

import pathlib

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
LABEL = {
    "available": "yes",
    "empty_no_data_published": "none",
    "empty_in_tested_window": "empty*",
    "uninvestigated": "?",
    "access_failed": "fail",
}
PRODUCTS = (
    ("discharge_daily_mean", "Q day mean"),
    ("discharge_daily_max", "Q day max"),
    ("stage_daily_max", "H day max"),
    ("discharge_instantaneous", "Q inst"),
    ("stage_instantaneous", "H inst"),
    ("water_temperature_reported", "Temp"),
)


def main() -> None:
    frame = pd.read_csv(HERE / "inventory" / "station_product_evidence.csv", dtype=str)
    frame["n"] = pd.to_numeric(frame.observations, errors="coerce")

    def cell(group: pd.DataFrame, product: str) -> str:
        row = group[group.product_id == product]
        if row.empty:
            return "—"
        status = row.iloc[0].status
        if status == "available":
            count = row.iloc[0]["n"]
            return f"**yes** ({int(count):,})" if pd.notna(count) else "**yes**"
        return LABEL[status]

    lines = [
        "# fr_hubeau — station list with established coverage",
        "",
        "One row per station in the committed 7,323-station baseline. Generated from",
        "`inventory/station_product_evidence.csv` by `scripts/build_station_table.py`; no station is omitted.",
        "",
        "The 6,454 hydrometry stations carry the five hydrometric products; the 869 temperature stations are a",
        "disjoint population carrying only `water_temperature_reported`, shown as `—` for the rest.",
        "",
        "| Value | Meaning |",
        "| --- | --- |",
        "| `yes (n)` | the publisher reports *n* observations for that pair |",
        "| `none` | the publisher reports a total of zero **over the station's whole record** (no date filter) |",
        "| `empty*` | zero within a tested window only — the source states nothing about support |",
        "| `?` | uninvestigated: not resolved by this survey, and deliberately **not** recorded as absence |",
        "",
        "Daily and temperature products rest on whole-record totals, so `none` there is a published fact.",
        "Instantaneous products have no whole-record total available, so their negatives are window-bounded",
        "and appear as `empty*` or `?`. See `FINDINGS.md` for why.",
        "",
        "| Station | Name | River | Dept | Site | In service | Producer | "
        + " | ".join(label for _, label in PRODUCTS)
        + " |",
        "| --- | --- | --- | --- | --- | --- | --- | " + " | ".join("---" for _ in PRODUCTS) + " |",
    ]
    for station, group in sorted(frame.groupby("code_station")):
        first = group.iloc[0]
        producer = str(first.producer) if pd.notna(first.producer) else ""
        lines.append(
            f"| `{station}` | {first.station_name} | {first.river} | {first.departement} "
            f"| {first.code_site} | {'yes' if str(first.en_service) == 'True' else 'no'} "
            f"| {producer[:44]} | " + " | ".join(cell(group, product) for product, _ in PRODUCTS) + " |"
        )

    counts = frame.groupby(["product_id", "status"]).size()
    lines += [
        "",
        f"**{frame.code_station.nunique():,} stations · {len(frame):,} station × product pairs · "
        f"{int((frame.status == 'available').sum()):,} established series.**",
        "",
        "| Product | available | none published | empty in window | uninvestigated |",
        "| --- | --- | --- | --- | --- |",
    ]
    for product, _ in PRODUCTS:
        lines.append(
            f"| `{product}` | {counts.get((product, 'available'), 0):,} "
            f"| {counts.get((product, 'empty_no_data_published'), 0):,} "
            f"| {counts.get((product, 'empty_in_tested_window'), 0):,} "
            f"| {counts.get((product, 'uninvestigated'), 0):,} |"
        )
    (HERE / "STATION_TABLE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote STATION_TABLE.md — {frame.code_station.nunique()} stations")


if __name__ == "__main__":
    main()
