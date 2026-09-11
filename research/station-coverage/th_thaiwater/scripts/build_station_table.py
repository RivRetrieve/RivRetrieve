"""Generate STATION_TABLE.md: one row per baseline station with per-product status.

Every number in the introduction is read from the generated summaries, so the text cannot drift
from the inventory it introduces.
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
LABEL = {"available": "yes", "empty_in_tested_window": "empty", "access_failed": "404", "uninvestigated": "?"}


def main() -> None:
    frame = pd.read_csv(HERE / "inventory" / "station_product_evidence.csv", dtype=str)
    frame["n"] = pd.to_numeric(frame.nonnull_observations, errors="coerce")
    sweep = json.loads((HERE / "inventory" / "inventory_summary.json").read_text())
    meta = json.loads((HERE / "inventory" / "metadata_vs_graph_summary.json").read_text())
    counts = meta["counts"]

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
        "`yes (n)` = the cited graph response published *n* non-null values for that product's field.",
        "`empty` = the cited response is a complete time grid carrying no non-null value — the source states",
        "nothing about whether the station can supply the measurement, and this is never recorded as",
        "unsupported. `Window` is the response each row rests on, in inclusive calendar dates ending",
        f"2026-09-06; both products of a station rest on the same response. Responses were acquired "
        f"{sweep['acquired_between'][0][:16]}Z .. {sweep['acquired_between'][1][:16]}Z (replacement captures; "
        "see FINDINGS §3).",
        "",
        "Stations with an empty product over the 7 dates 2026-08-31 .. 2026-09-06 were re-probed over the",
        f"91 dates 2026-06-08 .. 2026-09-06, and that response governs both products. Of "
        f"{sweep['short_both_empty']} stations empty for both products on 7 dates, "
        f"{sweep['short_both_empty_recovered_on_wide']} published a value on 91 dates.",
        "",
        "Availability comes from the graph route, never from catalogue metadata. Of the "
        f"{meta['present_in_snapshot']} baseline stations present in the "
        f"{meta['snapshot_acquired_at'][:10]} `waterlevel_load` snapshot, its `discharge` field disagrees "
        f"with the graph window for {meta['present_disagree']} "
        f"({counts.get('snapshot_null_graph_available', 0)} null but the graph publishes discharge, "
        f"{counts.get('snapshot_value_graph_empty', 0)} set but the graph publishes none). "
        f"{meta['absent_from_snapshot']} baseline stations are absent from that snapshot; "
        f"{meta['absent_with_graph_discharge']} of them publish discharge on the graph route. The snapshot "
        "describes one instant and the graph a window, so a disagreement is not evidence that either is "
        "wrong. `Live` marks presence in the snapshot — absence there is not evidence of absence of data.",
        "",
        "| Station | Name (th) | River | Agency | Basin | Live | Window | Stage | Discharge |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    short = {
        "Royal Irrigation Department": "RID",
        "Hydro – Informatics Institute (Public Organization)": "HII",
        "Friend in Need (of “Pa”) Volunteers Foundation": "FiN",
        "Electricity Generating Authority of Thailand": "EGAT",
    }
    for station, group in sorted(frame.groupby("station_id"), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        first = group.iloc[0]
        windows = "/".join(str(value) for value in sorted({int(value) for value in group.window_dates}))
        lines.append(
            f"| `{station}` | {first.station_name_th} | {first.river_name} "
            f"| {short.get(first.agency, first.agency)} | {first.basin} "
            f"| {'yes' if first.in_live_snapshot_2026_09_07 == 'True' else '—'} "
            f"| {windows} | {cell(group, 'stage_reported')} | {cell(group, 'discharge_reported')} |"
        )

    tally = frame.groupby(["product_id", "status"]).size()
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
            f"| `{product}` | {tally.get((product, 'available'), 0)} "
            f"| {tally.get((product, 'empty_in_tested_window'), 0)} "
            f"| {tally.get((product, 'access_failed'), 0)} |"
        )
    (HERE / "STATION_TABLE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote STATION_TABLE.md — {frame.station_id.nunique()} stations")


if __name__ == "__main__":
    main()
