"""Acquisition identity and overlapping transaction composition through the driver."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import polars as pl
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
    _make_fetch_window,
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


@pytest.mark.parametrize("failed_first", [False, True])
@pytest.mark.parametrize("failure_kind", ["unknown", "partial"])
def test_failed_overlap_returned_rows_agree_with_persisted_replacement(tmp_path, failed_first, failure_kind):
    from rivretrieve._internal.source_acquisition import FailedSourceRequest, SourceRequestTarget
    from rivretrieve._internal.source_series import SeriesWindow
    from rivretrieve._internal.transport import HttpMethod, TransportFailure, TransportFailureReason, TransportRequest

    payload = single_payload()
    store = tmp_path / "store"
    held = run(store, (payload,))
    document = json.loads(payload.content)
    for member in document["tsList"]:
        for row in member["tsData"]["data"]["values"]:
            row[1] = 999
    fresh = replace(payload, content=json.dumps(document).encode(), acquisition_id="new-values")
    if failure_kind == "unknown":
        request = TransportRequest(HttpMethod.GET, "https://example.test/observations")
        event = FailedSourceRequest(
            "unknown-failure",
            SourceRequestTarget("0-203-1-000400", "discharge_daily_mean"),
            SeriesWindow(start=datetime(2023, 6, 1), end=datetime(2023, 6, 2, 23, 59, 59, 999999)),
            request,
            TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503),
        )
        acquired = SourceAcquisition((fresh,), failed_requests=(event,))
        expected = held.canonical_rows
    else:
        failed = replace(
            payload,
            content=b"{}",
            acquisition_id="failed-subinterval",
            fetch_window=_make_fetch_window(
                WindowEndpoint.from_datetime(datetime(2023, 6, 2)),
                WindowEndpoint.from_datetime(datetime(2023, 6, 2, 23, 59, 59, 999999)),
            ),
        )
        acquired = (failed, fresh) if failed_first else (fresh, failed)
        expected = held.canonical_rows.with_columns(
            pl.when(pl.col("time").dt.day() == 1).then(999.0).otherwise(pl.col("value")).alias("value")
        )
    result = run(store, acquired)
    assert_frame_equal(result.canonical_rows.sort("time"), expected.sort("time"))
    persisted = pl.concat([pl.read_parquet(path) for path in store.rglob("*.parquet")])
    assert_frame_equal(persisted.select("time", "value").sort("time"), expected.select("time", "value").sort("time"))


@pytest.mark.parametrize("overlap", [False, True])
def test_snapshot_contributions_keep_distinct_key_groups_and_acquisition_vintages(tmp_path, monkeypatch, overlap):
    from rivretrieve._internal.issues import FatalContractError

    original_parse = parse

    def snapshot_parse(payload, config):
        parsed = original_parse(payload, config)
        day = 1 if payload.acquisition_id == "first" or overlap else 2
        return replace(
            parsed,
            rows=parsed.rows.filter(pl.col("time").dt.day() == day),
            outcomes=tuple(item.model_copy(update={"coverage": "observations"}) for item in parsed.outcomes),
        )

    monkeypatch.setattr("tests.test_acquisition_composition.parse", snapshot_parse)
    payload = single_payload()
    first_time = datetime(2026, 9, 28, tzinfo=UTC)
    second_time = datetime(2026, 9, 29, tzinfo=UTC)
    payloads = (
        replace(payload, acquisition_id="first", origin=replace(payload.origin, retrieved_at=first_time)),
        replace(payload, acquisition_id="second", origin=replace(payload.origin, retrieved_at=second_time)),
    )
    if overlap:
        with pytest.raises(FatalContractError, match="Independent snapshot acquisitions overlap"):
            run(tmp_path / "store", payloads)
        return
    result = run(tmp_path / "store", payloads)
    assert result.canonical_rows.height == 2
    manifest = StoreReader().status(StoreRoot(tmp_path / "store"), ProviderId("cz_chmi")).manifest
    assert manifest.coverage == ()
    assert {key[1].day: item.retrieved_at for item in manifest.outcomes for key in item.observation_keys} == {
        1: first_time,
        2: second_time,
    }


@pytest.mark.parametrize("defect", ["mixed_failure", "unknown_offset"])
def test_incompatible_axis_evidence_is_fatal_before_cache_mutation(tmp_path, monkeypatch, defect):
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.source_acquisition import FailedSourceRequest, SourceRequestTarget
    from rivretrieve._internal.source_series import SeriesWindow
    from rivretrieve._internal.time_axis import TimeAxis
    from rivretrieve._internal.transport import HttpMethod, TransportFailure, TransportFailureReason, TransportRequest

    store = tmp_path / "store"
    payload = single_payload()
    run(store, (payload,))
    before = {path.relative_to(store): path.read_bytes() for path in store.rglob("*") if path.is_file()}
    original_parse = parse

    def axis_parse(received, config):
        parsed = original_parse(received, config)
        return replace(
            parsed,
            rows=parsed.rows.with_columns(
                pl.lit("unknown" if defect == "unknown_offset" else "+00:00").alias("time_zone")
            ),
            outcomes=tuple(
                item.model_copy(update={"window": item.window.model_copy(update={"axis": TimeAxis.UTC})})
                for item in parsed.outcomes
            ),
        )

    monkeypatch.setattr("tests.test_acquisition_composition.parse", axis_parse)
    if defect == "mixed_failure":
        request = TransportRequest(HttpMethod.GET, "https://example.test/observations")
        failure = FailedSourceRequest(
            "native-failure",
            SourceRequestTarget("0-203-1-000400", "discharge_daily_mean"),
            SeriesWindow(start=datetime(2023, 6, 1), end=datetime(2023, 6, 2)),
            request,
            TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503),
        )
        acquired = SourceAcquisition((payload,), failed_requests=(failure,))
        message = "cannot mix acquisition time axes"
    else:
        acquired = (payload,)
        message = "UTC acquisition rows require published fixed offsets"
    with pytest.raises(FatalContractError, match=message):
        run(store, acquired)
    assert {path.relative_to(store): path.read_bytes() for path in store.rglob("*") if path.is_file()} == before
