import polars as pl

import rivretrieve as rr

selection = rr.find(provider="no_nve")
frame = rr.series(selection)
print("catalogue locations", len(selection.locations))
print("series rows", frame.height)
print("unique stations", frame["station_id"].n_unique())
print(
    frame.group_by("quantity", "frequency", "statistic")
    .agg(pl.col("station_id").n_unique().alias("stations"))
    .sort("quantity", "frequency", "statistic")
    .write_csv()
)
print(
    frame.group_by("product_id").agg(pl.col("station_id").n_unique().alias("stations")).sort("product_id").write_csv()
)
print(rr.providers())
print(rr.as_frame(rr.find(provider="no_nve", station="2.605.0")))
