"""Authored cursor chains distinguish partial observations from exhaustive coverage."""

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
from rivretrieve._internal.store import StoreRoot
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
def test_incomplete_cursor_retains_rows_and_bytes_but_retries_uncovered_window(tmp_path, late):
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
    assert partial.canonical_rows.height == 1
    assert [entry.content for entry in partial.receipts.entries] == (
        [page(NEXT)] if late == "fail" else [page(NEXT), late]
    )
    unresolved = next(outcome for outcome in partial.outcomes if outcome.status is OutcomeStatus.UNRESOLVED)
    assert len(unresolved.calls) == 2
    assert set(unresolved.calls).issubset({call["call_id"] for call in partial.provenance.calls_made})
    assert any(issue.severity == "error" for issue in partial.issues)
    complete = run()
    assert len(transport.requests) == 3
    assert complete.canonical_rows.height == 1
