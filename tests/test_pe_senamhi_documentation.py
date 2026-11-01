"""Tests for Peru SENAMHI user documentation."""

import ast
import io
import json
import re
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.transport import TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/providers/pe_senamhi.md"

_GENUINE_DAILY_HUAYABAMBA = {
    "status": True,
    "data": {
        "station": {"code": "212600", "name": "HUAYABAMBA", "river": "RÍO HUAYABAMBA"},
        "type": "DAILY",
        "variable": "FLOW",
        "unit": "m3/s",
        "daily": [
            {
                "date": "2024-01-01",
                "historicalAverage": 1000.8,
                "minimum": 1231.1693,
                "maximum": 1482.4322,
                "current": 1333.9661,
                "previous": 636.683,
            },
            {
                "date": "2024-01-02",
                "historicalAverage": 1001.5,
                "minimum": 1031.6989,
                "maximum": 1298.3508,
                "current": 1184.2294,
                "previous": 594.6572,
            },
            {
                "date": "2024-01-03",
                "historicalAverage": 990.1,
                "minimum": 1165.6125,
                "maximum": 1464.4183,
                "current": 1306.6894,
                "previous": 446.0414,
            },
            {
                "date": "2024-01-04",
                "historicalAverage": 985.7,
                "minimum": 1117.5112,
                "maximum": 1149.4772,
                "current": 1131.4741,
                "previous": 403.4278,
            },
            {
                "date": "2024-01-05",
                "historicalAverage": 979.1,
                "minimum": 1016.4267,
                "maximum": 2070.067,
                "current": 1444.8501,
                "previous": 606.0016,
            },
            {
                "date": "2024-01-06",
                "historicalAverage": 974.4,
                "minimum": 1677.7088,
                "maximum": 2516.8888,
                "current": 2218.5473,
                "previous": 939.5022,
            },
            {
                "date": "2024-01-07",
                "historicalAverage": 958.8,
                "minimum": 1402.1693,
                "maximum": 1537.0831,
                "current": 1464.7927,
                "previous": 709.6359,
            },
        ],
    },
}


class _MockDailyReplay:
    def send(self, request):
        return TransportResponse(
            content=json.dumps(_GENUINE_DAILY_HUAYABAMBA).encode(),
            status_code=200,
            retrieved_at=datetime(2026, 11, 1, tzinfo=UTC),
            content_type="application/json",
            url=request.url,
            request_parameters=request.params,
        )


def test_senamhi_documentation_file_exists_and_snippets_are_valid():
    assert PAGE.exists(), "docs/providers/pe_senamhi.md must exist"
    text = PAGE.read_text()
    snippets = re.findall(r"```python\n(.*?)```", text, re.DOTALL)
    assert len(snippets) == 1, "Expected one practical Python example"
    for snippet in snippets:
        ast.parse(snippet)


def test_senamhi_documentation_example_execution(monkeypatch, tmp_path):
    text = PAGE.read_text()
    blocks = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", text, re.DOTALL)
    assert len(blocks) == 1, "Expected one code block with an Output block"
    code, expected_output = blocks[0]

    monkeypatch.setattr(discovery, "HttpClient", lambda: _MockDailyReplay())
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)

    namespace = {}
    captured = io.StringIO()
    with redirect_stdout(captured):
        exec(compile(code, "pe_senamhi.md:example", "exec"), namespace)

    assert captured.getvalue() == expected_output
    result = namespace["result"]
    assert result.data.height == 7
    assert result.data["time_zone"].unique().to_list() == ["unknown"]
    assert result.data["unit"].unique().to_list() == ["m3/s"]
    assert len(result.issues) == 2


def test_senamhi_documentation_navigation_and_catalogue_counts():
    selection = rr.find(provider="pe_senamhi")
    assert len(selection.locations) == 771
    assert rr.as_frame(selection)["station_id"].n_unique() == 270

    text = PAGE.read_text()
    assert "270" in text
    assert "771" in text

    readme = (ROOT / "docs/README.md").read_text()
    assert "(providers/pe_senamhi.md)" in readme

    station_metadata = (ROOT / "docs/station-metadata.md").read_text()
    assert "pe_senamhi" in station_metadata
    assert "(providers/pe_senamhi.md)" in station_metadata

    mkdocs_config = (ROOT / "mkdocs.yml").read_text()
    assert "providers/pe_senamhi.md" in mkdocs_config


def test_senamhi_documentation_preserves_explicit_unknowns_and_limitations():
    text = PAGE.read_text()

    # Preserved physical unknowns and limits from #608 handoff and vision
    assert "daily mean" in text
    assert "unknown" in text
    assert "m.s.n.m" in text
    assert "datum" in text
    assert "one request per second" in text
    assert "null" in text
