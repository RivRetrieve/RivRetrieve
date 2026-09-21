"""Verify saved source evidence offline; defaults to this script's directory."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from rivretrieve._internal.recordings import read_recording

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--evidence-dir", type=Path, default=Path(__file__).resolve().parent)
OUT = parser.parse_args().evidence_dir.resolve()
manifest = json.loads((OUT / "manifest.json").read_text())
for entry in manifest:
    name = entry["name"]
    raw = (OUT / f"{name}.attempt1.response.body").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
    exchange = json.loads((OUT / f"{name}.attempt1.exchange.json").read_text())
    request = (OUT / f"{name}.attempt1.request.http").read_bytes()
    assert hashlib.sha256(request).hexdigest() == exchange["request_sha256"]
    if "rows" not in entry:
        continue
    recording = read_recording(OUT / f"{name}.recording.json")
    assert recording.content == raw
    station, metric = name.split("_")[:2]
    series = json.loads(raw)["series"]
    assert series["code"] == station and series["metric"] == metric
    assert series["statuses"] == recording.request.parameters["hydro_series[statusData]"]
    assert series["unit"] == ("l" if metric == "Q" else "mm")
    assert json.loads(raw)["timezone"] == "UTC"
    assert series["title"].startswith("Débit instantané" if metric == "Q" else "Hauteur instantanée")
    assert all(row["t"].endswith("Z") for row in series["data"])


def rows(station, metric, window, variant):
    return json.loads((OUT / f"{station}_{metric}_{window}_{variant}.attempt1.response.body").read_bytes())["series"][
        "data"
    ]


for metric in ("Q", "H"):
    for window in ("padded", "direct"):
        assert rows("1232000101", metric, window, "raw") == rows("1232000101", metric, window, "most_valid")
        assert (
            rows("1232000101", metric, window, "validated")
            == rows("1232000101", metric, window, "pre_validated_and_validated")
            == []
        )
        assert (
            rows("Y251002001", metric, window, "validated")
            == rows("Y251002001", metric, window, "pre_validated_and_validated")
            == rows("Y251002001", metric, window, "most_valid")
        )
        assert rows("Y251002001", metric, window, "raw") != rows("Y251002001", metric, window, "validated")
form = (OUT / "station-form.attempt1.response.body").read_text()
inputs = re.findall(r'<input[^>]+name="hydro_series\[statusData\]"[^>]+>', form)
assert {re.search(r'value="([^"]+)"', value).group(1) for value in inputs} == {
    "raw",
    "validated",
    "pre_validated_and_validated",
    "most_valid",
}
assert len(inputs) == 4
print(
    "Verified 38 response hashes, request hashes, 32 recording bytes and identities (including empty envelopes), selector form, and overlapping observation arrays."
)
