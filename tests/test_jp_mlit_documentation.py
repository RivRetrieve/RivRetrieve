"""Execute the Japan guide against saved publisher exchanges, not live access."""

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import ReplayTransport

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]


def test_japan_page_examples_and_displayed_outputs(monkeypatch, tmp_path, retained_evidence_root):
    page = (ROOT / "docs/providers/jp_mlit.md").read_text()
    blocks = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.DOTALL)
    assert len(blocks) == page.count("```python") == 2
    replay = ReplayTransport(
        [
            retained_evidence_root / "tests/test_data/japan_provider_documentation" / f"jp_mlit-{i}.recording.json"
            for i in range(2)
        ]
    )
    calls = []
    send = replay.send

    def tracked_send(request):
        calls.append(request)
        return send(request)

    monkeypatch.setattr(replay, "send", tracked_send)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)
    namespace = {}
    for index, (code, expected) in enumerate(blocks, 1):
        output = io.StringIO()
        with redirect_stdout(output):
            exec(compile(code, f"jp_mlit.md:block-{index}", "exec"), namespace)
        assert output.getvalue() == expected, index
        if index == 1:
            assert not namespace["rr"].cache_status("jp_mlit").exists
    result = namespace["result"]
    cached = namespace["cached_result"]
    repeated = namespace["repeated_result"]
    assert_frame_equal(result.data, cached.data)
    assert_frame_equal(cached.data, repeated.data)
    assert len(calls) == 4
    assert result.issues == cached.issues == repeated.issues
    assert result.issues[0].details == {
        "count": 17,
        "first_source_label": "2020年4月30日",
        "last_source_label": "2020年7月1日",
    }
    assert [outcome.status for outcome in result.outcomes] == ["success"]


def test_japan_page_catalogue_count_and_unknown_statistic():
    import rivretrieve as rr

    page = (ROOT / "docs/providers/jp_mlit.md").read_text()
    catalogue = ROOT / "src/rivretrieve/_internal/providers/jp_mlit/catalogue"
    assert pl.read_parquet(catalogue / "stations.parquet").height == 1023
    assert "| Stations in the catalogue | 1,023." in page
    selection = rr.find(provider="jp_mlit", station="305071285512040", quantity="discharge", frequency="daily")
    assert rr.series(selection)["statistic"].to_list() == [None]
    index = (ROOT / "docs/README.md").read_text()
    for provider in ("jp_mlit", "ch_foen", "fr_hubeau", "fr_hydroportail"):
        assert f"(providers/{provider}.md)" in index
