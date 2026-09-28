"""Acquisition identity and overlapping transaction composition through the driver."""

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    ObservationRequest,
    RequestedWindow,
    SourceAcquisition,
    SourceCoordinates,
    WindowEndpoint,
    WithIssues,
)
from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.cz_chmi.declaration import declaration
from rivretrieve._internal.providers.cz_chmi.parse import parse
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.store import StoreReader, StoreRoot
from tests.test_chmi_source_boundary_isolation import _payload


def single_payload():
    payload = _payload()
    return replace(
        payload,
        station_products=(("0-203-1-000400", ProductId("discharge_daily_mean")),),
        source_coordinates=SourceCoordinates(replace(payload.source_coordinates.value, ts_con_ids=("QD",))),
    )


def run(store, payloads):
    stages = declaration.observations.stages
    provider = SimpleNamespace(
        config=stages.config,
        window_declarations=stages.window_declarations,
        fetch=lambda *args, **kwargs: payloads if isinstance(payloads, SourceAcquisition) else WithIssues(payloads),
        parse=parse,
    )
    return drive(
        ObservationRequest(
            ProviderId("cz_chmi"),
            ("0-203-1-000400",),
            (ProductId("discharge_daily_mean"),),
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2023, 6, 1)), WindowEndpoint.from_datetime(datetime(2023, 6, 2))
            ),
        ),
        provider,
        provenance=ObservationProvenance(source="CHMI", provider_id=ProviderId("cz_chmi")),
        cache="refresh",
        store=StoreRoot(store),
        receipts=ReceiptMode.INCLUDE,
    )


@pytest.mark.parametrize("failed_first", [False, True])
def test_overlapping_failure_fallback_is_order_independent(tmp_path, failed_first):
    payload = single_payload()
    held = run(tmp_path / "store", (payload,))
    failed = replace(payload, content=b"{}", acquisition_id="failed")
    fresh = replace(payload, acquisition_id="fresh")
    result = run(tmp_path / "store", (failed, fresh) if failed_first else (fresh, failed))
    assert_frame_equal(result.canonical_rows, held.canonical_rows)
    manifest = StoreReader().status(StoreRoot(tmp_path / "store"), ProviderId("cz_chmi")).manifest
    assert len(manifest.coverage) == 1
    assert manifest.coverage[0].outcome_id == held.outcomes[0].outcome_id
    assert any(item.status is OutcomeStatus.UNSUPPORTED for item in result.outcomes)


def test_equal_failed_bytes_and_timestamps_keep_distinct_calls_and_inventories(tmp_path):
    payload = replace(single_payload(), content=b"{}")
    result = run(
        tmp_path / "store", (replace(payload, acquisition_id="first"), replace(payload, acquisition_id="second"))
    )
    unsupported = [item for item in result.outcomes if item.status is OutcomeStatus.UNSUPPORTED]
    assert len(unsupported) == 2
    assert {item.calls for item in unsupported} == {("first",), ("second",)}
    assert len(result.receipts.entries) == 2
    assert len([item for item in result.inventories if item.origin == "response"]) == 2
    assert {item["call_id"] for item in result.provenance.calls_made} == {"first", "second"}


def test_unknown_series_failed_request_keeps_call_and_interval(tmp_path):
    from rivretrieve._internal.source_acquisition import FailedSourceRequest, SourceRequestTarget
    from rivretrieve._internal.source_series import SeriesWindow
    from rivretrieve._internal.transport import HttpMethod, TransportFailure, TransportFailureReason, TransportRequest

    request = TransportRequest(HttpMethod.GET, "https://example.test/observations")
    event = FailedSourceRequest(
        "unknown-failure",
        SourceRequestTarget("0-203-1-000400", "discharge_daily_mean"),
        SeriesWindow(start=datetime(2023, 6, 1), end=datetime(2023, 6, 2)),
        request,
        TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503),
    )
    result = run(tmp_path / "store", SourceAcquisition((), failed_requests=(event,)))
    assert result.canonical_rows.is_empty()
    assert result.outcomes[0].series_id is None
    assert result.outcomes[0].calls == ("unknown-failure",)
    assert result.provenance.calls_made[0]["status_code"] == 503
