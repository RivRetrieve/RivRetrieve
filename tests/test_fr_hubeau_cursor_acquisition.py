"""Authored cursor chains preserve receipts without accepting failed observation scopes."""

import json
from datetime import UTC, datetime

import pytest

from rivretrieve._internal import engine
from rivretrieve._internal.driver import drive
from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.fr_hubeau.config import config, window_declarations
from rivretrieve._internal.providers.fr_hubeau.fetch import fetch
from rivretrieve._internal.providers.fr_hubeau.parse import parse
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.store import StoreReader, StoreRoot
from rivretrieve._internal.transport import TransportFailure, TransportFailureReason, TransportResponse

PRODUCT = ProductId("discharge_daily_mean")
STATION = "1011000101"
NEXT = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab?page=2"


def page(next_url=None):
    return json.dumps(
        {
            "data": [
                {
                    "code_station": STATION,
                    "grandeur_hydro_elab": "QmnJ",
                    "date_obs_elab": "2000-01-01",
                    "resultat_obs_elab": 12,
                }
            ],
            "next": next_url,
        }
    ).encode()


class Transport:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        content = next(self.responses)
        if content == "fail":
            raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
        return TransportResponse(
            content, 200, datetime(2026, 9, 28, tzinfo=UTC), "application/json", request.url, request.params or {}
        )


@pytest.mark.parametrize(
    "late",
    [
        "fail",
        b"{}",
        json.dumps({"data": [], "next": NEXT}).encode(),
        json.dumps({"data": [], "next": "https://outside.example/"}).encode(),
    ],
)
def test_incomplete_cursor_refuses_rows_retains_bytes_and_retries_uncovered_window(tmp_path, late):
    class Stages:
        config = config()
        window_declarations = window_declarations()
        fetch = staticmethod(fetch)
        parse = staticmethod(parse)

    request = engine.ObservationRequest(
        ProviderId("fr_hubeau"),
        (STATION,),
        (PRODUCT,),
        engine.RequestedWindow(
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 1)),
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 2)),
        ),
    )
    transport = Transport(page(NEXT), late, page())
    store = StoreRoot(tmp_path / "store")

    def run():
        return drive(
            request,
            Stages(),
            transport=transport,
            cache="reuse",
            receipts=ReceiptMode.INCLUDE,
            store=store,
            provenance=ObservationProvenance(source="Hub Eau", provider_id=ProviderId("fr_hubeau")),
        )

    partial = run()
    # The acquisition declares this concrete series unresolved over its full
    # window. The result cannot accept page rows that persistence must refuse.
    assert partial.canonical_rows.is_empty()
    manifest = StoreReader().status(store, ProviderId("fr_hubeau")).manifest
    assert manifest.coverage == ()
    assert not list(store.rglob("*.parquet"))
    assert [entry.content for entry in partial.receipts.entries] == (
        [page(NEXT)] if late == "fail" else [page(NEXT), late]
    )
    unresolved = next(outcome for outcome in partial.outcomes if outcome.status is OutcomeStatus.UNRESOLVED)
    definition = next(item for item in partial.source_series if item.series_id == unresolved.series_id)
    assert unresolved.facts_ids == tuple(item.facts_id for item in definition.facts)
    assert unresolved.window.start == datetime(1999, 12, 30)
    assert unresolved.window.end == datetime(2000, 1, 4, 23, 59, 59, 999999)
    assert len(unresolved.calls) == 2
    assert set(unresolved.calls).issubset({call["call_id"] for call in partial.provenance.calls_made})
    assert any(issue.severity == "error" for issue in partial.issues)
    complete = run()
    assert len(transport.requests) == 3
    assert complete.canonical_rows.height == 1


def test_incomplete_hubeau_cursor_links_actual_http_retry_attempts():
    from tests.test_transport_attempt_evidence import client_for

    client, _ = client_for([(page(NEXT), 200, "application/json"), *[(b"unavailable", 503, "text/plain")] * 3])
    bounds = engine._make_fetch_window(
        engine.WindowEndpoint.from_datetime(datetime(2000, 1, 1)),
        engine.WindowEndpoint.from_datetime(datetime(2000, 1, 2)),
    )
    result = fetch(
        (STATION,),
        (PRODUCT,),
        {PRODUCT: (engine.RenderedWindow("2000-01-01", "2000-01-02"),)},
        bounds,
        config(),
        client,
    )
    expected = tuple(item.attempt_id for item in result.value[0].attempt_traces) + tuple(
        item.attempt_id for item in result.failed_requests[0].failure.attempt_traces
    )
    unresolved = next(item for item in result.outcomes if item.status is OutcomeStatus.UNRESOLVED)
    assert unresolved.calls == expected
    assert len(expected) == 4


@pytest.mark.parametrize(
    ("product", "station", "expected_url", "expected_params", "next_url", "page1_row", "page2_row"),
    [
        (
            ProductId("discharge_daily_mean"),
            STATION,
            "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab",
            {
                "code_entite": STATION,
                "date_debut_obs_elab": "2000-01-01",
                "date_fin_obs_elab": "2000-01-02",
                "grandeur_hydro_elab": "QmnJ",
                "size": 2500,
            },
            "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab?cursor=page2&size=2500",
            {
                "code_station": STATION,
                "grandeur_hydro_elab": "QmnJ",
                "date_obs_elab": "2000-01-01",
                "resultat_obs_elab": 12,
            },
            {
                "code_station": STATION,
                "grandeur_hydro_elab": "QmnJ",
                "date_obs_elab": "2000-01-02",
                "resultat_obs_elab": 14,
            },
        ),
        (
            ProductId("water_temperature_reported"),
            "01001336",
            "https://hubeau.eaufrance.fr/api/v1/temperature/chronique",
            {
                "code_station": "01001336",
                "date_debut_mesure": "2008-07-09",
                "date_fin_mesure": "2008-07-10",
                "size": 2500,
            },
            "https://hubeau.eaufrance.fr/api/v1/temperature/chronique?page=2&size=2500",
            {
                "code_station": "01001336",
                "code_parametre": "1301",
                "code_unite": "27",
                "symbole_unite": "°C",
                "date_mesure_temp": "2008-07-09",
                "heure_mesure_temp": "11:00:00",
                "resultat": 14.2,
            },
            {
                "code_station": "01001336",
                "code_parametre": "1301",
                "code_unite": "27",
                "symbole_unite": "°C",
                "date_mesure_temp": "2008-07-09",
                "heure_mesure_temp": "12:00:00",
                "resultat": 14.5,
            },
        ),
    ],
)
def test_hubeau_fetch_requests_page_size_2500_and_follows_next_without_original_params(
    product, station, expected_url, expected_params, next_url, page1_row, page2_row
):
    first_body = json.dumps({"data": [page1_row], "next": next_url}).encode()
    second_body = json.dumps({"data": [page2_row], "next": None}).encode()
    transport = Transport(first_body, second_body)
    start = expected_params.get("date_debut_obs_elab") or expected_params["date_debut_mesure"]
    stop = expected_params.get("date_fin_obs_elab") or expected_params["date_fin_mesure"]
    bounds = engine._make_fetch_window(
        engine.WindowEndpoint.from_datetime(datetime.fromisoformat(start)),
        engine.WindowEndpoint.from_datetime(datetime.fromisoformat(stop)),
    )
    result = fetch(
        (station,),
        (product,),
        {product: (engine.RenderedWindow(start, stop),)},
        bounds,
        config(),
        transport,
    )
    assert not result.failed_requests
    assert not result.issues
    assert len(result.value) == 2
    assert len(transport.requests) == 2
    assert transport.requests[0].url == expected_url
    assert dict(transport.requests[0].params or {}) == expected_params
    assert transport.requests[1].url == next_url
    assert transport.requests[1].params is None
