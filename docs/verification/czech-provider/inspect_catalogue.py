import polars as pl

import rivretrieve as rr

selection = rr.find(provider="cz_chmi")
print("Station count:", len(selection.locations))
print("Series count:", rr.series(selection).height)
print(
    rr.series(selection)
    .select("quantity", "frequency", "statistic", "inventory_status")
    .unique()
    .sort("quantity", "frequency")
)
native = pl.read_parquet("src/rivretrieve/_internal/providers/cz_chmi/catalogue/native.parquet")
print(native.filter(pl.col("objID") == "0-203-1-180100").select("objID", "STATION_NAME", "STREAM_NAME"))
