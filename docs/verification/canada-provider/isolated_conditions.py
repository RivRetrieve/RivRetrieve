import rivretrieve as rr

print("catalogue", len(rr.find(provider="ca_eccc").locations))
selection = rr.find(provider="ca_eccc", station="05OG008", quantity="discharge", frequency="daily", statistic="mean")
print("station", selection.locations)
print("series", rr.series(selection))
print("absent status", rr.cache_status("ca_eccc"))
result = rr.fetch(selection, start="2000-01-01", end="2000-01-07")
print("missing rows", result.data.height)
print("missing issues", result.issues)
print("provenance", result.provenance)
try:
    rr.fetch(selection, start="2000-01-01", end="2000-01-07", cache="refresh")
except Exception as exc:
    print("refresh refusal", type(exc).__name__, str(exc))
