import rivretrieve as rr
# Archive preparation already executed successfully by acquire.py.

selection = rr.find(
    provider="ca_eccc",
    station="05OG008",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)

result = rr.fetch(
    selection, start="1991-03-01", end="1991-03-07", cache="bypass"
)

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(float_precision=3), end="")

print(result.data.height)
print(result.issues)


status = rr.cache_status("ca_eccc")

print(status.presence.value)
print(status.source_vintage)
