"""Publication services declare and access only their own retained products."""

import pytest

from rivretrieve._internal.providers.fr_hubeau.config import config as hubeau_config
from rivretrieve._internal.providers.fr_hydroportail.config import config as hydroportail_config


def test_retained_products_have_independent_publication_services():
    assert set(hubeau_config().products) == {
        "discharge_daily_mean",
        "discharge_daily_max",
        "stage_daily_max",
        "water_temperature_reported",
    }
    assert set(hydroportail_config().products) == {"discharge_instantaneous", "stage_instantaneous"}


@pytest.mark.parametrize("product", ["discharge_instantaneous", "stage_instantaneous"])
def test_hubeau_cannot_route_hydroportail_products(product):
    with pytest.raises(KeyError):
        hubeau_config().products[product]


def test_public_discovery_keeps_overlapping_station_identity_separate():
    import rivretrieve as rr

    station = "1232000101"
    hubeau = rr.find(provider="fr_hubeau", station=station)
    hydroportail = rr.find(provider="fr_hydroportail", station=station)
    assert {item.provider_id for item in hubeau.series} == {"fr_hubeau"}
    assert {item.provider_id for item in hydroportail.series} == {"fr_hydroportail"}
    assert len(hubeau.series) == 3
    assert len(hydroportail.series) == 8
    assert {item.series_id for item in hubeau.series}.isdisjoint(item.series_id for item in hydroportail.series)
    assert rr.series(rr.pick(hydroportail, quantity="discharge")).height == 4
    assert rr.series(rr.find(provider="fr_hubeau", statistic="instantaneous")).is_empty()
    assert rr.series(rr.find(provider="fr_hydroportail", frequency="daily")).is_empty()


@pytest.mark.parametrize(
    "provider,station,predicates,start,end,recording_name,host",
    [
        (
            "fr_hubeau",
            "1011000101",
            {"quantity": "discharge", "frequency": "daily", "statistic": "mean"},
            "2025-01-03",
            "2025-01-03",
            "fr_hubeau_1011000101_QmnJ_padded.recording.json",
            "https://hubeau.eaufrance.fr/",
        ),
        (
            "fr_hydroportail",
            "1232000101",
            {"quantity": "discharge", "statistic": "instantaneous"},
            "2026-06-01",
            "2026-06-02",
            "fr_hydroportail_station_Q_padded.recording.json",
            "https://hydro.eaufrance.fr/",
        ),
    ],
)
def test_public_fetch_receipts_and_exports_preserve_service(
    monkeypatch, provider, station, predicates, start, end, recording_name, host
):
    from pathlib import Path

    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery
    from rivretrieve._internal.recordings import ReplayTransport, read_recording

    recording = read_recording(Path(__file__).parent / "test_data" / recording_name)
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selection = rr.find(provider=provider, station=station, **predicates)
    if provider == "fr_hydroportail":
        selection = rr.pick(selection, variant="raw")
    result = rr.fetch(selection, start=start, end=end, receipts=True, on_issue="raise")
    assert result.provenance.provider_id == provider
    assert result.data.height > 0
    assert result.receipts.entries[0].content == recording.content
    assert all(call["url"].startswith(host) for call in result.provenance.calls_made)
    assert all(item.provider_id == provider for item in result.source_series)
    restored = rr.from_bundle(rr.to_bundle(result))
    assert restored.provenance.provider_id == provider
    assert restored.source_series == result.source_series
    assert restored.receipts == result.receipts


def test_hydroportail_failure_preserves_independent_raw_series(monkeypatch):
    from pathlib import Path

    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery
    from rivretrieve._internal.recordings import ReplayTransport, read_recording
    from rivretrieve._internal.transport import TransportFailure, TransportFailureReason

    recording = read_recording(Path(__file__).parent / "test_data/fr_hydroportail_station_Q_padded.recording.json")
    replay = ReplayTransport((recording,))
    requests = []

    class SourceFailure:
        def send(self, request):
            requests.append(request)
            if request.params["hydro_series[simpleAndInterpolatedAndHourlyVariable]"] == "H":
                raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
            return replay.send(request)

    monkeypatch.setattr(discovery, "HttpClient", SourceFailure)
    selection = rr.pick(rr.find(provider="fr_hydroportail", station="1232000101"), variant="raw")
    result = rr.fetch(selection, start="2026-06-01", end="2026-06-02", receipts=True, on_issue="ignore")
    assert result.data.height == 282
    assert set(result.data["product_id"]) == {"discharge_instantaneous"}
    assert result.issues
    assert all(issue.provider_id == "fr_hydroportail" for issue in result.issues)
    assert {outcome.status for outcome in result.outcomes} == {"success", "failed"}
    assert all(request.url.startswith("https://hydro.eaufrance.fr/") for request in requests)
    assert result.receipts.entries[0].content == recording.content
