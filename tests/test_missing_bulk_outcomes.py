"""Missing compiled stores remain identified local failures, never empty successes."""

from datetime import datetime
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.issues import IssuePolicyError

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


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


@pytest.mark.parametrize("members", ["mixed", "unknown_only"])
@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_missing_bulk_store_accounts_for_every_explicit_selector_without_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, members: str, policy: str
):
    import polars as pl

    from rivretrieve._internal import registry
    from rivretrieve._internal.source_series import OutcomeStatus, RequestedSelector

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    calls = []

    class NoNetwork:
        def send(self, request):
            calls.append(request)
            pytest.fail("A missing compiled store cannot trigger observation or download calls")

    monkeypatch.setattr(discovery, "HttpClient", NoNetwork)
    monkeypatch.setattr(rr, "download", lambda *args, **kwargs: pytest.fail("No implicit download"))
    monkeypatch.setattr(registry, "drive_store", lambda *args, **kwargs: pytest.fail("No compiled store to scan"))
    selection = rr.find(provider="ca_eccc", station="02GA010", quantity="stage")
    known = selection.series[0]
    unknown_id = "unpublished-requested-series"
    identifiers = (known.series_id, unknown_id) if members == "mixed" else (unknown_id,)
    restricted = rr.pick(selection, series_id=identifiers, on_issue="ignore")

    def fetch():
        return rr.fetch(restricted, start="2020-01-01", end="2020-01-01", receipts=True, on_issue=policy)

    if policy == "raise":
        with pytest.raises(IssuePolicyError) as caught:
            fetch()
        issues = caught.value.issues
    else:
        if policy == "warn":
            with pytest.warns(RuntimeWarning) as reported:
                result = fetch()
            assert any("No compiled observation store exists" in str(item.message) for item in reported)
            assert any("requested series_id" in str(item.message) for item in reported)
        else:
            result = fetch()
        issues = result.issues
        assert result.data.is_empty()
        assert result.provenance.calls_made == ()
        assert result.provenance.served_intervals == ()
        assert result.receipts.entries == ()
        assert result.scope == restricted.scope
        concrete = [outcome for outcome in result.outcomes if outcome.series_id is not None]
        assert len(concrete) == (1 if members == "mixed" else 0)
        if concrete:
            assert concrete[0].series_id == known.series_id
            assert concrete[0].facts_ids == tuple(fact.facts_id for fact in known.facts)
            assert next(item for item in result.source_series if item.series_id == known.series_id) == known
        requested = [outcome for outcome in result.outcomes if outcome.requested_selector is not None]
        assert len(requested) == 1
        assert requested[0].requested_selector == RequestedSelector(kind="series_id", value=unknown_id)
        assert requested[0].series_id is None
        assert requested[0].facts_ids == ()
        assert requested[0].window.start == datetime(2020, 1, 1)
        assert requested[0].window.end == datetime(2020, 1, 1, 23, 59, 59, 999999)
        assert len(result.outcomes) == len(concrete) + len(requested)
        assert all(outcome.status is OutcomeStatus.UNRESOLVED and outcome.reason for outcome in result.outcomes)
        assert all(outcome.retrieved_at is None and outcome.calls == () for outcome in result.outcomes)
        inspected = rr.series(result).filter(pl.col("requested_selector_value") == unknown_id)
        assert inspected.height == 1
        assert inspected["requested_selector_kind"].item() == "series_id"
        assert inspected["series_id"].item() is None
        assert inspected["published_id"].item() is None
        assert inspected["outcomes"].to_list() == [["unresolved"]]
    assert any(issue.code == "bulk.store_missing" for issue in issues)
    diagnostics = [issue for issue in issues if issue.code == "source.inventory_unresolved"]
    assert len(diagnostics) == 1
    assert diagnostics[0].details["requested_selector"] == {"kind": "series_id", "value": unknown_id}
    assert calls == []
    assert list(tmp_path.iterdir()) == []
