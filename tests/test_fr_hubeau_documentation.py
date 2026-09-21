"""Execute the French guide against exact saved public source exchanges.

This checks examples and printed outputs offline, not current source availability.
"""

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

import polars as pl

import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import ReplayTransport

ROOT = Path(__file__).resolve().parents[1]


def test_french_page_examples_and_displayed_outputs(monkeypatch, tmp_path):
    page = (ROOT / "docs/providers/fr_hubeau.md").read_text()
    blocks = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.DOTALL)
    assert len(blocks) == page.count("```python") == 1
    replay = ReplayTransport(
        [
            ROOT / "tests/test_data/fr_hubeau_Y251002001_daily_january2024.recording.json",
        ]
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.chdir(tmp_path)
    namespace = {}
    for index, (code, expected) in enumerate(blocks, 1):
        output = io.StringIO()
        with redirect_stdout(output):
            exec(compile(code, f"fr_hubeau.md:block-{index}", "exec"), namespace)
        assert output.getvalue() == expected, index
    assert not namespace["result"].issues


def test_french_page_station_count():
    page = (ROOT / "docs/providers/fr_hubeau.md").read_text()
    catalogue = ROOT / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue"
    station_count = pl.read_parquet(catalogue / "stations.parquet").height
    assert f"| Stations in the catalogue | Hub'Eau: {station_count:,} (" in page
    hydroportail = ROOT / "src/rivretrieve/_internal/providers/fr_hydroportail/catalogue"
    hydroportail_count = pl.read_parquet(hydroportail / "stations.parquet").height
    assert f"HydroPortail: {hydroportail_count:,}." in page
