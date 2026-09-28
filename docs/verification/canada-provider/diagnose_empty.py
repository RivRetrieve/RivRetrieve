import os
from pathlib import Path
import polars as pl
import rivretrieve as rr
root=Path(os.environ["RIVRETRIEVE_CACHE_DIR"])/"ca_eccc"/"store"
paths=list(root.rglob("*.parquet"))
print("partitions",len(paths),[str(p.relative_to(root)) for p in paths[:5]])
frame=pl.scan_parquet(paths).filter(pl.col("station_id")=="05OG008")
print(frame.select("time","value","series_id","facts_id").collect().head(10))
print(frame.select(pl.col("time").min().alias("min"),pl.col("time").max().alias("max"),pl.len()).collect())
print(frame.filter(pl.col("time").dt.year()==2000).select("time","value","series_id","facts_id").collect().head(10))
sel=rr.find(provider="ca_eccc",station="05OG008",quantity="discharge",frequency="daily",statistic="mean")
print("selected",sel.series)
