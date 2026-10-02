"""Norway documentation checks over fresh captured bytes, not live verification."""

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import ReplayTransport

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path("docs/verification/norway-provider")


def test_norway_page_examples_match_recorded_responses(retained_evidence_root, monkeypatch, tmp_path):
    page = (ROOT / "docs/providers/no_nve.md").read_text()
    blocks = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.S)
    assert len(blocks) == page.count("```python") == 2
    replay = ReplayTransport(
        [retained_evidence_root / EVIDENCE / "recordings" / f"discharge-week_p{page}.recording.json" for page in (1, 2)]
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-documentation-test")
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    namespace = {}
    for index, (code, expected) in enumerate(blocks, 1):
        output = io.StringIO()
        with redirect_stdout(output):
            exec(compile(code, f"no_nve.md:block-{index}", "exec"), namespace)
        assert output.getvalue() == expected, index
    candidates = rr.series(namespace["other_station"])
    assert candidates.select("station_id", "quantity", "variant", "frequency", "statistic").sort("variant").rows() == [
        ("109.42.0", "discharge", variant, "daily", "mean") for variant in ("1", "2", "3")
    ]
    result = namespace["result"]
    assert result.data["value"].null_count() == 0
    assert [(issue.severity, issue.code) for issue in result.issues] == [
        ("info", "source_quality_code"),
        ("info", "source_correction_code"),
    ]
    assert [call["url"].rsplit("/", 1)[-1] for call in result.provenance.calls_made] == ["Series", "Observations"]
    assert result.provenance.calls_made[-1]["request_parameters"]["VersionNumber"] == 1


def test_norway_page_catalogue_counts_and_index():
    selection = rr.find(provider="no_nve")
    assert len(selection.locations) == 4902
    assert rr.series(selection)["station_id"].n_unique() == 3804
    for quantity, expected in (("discharge", 1620), ("stage", 2790), ("temperature", 1153)):
        daily = rr.find(provider="no_nve", quantity=quantity, frequency="daily", statistic="mean")
        assert rr.series(daily)["station_id"].n_unique() == expected
    assert "providers/no_nve.md" in (ROOT / "docs/README.md").read_text()
