"""metadata_fields : PackagedCatalogue → FieldsByProviderTable.

Print or update the "Fields by provider" table in docs/station-metadata.md from the packaged
catalogue, so it cannot drift from what `rr.metadata(view="source")` returns:

    uv run python docs/scripts/metadata_fields.py            # print the table
    uv run python docs/scripts/metadata_fields.py --write    # update the page between its markers

Each cell lists the native field names behind one role, in the source's own spelling, with the
unit the source publishes, where one is established. A dash means the provider exposes no field
for that role. Field meanings are not stated here; the agency's definition decides.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

import rivretrieve as rr

PAGE = Path(__file__).resolve().parents[1] / "station-metadata.md"
START = "<!-- fields-by-provider:start -->"
END = "<!-- fields-by-provider:end -->"
ROLES = (
    ("station_name", "Station name"),
    ("water_body_name", "Water body"),
    ("drainage_area", "Drainage area"),
    ("elevation", "Elevation"),
)


def cell(rows: pl.DataFrame, role: str) -> str:
    """List a role's fields, grouped by the unit the source publishes for them."""
    fields = rows.filter(pl.col("attribute_role") == role)
    if fields.is_empty():
        return "—"
    units: dict[str, set[str]] = {}
    for field, unit in fields.select("source_field", "source_unit").unique().iter_rows():
        units.setdefault(field, set())
        if unit is not None:
            units[field].add(unit)
    by_unit: dict[str, list[str]] = {}
    for field in sorted(units):
        by_unit.setdefault(" / ".join(sorted(units[field])), []).append(field)
    parts = []
    for unit, names in by_unit.items():
        listed = ", ".join(f"`{name}`" for name in names)
        parts.append(f"{listed} ({unit})" if unit else listed)
    return "; ".join(parts)


def table() -> str:
    source = rr.metadata(rr.find(), view="source").filter(pl.col("state") != "no_metadata")
    providers = sorted(rr.as_frame(rr.find())["provider_id"].unique())
    lines = [
        "| Provider | " + " | ".join(label for _, label in ROLES) + " |",
        "|" + "---|" * (len(ROLES) + 1),
    ]
    for provider in providers:
        rows = source.filter(pl.col("provider_id") == provider)
        page = Path(__file__).resolve().parents[1] / "providers" / f"{provider}.md"
        name = f"[`{provider}`](providers/{provider}.md)" if page.exists() else f"`{provider}`"
        lines.append(f"| {name} | " + " | ".join(cell(rows, role) for role, _ in ROLES) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Print or update the metadata fields by provider table")
    parser.add_argument("--write", action="store_true", help=f"replace the text between {START} and {END}")
    args = parser.parse_args()
    text = table()
    if not args.write:
        print(text)
        return
    page = PAGE.read_text()
    before, _, rest = page.partition(START)
    _, _, after = rest.partition(END)
    if not rest or not after:
        raise SystemExit(f"{PAGE} lacks the {START} and {END} markers")
    PAGE.write_text(f"{before}{START}\n{text}\n{END}{after}")


if __name__ == "__main__":
    main()
