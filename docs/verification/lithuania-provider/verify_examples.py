"""Execute the Lithuania page through the public API, then check its behaviour claims live."""

import io
import re
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

import rivretrieve as rr

print("run at", datetime.now(UTC).isoformat(timespec="seconds"))
page = Path("docs/providers/lt_lhmt.md").read_text()
blocks = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.S)
assert len(blocks) == page.count("```python") == 2
namespace = {}
for index, (code, expected) in enumerate(blocks, 1):
    output = io.StringIO()
    with redirect_stdout(output):
        exec(compile(code, f"lt_lhmt.md:block-{index}", "exec"), namespace)
    print(f"BLOCK {index}")
    print(output.getvalue(), end="")
    assert output.getvalue() == expected, index
print("Public snippets match all displayed output.")
for name in ("result", "stage_result"):
    calls = namespace[name].provenance.calls_made
    print(name, "source calls:", [(call["url"].rsplit("/", 1)[-1], call["status_code"]) for call in calls])


def daily_mean(station, quantity):
    return rr.find(provider="lt_lhmt", station=station, quantity=quantity, frequency="daily", statistic="mean")


def summary(label, result):
    calls = [(call["url"].rsplit("/", 1)[-1], call["status_code"]) for call in result.provenance.calls_made]
    issues = [(issue.severity, issue.code) for issue in result.issues]
    nulls = result.data["value"].null_count()
    print(f"{label}: rows={result.data.height} nulls={nulls} calls={calls} issues={issues}")
    return result


print("CLAIMS")
print("catalogue stations:", len(rr.find(provider="lt_lhmt").locations))
print(
    "nemajunu-vms series:",
    rr.series(rr.find(provider="lt_lhmt", station="nemajunu-vms"))
    .select("quantity", "frequency", "statistic", "source_unit", "unit", "time_zone", "day_definition")
    .sort("quantity")
    .rows(),
)
nulls = summary(
    "published null discharge birstono-vms 2024-06-10..12",
    rr.fetch(daily_mean("birstono-vms", "discharge"), start="2024-06-10", end="2024-06-12", cache="bypass"),
)
assert nulls.data.height == 3 and nulls.data["value"].null_count() == 3 and nulls.issues == ()
unpublished = summary(
    "unpublished period nemajunu-vms 2025-06-10..12",
    rr.fetch(
        daily_mean("nemajunu-vms", "discharge"), start="2025-06-10", end="2025-06-12", cache="bypass", on_issue="ignore"
    ),
)
assert unpublished.data.height == 0 and [issue.code for issue in unpublished.issues] == ["source.http_not_found"]
edge = summary(
    "unpublished padding month nemajunu-vms 2024-12-27..30",
    rr.fetch(daily_mean("nemajunu-vms", "discharge"), start="2024-12-27", end="2024-12-30", cache="bypass"),
)
assert edge.data.height == 4 and edge.issues == ()
coastal = summary(
    "no historical record juodkrantes-vms stage 2020-01-10..12",
    rr.fetch(
        daily_mean("juodkrantes-vms", "stage"), start="2020-01-10", end="2020-01-12", cache="bypass", on_issue="ignore"
    ),
)
print("Behaviour claims hold.")
