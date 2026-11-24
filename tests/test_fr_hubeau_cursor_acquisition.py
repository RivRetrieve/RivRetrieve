"""Authored cursor chains preserve receipts without accepting failed observation scopes."""

import json
from dataclasses import replace
from datetime import UTC, datetime

import polars.testing as pt
import pytest

from rivretrieve._internal import engine
from rivretrieve._internal.driver import drive
from rivretrieve._internal.observations import ObservationProvenance, ReceiptAuthorship, ReceiptMode
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


@pytest.mark.parametrize(
    ("product", "station", "rows_per_page", "next_prefix"),
    [
        (
            ProductId("discharge_daily_mean"),
            STATION,
            [
                [
                    {
                        "code_station": STATION,
                        "grandeur_hydro_elab": "QmnJ",
                        "date_obs_elab": f"2000-01-0{day}",
                        "resultat_obs_elab": 10.0 + day,
                        "code_statut": 16,
                        "libelle_statut": "Validée",
                    }
                ]
                for day in (1, 2, 3)
            ],
            "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab?cursor=p",
        ),
        (
            ProductId("water_temperature_reported"),
            "01001336",
            [
                [
                    {
                        "code_station": "01001336",
                        "code_parametre": "1301",
                        "code_unite": "27",
                        "symbole_unite": "°C",
                        "date_mesure_temp": f"2000-01-0{day}",
                        "heure_mesure_temp": "12:00:00",
                        "resultat": 8.0 + day,
                        "code_qualification": "1",
                        "libelle_qualification": "Bonne",
                    }
                ]
                for day in (1, 2, 3)
            ],
            "https://hubeau.eaufrance.fr/api/v1/temperature/chronique?page=",
        ),
    ],
)
def test_hubeau_paginated_retrieval_decodes_each_page_once_and_skips_driver_parse(
    monkeypatch, product, station, rows_per_page, next_prefix
):
    import rivretrieve._internal.providers.fr_hubeau.parse as hubeau_parse

    pages = [
        json.dumps(
            {
                "data": rows,
                "next": f"{next_prefix}{idx + 2}" if idx < len(rows_per_page) - 1 else None,
            }
        ).encode()
        for idx, rows in enumerate(rows_per_page)
    ]

    driver_parse_calls = 0
    json_loads_calls = 0
    real_loads = hubeau_parse.json.loads

    def counted_loads(*args, **kwargs):
        nonlocal json_loads_calls
        json_loads_calls += 1
        return real_loads(*args, **kwargs)

    monkeypatch.setattr(hubeau_parse.json, "loads", counted_loads)

    class ReusedStages:
        config = config()
        window_declarations = window_declarations()
        fetch = staticmethod(fetch)

        @staticmethod
        def parse(payload, provider_config):
            nonlocal driver_parse_calls
            driver_parse_calls += 1
            return parse(payload, provider_config)

    class BaselineStages:
        config = config()
        window_declarations = window_declarations()

        @staticmethod
        def fetch(*args, **kwargs):
            return replace(fetch(*args, **kwargs), interpretations=())

        parse = staticmethod(parse)

    request = engine.ObservationRequest(
        ProviderId("fr_hubeau"),
        (station,),
        (product,),
        engine.RequestedWindow(
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 1)),
            engine.WindowEndpoint.from_datetime(datetime(2000, 1, 3, 23, 59, 59, 999999)),
        ),
    )
    provenance = ObservationProvenance(source="Hub Eau", provider_id=ProviderId("fr_hubeau"))

    reused = drive(
        request,
        ReusedStages(),
        transport=Transport(*pages),
        receipts=ReceiptMode.INCLUDE,
        provenance=provenance,
    )
    assert driver_parse_calls == 0
    assert json_loads_calls == 3

    baseline = drive(
        request,
        BaselineStages(),
        transport=Transport(*pages),
        receipts=ReceiptMode.INCLUDE,
        provenance=provenance,
    )
    pt.assert_frame_equal(reused.canonical_rows, baseline.canonical_rows)
    assert [
        (
            o.series_id,
            o.station_id,
            o.product_id,
            o.window,
            o.status,
            o.facts_ids,
            o.reason,
            o.retrieved_at,
            len(o.calls),
        )
        for o in reused.outcomes
    ] == [
        (
            o.series_id,
            o.station_id,
            o.product_id,
            o.window,
            o.status,
            o.facts_ids,
            o.reason,
            o.retrieved_at,
            len(o.calls),
        )
        for o in baseline.outcomes
    ]
    assert [
        (i.scope, i.members, i.member_facts, i.completeness, i.access, i.origin, i.window, i.reason)
        for i in reused.inventories
    ] == [
        (i.scope, i.members, i.member_facts, i.completeness, i.access, i.origin, i.window, i.reason)
        for i in baseline.inventories
    ]
    assert reused.source_series == baseline.source_series
    assert reused.issues == baseline.issues
    assert [e.content for e in reused.receipts.entries] == [e.content for e in baseline.receipts.entries]
    assert reused.annotations.observation_tables.keys() == baseline.annotations.observation_tables.keys()
    for schema_id, table in reused.annotations.observation_tables.items():
        pt.assert_frame_equal(table.rows, baseline.annotations.observation_tables[schema_id].rows)


@pytest.mark.parametrize("late_failure", ["http_503", "cursor_cycle"])
def test_hubeau_refresh_retains_held_data_and_original_retrieved_at_on_late_failure_or_cycle(tmp_path, late_failure):
    old_time = datetime(2026, 9, 20, tzinfo=UTC)
    new_time = datetime(2026, 9, 25, tzinfo=UTC)

    class DatedTransport(Transport):
        def __init__(self, instant, *responses):
            super().__init__(*responses)
            self.instant = instant

        def send(self, request):
            self.requests.append(request)
            content = next(self.responses)
            if content == "fail":
                raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
            return TransportResponse(content, 200, self.instant, "application/json", request.url, request.params or {})

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
    store = StoreRoot(tmp_path / "store")
    provenance = ObservationProvenance(source="Hub Eau", provider_id=ProviderId("fr_hubeau"))

    seed = drive(
        request,
        Stages(),
        transport=DatedTransport(old_time, page()),
        cache="reuse",
        store=store,
        provenance=provenance,
    )
    assert seed.canonical_rows.height == 1

    fresh_page1 = json.dumps(
        {
            "data": [
                {
                    "code_station": STATION,
                    "grandeur_hydro_elab": "QmnJ",
                    "date_obs_elab": "2000-01-01",
                    "resultat_obs_elab": 99.0,
                }
            ],
            "next": NEXT,
        }
    ).encode()
    fresh_page2 = "fail" if late_failure == "http_503" else json.dumps({"data": [], "next": NEXT}).encode()

    refreshed = drive(
        request,
        Stages(),
        transport=DatedTransport(new_time, fresh_page1, fresh_page2),
        cache="refresh",
        receipts=ReceiptMode.INCLUDE,
        store=store,
        provenance=provenance,
    )

    pt.assert_frame_equal(refreshed.canonical_rows, seed.canonical_rows)
    assert refreshed.provenance.served_intervals
    assert all(interval.retrieved_at == old_time for interval in refreshed.provenance.served_intervals)
    manifest = StoreReader().status(store, ProviderId("fr_hubeau")).manifest
    assert {item.retrieved_at for item in manifest.coverage} == {old_time}
    unresolved = next(outcome for outcome in refreshed.outcomes if outcome.status is OutcomeStatus.UNRESOLVED)
    assert len(unresolved.calls) == 2
    assert set(unresolved.calls).issubset({call["call_id"] for call in refreshed.provenance.calls_made})
    if late_failure == "cursor_cycle":
        assert "cycle" in (unresolved.reason or "")
        assert any(issue.code == "source.acquisition_incomplete" for issue in refreshed.issues)
    else:
        assert any(issue.code == "source.request_failed" for issue in refreshed.issues)
    assert len(refreshed.receipts.entries) == (1 if late_failure == "http_503" else 2) + 1
    assert refreshed.receipts.entries[0].authorship is ReceiptAuthorship.STORE_EXCERPT
    assert all(entry.authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD for entry in refreshed.receipts.entries[1:])
