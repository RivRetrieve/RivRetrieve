"""Lithuania documentation checks over fresh captured bytes, not live verification."""

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import ReplayTransport

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/verification/lithuania-provider"


def test_lithuania_page_examples_match_recorded_responses(monkeypatch, tmp_path):
    page = (ROOT / "docs/providers/lt_lhmt.md").read_text()
    blocks = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.S)
    assert len(blocks) == page.count("```python") == 2
    replay = ReplayTransport(sorted((EVIDENCE / "recordings").glob("*.recording.json")))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    namespace = {}
    for index, (code, expected) in enumerate(blocks, 1):
        output = io.StringIO()
        with redirect_stdout(output):
            exec(compile(code, f"lt_lhmt.md:block-{index}", "exec"), namespace)
        assert output.getvalue() == expected, index
    for name in ("result", "stage_result"):
        result = namespace[name]
        assert result.data.height == 7
        assert result.data["value"].null_count() == 0
        assert [call["url"].rsplit("/", 1)[-1] for call in result.provenance.calls_made] == ["2019-12", "2020-01"]
    assert namespace["stage_result"].data["value"].head(3).to_list() == [0.45, 0.45, 0.51]


def test_lithuania_page_catalogue_count_units_and_index():
    assert len(rr.find(provider="lt_lhmt").locations) == 97
    candidates = rr.series(rr.find(provider="lt_lhmt", station="nemajunu-vms", frequency="daily", statistic="mean"))
    assert candidates.select("quantity", "statistic", "source_unit", "unit", "time_zone").sort("quantity").rows() == [
        ("discharge", "mean", "m3/s", "m3/s", "+00:00"),
        ("stage", "mean", "cm", "m", "+00:00"),
    ]
    assert "providers/lt_lhmt.md" in (ROOT / "docs/README.md").read_text()
