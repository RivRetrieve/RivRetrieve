"""Offline checks for the Canada documentation; not live acquisition evidence."""

import re
from pathlib import Path

import pytest

import rivretrieve as rr

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/providers/ca_eccc.md"
EVIDENCE = Path("docs/verification/canada-provider")


def test_canada_documentation_snippets_are_valid_current_python():
    text = PAGE.read_text()
    snippets = re.findall(r"```python\n(.*?)```", text, re.S)
    assert len(snippets) == 4
    for snippet in snippets:
        compile(snippet, str(PAGE), "exec")
    assert 'product="' not in text
    assert 'station="05OG008"' in snippets[1]
    assert 'frequency="daily"' in snippets[1]
    assert 'statistic="mean"' in snippets[1]
    assert "rr.annotations(result)" in snippets[3]
    assert "result.to_polars(annotations=True)" in snippets[3]
    assert "ca_eccc.dly_flows" in text
    assert "ca_eccc.dly_levels" in text
    assert "precision_code" in text
    assert "HYDAT_Definition_EN.pdf" in text


def test_canada_documentation_selection_matches_packaged_catalogue():
    assert len(rr.find(provider="ca_eccc").locations) == 8057
    selection = rr.find(
        provider="ca_eccc", station="05OG008", quantity="discharge", frequency="daily", statistic="mean"
    )
    assert rr.series(selection).select("station_id", "quantity", "frequency", "statistic").rows() == [
        ("05OG008", "discharge", "daily", "mean")
    ]
