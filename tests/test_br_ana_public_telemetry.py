"""public ANA retrieval : PackagedCatalogue × Credentials × Recording → ObservationResult.

Observation bytes and boundary literals come from the retained source recording and
independent-expectations.md. The token response below is protocol-only test input.
"""

from datetime import datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.authentication import ExchangeSpec
from rivretrieve._internal.issues import MissingCredentialError
from rivretrieve._internal.observations import ReceiptAuthorship
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.transport import HttpClient, TransportRequest, TransportResponse

_DATA = Path(__file__).parent / "recordings" / "br_ana"
_PRODUCTS = ("discharge_instantaneous", "stage_instantaneous")
_START = "2024-01-01T23:30:00"
_END = "2024-01-02T00:30:00"
_IDENTIFIER = "protocol-identifier-sentinel"
_PASSWORD = "protocol-password-sentinel"
_TOKEN = "protocol-bearer-sentinel"


@pytest.fixture(autouse=True)
def isolated_public_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Never inspect the owner's working-directory .env or local observation cache.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    for name in ("ANA_IDENTIFICADOR", "ANA_SENHA", "NVE_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    def forbidden_client():
        raise AssertionError("offline public tests must inject their transport")

    monkeypatch.setattr(discovery, "HttpClient", forbidden_client)


class _AuthenticatedReplay:
    def __init__(self) -> None:
        self.recording = read_recording(_DATA / "telemetry_15400000_2024-01-04_DIAS_30.recording.json")
        self.replay = ReplayTransport((self.recording,))
        self.exchange_calls = 0
        self.observation_calls = 0

    def send(self, request: TransportRequest) -> TransportResponse:
        if request.url == ExchangeSpec.ana().exchange_url:
            self.exchange_calls += 1

            # Protocol-only credential exchange, never an observation recording.
            def token_sender(request, timeout_seconds):
                assert request.headers["Identificador"] == _IDENTIFIER
                assert request.headers["Senha"] == _PASSWORD
                return b'{"items":{"tokenautenticacao":"protocol-bearer-sentinel"}}', 200, "application/json"

            return HttpClient(sender=token_sender).send(request)
        self.observation_calls += 1
        assert request.headers["Authorization"] == f"Bearer {_TOKEN}"
        assert "Identificador" not in request.headers
        assert "Senha" not in request.headers
        return self.replay.send(request)


def _authenticated_replay(monkeypatch: pytest.MonkeyPatch) -> _AuthenticatedReplay:
    monkeypatch.setenv("ANA_IDENTIFICADOR", _IDENTIFIER)
    monkeypatch.setenv("ANA_SENHA", _PASSWORD)
    transport = _AuthenticatedReplay()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    return transport


def test_public_catalogue_exposes_national_candidates_without_claiming_availability() -> None:
    selection = rr.find(provider="br_ana")
    frame = rr.as_frame(selection).filter(pl.col("product_id").is_in(_PRODUCTS))
    assert set(_PRODUCTS) <= set(rr.products("br_ana"))
    assert frame["station_id"].n_unique() == 17914
    assert frame.height == 17914 * 2
    assert set(frame["product_id"]) == set(_PRODUCTS)
    assert frame["published_record_start_date"].null_count() == frame.height
    assert frame["published_record_end_date"].null_count() == frame.height
    available = frame.filter(pl.col("availability") == "available")
    assert set(available["station_id"]) == {"15400000"}
    assert available.height == 2
    unknown = frame.filter(pl.col("station_id") != "15400000")
    assert set(unknown["availability"]) == {"unknown"}
    station = unknown.item(0, "station_id")
    explicit = rr.find(provider="br_ana", station=station, product="discharge_instantaneous")
    picked = rr.pick(selection, station=station, product="discharge_instantaneous")
    pl_testing.assert_frame_equal(rr.as_frame(explicit), rr.as_frame(picked))
    assert len(explicit.series) == 1
    assert explicit.series[0].availability == "unknown"
    assert selection.acquisition_provenance


def test_public_fetch_requires_both_ana_credentials_before_transport() -> None:
    selection = rr.pick(rr.find(provider="br_ana"), station="15400000", product="discharge_instantaneous")
    access = rr.providers().filter(pl.col("provider_id") == "br_ana").item(0, "access")
    assert access == "missing ANA_IDENTIFICADOR, ANA_SENHA"
    with pytest.raises(MissingCredentialError) as raised:
        rr.fetch(selection, start=_START, end=_END)
    assert raised.value.missing_by_provider == {"br_ana": ("ANA_IDENTIFICADOR", "ANA_SENHA")}


@pytest.mark.parametrize("product", _PRODUCTS)
def test_public_native_midnight_values_receipts_and_provenance(monkeypatch: pytest.MonkeyPatch, product: str) -> None:
    transport = _authenticated_replay(monkeypatch)
    selection = rr.pick(rr.find(provider="br_ana"), station="15400000", product=product)
    result = rr.fetch(selection, start=_START, end=_END, receipts=True, on_issue="ignore")
    data = result.data.sort("time")
    # The independent author supplied these three literals before reading port code.
    assert data.height == 5
    assert data.item(0, "time") == datetime(2024, 1, 1, 23, 30)
    assert data.item(-1, "time") == datetime(2024, 1, 2, 0, 30)
    values = (
        [13841.20, 13841.20, 13863.50, 13885.80, 13885.80]
        if product == "discharge_instantaneous"
        else [7.81, 7.81, 7.82, 7.83, 7.83]
    )
    expected = pl.DataFrame(
        {
            "time": [
                datetime(2024, 1, 1, 23, 30),
                datetime(2024, 1, 1, 23, 45),
                datetime(2024, 1, 2),
                datetime(2024, 1, 2, 0, 15),
                datetime(2024, 1, 2, 0, 30),
            ],
            "time_zone": ["unknown"] * 5,
            "station_id": ["15400000"] * 5,
            "product_id": [product] * 5,
            "value": values,
        }
    )
    pl_testing.assert_frame_equal(data, expected)
    assert transport.exchange_calls == transport.observation_calls == 1
    assert len(result.receipts.entries) == 1
    receipt = result.receipts.entries[0]
    assert receipt.authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD
    assert receipt.content == transport.recording.content
    assert receipt.origin.url == transport.recording.request.url
    assert result.provenance.provider_id == "br_ana"
    assert result.provenance.acquisition_provenance is not None
    assert any(
        call.get("request_parameters") == dict(transport.recording.request.parameters or {})
        for call in result.provenance.calls_made
    )
    assert not any(issue.severity == "error" for issue in result.issues)
    for secret in (_IDENTIFIER, _PASSWORD, _TOKEN):
        assert secret not in repr(result)
        assert secret.encode() not in receipt.content


@pytest.mark.parametrize("product", _PRODUCTS)
def test_public_cache_reuse_needs_no_new_exchange_or_observation(monkeypatch: pytest.MonkeyPatch, product: str) -> None:
    transport = _authenticated_replay(monkeypatch)
    selection = rr.find(provider="br_ana", station="15400000", product=product)
    live = rr.fetch(selection, start=_START, end=_END, cache="reuse", on_issue="ignore")
    assert live.data.height == 5

    # The composition root constructs transport even for a cache hit. Empty exact
    # replay refuses both token exchange and observations if either is attempted.
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(()))
    cached = rr.fetch(selection, start=_START, end=_END, cache="reuse", on_issue="ignore")
    pl_testing.assert_frame_equal(live.data, cached.data)
    assert live.receipts.entries == cached.receipts.entries == ()
    assert cached.provenance.served_intervals
    assert transport.exchange_calls == transport.observation_calls == 1
