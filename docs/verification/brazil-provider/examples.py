"""Exact provider-page snippets, in reading order. Run from the credential-provisioned directory."""

import rivretrieve as rr

selection = rr.find(
    provider="br_ana",
    station="15400000",
    quantity="discharge",
    frequency="daily",
    statistic="mean",
)
consistido = rr.pick(selection, variant="consistido")

result = rr.fetch(
    consistido, start="2020-01-10", end="2020-01-12", cache="bypass"
)

preview = result.data.select("time", "time_zone", "value", "unit")
print(preview.write_csv(), end="")

print(result.data.height)
print(sorted({(issue.severity, issue.code) for issue in result.issues}))


telemetry = rr.pick(
    rr.find(provider="br_ana", station="15400000", quantity="discharge"),
    variant="Vazao_Adotada",
)

print(rr.series(telemetry).select("variant", "frequency", "statistic").rows())


print(
    rr.series(selection)
    .select("station_id", "variant", "frequency", "statistic")
    .rows()
)


both_result = rr.fetch(
    selection, start="2020-01-10", end="2020-01-12", cache="bypass"
)

print(rr.series(both_result).select("variant").rows())
print(both_result.data.height, both_result.data["series_id"].n_unique())
print(sorted({(issue.severity, issue.code) for issue in both_result.issues}))
