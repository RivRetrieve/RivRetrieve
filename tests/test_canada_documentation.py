"""Offline checks for the Canada documentation; not live acquisition evidence."""

import hashlib
import json
import re
from pathlib import Path

import rivretrieve as rr

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/providers/ca_eccc.md"
EVIDENCE = ROOT / "docs/verification/canada-provider"


def test_canada_documentation_snippets_are_valid_current_python():
    snippets = re.findall(r"```python\n(.*?)```", PAGE.read_text(), re.S)
    assert len(snippets) == 3
    for snippet in snippets:
        compile(snippet, str(PAGE), "exec")
    assert 'product="' not in PAGE.read_text()
    assert 'station="05OG008"' in snippets[1]
    assert 'frequency="daily"' in snippets[1]
    assert 'statistic="mean"' in snippets[1]


def test_canada_documentation_selection_matches_packaged_catalogue():
    assert len(rr.find(provider="ca_eccc").locations) == 8057
    selection = rr.find(
        provider="ca_eccc", station="05OG008", quantity="discharge", frequency="daily", statistic="mean"
    )
    assert rr.series(selection).select("station_id", "quantity", "frequency", "statistic").rows() == [
        ("05OG008", "discharge", "daily", "mean")
    ]


def test_canada_publisher_evidence_hashes_and_index_link():
    index = json.loads((EVIDENCE / "sources/INDEX.json").read_text())
    for name, metadata in index.items():
        body = (EVIDENCE / "sources" / f"{name}.response").read_bytes()
        assert metadata["status"] == 200
        assert hashlib.sha256(body).hexdigest() == metadata["sha256"]
    assert "providers/ca_eccc.md" in (ROOT / "docs/README.md").read_text()
