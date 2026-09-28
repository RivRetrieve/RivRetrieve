import rivretrieve as rr

selection = rr.find(
    provider="ba_fhmzbih",
    station="2310",
    quantity="discharge",
)

result = rr.fetch(
    selection,
    start="2026-09-01",
    end="2026-09-03T23:59:59",
    cache="bypass",
)

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print([(issue.severity, issue.code) for issue in result.issues])
