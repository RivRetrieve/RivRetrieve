"""Modern null/value controls replacing retired WaterML noDataValue rules.

Modern daily features publish a present null, not a numeric sentinel declaration.
Authored derivatives below retain negative numbers and isolate absent/invalid
values. Historical WaterML recordings remain independent evidence, unchanged.
"""

import json
from contextlib import nullcontext

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import IssuePolicyError
from tests import test_usgs_nwis_measurements as measurements
from tests.usgs_modern_recordings import body


@pytest.fixture
def selection():
    return rr.find(provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean")


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
@pytest.mark.parametrize("value", [measurements._MISSING, True, False, "NaN", "Infinity", "-Infinity"])
def test_invalid_or_absent_modern_values_do_not_authorize_coverage(monkeypatch, tmp_path, selection, policy, value):
    content, calls = measurements._install(monkeypatch, tmp_path, body("daily-07374000-docs-2023"), value)
    context = (
        pytest.raises(IssuePolicyError)
        if policy == "raise"
        else pytest.warns(RuntimeWarning)
        if policy == "warn"
        else nullcontext()
    )
    with context:
        first = measurements._fetch(selection, policy)
        assert first.data.height == 1
        assert first.data["value"][0] == pytest.approx(42 * 0.028316846592)
        assert first.receipts.entries[0].content == content
    again = measurements._fetch(selection, "ignore")
    assert len(calls) == 2
    assert again.data.height == 1
    unsupported = [outcome for outcome in again.outcomes if outcome.status == "unsupported"]
    assert unsupported and all(outcome.series_id and outcome.facts_ids for outcome in unsupported)
    healthy = next(
        series.series_id
        for series in again.source_series
        if series.identity.published_id == "authored-independent-series"
    )
    manifests = list((tmp_path / "cache").rglob("manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text())
    assert {coverage["series_id"] for coverage in manifest["coverage"]} == {healthy}


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
@pytest.mark.parametrize("value,expected", [("-999999", -999999.0), ("-1", -1.0), ("0", 0.0), (None, None)])
def test_negative_numbers_are_not_implicit_sentinels_and_null_stays_present(
    monkeypatch, tmp_path, selection, policy, value, expected
):
    content, calls = measurements._install(
        monkeypatch, tmp_path, body("daily-07374000-docs-2023"), value, sibling=False
    )
    first = measurements._fetch(selection, policy)
    assert first.data.height == 1
    if expected is None:
        assert first.data["value"].null_count() == 1
    else:
        assert first.data["value"][0] == pytest.approx(expected * 0.028316846592)
    assert first.outcomes[0].status == "success"
    assert first.receipts.entries[0].content == content
    restored = rr.from_bundle(rr.to_bundle(first))
    assert restored.data["value"].to_list() == first.data["value"].to_list()
    cached = measurements._fetch(selection, policy)
    assert len(calls) == 1
    assert cached.data["value"].to_list() == first.data["value"].to_list()
