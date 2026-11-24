"""Swiss documentation examples run offline for discovery and against mocked transport for annotations.

The live retrieval values in the opening example are checked separately against the
source; here we check that selection/discovery stay offline and that the opening
fetch plus annotation block reproduce their displayed output shapes.
"""

import ast
import json
import re
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.transport import TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/providers/ch_foen.md"


def _python_blocks(page: str) -> list[str]:
    return re.findall(r"```python\n(.*?)```", page, re.DOTALL)


def _selection_ast_before_fetch(block: str) -> ast.Module:
    tree = ast.parse(block)
    fetch_index = next(
        index
        for index, statement in enumerate(tree.body)
        if isinstance(statement, ast.Assign)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == "fetch"
    )
    return ast.Module(body=tree.body[:fetch_index], type_ignores=[])


def test_swiss_page_selection_and_discovery_are_offline(monkeypatch, tmp_path):
    def denied(*args, **kwargs):
        pytest.fail("Swiss discovery attempted network access")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.chdir(tmp_path)
    blocks = _python_blocks(PAGE.read_text())
    namespace = {}
    exec(compile(_selection_ast_before_fetch(blocks[0]), "ch_foen.md:selection", "exec"), namespace)
    exec(compile(blocks[1], "ch_foen.md:discovery", "exec"), namespace)
    series = namespace["rr"].series(namespace["daily"])
    assert series.select("station_id", "variant", "quantity", "frequency", "statistic").rows() == [
        ("2018", "TagMittel", "discharge", "P1D", "mean")
    ]
    assert not namespace["candidates"].is_empty()
    assert not namespace["metadata"].is_empty()


def test_swiss_page_annotation_example_and_required_explanations(monkeypatch, tmp_path, capsys):
    def denied(*args, **kwargs):
        pytest.fail("Documentation test attempted real socket access")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.chdir(tmp_path)
    page = PAGE.read_text()
    for term in (
        "ch_foen.archive",
        "ch_foen.recent",
        "releaseState",
        "releaseStatus",
        "ersetzt",
        "../usage.md#source-annotations",
    ):
        assert term in page

    examples = re.findall(r"```python\n(.*?)```\s+Output:\s+```text\n(.*?)```", page, re.S)
    assert len(examples) == 2

    start_utc = datetime(2023, 12, 31, 23, 0, tzinfo=UTC)
    values = [113.624, 107.088, 114.261, 120.0, 121.0, 122.0, 123.0]
    rows = [
        {
            "station": {"no": "2018"},
            "parameterName": "Q",
            "tsName": "TagMittel",
            "unitSymbol": "m3/s",
            "timestamp": (start_utc + timedelta(days=day)).isoformat().replace("+00:00", "Z"),
            "value": val,
            "releaseState": "3",
        }
        for day, val in enumerate(values)
    ]

    class MockTransport:
        def send(self, request):
            return TransportResponse(
                json.dumps({"data": {"water": {"observations": {"data_1day_mean": rows}}}}).encode(),
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                "application/json",
                request.url,
                {},
            )

    monkeypatch.setattr(discovery, "HttpClient", MockTransport)
    blocks = _python_blocks(page)
    namespace = {}
    exec(compile(blocks[0], "ch_foen.md:fetch", "exec"), namespace)
    assert capsys.readouterr().out == examples[0][1]
    exec(compile(blocks[1], "ch_foen.md:discovery", "exec"), namespace)
    exec(compile(blocks[2], "ch_foen.md:annotations", "exec"), namespace)
    assert capsys.readouterr().out == examples[1][1]
