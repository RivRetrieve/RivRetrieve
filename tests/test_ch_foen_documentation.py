"""Swiss discovery examples run offline with packaged catalogue inputs."""

import re
import socket
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]


def test_swiss_page_examples_are_offline(monkeypatch, tmp_path):
    def denied(*args, **kwargs):
        pytest.fail("Swiss documentation attempted network access")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.chdir(tmp_path)
    page = (ROOT / "docs/providers/ch_foen.md").read_text()
    blocks = re.findall(r"```python\n(.*?)```", page, re.DOTALL)
    assert blocks
    namespace = {}
    for index, code in enumerate(blocks, 1):
        exec(compile(code, f"ch_foen.md:block-{index}", "exec"), namespace)
    assert not namespace["candidates"].is_empty()
    assert not namespace["metadata"].is_empty()
