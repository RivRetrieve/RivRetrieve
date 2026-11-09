"""Restored selections can fetch without earlier catalogue discovery."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import rivretrieve as rr


@pytest.mark.usefixtures("reuse_packaged_catalogues")
@pytest.mark.parametrize("method", ["fetch", "fetch_by_provider"])
@pytest.mark.parametrize("cache", ["bypass", "refresh"])
def test_restored_selection_fetches_in_fresh_process(tmp_path, method, cache):
    selection = rr.find(
        provider="usgs_nwis", station="02196000", quantity="discharge", frequency="daily", statistic="mean"
    )
    bundle = tmp_path / "selection.zip"
    bundle.write_bytes(rr.to_bundle(selection))
    # No find/providers call in the consumer: only the bundle supplies its selection.
    script = """
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import rivretrieve as rr
from tests.test_usgs_observation_acquisition import Transport, feature, page

selection = rr.from_bundle(Path(sys.argv[1]).read_bytes())
selection = rr.pick(selection, series_id=selection.series[0].series_id)
identifier = selection.series[0].identity.published_id
transport = Transport(page(feature(identifier)))
with patch("rivretrieve._internal.discovery.HttpClient", return_value=transport):
    result = getattr(rr, sys.argv[2])(
        selection, start="2000-01-01", end="2000-01-01", cache=sys.argv[3], on_issue="raise"
    )
if sys.argv[2] == "fetch_by_provider":
    assert set(result) == {"usgs_nwis"}
    result = result["usgs_nwis"]
assert len(transport.requests) == 1
assert result.data.select("time", "source_unit", "unit").rows() == [
    (datetime(2000, 1, 1), "ft^3/s", "m3/s")
]
assert result.data["value"].item() == pytest.approx(12.25 * 0.0283168466)
assert result.data["series_id"].item() == selection.series[0].series_id
"""
    root = Path(__file__).resolve().parents[1]
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root))),
        "RIVRETRIEVE_CACHE_DIR": str(tmp_path / "cache"),
    }
    completed = subprocess.run(
        [sys.executable, "-c", script, str(bundle), method, cache],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
