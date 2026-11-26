"""Germany PEGELONLINE documentation checks over a retained recorded response, not live verification."""

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import ReplayTransport

ROOT = Path(__file__).resolve().parents[1]
RECORDING = Path("tests/test_data/de_pegelonline_hofkirchen_q_recent.recording.json")


@pytest.mark.recorded(str(RECORDING))
def test_pegelonline_page_example_matches_recorded_response(retained_evidence_root, monkeypatch, tmp_path):
    page = (ROOT / "docs/providers/de_pegelonline.md").read_text()
    blocks = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.S)
    assert len(blocks) == page.count("```python") == 1
    replay = ReplayTransport([retained_evidence_root / RECORDING])
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    namespace: dict[str, object] = {}
    for index, (code, expected) in enumerate(blocks, 1):
        output = io.StringIO()
        with redirect_stdout(output):
            exec(compile(code, f"de_pegelonline.md:block-{index}", "exec"), namespace)
        assert output.getvalue() == expected, index
    result = namespace["result"]
    assert result.data.height == 221
    assert result.data["value"].null_count() == 0


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_pegelonline_page_catalogue_count_units_and_index():
    assert len(rr.find(provider="de_pegelonline").locations) == 787
    candidates = rr.series(
        rr.find(provider="de_pegelonline", station="616dd98e-816d-4e17-b8cd-57b163dbc8a2")
    )
    rows = candidates.select("quantity", "source_unit", "unit").sort("quantity").rows()
    assert ("discharge", "m³/s", "m3/s") in rows
    assert "providers/de_pegelonline.md" in (ROOT / "docs/README.md").read_text()
    assert "providers/de_pegelonline.md" in (ROOT / "mkdocs.yml").read_text()
    assert "providers/de_pegelonline.md" in (ROOT / "docs/station-metadata.md").read_text()
