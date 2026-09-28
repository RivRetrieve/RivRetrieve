selection = rr.find(provider="pl_imgw", station="152140020", quantity="discharge")

result = rr.fetch(selection, start="2024-01-01", end="2024-01-07")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print([(issue.severity, issue.code) for issue in result.issues])
