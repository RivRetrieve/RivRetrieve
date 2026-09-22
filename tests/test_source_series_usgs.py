"""Independent legacy evidence; active behavior is tested against modern recordings.

No legacy numeric method is aliased to a modern opaque series ID.
See test_data/usgs_modern/REGRESSION-COVERAGE.md for active replacement coverage.
"""

import hashlib
import json
from pathlib import Path

from rivretrieve._internal.recordings import read_recording

DATA = Path(__file__).parent / "test_data"


def test_original_two_method_capture_remains_exact_and_independent():
    content = (DATA / "usgs_nwis_02196000_multi_method.json").read_bytes()
    assert len(content) == 1702244
    assert hashlib.sha256(content).hexdigest() == "92c43227ececed5373bc92abc4cbb19035dfc4b0ec7db736f2b4e443d8bf1275"
    source = json.loads(content)["value"]["timeSeries"]
    blocks = [block for item in source for block in item["values"]]
    assert {str(block["method"][0]["methodID"]) for block in blocks} == {"126801", "126805"}
    assert sorted(len(block["value"]) for block in blocks) == [7989, 15388]
    provenance = json.loads((DATA / "usgs_nwis_02196000_multi_method.provenance.json").read_text())
    assert provenance["status_code"] == {"state": "not_established"}
    assert provenance["retrieved_at"] == {"state": "not_established"}


def test_legacy_empty_method_description_is_not_modern_null_description():
    recording = read_recording(DATA / "usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json")
    blocks = json.loads(recording.content)["value"]["timeSeries"][0]["values"]
    assert blocks[0]["method"][0]["methodDescription"] == ""
    assert str(blocks[0]["method"][0]["methodID"]) == "61176"
    assert recording.request.url == "https://waterservices.usgs.gov/nwis/dv/"
