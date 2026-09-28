"""Keep the Swiss page examples aligned with an exact recorded source response.

This is offline regression evidence. Live page execution is recorded in the PR.
"""

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

import pytest

import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import ReplayTransport

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]


def test_swiss_page_examples_and_displayed_outputs(monkeypatch, tmp_path):
    page = (ROOT / "docs/providers/ch_foen.md").read_text()
    blocks = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.DOTALL)
    assert len(blocks) == page.count("```python") == 3
    replay = ReplayTransport([ROOT / "tests/test_data/ch_foen_2018_flux_january2024_full.recording.json"])
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.chdir(tmp_path)
    namespace = {}
    for index, (code, expected) in enumerate(blocks, 1):
        output = io.StringIO()
        with redirect_stdout(output):
            exec(compile(code, f"ch_foen.md:block-{index}", "exec"), namespace)
        assert output.getvalue() == expected, index
    assert not namespace["result"].issues
