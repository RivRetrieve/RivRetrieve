"""public ANA retrieval : PackagedCatalogue × Credentials × Recording → ObservationResult.

Observation bytes come from retained exact modern monthly recordings. The token response below is protocol-only test input.
"""

import json
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

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_DATA = Path(__file__).parent / "recordings" / "br_ana"
_PRODUCTS = (
    "discharge_daily_mean_bruto",
    "discharge_daily_mean_consistido",
    "stage_daily_mean_bruto",
    "stage_daily_mean_consistido",
)
_START = "2020-01-10"
_END = "2020-01-20"
_IDENTIFIER = "protocol-identifier-sentinel"
_PASSWORD = "protocol-password-sentinel"
_TOKEN = "protocol-bearer-sentinel"


def _selection(product: str):
    quantity = "stage" if product.startswith("stage") else "discharge"
    variant = "bruto" if product.endswith("bruto") else "consistido"
    return rr.pick(
        rr.find(provider="br_ana", station="15400000", quantity=quantity, frequency="daily", statistic="mean"),
        variant=variant,
    )


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
    def __init__(self, product: str) -> None:
        endpoint = "HidroSerieCotas" if product.startswith("stage") else "HidroSerieVazao"
        month = "2024-01" if product == "discharge_daily_mean_bruto" else "2020-01"
        self.recording = read_recording(_DATA / f"{endpoint}_15400000_{month}-01_{month}-31.recording.json")
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


def _authenticated_replay(monkeypatch: pytest.MonkeyPatch, product: str) -> _AuthenticatedReplay:
    monkeypatch.setenv("ANA_IDENTIFICADOR", _IDENTIFIER)
    monkeypatch.setenv("ANA_SENHA", _PASSWORD)
    transport = _AuthenticatedReplay(product)
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    return transport


@pytest.mark.parametrize("product", _PRODUCTS)
def test_public_daily_requires_credentials_before_transport(product: str) -> None:
    selection = _selection(product)
    with pytest.raises(MissingCredentialError) as raised:
        rr.fetch(selection, start=_START, end=_END)
    assert raised.value.missing_by_provider == {"br_ana": ("ANA_IDENTIFICADOR", "ANA_SENHA")}


@pytest.mark.parametrize("product", _PRODUCTS)
def test_public_daily_authenticated_receipt_and_cache_roundtrip(monkeypatch: pytest.MonkeyPatch, product: str) -> None:
    transport = _authenticated_replay(monkeypatch, product)
    year = 2024 if product == "discharge_daily_mean_bruto" else 2020
    start, end = f"{year}-01-10", f"{year}-01-20"
    selection = _selection(product)
    assert len(selection.series) == 1
    facts = selection.series[0].facts[0]
    assert facts.label_time == "00:00"
    assert facts.timestamp_anchor.value is None
    assert facts.timestamp_anchor.evidence == ()
    live = rr.fetch(selection, start=start, end=end, cache="reuse", receipts=True, on_issue="ignore")
    assert transport.exchange_calls == 1
    assert transport.observation_calls == sum(
        call.get("url") == transport.recording.request.url for call in live.provenance.calls_made
    )
    assert transport.observation_calls >= 1
    # Interior cell fidelity uses modern source bytes, never SOAP precision or port output.
    prefix = "Cota" if product.startswith("stage") else "Vazao"
    level_field = "nivelconsistencia" if prefix == "Cota" else "Nivel_Consistencia"
    level = "1" if product.endswith("bruto") else "2"
    expected_rows = []
    for row in json.loads(transport.recording.content)["items"]:
        if row["Mediadiaria"] == "1" and row[level_field] == level:
            raw = row[f"{prefix}_15"]
            value = None if raw is None or not raw.strip() else float(raw)
            if value is not None and prefix == "Cota":
                value /= 100
            expected_rows.append((datetime(year, 1, 15), "unknown", "15400000", product, value))
    expected = pl.DataFrame(
        expected_rows,
        schema={name: live.data.schema[name] for name in ("time", "time_zone", "station_id", "product_id", "value")},
        orient="row",
    )
    pl_testing.assert_frame_equal(
        live.data.filter(pl.col("time") == datetime(year, 1, 15)).select(expected.columns), expected
    )
    receipt = live.receipts.entries[0]
    assert receipt.authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD
    assert receipt.content == transport.recording.content
    assert receipt.origin.url == transport.recording.request.url
    assert live.provenance.acquisition_provenance is not None
    assert any(
        call.get("request_parameters") == dict(transport.recording.request.parameters or {})
        for call in live.provenance.calls_made
    )
    assert not any(issue.severity == "error" for issue in live.issues)
    for secret in (_IDENTIFIER, _PASSWORD, _TOKEN):
        assert secret not in repr(live)
        assert secret.encode() not in receipt.content
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(()))
    cached = rr.fetch(selection, start=start, end=end, cache="reuse", receipts=True, on_issue="ignore")
    pl_testing.assert_frame_equal(live.data, cached.data)
    assert cached.provenance.served_intervals
    assert all(entry.authorship is ReceiptAuthorship.STORE_EXCERPT for entry in cached.receipts.entries)
    unasked = rr.fetch(selection, start=start, end=end, cache="reuse", on_issue="ignore")
    assert unasked.receipts.entries == ()


def test_public_daily_credential_rejection_is_safe(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    monkeypatch.setenv("ANA_IDENTIFICADOR", _IDENTIFIER)
    monkeypatch.setenv("ANA_SENHA", _PASSWORD)

    def rejected_sender(request, timeout_seconds):
        return b"Unauthorized", 401, "text/plain"

    monkeypatch.setattr(discovery, "HttpClient", lambda: HttpClient(sender=rejected_sender))
    selection = _selection("stage_daily_mean_bruto")
    result = rr.fetch(selection, start=_START, end=_END, receipts=True, on_issue="ignore")
    assert result.data.is_empty()
    assert any(issue.severity == "error" for issue in result.issues)
    assert result.receipts.entries == ()
    for secret in (_IDENTIFIER, _PASSWORD, _TOKEN):
        assert secret not in repr(result) + caplog.text


def test_daily_subset_cache_cannot_answer_all_and_refresh_preserves_sibling(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _authenticated_replay(monkeypatch, "stage_daily_mean_bruto")
    selection = rr.find(provider="br_ana", station="15400000", quantity="stage", frequency="daily", statistic="mean")
    bruto = rr.pick(selection, variant="bruto")
    consistido = rr.pick(selection, variant="consistido")
    first = rr.fetch(bruto, start=_START, end=_END, cache="reuse", on_issue="ignore")
    assert first.data.height == 11
    calls = transport.observation_calls
    both = rr.fetch(selection, start=_START, end=_END, cache="reuse", receipts=True, on_issue="ignore")
    assert transport.observation_calls > calls
    assert both.data.height == 22
    assert both.data["series_id"].n_unique() == 2
    assert all(entry.authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD for entry in both.receipts.entries)
    sibling = rr.pick(both, variant="consistido")
    refreshed = rr.fetch(bruto, start=_START, end=_END, cache="refresh", on_issue="ignore")
    pl_testing.assert_frame_equal(refreshed.data, first.data)
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(()))
    held = rr.fetch(consistido, start=_START, end=_END, cache="reuse", receipts=True, on_issue="ignore")
    pl_testing.assert_frame_equal(held.data, sibling.data)
    assert held.provenance.served_intervals
    assert all(entry.authorship is ReceiptAuthorship.STORE_EXCERPT for entry in held.receipts.entries)
    restored = rr.from_bundle(rr.to_bundle(held))
    pl_testing.assert_frame_equal(restored.data, held.data)
    assert restored.source_series == held.source_series
    assert restored.inventories == held.inventories


def test_unobserved_daily_sibling_is_unresolved_not_successful_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _authenticated_replay(monkeypatch, "discharge_daily_mean_bruto")
    selection = rr.find(
        provider="br_ana", station="15400000", quantity="discharge", frequency="daily", statistic="mean"
    )
    # This exact January 2024 response contains only Bruto daily means.
    both = rr.fetch(selection, start="2024-01-10", end="2024-01-20", cache="reuse", on_issue="ignore")
    assert {item.variant for item in both.source_series if item.series_id in both.data["series_id"]} == {"bruto"}
    unresolved = [item for item in both.outcomes if item.status.value == "unresolved"]
    assert unresolved
    assert any(item.code == "source.unresolved_inventory" for item in both.issues)
    calls = transport.observation_calls
    repeated = rr.fetch(selection, start="2024-01-10", end="2024-01-20", cache="reuse", on_issue="ignore")
    assert transport.observation_calls > calls
    assert any(item.status.value == "unresolved" for item in repeated.outcomes)
    pl_testing.assert_frame_equal(repeated.data, both.data)
