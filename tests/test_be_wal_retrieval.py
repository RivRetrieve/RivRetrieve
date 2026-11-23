"""Synthetic unit, driver/store, and catalogue-identity parity tests for Belgium - Wallonia (`be_wal`)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

import pytest

from rivretrieve._internal.catalogues.source_series import catalogue_series
from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    Daily,
    DailyLabelTime,
    DayDefinition,
    Hourly,
    IntervalDefinition,
    ObservationRequest,
    Payload,
    ProductWindowDeclarations,
    ProviderConfig,
    RequestedWindow,
    SourceCallOrigin,
    SourceCoordinates,
    StopConvention,
    Unit,
    UnknownOriginFact,
    UnknownTemporalSupport,
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
    ZoneValue,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.be_wal.annotations import BE_WAL_QUALITY_SCHEMA
from rivretrieve._internal.providers.be_wal.config import (
    BeWalTimeseriesListCoordinates,
    BeWalTimeseriesValuesCoordinates,
    config,
    window_declarations,
)
from rivretrieve._internal.providers.be_wal.fetch import fetch
from rivretrieve._internal.providers.be_wal.parse import parse
from rivretrieve._internal.providers.be_wal.series import KIWIS_NAMESPACE, KIWIS_URL, PRODUCT_SPECS, source_series
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, ReplayTransport
from rivretrieve._internal.source_series import OutcomeStatus, RestrictionKind, SeriesScope
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.time_axis import TimeAxis
from rivretrieve._internal.transport import (
    TRANSPORT_POLICY,
    HttpMethod,
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)
from tests._catalogue import catalogue_reader
from tests.test_internal_driver import _provenance

_RETRIEVED_AT = datetime(2026, 11, 23, 23, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _BeWalStages:
    config: ProviderConfig = config()
    window_declarations: ProductWindowDeclarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


def _envelope(params: dict[str, str], body: object, *, status: int = 200) -> RecordingEnvelope:
    return RecordingEnvelope(
        request=RecordedRequest(
            HttpMethod.GET,
            KIWIS_URL,
            params,
            ordinary_headers={
                "Accept": "application/json",
                "User-Agent": TRANSPORT_POLICY.user_agent,
            },
        ),
        content=body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"),
        status_code=status,
        retrieved_at=_RETRIEVED_AT,
        content_type="application/json",
    )


def _origin(url: str = KIWIS_URL) -> SourceCallOrigin:
    return SourceCallOrigin(
        url=url,
        request_parameters={},
        status_code=200,
        retrieved_at=_RETRIEVED_AT,
        content_type="application/json",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )


def _values_params(ts_id: str, start: str, stop: str) -> dict[str, str]:
    return {
        "service": "kisters",
        "type": "queryServices",
        "datasource": "0",
        "request": "getTimeseriesValues",
        "ts_id": ts_id,
        "from": start,
        "to": stop,
        "timezone": "UTC",
        "format": "json",
        "metadata": "true",
        "returnfields": "Timestamp,Value,Quality Code,Quality Code Name",
        "md_returnfields": "ts_id,ts_name,station_no,stationparameter_name,parametertype_name,ts_unitsymbol",
    }


def _list_params(station: str, ts_name: str) -> dict[str, str]:
    return {
        "service": "kisters",
        "type": "queryServices",
        "datasource": "0",
        "request": "getTimeseriesList",
        "station_no": station,
        "ts_name": ts_name,
        "format": "json",
        "returnfields": "ts_id,ts_name,station_no,stationparameter_name,parametertype_name,ts_unitsymbol",
    }


def _values_block(
    *,
    ts_id: str,
    ts_name: str,
    station: str,
    stationparameter_name: str,
    parametertype_name: str,
    unit: str,
    data: list[list[object]],
) -> list[dict[str, object]]:
    return [
        {
            "ts_id": ts_id,
            "ts_name": ts_name,
            "station_no": station,
            "stationparameter_name": stationparameter_name,
            "parametertype_name": parametertype_name,
            "ts_unitsymbol": unit,
            "rows": str(len(data)),
            "columns": "Timestamp,Value,Quality Code,Quality Code Name",
            "data": data,
        }
    ]


def test_config_and_window_declarations_cover_all_62_products() -> None:
    cfg = config()
    win_decls = window_declarations()
    assert cfg.zone == ZoneValue("+01:00")
    assert len(cfg.products) == 62
    assert set(cfg.products) == {ProductId(spec.product_id) for spec in PRODUCT_SPECS}
    assert set(win_decls.products) == set(cfg.products)

    expected_units = {"m3/s": Unit.M3_S, "m": Unit.M, "degC": Unit.DEG_C}
    daily_count = 0
    hourly_count = 0
    unknown_count = 0
    for spec in PRODUCT_SPECS:
        pid = ProductId(spec.product_id)
        prod_cfg = cfg.products[pid]
        assert prod_cfg.coordinates.value == BeWalTimeseriesValuesCoordinates(spec.product_id)
        assert prod_cfg.unit is expected_units[spec.normalized_unit]

        wdecl = win_decls.products[pid]
        assert wdecl.rendering is WindowRenderingVocabulary.ISO_INSTANT
        assert wdecl.stop_convention is StopConvention.INCLUSIVE
        assert wdecl.fetch_padding is None
        if spec.frequency == "daily":
            daily_count += 1
            assert prod_cfg.semantics == Daily(DayDefinition("00:00"), DailyLabelTime("00:00:00"))
            assert wdecl.granularity == WindowGranularity("iso-instant")
            assert wdecl.size is None
        elif spec.frequency == "hourly":
            hourly_count += 1
            assert prod_cfg.semantics == Hourly(IntervalDefinition("unknown"))
            assert wdecl.granularity == WindowGranularity("capped-span")
            assert wdecl.size == 3650
        else:
            unknown_count += 1
            assert prod_cfg.semantics == UnknownTemporalSupport()
            if spec.frequency is None:
                assert wdecl.granularity == WindowGranularity("capped-span")
                assert wdecl.size == 365
            else:
                assert wdecl.granularity == WindowGranularity("iso-instant")
                assert wdecl.size is None

    assert (daily_count, hourly_count, unknown_count) == (15, 15, 32)

    with pytest.raises(FatalContractError):
        BeWalTimeseriesListCoordinates("discharge_daily_mean", "WRONG")
    with pytest.raises(FatalContractError):
        BeWalTimeseriesValuesCoordinates("nonexistent_product")
    with pytest.raises(FatalContractError):
        BeWalTimeseriesValuesCoordinates("discharge_daily_mean", ts_id="0")


def test_source_series_matches_all_8198_packaged_catalogue_identities_and_facts() -> None:
    artifact = catalogue_reader("be_wal").artifact
    pkg_series, _ = catalogue_series(artifact)
    assert len(pkg_series) == 8198
    for expected in pkg_series:
        assert expected.identity.namespace == KIWIS_NAMESPACE
        assert expected.identity.published_id is not None
        built = source_series(
            expected.station_id,
            expected.product_id,
            ts_id=expected.identity.published_id,
            origin="catalogue",
        )
        assert built == expected


def test_parse_cet_conversion_null_quality_annotations_and_empty_window() -> None:
    cfg = config()
    fw = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2011, 8, 1)),
        WindowEndpoint.from_datetime(datetime(2011, 8, 5, 23, 59, 59)),
    )
    coords = SourceCoordinates(BeWalTimeseriesValuesCoordinates("discharge_daily_mean", ts_id="297170010"))
    content = json.dumps(
        _values_block(
            ts_id="297170010",
            ts_name="20-Debit.Jour.Moyen",
            station="3561",
            stationparameter_name="Débit",
            parametertype_name="Q",
            unit="m³/s",
            data=[
                ["2011-08-03T23:00:00.000Z", 0.0, 200, "Unknown"],
                ["2011-08-04T23:00:00.000Z", None, -1, None],
            ],
        )
    ).encode("utf-8")
    parsed = parse(
        Payload(
            source_coordinates=coords,
            station_products=(("3561", ProductId("discharge_daily_mean")),),
            fetch_window=fw,
            content=content,
            origin=_origin(),
            prerequisite_calls=(),
            acquisition_axis=TimeAxis.UTC,
        ),
        cfg,
    )
    assert parsed.issues == ()
    assert [o.status for o in parsed.outcomes] == [OutcomeStatus.SUCCESS]
    assert parsed.rows["time"].to_list() == [datetime(2011, 8, 4), datetime(2011, 8, 5)]
    assert parsed.rows["value"].to_list() == [0.0, None]
    assert parsed.rows["time_zone"].to_list() == ["+01:00", "+01:00"]

    ann = parsed.annotations.observation_tables[BE_WAL_QUALITY_SCHEMA.schema_id]
    assert ann.measurement_indices == (0, 1)
    assert ann.rows["measured"].to_list() == [True, True]
    assert ann.rows["quality_code"].to_list() == [200, -1]
    assert ann.rows["quality_code_name"].to_list() == ["Unknown", None]

    empty_parsed = parse(
        Payload(
            source_coordinates=coords,
            station_products=(("3561", ProductId("discharge_daily_mean")),),
            fetch_window=fw,
            content=json.dumps(
                _values_block(
                    ts_id="297170010",
                    ts_name="20-Debit.Jour.Moyen",
                    station="3561",
                    stationparameter_name="Débit",
                    parametertype_name="Q",
                    unit="m³/s",
                    data=[],
                )
            ).encode("utf-8"),
            origin=_origin(),
            prerequisite_calls=(),
            acquisition_axis=TimeAxis.UTC,
        ),
        cfg,
    )
    assert empty_parsed.rows.is_empty()
    assert [o.status for o in empty_parsed.outcomes] == [OutcomeStatus.EMPTY]
    assert empty_parsed.annotations.is_empty


@pytest.mark.parametrize(
    "bad_body",
    [
        b"not json",
        json.dumps({"type": "error", "code": "InvalidParameterValue", "message": "not found"}).encode(),
        json.dumps(
            _values_block(
                ts_id="297170010",
                ts_name="21-Debit.Jour.Minimum",
                station="3561",
                stationparameter_name="Débit",
                parametertype_name="Q",
                unit="m³/s",
                data=[],
            )
        ).encode(),
        json.dumps(
            _values_block(
                ts_id="297170010",
                ts_name="20-Debit.Jour.Moyen",
                station="3561",
                stationparameter_name="Débit",
                parametertype_name="Q",
                unit="l/s",
                data=[],
            )
        ).encode(),
        json.dumps(
            _values_block(
                ts_id="297170010",
                ts_name="20-Debit.Jour.Moyen",
                station="3561",
                stationparameter_name="Débit",
                parametertype_name="Q",
                unit="m³/s",
                data=[["2011-08-03T23:00:00+02:00", 1.0, 40, "Good"]],
            )
        ).encode(),
        json.dumps(
            _values_block(
                ts_id="297170010",
                ts_name="20-Debit.Jour.Moyen",
                station="3561",
                stationparameter_name="Débit",
                parametertype_name="Q",
                unit="m³/s",
                data=[["2011-08-03T23:00:00.000Z", True, 40, "Good"]],
            )
        ).encode(),
        json.dumps(
            _values_block(
                ts_id="297170010",
                ts_name="20-Debit.Jour.Moyen",
                station="3561",
                stationparameter_name="Débit",
                parametertype_name="Q",
                unit="m³/s",
                data=[
                    ["2011-08-03T23:00:00.000Z", 1.0, 40, "Good"],
                    ["2011-08-03T23:00:00.000Z", 2.0, 40, "Good"],
                ],
            )
        ).encode(),
    ],
)
def test_parse_confines_corrupt_and_contradictory_responses_to_bounded_failures(bad_body: bytes) -> None:
    cfg = config()
    fw = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2011, 8, 1)),
        WindowEndpoint.from_datetime(datetime(2011, 8, 5, 23, 59, 59)),
    )
    parsed = parse(
        Payload(
            source_coordinates=SourceCoordinates(
                BeWalTimeseriesValuesCoordinates("discharge_daily_mean", ts_id="297170010")
            ),
            station_products=(("3561", ProductId("discharge_daily_mean")),),
            fetch_window=fw,
            content=bad_body,
            origin=_origin(),
            prerequisite_calls=(),
            acquisition_axis=TimeAxis.UTC,
        ),
        cfg,
    )
    assert parsed.rows.is_empty()
    assert [o.status for o in parsed.outcomes] == [OutcomeStatus.FAILED]
    assert parsed.issues[0].code == "source.unsupported_structure"


def test_uncatalogued_lookup_variant_filtering_and_no_match(tmp_path: Path) -> None:
    replay = ReplayTransport(
        (
            _envelope(
                _list_params("9434", "20-Debit.Jour.Moyen"),
                [
                    ["ts_id", "ts_name", "station_no", "stationparameter_name", "parametertype_name", "ts_unitsymbol"],
                    ["302414010", "20-Debit.Jour.Moyen", "9434", "Débit", "Q", "m³/s"],
                ],
            ),
            _envelope(
                _values_params("302414010", "2024-06-29T00:00:00Z", "2024-07-04T23:59:59.999999Z"),
                _values_block(
                    ts_id="302414010",
                    ts_name="20-Debit.Jour.Moyen",
                    station="9434",
                    stationparameter_name="Débit",
                    parametertype_name="Q",
                    unit="m³/s",
                    data=[["2024-07-01T23:00:00.000Z", 12.5, 40, "Good"]],
                ),
            ),
            _envelope(
                _list_params("3270", "20-Debit.Jour.Moyen"),
                [["ts_id", "ts_name", "station_no", "stationparameter_name", "parametertype_name", "ts_unitsymbol"]],
            ),
        )
    )
    req_ok = ObservationRequest(
        provider_id=ProviderId("be_wal"),
        stations=("9434",),
        products=(ProductId("discharge_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 7, 1)),
            WindowEndpoint.from_datetime(datetime(2024, 7, 2)),
        ),
    )
    res_ok = drive(
        req_ok,
        _BeWalStages(),
        provenance=_provenance(req_ok),
        receipts=ReceiptMode.OMIT,
        transport=replay,
        cache="bypass",
        store=StoreRoot(tmp_path / "store-ok"),
    )
    assert res_ok.issues == ()
    assert res_ok.canonical_rows["value"].to_list() == [12.5]
    assert res_ok.canonical_rows["time"].to_list() == [datetime(2024, 7, 2)]

    req_nomatch = ObservationRequest(
        provider_id=ProviderId("be_wal"),
        stations=("3270",),
        products=(ProductId("discharge_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 7, 1)),
            WindowEndpoint.from_datetime(datetime(2024, 7, 2)),
        ),
    )
    res_nomatch = drive(
        req_nomatch,
        _BeWalStages(),
        provenance=_provenance(req_nomatch),
        receipts=ReceiptMode.OMIT,
        transport=replay,
        cache="bypass",
        store=StoreRoot(tmp_path / "store-nomatch"),
    )
    assert res_nomatch.canonical_rows.is_empty()
    assert [o.status for o in res_nomatch.outcomes] == [OutcomeStatus.NO_MATCH]

    # Variant mismatch on uncatalogued fallback resolves getTimeseriesList and emits NO_MATCH.
    replay_var = ReplayTransport(
        (
            _envelope(
                _list_params("9434", "20-Debit.Jour.Moyen"),
                [
                    ["ts_id", "ts_name", "station_no", "stationparameter_name", "parametertype_name", "ts_unitsymbol"],
                    ["302414010", "20-Debit.Jour.Moyen", "9434", "Débit", "Q", "m³/s"],
                ],
            ),
        )
    )
    req_var = ObservationRequest(
        provider_id=ProviderId("be_wal"),
        stations=("9434",),
        products=(ProductId("discharge_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 7, 1)),
            WindowEndpoint.from_datetime(datetime(2024, 7, 2)),
        ),
        scope=SeriesScope(provider_ids=("be_wal",), restriction=RestrictionKind.EXPLICIT, variants=("999999",)),
    )
    res_var = drive(
        req_var,
        _BeWalStages(),
        provenance=_provenance(req_var),
        receipts=ReceiptMode.OMIT,
        transport=replay_var,
        cache="bypass",
        store=StoreRoot(tmp_path / "store-var"),
    )
    assert res_var.canonical_rows.is_empty()
    assert [o.status for o in res_var.outcomes] == [OutcomeStatus.NO_MATCH]


def test_multichunk_utc_ownership_deduplicates_kiwis_microsecond_overlap_and_caches(tmp_path: Path) -> None:
    known = source_series("2708", "discharge_complete", ts_id="235889010", origin="catalogue")
    replay = ReplayTransport(
        (
            _envelope(
                _values_params("235889010", "2023-12-30T00:00:00Z", "2024-12-28T23:59:59.999999Z"),
                _values_block(
                    ts_id="235889010",
                    ts_name="05-Debit.Complet",
                    station="2708",
                    stationparameter_name="Débit",
                    parametertype_name="Q",
                    unit="m³/s",
                    data=[
                        ["2024-12-28T23:00:00.000Z", 10.0, 40, "Good"],
                        ["2024-12-28T23:55:00.000Z", 10.1, 40, "Good"],
                        # Simulates KiWIS interpreting .999999Z as +999,999ms overlap into Chunk 2:
                        ["2024-12-29T00:00:00.000Z", 10.2, 40, "Good"],
                        ["2024-12-29T00:05:00.000Z", 10.3, 40, "Good"],
                    ],
                ),
            ),
            _envelope(
                _values_params("235889010", "2024-12-29T00:00:00Z", "2025-01-02T23:59:59Z"),
                _values_block(
                    ts_id="235889010",
                    ts_name="05-Debit.Complet",
                    station="2708",
                    stationparameter_name="Débit",
                    parametertype_name="Q",
                    unit="m³/s",
                    data=[
                        ["2024-12-29T00:00:00.000Z", 10.2, 40, "Good"],
                        ["2024-12-29T00:05:00.000Z", 10.3, 40, "Good"],
                    ],
                ),
            ),
        )
    )
    req = ObservationRequest(
        provider_id=ProviderId("be_wal"),
        stations=("2708",),
        products=(ProductId("discharge_complete"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2024, 12, 31, 23, 59, 59)),
        ),
        known_series=(known,),
    )
    store = StoreRoot(tmp_path / "store-2c")
    first = drive(
        req,
        _BeWalStages(),
        provenance=_provenance(req),
        receipts=ReceiptMode.OMIT,
        transport=replay,
        cache="reuse",
        store=store,
    )
    # Chunk 1 keeps 23:00Z/23:55Z (= 2024-12-29 00:00/00:55 +01:00) and drops overlap; Chunk 2 keeps 00:00Z/00:05Z.
    assert first.canonical_rows["time"].to_list() == [
        datetime(2024, 12, 29, 0, 0),
        datetime(2024, 12, 29, 0, 55),
        datetime(2024, 12, 29, 1, 0),
        datetime(2024, 12, 29, 1, 5),
    ]
    assert first.canonical_rows["value"].to_list() == [10.0, 10.1, 10.2, 10.3]

    # Cache reuse hits with zero additional transport calls.
    second = drive(
        req,
        _BeWalStages(),
        provenance=_provenance(req),
        receipts=ReceiptMode.OMIT,
        transport=ReplayTransport(()),
        cache="reuse",
        store=store,
    )
    assert second.canonical_rows.equals(first.canonical_rows)


def test_http_500_failure_isolation_and_held_cache_survival(tmp_path: Path) -> None:
    known_ok = source_series("1046", "discharge_daily_mean", ts_id="296450010", origin="catalogue")
    known_fail = source_series("9434", "discharge_daily_mean", ts_id="999999999", origin="catalogue")
    fail_9434 = False

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            if params.get("ts_id") == "999999999" and fail_9434:
                raise TransportFailure(
                    request,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=500,
                    category=TransportFailureCategory.HTTP_STATUS,
                )
            st = "1046" if params.get("ts_id") == "296450010" else "9434"
            return TransportResponse(
                content=json.dumps(
                    _values_block(
                        ts_id=str(params["ts_id"]),
                        ts_name="20-Debit.Jour.Moyen",
                        station=st,
                        stationparameter_name="Débit",
                        parametertype_name="Q",
                        unit="m³/s",
                        data=[["2024-07-01T23:00:00.000Z", 5.5 if st == "1046" else 9.9, 40, "Good"]],
                    )
                ).encode("utf-8"),
                status_code=200,
                retrieved_at=_RETRIEVED_AT,
                content_type="application/json",
                url=request.url,
                request_parameters=MappingProxyType(params),
            )

    store = StoreRoot(tmp_path / "store-iso")
    req = ObservationRequest(
        provider_id=ProviderId("be_wal"),
        stations=("1046", "9434"),
        products=(ProductId("discharge_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 7, 1)),
            WindowEndpoint.from_datetime(datetime(2024, 7, 2)),
        ),
        known_series=(known_ok, known_fail),
    )
    seeded = drive(
        req,
        _BeWalStages(),
        provenance=_provenance(req),
        receipts=ReceiptMode.OMIT,
        transport=_Transport(),
        cache="reuse",
        store=store,
    )
    assert seeded.canonical_rows.height == 2

    fail_9434 = True
    refreshed = drive(
        req,
        _BeWalStages(),
        provenance=_provenance(req),
        receipts=ReceiptMode.OMIT,
        transport=_Transport(),
        cache="refresh",
        store=store,
    )
    assert refreshed.canonical_rows.height == 2
    assert {o.station_id: o.status for o in refreshed.outcomes} == {
        "1046": OutcomeStatus.SUCCESS,
        "9434": OutcomeStatus.FAILED,
    }
