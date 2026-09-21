"""Execute French provider guides against exact saved public exchanges.

These tests check examples offline, not current source availability.
"""

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

import polars as pl
import pytest

import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import ReplayTransport

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "maintenance/verification/french-provider-documentation/2026-09-21"


@pytest.mark.parametrize("provider,block_count", [("fr_hubeau", 1), ("fr_hydroportail", 3)])
def test_french_page_examples_and_displayed_outputs(monkeypatch, tmp_path, provider, block_count):
    page = (ROOT / f"docs/providers/{provider}.md").read_text()
    blocks = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.DOTALL)
    assert len(blocks) == page.count("```python") == block_count
    replay = ReplayTransport(sorted(EVIDENCE.glob(f"{provider}-*.recording.json")))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.chdir(tmp_path)
    namespace = {}
    for index, (code, expected) in enumerate(blocks, 1):
        output = io.StringIO()
        with redirect_stdout(output):
            exec(compile(code, f"{provider}.md:block-{index}", "exec"), namespace)
        assert output.getvalue() == expected, index
    if provider == "fr_hubeau":
        assert not namespace["result"].issues
    else:
        assert [(issue.severity, issue.code) for issue in namespace["result"].issues] == [
            ("info", "provenance.license_not_established"),
            ("info", "provenance.citation_not_established"),
        ]
        assert namespace["rr"].series(namespace["result"])["variant"].to_list() == ["validated"]


@pytest.mark.parametrize("provider", ["fr_hubeau", "fr_hydroportail"])
def test_french_page_station_count(provider):
    page = (ROOT / f"docs/providers/{provider}.md").read_text()
    catalogue = ROOT / f"src/rivretrieve/_internal/providers/{provider}/catalogue"
    station_count = pl.read_parquet(catalogue / "stations.parquet").height
    assert f"| Stations in the catalogue | {station_count:,}" in page
    index = (ROOT / "docs/README.md").read_text()
    assert f"(providers/{provider}.md)" in index
