"""Inspect the packaged catalogue without contacting an observation service."""

import argparse
from pathlib import Path

import polars as pl

import rivretrieve as rr

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--native", type=Path, required=True, help="External retained native table")
args = parser.parse_args()

root = Path("src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue")
selection = rr.find(provider="ba_fhmzbih")
print("locations", len(selection.locations))
print("series_candidates", len(selection.series))
print("inventory_status", sorted({item.completeness for item in selection.inventories}))
products = pl.read_parquet(root / "station_products.parquet")
print(products.group_by("product_id", "availability").len().sort("product_id", "availability").write_csv(), end="")
native = pl.read_parquet(args.native)
print(
    native.filter(pl.col("metadata_station_no") == "2310")
    .select("metadata_station_no", "metadata_station_name", "metadata_river_name", "retrieved_at")
    .write_csv(),
    end="",
)
print(rr.series(selection).select("quantity", "frequency", "statistic").unique().sort("quantity").write_csv(), end="")
