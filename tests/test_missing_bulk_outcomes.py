"""Missing compiled stores remain identified local failures, never empty successes."""

from datetime import datetime
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.issues import IssuePolicyError


@pytest.mark.parametrize("provider,station", [("ca_eccc", "02GA010"), ("pl_imgw", "154210010")])
@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_missing_bulk_store_reports_concrete_outcome_without_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str, station: str, policy: str
):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))

    class NoNetwork:
        def send(self, request):
            pytest.fail("Missing local bulk stores must not trigger a source request or download")

    monkeypatch.setattr(discovery, "HttpClient", NoNetwork)
    selection = rr.find(provider=provider, station=station, quantity="stage")
    assert len(selection.series) == 1
    assert list(tmp_path.iterdir()) == []

    def fetch():
        return rr.fetch(selection, start="2020-01-01", end="2020-01-01", receipts=True, on_issue=policy)

    if policy == "raise":
        with pytest.raises(IssuePolicyError) as error:
            fetch()
        assert any(issue.code == "bulk.store_missing" for issue in error.value.issues)
    else:
        if policy == "warn":
            with pytest.warns(RuntimeWarning, match="No compiled observation store exists"):
                result = fetch()
        else:
            result = fetch()
        assert result.data.is_empty()
        assert len(result.outcomes) == 1, "missing local availability must remain inspectable outside observation rows"
        outcome = result.outcomes[0]
        source = selection.series[0]
        assert outcome.series_id == source.series_id
        assert outcome.station_id == station
        assert outcome.product_id == source.product_id
        assert outcome.facts_ids == tuple(facts.facts_id for facts in source.facts)
        assert outcome.status == "unresolved"
        assert "No compiled observation store exists" in outcome.reason
        assert outcome.window.start == datetime(2020, 1, 1)
        assert outcome.window.end == datetime(2020, 1, 1, 23, 59, 59, 999999)
        assert outcome.retrieved_at is None
        assert outcome.calls == ()
        assert rr.series(result)["outcomes"].to_list()[0]
        assert any(issue.code == "bulk.store_missing" for issue in result.issues)
        assert result.provenance.calls_made == ()
        assert result.provenance.served_intervals == ()
        assert result.receipts.entries == ()
    assert list(tmp_path.iterdir()) == []
