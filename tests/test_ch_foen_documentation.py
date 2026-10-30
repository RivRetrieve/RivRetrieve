"""Swiss example selection and discovery run offline with packaged catalogues.

The retrieval block is checked separately against the live source. This test
stops before fetch, then runs the guide's offline inspection block.
"""

import ast
import re
import socket
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]


def test_swiss_page_selection_and_discovery_are_offline(monkeypatch, tmp_path):
    def denied(*args, **kwargs):
        pytest.fail("Swiss discovery attempted network access")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.chdir(tmp_path)
    page = (ROOT / "docs/providers/ch_foen.md").read_text()
    blocks = re.findall(r"```python\n(.*?)```", page, re.DOTALL)
    tree = ast.parse(blocks[0])
    fetch_index = next(
        index
        for index, statement in enumerate(tree.body)
        if isinstance(statement, ast.Assign)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == "fetch"
    )
    namespace = {}
    exec(compile(ast.Module(body=tree.body[:fetch_index], type_ignores=[]), "ch_foen.md:selection", "exec"), namespace)
    for index, code in enumerate(blocks[1:], 2):
        exec(compile(code, f"ch_foen.md:block-{index}", "exec"), namespace)
    series = namespace["rr"].series(namespace["daily"])
    assert series.select("station_id", "variant", "quantity", "frequency", "statistic").rows() == [
        ("2018", "TagMittel", "discharge", "daily", "mean")
    ]
    assert not namespace["candidates"].is_empty()
    assert not namespace["metadata"].is_empty()
