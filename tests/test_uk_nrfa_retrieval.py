"""Source-independent tests for NRFA acquisition config, windows, fetch, and parse (#594)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal import driver as driver_module
from rivretrieve._internal.engine import (
    Daily,
    DailyLabelTime,
    DayDefinition,
    FetchWindow,
    ObservationRequest,
    Payload,
    ProductConfig,
    ProviderConfig,
    RenderedWindow,
    RequestedWindow,
    SourceCallOrigin,
    SourceCoordinates,
    StopConvention,
    Unit,
    UnknownOriginFact,
    UnknownTemporalSupport,
    WindowDeclaration,
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
    ZoneValue,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError, ObservationsUnavailableError
from rivretrieve._internal.observations import (
    ObservationProvenance,
    ObservationResult,
    ReceiptMode,
)
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.uk_nrfa.annotations import (
    UK_NRFA_AMAX_REJECTION_SCHEMA,
    UK_NRFA_OBSERVATIONS_SCHEMA,
    UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA,
    UK_NRFA_SERIES_METADATA_SCHEMA,
)
from rivretrieve._internal.providers.uk_nrfa.series import PEAK_REJECTED_PERIOD_PRODUCTS, PRODUCT_IDS
from rivretrieve._internal.source_acquisition import SourceResponseMeaning
from rivretrieve._internal.source_annotations import with_annotations
from rivretrieve._internal.source_series import InventoryCompleteness, OutcomeStatus, RestrictionKind, SeriesScope
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.transport import (
    HttpMethod,
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)


def test_uk_nrfa_config_and_window_declarations() -> None:
    from rivretrieve._internal.providers.uk_nrfa.config import (
        SHARED_ACQUISITION_PRODUCTS,
        UkNrfaPeakMetadataCoordinates,
        UkNrfaSourceCoordinates,
        config,
        window_declarations,
    )

    cfg = config()
    assert cfg.zone == ZoneValue("unknown")
    assert cfg.cache is None
    assert tuple(cfg.products) == PRODUCT_IDS

    stage_products = {"gauging-stage", "amax-stage", "pot-stage"}
    daily_products = {"gdf", "ndf"}
    for pid in PRODUCT_IDS:
        product_cfg = cfg.products[ProductId(pid)]
        assert product_cfg.unit is (Unit.M if pid in stage_products else Unit.M3_S)
        assert product_cfg.coordinates == SourceCoordinates(UkNrfaSourceCoordinates(data_type=pid))
        if pid in daily_products:
            assert product_cfg.semantics == Daily(DayDefinition("unknown"), DailyLabelTime("00:00"))
        else:
            assert product_cfg.semantics == UnknownTemporalSupport()

    decls = window_declarations()
    assert tuple(decls.products) == PRODUCT_IDS
    expected_date_decl = WindowDeclaration(
        WindowGranularity("date"),
        WindowRenderingVocabulary.DATE,
        StopConvention.INCLUSIVE,
    )
    expected_none_decl = WindowDeclaration(
        WindowGranularity("none"),
        WindowRenderingVocabulary.NONE,
        StopConvention.INCLUSIVE,
    )
    for pid in PRODUCT_IDS:
        expected_decl = expected_none_decl if pid in {"gmf", "nmf"} else expected_date_decl
        assert decls.products[ProductId(pid)] == expected_decl

    assert (frozenset(ProductId(pid) for pid in PEAK_REJECTED_PERIOD_PRODUCTS),) == SHARED_ACQUISITION_PRODUCTS
    assert UkNrfaPeakMetadataCoordinates() == UkNrfaPeakMetadataCoordinates()

    with pytest.raises(FatalContractError):
        UkNrfaSourceCoordinates(data_type="unsupported")
    with pytest.raises(FatalContractError):
        UkNrfaSourceCoordinates(data_type="gdf", peak_metadata_content=b"{}")


def test_uk_nrfa_public_fetch_remains_catalogue_only() -> None:
    selection = rr.find(provider="uk_nrfa", station="39001")
    with pytest.raises(ObservationsUnavailableError):
        rr.fetch(selection, start="2020-01-01", end="2020-01-05")


class _StubTransport:
    def __init__(self, handler: Callable[[TransportRequest], TransportResponse]) -> None:
        self.handler = handler
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        return self.handler(request)


def _fetch_window(start: datetime, end: datetime) -> FetchWindow:
    return _make_fetch_window(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end))


def _ts_bytes(
    product_id: str,
    stream: list[object],
    *,
    station_id: int = 39001,
    interval: str | None = "R1/2020-01-01/P1D",
) -> bytes:
    headers = {
        "gdf": ("Gauged Daily Flow", "Flow", "m3/s", "Mean", "P1D"),
        "ndf": ("Naturalised Daily Flow", "Flow", "m3/s", "Mean", "P1D"),
        "gmf": ("Gauged Monthly Flow", "Flow", "m3/s", "Mean", "P1M"),
        "nmf": ("Naturalised Monthly Flow", "Flow", "m3/s", "Mean", "P1M"),
        "gauging-flow": ("Gauging - Flow", "Flow", "m3/s", "Measured", "PT1S"),
        "gauging-stage": ("Gauging - Stage", "Stage", "m", "Measured", "PT1S"),
        "amax-flow": ("Annual Maxima - Flow", "Flow", "m3/s", "Maximum", "PT15M"),
        "amax-stage": ("Annual Maxima - Stage", "Stage", "m", "Maximum", "PT15M"),
        "pot-flow": ("Peaks Over Threshold - Flow", "Flow", "m3/s", "Measured", "PT15M"),
        "pot-stage": ("Peaks Over Threshold - Stage", "Stage", "m", "Measured", "PT15M"),
    }
    name, parameter, units, measurement_type, period = headers[product_id]
    doc: dict[str, object] = {
        "timestamp": "2026-11-16T14:00:00Z",
        "station": {"id": station_id, "name": f"Station {station_id}"},
        "data-type": {
            "id": product_id,
            "name": name,
            "parameter": parameter,
            "units": units,
            "measurement-type": measurement_type,
            "period": period,
        },
        "data-stream": stream,
    }
    if interval is not None:
        doc["interval"] = interval
    return json.dumps(doc).encode("utf-8")


def _station_info_bytes(
    station_id: int,
    *,
    excluded_years: list[int] | None = None,
    rejected_periods: list[str] | None = None,
) -> bytes:
    return json.dumps(
        {
            "timestamp": "2026-11-16T14:00:00Z",
            "data": [
                {
                    "id": station_id,
                    "peak-flow-rejected-amax-years": (
                        {"excluded-years": excluded_years} if excluded_years is not None else None
                    ),
                    "peak-flow-rejected-periods": (
                        {"rejected-periods": rejected_periods} if rejected_periods is not None else None
                    ),
                }
            ],
        }
    ).encode("utf-8")


def _ok_response(request: TransportRequest, content: bytes) -> TransportResponse:
    return TransportResponse(
        status_code=200,
        content=content,
        url=request.url,
        request_parameters=request.params or {},
        retrieved_at=datetime(2026, 11, 16, 14, 0, tzinfo=UTC),
        content_type="application/json",
    )


def test_extract_peak_metadata_row_validates_shape_identity_and_rejection_fields() -> None:
    from rivretrieve._internal.providers.uk_nrfa.fetch import extract_peak_metadata_row

    valid = _station_info_bytes(82001, excluded_years=[1962], rejected_periods=["1963-09-05/1982-05-31"])
    row = extract_peak_metadata_row(valid, "82001")
    assert row["id"] == 82001

    for bad_bytes, station in (
        (b"", "82001"),
        (b"\xff", "82001"),
        (b"[]", "82001"),
        (b'{"data": []}', "82001"),
        (b'{"data": [1, 2]}', "82001"),
        (_station_info_bytes(6007), "82001"),
        (
            json.dumps(
                {"data": [{"id": True, "peak-flow-rejected-amax-years": None, "peak-flow-rejected-periods": None}]}
            ).encode(),
            "82001",
        ),
        (json.dumps({"data": [{"id": 82001, "peak-flow-rejected-amax-years": None}]}).encode(), "82001"),
        (
            json.dumps(
                {
                    "data": [
                        {
                            "id": 82001,
                            "peak-flow-rejected-amax-years": {"wrong": []},
                            "peak-flow-rejected-periods": None,
                        }
                    ]
                }
            ).encode(),
            "82001",
        ),
    ):
        with pytest.raises(UnsupportedSourceStructureError):
            extract_peak_metadata_row(bad_bytes, station)


def test_fetch_contract_validation_errors() -> None:
    from rivretrieve._internal.providers.uk_nrfa.config import UkNrfaPeakMetadataCoordinates, config
    from rivretrieve._internal.providers.uk_nrfa.fetch import fetch

    cfg = config()
    fw = _fetch_window(datetime(2020, 1, 1), datetime(2020, 1, 5, 23, 59, 59))
    transport = _StubTransport(lambda req: _ok_response(req, b"{}"))
    date_rendered = (RenderedWindow("2020-01-01", "2020-01-05"),)

    with pytest.raises(FatalContractError):
        fetch((), (ProductId("gdf"),), {ProductId("gdf"): date_rendered}, fw, cfg, transport)
    with pytest.raises(FatalContractError):
        fetch(("39001",), (), {}, fw, cfg, transport)
    with pytest.raises(FatalContractError):
        fetch(("",), (ProductId("gdf"),), {ProductId("gdf"): date_rendered}, fw, cfg, transport)
    with pytest.raises(FatalContractError):
        fetch(("39001",), (ProductId("unknown"),), {ProductId("unknown"): date_rendered}, fw, cfg, transport)
    with pytest.raises(FatalContractError):
        fetch(("39001",), (ProductId("gdf"),), {ProductId("gdf"): ()}, fw, cfg, transport)
    with pytest.raises(FatalContractError):
        fetch(
            ("39001",),
            (ProductId("gdf"),),
            {ProductId("gdf"): (RenderedWindow("2020", None),)},
            fw,
            cfg,
            transport,
        )
    with pytest.raises(FatalContractError):
        fetch(
            ("39001",),
            (ProductId("gmf"),),
            {ProductId("gmf"): date_rendered},
            fw,
            cfg,
            transport,
        )
    bad_cfg = ProviderConfig(
        zone=cfg.zone,
        products={
            ProductId("gdf"): ProductConfig(
                coordinates=SourceCoordinates(UkNrfaPeakMetadataCoordinates()),
                unit=Unit.M3_S,
                semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")),
            )
        },
    )
    with pytest.raises(FatalContractError):
        fetch(("39001",), (ProductId("gdf"),), {ProductId("gdf"): date_rendered}, fw, bad_cfg, transport)
    assert transport.requests == []


def test_fetch_requests_routes_params_deduplicates_station_info_and_isolates_failures() -> None:
    from rivretrieve._internal.providers.uk_nrfa.config import (
        UkNrfaPeakMetadataCoordinates,
        UkNrfaSourceCoordinates,
        config,
    )
    from rivretrieve._internal.providers.uk_nrfa.fetch import fetch

    cfg = config()
    fw = _fetch_window(datetime(2020, 1, 1), datetime(2020, 1, 5, 23, 59, 59))
    rendered = {
        ProductId("gdf"): (RenderedWindow("2020-01-01", "2020-01-05"),),
        ProductId("gmf"): (),
        ProductId("amax-flow"): (RenderedWindow("2020-01-01", "2020-01-05"),),
        ProductId("pot-stage"): (RenderedWindow("2020-01-01", "2020-01-05"),),
    }

    def handler(req: TransportRequest) -> TransportResponse:
        params = req.params or {}
        if req.url.endswith("/station-info"):
            assert req.method is HttpMethod.GET
            assert req.url == "https://nrfaapps.ceh.ac.uk/nrfa/ws/station-info"
            assert req.headers == {"Accept": "application/json"}
            assert params == {"station": params["station"], "format": "json-object", "fields": "id,peak-flow-metadata"}
            if params["station"] == "999999":
                raise TransportFailure(
                    req,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=400,
                    category=TransportFailureCategory.HTTP_STATUS,
                )
            if params["station"] == "777777":
                return _ok_response(req, b'{"data": []}')
            return _ok_response(req, _station_info_bytes(39001, excluded_years=[1987]))

        assert req.url == "https://nrfaapps.ceh.ac.uk/nrfa/ws/time-series"
        assert req.headers == {"Accept": "application/json"}
        if params["station"] == "999999" and params["data-type"] == "gdf":
            raise TransportFailure(
                req,
                TransportFailureReason.HTTP_STATUS,
                1,
                status_code=400,
                category=TransportFailureCategory.HTTP_STATUS,
            )
        if params["data-type"] in {"gmf", "nmf"}:
            assert "start-date" not in params and "end-date" not in params
        else:
            assert params["start-date"] == "2020-01-01" and params["end-date"] == "2020-01-05"
        if params["station"] == "39001" and params["data-type"] == "pot-stage":
            raise TransportFailure(
                req,
                TransportFailureReason.RETRY_EXHAUSTED,
                3,
                category=TransportFailureCategory.TIMEOUT,
            )
        return _ok_response(req, _ts_bytes(str(params["data-type"]), [], station_id=int(params["station"])))

    transport = _StubTransport(handler)
    acquired = fetch(
        ("39001", "777777", "999999"),
        (ProductId("gmf"), ProductId("gdf"), ProductId("amax-flow"), ProductId("pot-stage")),
        rendered,
        fw,
        cfg,
        transport,
    )

    # One station-info per station (never for gmf/gdf), and no child peak /time-series when station-info fails or is invalid.
    station_info_calls = [
        req.params["station"] for req in transport.requests if req.url.endswith("/station-info") and req.params
    ]
    assert station_info_calls == ["39001", "777777", "999999"]
    ts_calls = [
        (req.params["station"], req.params["data-type"])
        for req in transport.requests
        if req.url.endswith("/time-series") and req.params
    ]
    assert ts_calls == [
        ("39001", "gmf"),
        ("39001", "gdf"),
        ("39001", "amax-flow"),
        ("39001", "pot-stage"),
        ("777777", "gmf"),
        ("777777", "gdf"),
        ("999999", "gmf"),
        ("999999", "gdf"),
    ]

    # Payloads: 39001(gmf, gdf, meta, amax-flow), 777777(gmf, gdf, invalid meta), 999999(gmf).
    meta_39001 = next(
        p
        for p in acquired.value
        if isinstance(p.source_coordinates.value, UkNrfaPeakMetadataCoordinates) and p.station_products[0][0] == "39001"
    )
    assert meta_39001.station_products == (("39001", ProductId("amax-flow")), ("39001", ProductId("pot-stage")))

    amax_39001 = next(p for p in acquired.value if p.station_products == (("39001", ProductId("amax-flow")),))
    assert amax_39001.prerequisite_acquisition_ids == (meta_39001.acquisition_id,)
    assert isinstance(amax_39001.source_coordinates.value, UkNrfaSourceCoordinates)
    assert amax_39001.source_coordinates.value.peak_metadata_content == meta_39001.content

    gdf_39001 = next(p for p in acquired.value if p.station_products == (("39001", ProductId("gdf")),))
    assert gdf_39001.prerequisite_acquisition_ids == ()
    assert gdf_39001.source_coordinates.value == UkNrfaSourceCoordinates(data_type="gdf")

    # Failed requests: 39001 pot-stage (linked to meta_39001), 999999 gdf, 999999 amax-flow & pot-stage sharing one call_id.
    assert len(acquired.failed_requests) == 4
    by_pair = {(f.series.station_id, f.series.product_id): f for f in acquired.failed_requests}
    assert by_pair[("39001", "pot-stage")].prerequisite_acquisition_ids == (meta_39001.acquisition_id,)
    assert by_pair[("999999", "gdf")].meaning is SourceResponseMeaning.UNSPECIFIED
    assert by_pair[("999999", "amax-flow")].call_id is not None
    assert by_pair[("999999", "amax-flow")].call_id == by_pair[("999999", "pot-stage")].call_id
    assert by_pair[("999999", "amax-flow")].meaning is SourceResponseMeaning.UNSPECIFIED
    assert by_pair[("999999", "amax-flow")].prerequisite_acquisition_ids == ()


def _origin(url: str = "https://nrfaapps.ceh.ac.uk/nrfa/ws/time-series") -> SourceCallOrigin:
    return SourceCallOrigin(
        url=url,
        request_parameters={"format": "json-object"},
        status_code=200,
        retrieved_at=datetime(2026, 11, 16, 14, 0, tzinfo=UTC),
        content_type="application/json",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )


def _nrfa_stages():
    from rivretrieve._internal.providers.uk_nrfa.config import (
        SHARED_ACQUISITION_PRODUCTS,
    )
    from rivretrieve._internal.providers.uk_nrfa.config import (
        config as nrfa_config,
    )
    from rivretrieve._internal.providers.uk_nrfa.config import (
        window_declarations as nrfa_windows,
    )
    from rivretrieve._internal.providers.uk_nrfa.fetch import fetch as nrfa_fetch
    from rivretrieve._internal.providers.uk_nrfa.parse import parse as nrfa_parse

    resolved_config = nrfa_config()
    resolved_windows = nrfa_windows()

    class _Stages:
        observation_source = "live"
        config = resolved_config
        window_declarations = resolved_windows
        shared_acquisition_products = SHARED_ACQUISITION_PRODUCTS
        fetch = staticmethod(nrfa_fetch)
        parse = staticmethod(nrfa_parse)

    return _Stages


def test_parse_contract_validation_errors() -> None:
    from rivretrieve._internal.providers.uk_nrfa.config import (
        UkNrfaPeakMetadataCoordinates,
        UkNrfaSourceCoordinates,
        config,
    )
    from rivretrieve._internal.providers.uk_nrfa.parse import parse

    cfg = config()
    fw = _fetch_window(datetime(2020, 1, 1), datetime(2020, 1, 5, 23, 59, 59))
    base = Payload(
        source_coordinates=SourceCoordinates(UkNrfaSourceCoordinates(data_type="gdf")),
        station_products=(("39001", ProductId("gdf")),),
        fetch_window=fw,
        content=_ts_bytes("gdf", []),
        origin=_origin(),
        prerequisite_calls=(),
    )

    for bad in (
        replace(base, station_products=()),
        replace(base, station_products=(("39001", ProductId("gdf")), ("6007", ProductId("gdf")))),
        replace(base, station_products=(("39001", ProductId("unknown")),)),
        replace(base, source_coordinates=SourceCoordinates("invalid")),
        replace(
            base,
            source_coordinates=SourceCoordinates(UkNrfaPeakMetadataCoordinates()),
            station_products=(("39001", ProductId("gdf")),),
        ),
        replace(
            base,
            source_coordinates=SourceCoordinates(UkNrfaSourceCoordinates(data_type="ndf")),
        ),
        replace(
            base,
            source_coordinates=SourceCoordinates(UkNrfaSourceCoordinates(data_type="amax-flow")),
            station_products=(("39001", ProductId("amax-flow")),),
        ),
    ):
        with pytest.raises(FatalContractError):
            parse(bad, cfg)


def test_parse_handles_malformed_and_reversed_date_empty_bytes_as_failed_outcomes() -> None:
    from rivretrieve._internal.providers.uk_nrfa.config import (
        UkNrfaPeakMetadataCoordinates,
        UkNrfaSourceCoordinates,
        config,
    )
    from rivretrieve._internal.providers.uk_nrfa.parse import parse

    cfg = config()
    fw = _fetch_window(datetime(2020, 1, 1), datetime(2020, 1, 5, 23, 59, 59))

    for bad_content in (b"", b"<html>error</html>", json.dumps({"data-stream": ["2020-01-01", 1.0]}).encode()):
        payload = Payload(
            source_coordinates=SourceCoordinates(UkNrfaSourceCoordinates(data_type="gdf")),
            station_products=(("39001", ProductId("gdf")),),
            fetch_window=fw,
            content=bad_content,
            origin=_origin(),
            prerequisite_calls=(),
        )
        parsed = parse(payload, cfg)
        assert parsed.rows.is_empty()
        assert parsed.series == ()
        assert parsed.inventories == ()
        assert len(parsed.outcomes) == 1
        assert parsed.outcomes[0].status is OutcomeStatus.FAILED
        assert parsed.outcomes[0].series_id is None
        assert len(parsed.issues) == 1
        assert parsed.issues[0].code == "source.unsupported_structure"
        assert parsed.issues[0].severity == "error"

    valid_meta = Payload(
        source_coordinates=SourceCoordinates(UkNrfaPeakMetadataCoordinates()),
        station_products=(("82001", ProductId("amax-flow")), ("82001", ProductId("pot-stage"))),
        fetch_window=fw,
        content=_station_info_bytes(82001, excluded_years=[1962]),
        origin=_origin("https://nrfaapps.ceh.ac.uk/nrfa/ws/station-info"),
        prerequisite_calls=(),
    )
    parsed_valid_meta = parse(valid_meta, cfg)
    assert parsed_valid_meta.rows.is_empty()
    assert parsed_valid_meta.outcomes == ()
    assert parsed_valid_meta.issues == ()

    bad_meta = replace(valid_meta, content=b'{"data": []}')
    parsed_bad_meta = parse(bad_meta, cfg)
    assert [(o.product_id, o.status) for o in parsed_bad_meta.outcomes] == [
        ("amax-flow", OutcomeStatus.FAILED),
        ("pot-stage", OutcomeStatus.FAILED),
    ]
    assert len(parsed_bad_meta.issues) == 2
    assert {i.code for i in parsed_bad_meta.issues} == {"source.unsupported_structure"}


def test_parse_preserves_annotations_complete_inventory_and_scope_narrowing() -> None:
    from rivretrieve._internal.providers.uk_nrfa.config import UkNrfaSourceCoordinates, config
    from rivretrieve._internal.providers.uk_nrfa.parse import parse

    cfg = config()
    fw = _fetch_window(datetime(1962, 1, 1), datetime(1964, 12, 31, 23, 59, 59))
    meta_bytes = _station_info_bytes(82001, excluded_years=[1962], rejected_periods=["1963-09-05/1982-05-31"])
    amax_bytes = _ts_bytes(
        "amax-flow",
        ["1962-01-11T12:00:00", 50.0, "1963-11-12T00:00:00", [80.0, "E"]],
        station_id=82001,
    )
    payload = Payload(
        source_coordinates=SourceCoordinates(
            UkNrfaSourceCoordinates(data_type="amax-flow", peak_metadata_content=meta_bytes)
        ),
        station_products=(("82001", ProductId("amax-flow")),),
        fetch_window=fw,
        content=amax_bytes,
        origin=_origin(),
        prerequisite_calls=(),
    )

    parsed = parse(payload, cfg)
    assert parsed.rows["value"].to_list() == [50.0, 80.0]
    assert parsed.outcomes[0].status is OutcomeStatus.SUCCESS
    assert parsed.inventories[0].completeness is InventoryCompleteness.COMPLETE
    assert parsed.inventories[0].members == (parsed.series[0].series_id,)
    assert parsed.annotations.schema_table(UK_NRFA_AMAX_REJECTION_SCHEMA.schema_id)[
        "rejected_amax_years"
    ].to_list() == [[1962]]
    assert parsed.annotations.schema_table(UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA.schema_id)[
        "rejected_periods"
    ].to_list() == [["1963-09-05/1982-05-31"]]
    assert parsed.annotations.schema_table(UK_NRFA_OBSERVATIONS_SCHEMA.schema_id)["flag"].to_list() == [None, "E"]
    assert parsed.annotations.schema_table(UK_NRFA_SERIES_METADATA_SCHEMA.schema_id)["source_period"].to_list() == [
        "PT15M"
    ]

    # Empty data-stream establishes COMPLETE empty outcome.
    empty_payload = replace(
        payload,
        source_coordinates=SourceCoordinates(UkNrfaSourceCoordinates(data_type="gdf")),
        station_products=(("39001", ProductId("gdf")),),
        content=_ts_bytes("gdf", [], station_id=39001, interval=None),
    )
    empty_parsed = parse(empty_payload, cfg)
    assert empty_parsed.outcomes[0].status is OutcomeStatus.EMPTY
    assert empty_parsed.inventories[0].completeness is InventoryCompleteness.COMPLETE

    # Excluded scope preserves series definition and inventory without emitting rows or outcomes.
    narrowed = replace(
        empty_payload,
        scope=SeriesScope(
            provider_ids=("uk_nrfa",),
            series_ids=("unrelated-series",),
            restriction=RestrictionKind.EXPLICIT,
        ),
    )
    narrowed_parsed = parse(narrowed, cfg)
    assert len(narrowed_parsed.series) == 1
    assert len(narrowed_parsed.inventories) == 1
    assert narrowed_parsed.rows.is_empty()
    assert narrowed_parsed.outcomes == ()


def test_drive_monthly_partial_window_and_microsecond_event_bounds_preserve_observations() -> None:
    stages = _nrfa_stages()

    def handler(req: TransportRequest) -> TransportResponse:
        params = req.params or {}
        if params["data-type"] == "gmf":
            assert "start-date" not in params and "end-date" not in params
            return _ok_response(
                req,
                _ts_bytes(
                    "gmf",
                    ["2020-01", 10.0, "2020-02", 20.0, "2020-03", 30.0, "2020-04", 40.0],
                    interval="R4/2020-01/P1M",
                ),
            )
        assert params["start-date"] == "2024-07-07"
        assert params["end-date"] == "2024-07-11"
        return _ok_response(
            req,
            _ts_bytes("gauging-flow", ["2024-07-09T12:00:22", 15.5], interval="R1/2024-07-09/P1D"),
        )

    transport = _StubTransport(handler)
    gmf_req = ObservationRequest(
        ProviderId("uk_nrfa"),
        ("39001",),
        (ProductId("gmf"),),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2020, 1, 15, 0, 0, 0)),
            WindowEndpoint.from_datetime(datetime(2020, 3, 15, 0, 0, 0)),
        ),
    )
    gmf_out = driver_module.drive(
        gmf_req,
        stages,
        provenance=ObservationProvenance(source="test", provider_id=ProviderId("uk_nrfa"), request={}),
        transport=transport,
    )
    assert gmf_out.canonical_rows["value"].to_list() == [20.0, 30.0]
    assert gmf_out.annotations.schema_table(UK_NRFA_OBSERVATIONS_SCHEMA.schema_id)["source_label"].to_list() == [
        "2020-02",
        "2020-03",
    ]

    gauge_req = ObservationRequest(
        ProviderId("uk_nrfa"),
        ("39001",),
        (ProductId("gauging-flow"),),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 7, 9, 0, 0, 0, 1)),
            WindowEndpoint.from_datetime(datetime(2024, 7, 9, 23, 59, 59, 999999)),
        ),
    )
    gauge_out = driver_module.drive(
        gauge_req,
        stages,
        provenance=ObservationProvenance(source="test", provider_id=ProviderId("uk_nrfa"), request={}),
        transport=transport,
    )
    assert gauge_out.canonical_rows["value"].to_list() == [15.5]


def test_drive_shared_peak_prerequisite_receipts_partial_failures_and_store_reuse(tmp_path: Path) -> None:
    stages = _nrfa_stages()
    store = StoreRoot(tmp_path / "nrfa-store")

    def handler(req: TransportRequest) -> TransportResponse:
        params = req.params or {}
        if req.url.endswith("/station-info"):
            if params["station"] == "999999":
                raise TransportFailure(
                    req,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=400,
                    category=TransportFailureCategory.HTTP_STATUS,
                )
            return _ok_response(
                req,
                _station_info_bytes(82001, excluded_years=[1962], rejected_periods=["1963-09-05/1982-05-31"]),
            )
        if params["station"] == "999999":
            raise TransportFailure(
                req,
                TransportFailureReason.HTTP_STATUS,
                1,
                status_code=400,
                category=TransportFailureCategory.HTTP_STATUS,
            )
        dtype = str(params["data-type"])
        if dtype == "amax-flow":
            return _ok_response(req, _ts_bytes("amax-flow", ["1962-11-01T00:00:00", 50.0], station_id=82001))
        if dtype == "pot-stage":
            return _ok_response(req, _ts_bytes("pot-stage", ["1963-10-02T00:00:00", [2.4, "S"]], station_id=82001))
        return _ok_response(req, _ts_bytes("gdf", ["1963-10-02", 12.0], station_id=82001))

    transport = _StubTransport(handler)
    req = ObservationRequest(
        ProviderId("uk_nrfa"),
        ("82001", "999999"),
        (ProductId("amax-flow"), ProductId("pot-stage"), ProductId("gdf")),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1962, 1, 1)),
            WindowEndpoint.from_datetime(datetime(1964, 12, 31, 23, 59, 59)),
        ),
    )
    assembled = driver_module.drive(
        req,
        stages,
        provenance=ObservationProvenance(source="test", provider_id=ProviderId("uk_nrfa"), request={}),
        receipts=ReceiptMode.INCLUDE,
        transport=transport,
        cache="reuse",
        store=store,
    )

    # 82001 sends 1 station-info + 3 time-series; 999999 fails on 1 station-info + 1 gdf time-series.
    assert len(transport.requests) == 6
    assert len(assembled.receipts.entries) == 4
    result = with_annotations(
        ObservationResult(
            data=assembled.canonical_rows,
            source_series=assembled.source_series,
            inventories=assembled.inventories,
            outcomes=assembled.outcomes,
            supporting_outcomes=assembled.supporting_outcomes,
            scope=assembled.scope,
            provenance=assembled.provenance,
            issues=assembled.issues,
            receipts=assembled.receipts,
        ),
        assembled.annotations,
    )
    assert sorted(result.data["value"].to_list()) == [2.4, 12.0, 50.0]
    series_df = rr.series(result, annotations=True)
    by_station_product = {(row["station_id"], row["product_id"]): row for row in series_df.iter_rows(named=True)}
    assert by_station_product[("82001", "amax-flow")]["rejected_amax_years"] == [1962]
    assert by_station_product[("82001", "amax-flow")]["rejected_periods"] == ["1963-09-05/1982-05-31"]
    assert by_station_product[("82001", "pot-stage")]["rejected_amax_years"] is None
    assert by_station_product[("82001", "pot-stage")]["rejected_periods"] == ["1963-09-05/1982-05-31"]
    assert by_station_product[("82001", "gdf")]["rejected_amax_years"] is None
    assert by_station_product[("82001", "gdf")]["rejected_periods"] is None
    assert by_station_product[("999999", "amax-flow")]["series_id"] is None
    assert by_station_product[("999999", "amax-flow")]["rejected_amax_years"] is None

    # Provenance calls link 82001 peak calls to /station-info via prerequisite_acquisition_ids.
    station_info_call = next(
        call
        for call in assembled.provenance.calls_made
        if str(call.get("url", "")).endswith("/station-info") and call.get("status_code") == 200
    )
    amax_call = next(
        call
        for call in assembled.provenance.calls_made
        if (call.get("request_parameters") or {}).get("data-type") == "amax-flow" and call.get("status_code") == 200
    )
    gdf_call = next(
        call
        for call in assembled.provenance.calls_made
        if (call.get("request_parameters") or {}).get("data-type") == "gdf" and call.get("status_code") == 200
    )
    assert amax_call["prerequisite_acquisition_ids"] == (station_info_call["call_id"],)
    assert gdf_call["prerequisite_acquisition_ids"] == ()

    # Station 999999 failed outcomes remain alongside 82001 results.
    failed_999999 = [o for o in assembled.outcomes if o.station_id == "999999"]
    assert len(failed_999999) == 3
    assert all(o.status is OutcomeStatus.FAILED for o in failed_999999)

    # StoreRoot cache="reuse" serves 82001 rows and peak rejection annotations with zero transport calls.
    no_call_transport = _StubTransport(
        lambda r: (_ for _ in ()).throw(AssertionError(f"Unexpected transport call on cached reuse: {r.url}"))
    )
    reused_req = replace(req, stations=("82001",))
    reused = driver_module.drive(
        reused_req,
        stages,
        provenance=ObservationProvenance(source="test", provider_id=ProviderId("uk_nrfa"), request={}),
        transport=no_call_transport,
        cache="reuse",
        store=store,
    )
    assert no_call_transport.requests == []
    assert sorted(reused.canonical_rows["value"].to_list()) == [2.4, 12.0, 50.0]
    assert reused.annotations.schema_table(UK_NRFA_AMAX_REJECTION_SCHEMA.schema_id)[
        "rejected_amax_years"
    ].to_list() == [[1962]]
    assert sorted(
        reused.annotations.schema_table(UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA.schema_id)["rejected_periods"].to_list()
    ) == [["1963-09-05/1982-05-31"], ["1963-09-05/1982-05-31"]]
