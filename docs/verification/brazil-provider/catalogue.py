import rivretrieve as rr

selection = rr.find(provider="br_ana")
frame = rr.series(selection)
print(frame.columns)
print(frame["station_id"].n_unique(), frame.height)
print(frame.group_by("variant", "frequency", "statistic", "source_unit", "unit").len().sort("variant"))
