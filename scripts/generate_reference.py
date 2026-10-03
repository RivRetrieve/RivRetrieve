"""Generate factual reference tables from local schemas and packaged catalogues."""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

from rivretrieve._internal.observations import ObservationDataSchema
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
from rivretrieve._internal.providers.registration import BulkStore, CatalogueOnly, LiveStages, load_manifest
from rivretrieve._internal.selection import _series_frame
from rivretrieve._internal.source_series import SeriesScope
from rivretrieve._internal.station_metadata import SOURCE_METADATA_SCHEMA, STATION_METADATA_SCHEMA


def _schema(title: str, schema: pl.Schema) -> str:
    rows = [f"### {title}", "", "| Column | Polars dtype |", "| --- | --- |"]
    rows.extend(f"| `{name}` | `{dtype}` |" for name, dtype in schema.items())
    return "\n".join(rows) + "\n"


def render_tables() -> str:
    """Read local schemas and catalogue facts as deterministic Markdown tables.

    This is the offline composition root. It does not call providers(), whose
    credential-readiness check reads the working directory's .env file.
    """
    parts = []
    parts.extend(
        (
            "## Frame schemas\n",
            _schema("Series inspection frame", _series_frame((), SeriesScope()).schema),
            "Identity and facts are separate. Nullable facts carry explicit evidence states; "
            "admission and inventory are not completeness scores. Use to_bundle for lossless exports.\n",
            _schema("Station metadata summary", STATION_METADATA_SCHEMA),
            _schema("Source metadata frame", SOURCE_METADATA_SCHEMA),
            "See `metadata` above and [station metadata](station-metadata.md) for name alternatives, JSON decoding and absence states.\n",
            _schema("Observation frame", ObservationDataSchema.polars_schema),
            "Only value is nullable. Time precision can vary while remaining Datetime. "
            "The zone belongs to each row, not the timestamp dtype. "
            "See `ObservationResult` above for units and meanings.\n",
        )
    )
    parts.extend(
        (
            "\n## Shipped software capabilities\n",
            "The table uses the built-in manifest and declarations, not source probes. "
            "Credential names are requirements, not a readiness or successful-access test. "
            "Bulk retrieval needs explicit `download()` consent before a store exists.\n",
            "Counts describe packaged inventory accounting only. They do not establish "
            "countrywide completeness, continuous history or present-day source access. "
            "Pair counts describe access routes, not concrete source-series counts or admission. "
            "See the [provider handoff](index.md#river-data-and-where-to-find-them) for ownership and coverage qualifications.\n",
            "| Provider | Observation kind | Required credential variables | Stations | Available pairs | Unknown pairs | Unavailable pairs |\n"
            "| --- | --- | --- | ---: | ---: | ---: | ---: |",
        )
    )
    products: list[str] = []
    for declared in load_manifest(BUILTIN_PROVIDER_IDS):
        declaration = declared.declaration
        kind = declaration.observations
        if isinstance(kind, LiveStages):
            label = "live"
        elif isinstance(kind, BulkStore):
            label = "bulk store"
        elif isinstance(kind, CatalogueOnly):
            label = "catalogue-only"
        else:
            raise TypeError(f"Unrecognized provider kind: {type(kind)}")
        credentials = ", ".join(f"`{name}`" for name in declaration.required_credentials) or "none"
        stations = pl.read_parquet(declaration.catalogue / "stations.parquet").height
        pairs = pl.read_parquet(declaration.catalogue / "station_products.parquet")
        counts = [
            pairs.filter(pl.col("availability") == state).height for state in ("available", "unknown", "unavailable")
        ]
        parts.append(
            f"| `{declared.provider_id}` | {label} | {credentials} | {stations} | "
            + " | ".join(str(count) for count in counts)
            + " |"
        )
        table = pl.read_parquet(declaration.catalogue / "products.parquet").sort("product_id")
        for row in table.iter_rows(named=True):
            products.append(f"| `{declared.provider_id}` | `{row['product_id']}` | `{row['unit']}` |")
    parts.extend(
        (
            "\n### Packaged access coordinates\n",
            "Access coordinates and declared units come from products.parquet. "
            "These are internal routes, not public physical filters or scientific authority. "
            "A provider listing a route does not imply that every station offers it. "
            "Use physical filters in `find` and inspect `series` for admission, units and facts. "
            "A product route does not select a preferred source variant.\n",
            "| Provider | Product | Canonical unit |\n| --- | --- | --- |",
            *products,
        )
    )
    return "\n".join(parts).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the generated reference differs")
    args = parser.parse_args()
    destination = Path(__file__).resolve().parents[1] / "docs" / "_generated" / "reference-tables.md"
    text = render_tables()
    if args.check:
        if not destination.exists() or destination.read_text(encoding="utf-8") != text:
            raise SystemExit("Reference drift: run uv run python scripts/generate_reference.py")
        print("Reference is current.")
    else:
        destination.write_text(text, encoding="utf-8")
        print(f"Wrote {destination}")


if __name__ == "__main__":
    main()
