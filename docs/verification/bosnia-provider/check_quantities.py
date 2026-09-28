"""Additional live checks; not an additional provider-page example."""

import rivretrieve as rr

for station, quantity, start, end in (
    ("2310", "discharge", "2026-09-01", "2026-09-03T23:59:59"),
    ("2310", "stage", "2026-09-01", "2026-09-03T23:59:59"),
    ("4110", "temperature", "2025-10-01", "2025-10-03T23:59:59"),
):
    result = rr.fetch(
        rr.find(provider="ba_fhmzbih", station=station, quantity=quantity), start=start, end=end, cache="bypass"
    )
    print(station, quantity, start, end)
    print("rows", result.data.height, "nulls", result.data["value"].null_count())
    print(result.data.select("time", "time_zone", "source_unit", "unit", "value").head(3).write_csv(), end="")
    print("time_span", result.data["time"].min(), result.data["time"].max())
    print("issues", [(issue.severity, issue.code) for issue in result.issues])
