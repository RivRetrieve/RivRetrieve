import rivretrieve as rr

selection = rr.find(provider="no_nve", station="2.605.0", quantity="discharge", frequency="daily", statistic="mean")
print(rr.series(selection))
result = rr.fetch(selection, start="2024-01-01", end="2024-01-07", cache="bypass", receipts=True)
print(result.data.select("time", "time_zone", "value", "unit").head(3).write_csv(float_precision=3), end="")
print(result.data.height)
print(result.issues)
print(rr.series(result))
print(result.provenance.calls_made)
