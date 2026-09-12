"""Generate STATION_TABLE.md: one row per baseline station with per-product status.

render : (Inventory, Baseline) -> Markdown   (pure)
"""

from __future__ import annotations

import collections
import csv
import pathlib

import pandas as pd

LABEL = {
    "available": "yes",
    "empty_no_data_published": "none",
    "empty_in_both_history_windows": "empty ×2",
    "history_check_failed": "check failed",
    "recent_window_empty_history_unchecked": "30d empty",
    "access_failed": "fail",
}
PRODUCTS = (
    ("discharge_daily_mean", "Q day mean"),
    ("discharge_daily_max", "Q day max"),
    ("stage_daily_max", "H day max"),
    ("discharge_instantaneous", "Q inst (station series)"),
    ("stage_instantaneous", "H inst"),
    ("water_temperature_reported", "Temp"),
)


def _cell(value: object) -> str:
    text = "" if value is None or (isinstance(value, float) and value != value) else str(value)
    return text.replace("|", "/").strip()


def main() -> None:
    here = pathlib.Path(__file__).resolve().parents[1]
    native = pd.read_parquet(here.parents[2] / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet")
    names = {
        str(row.code_station): (
            _cell(row.libelle_station),
            _cell(row.libelle_cours_eau),
            _cell(row.libelle_departement),
        )
        for row in native.itertuples()
    }
    with (here / "inventory" / "station_product_evidence.csv").open(newline="", encoding="utf-8") as handle:
        inventory = list(csv.DictReader(handle))
    by_station: dict[str, dict[str, dict[str, str]]] = collections.defaultdict(dict)
    for row in inventory:
        by_station[row["code_station"]][row["product_id"]] = row

    lines = [
        "# fr_hubeau — station list with established coverage",
        "",
        "One row per station in the committed 7,323-station baseline. Generated from",
        "`inventory/station_product_evidence.csv` by `scripts/build_station_table.py`; no station is omitted.",
        "Every cell traces to the receipts named in that row's `evidence_refs`.",
        "",
        "The 6,454 hydrometry stations carry the five hydrometric products; the 869 temperature stations are a",
        "disjoint population carrying only `water_temperature_reported`, shown as `—` for the rest.",
        "",
        "| Value | Meaning |",
        "| --- | --- |",
        "| `yes (n)` | *n* observations reported: whole-record count, 30-day count, or HydroPortail points in a tested window |",
        "| `none` | whole-record count of zero (daily and temperature products only) |",
        "| `empty ×2` | 30-day count of zero and both HydroPortail history windows answered HTTP 200 with no point — emptiness **in those two windows only** |",
        "| `check failed` | 30-day count of zero and at least one history window never answered — **no claim** |",
        "| `30d empty` | 30-day count of zero; **never checked against history** |",
        "| `fail` | the count request was never answered — **no claim** |",
        "",
        "**`Q inst` is the station's own discharge series.** Production requests the *site* series, which a",
        "station result does not establish — see `FINDINGS.md` §5. The organisation column carries the Sandre",
        "field named in brackets; neither field is established as the producer of the series (`HANDOFF.md` §6).",
        "",
        "| Station | Name | River | Dept | Site | In service | Organisation [field] | "
        + " | ".join(label for _, label in PRODUCTS)
        + " |",
        "| --- | --- | --- | --- | --- | --- | --- | " + " | ".join("---" for _ in PRODUCTS) + " |",
    ]
    for station in sorted(by_station):
        rows = by_station[station]
        first = next(iter(rows.values()))
        name, river, dept = names[station]
        field = "NI" if first["station_organisation_field"] == "NomIntervenant" else "PdJ"
        organisation = (
            f"{first['station_organisation_name'][:44]} [{field}]"
            if first["station_organisation_name"]
            else f"— [{field}]"
        )
        cells = []
        for product, _ in PRODUCTS:
            row = rows.get(product)
            if row is None:
                cells.append("—")
            elif row["status"] == "available":
                cells.append(f"**yes** ({int(row['observations']):,})")
            else:
                cells.append(LABEL[row["status"]])
        service = {"True": "yes", "False": "no"}.get(first["en_service"], "")
        lines.append(
            f"| `{station}` | {name} | {river} | {dept} | {first['code_site']} | {service} | {organisation} | "
            + " | ".join(cells)
            + " |"
        )

    tally = collections.Counter((row["product_id"], row["status"]) for row in inventory)
    statuses = list(LABEL)
    lines += [
        "",
        f"**{len(by_station):,} stations · {len(inventory):,} station × product pairs.**",
        "",
        "| Product | " + " | ".join(f"`{status}`" for status in statuses) + " |",
        "| --- | " + " | ".join("---" for _ in statuses) + " |",
    ]
    for product, _ in PRODUCTS:
        lines.append(f"| `{product}` | " + " | ".join(f"{tally.get((product, s), 0):,}" for s in statuses) + " |")
    (here / "STATION_TABLE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote STATION_TABLE.md — {len(by_station)} stations")


if __name__ == "__main__":
    main()
