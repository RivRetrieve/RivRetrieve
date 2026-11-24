"""Synthetic unit, SharedParseProvider, annotation, cache, and isolation tests for ``ie_opw``."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

import rivretrieve._internal.providers.ie_opw.parse as ie_parse_mod
from rivretrieve._internal.catalogues.source_series import catalogue_series
from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    Daily,
    DailyLabelTime,
    DayDefinition,
    Instant,
    ObservationRequest,
    Payload,
    ProductWindowDeclarations,
    ProviderConfig,
    RequestedWindow,
    SourceCallOrigin,
    StopConvention,
    Unit,
    UnknownOriginFact,
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
    ZoneValue,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.ie_opw.annotations import (
    IE_OPW_DAILY_STAGE_SCHEMA,
    IE_OPW_SERIES_SCHEMA,
)
from rivretrieve._internal.providers.ie_opw.config import (
    OpwCompleteZipCoordinates,
    OpwDailyYearJsonCoordinates,
    OpwDailyYearJsonEndpointCoordinates,
    config,
    window_declarations,
)
from rivretrieve._internal.providers.ie_opw.fetch import (
    complete_zip_url,
    daily_year_json_url,
    fetch,
    validate_station_id,
)
from rivretrieve._internal.providers.ie_opw.parse import parse, parse_group
from rivretrieve._internal.providers.ie_opw.series import PRODUCT_SPECS, SHARED_DAILY_PRODUCTS, source_series
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, ReplayTransport
from rivretrieve._internal.source_series import InventoryCompleteness, OutcomeStatus, SeriesScope, stable_id
from rivretrieve._internal.store import StoreRoot
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

_RETRIEVED_AT = datetime(2026, 11, 23, 21, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _IeOpwStages:
    observation_source: str = "live"
    config: ProviderConfig = config()
    window_declarations: ProductWindowDeclarations = window_declarations()
    shared_acquisition_products: tuple[frozenset[ProductId], ...] = SHARED_DAILY_PRODUCTS
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)
    parse_group = staticmethod(parse_group)


def _envelope(
    url: str,
    body: bytes | object,
    *,
    status: int = 200,
    content_type: str = "application/json",
) -> RecordingEnvelope:
    return RecordingEnvelope(
        request=RecordedRequest(
            HttpMethod.GET,
            url,
            None,
            ordinary_headers={"User-Agent": TRANSPORT_POLICY.user_agent},
        ),
        content=body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"),
        status_code=status,
        retrieved_at=_RETRIEVED_AT,
        content_type=content_type,
    )


def _zip_bytes(
    *,
    station: str = "01041",
    parameter: str = "Q",
    ts_shortname: str = "WEB.Cmd.Runoff",
    unit: str = "cumec",
    rows_count: int | None = None,
    lines: tuple[str, ...] = (),
    tz_line: str | None = None,
    member_name: str = "tsvalues.csv",
) -> bytes:
    header = [
        "#station_name;Sandy Mills",
        f"#station_no;{station}",
        "#station_latitude;54.83831806",
        "#station_longitude;-7.575758056",
        f"#stationparameter_name;{parameter}",
        f"#ts_shortname;{ts_shortname}",
        f"#ts_unitsymbol;{unit}",
        "#WTO_OBJECT;DEELE",
        "#RBD;NORTH WESTERN RBD",
    ]
    if tz_line is not None:
        header.append(tz_line)
    count = len(lines) if rows_count is None else rows_count
    header.append(f"#rows;{count}")
    header.append("#Timestamp;Value;Quality Code")
    csv_text = "\n".join([*header, *lines]) + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member_name, csv_text.encode("utf-8"))
    return buf.getvalue()


def _origin(url: str) -> SourceCallOrigin:
    return SourceCallOrigin(
        url=url,
        request_parameters={},
        status_code=200,
        retrieved_at=_RETRIEVED_AT,
        content_type="application/json",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )


def test_config_window_declarations_and_coordinates_cover_all_12_products() -> None:
    cfg = config()
    win_decls = window_declarations()
    assert cfg.zone == ZoneValue("+00:00")
    assert len(cfg.products) == 12
    assert set(cfg.products) == {ProductId(spec.product_id) for spec in PRODUCT_SPECS}

    expected_units = {"cumec": Unit.M3_S, "m": Unit.M, "°C": Unit.DEG_C}
    for spec in PRODUCT_SPECS:
        pid = ProductId(spec.product_id)
        prod_cfg = cfg.products[pid]
        assert prod_cfg.unit == expected_units[spec.source_unit]
        if spec.route == "year.json":
            assert prod_cfg.coordinates.value == OpwDailyYearJsonCoordinates(
                spec.parameter, spec.ts_shortname, spec.product_id
            )
            assert prod_cfg.semantics == Daily(DayDefinition("00:00"), DailyLabelTime("00:00"))
        else:
            assert prod_cfg.coordinates.value == OpwCompleteZipCoordinates(
                spec.parameter, spec.route, spec.ts_shortname, spec.product_id
            )
            assert prod_cfg.semantics == Instant()
        decl = win_decls.products[pid]
        assert decl.granularity == WindowGranularity("none")
        assert decl.rendering == WindowRenderingVocabulary.NONE
        assert decl.stop_convention == StopConvention.INCLUSIVE
        assert decl.fetch_padding == timedelta(0)

    with pytest.raises(FatalContractError, match="Invalid ie_opw year.json coordinates"):
        OpwDailyYearJsonCoordinates("Q", "WEB.Day.Mean", "stage_daily_mean")
    with pytest.raises(FatalContractError, match="Invalid ie_opw complete.zip coordinates"):
        OpwCompleteZipCoordinates("Q", "Waterlevel_complete.zip", "WEB.Cmd.Runoff", "discharge_instantaneous")
    with pytest.raises(FatalContractError, match="Invalid ie_opw year.json parameter"):
        OpwDailyYearJsonEndpointCoordinates(cast("Any", "Rain"))


def test_source_series_matches_every_packaged_catalogue_series_id_and_facts_id() -> None:
    artifact = catalogue_reader("ie_opw").artifact
    assert artifact.station_products.height == 4620
    materialized, _ = catalogue_series(artifact, scope=SeriesScope(provider_ids=("ie_opw",)))
    assert len(materialized) == 4572

    for cat_item in materialized:
        runtime_item = source_series(cat_item.station_id, cat_item.product_id)
        assert runtime_item.series_id == cat_item.series_id
        assert runtime_item.series_id == stable_id(
            "ie_opw", cat_item.station_id, runtime_item.identity.namespace, runtime_item.identity.published_id
        )
        assert runtime_item.facts == cat_item.facts
        assert runtime_item.facts[0].facts_id == cat_item.facts[0].facts_id


def test_station_validation_url_builders_and_fetch_grouping_contracts() -> None:
    validate_station_id("01041")
    validate_station_id("00001")
    validate_station_id("41000")
    assert (
        daily_year_json_url("01041", "Q")
        == "https://waterlevel.ie/hydro-data/data/internet/stations/0/01041/Q/year.json"
    )
    assert (
        complete_zip_url("30061", "S")
        == "https://waterlevel.ie/hydro-data/data/internet/stations/0/30061/S/Waterlevel_complete.zip"
    )

    for bad_station in ("80101", "00000", "41001", "1041", "0104A", "../01041"):
        with pytest.raises(FatalContractError):
            validate_station_id(bad_station)

    fw = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2025, 1, 5, 23, 59, 59, 999999)),
    )
    cfg = config()

    with pytest.raises(FatalContractError, match="requires at least one station and product"):
        fetch((), (ProductId("discharge_daily_mean"),), {}, fw, cfg, ReplayTransport(()))
    with pytest.raises(FatalContractError, match="absent from provider config"):
        fetch(("01041",), (ProductId("bogus"),), {}, fw, cfg, ReplayTransport(()))
    with pytest.raises(FatalContractError, match="unexpected rendered windows"):
        fetch(
            ("01041",),
            (ProductId("discharge_daily_mean"),),
            cast("Any", {ProductId("discharge_daily_mean"): (object(),)}),
            fw,
            cfg,
            ReplayTransport(()),
        )

    class _MixedFailTransport:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.urls.append(request.url)
            if "/TWater/" in request.url:
                raise TransportFailure(
                    request,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=404,
                    category=TransportFailureCategory.HTTP_STATUS,
                )
            return TransportResponse(
                content=b"[]",
                status_code=200,
                retrieved_at=_RETRIEVED_AT,
                content_type="application/json",
                url=request.url,
                request_parameters={},
            )

    transport = _MixedFailTransport()
    acq = fetch(
        ("01041",),
        (
            ProductId("discharge_daily_mean"),
            ProductId("discharge_daily_min"),
            ProductId("discharge_daily_max"),
            ProductId("water_temperature_daily_mean"),
            ProductId("water_temperature_daily_max"),
            ProductId("stage_instantaneous"),
        ),
        {},
        fw,
        cfg,
        transport,
        known_series=(source_series("01041", "discharge_daily_mean", origin="catalogue"),),
    )
    assert transport.urls == [
        "https://waterlevel.ie/hydro-data/data/internet/stations/0/01041/Q/year.json",
        "https://waterlevel.ie/hydro-data/data/internet/stations/0/01041/TWater/year.json",
        "https://waterlevel.ie/hydro-data/data/internet/stations/0/01041/S/Waterlevel_complete.zip",
    ]
    assert len(acq.value) == 2
    assert acq.value[0].source_coordinates.value == OpwDailyYearJsonEndpointCoordinates("Q")
    assert len(acq.failed_requests) == 2
    assert {item.series.product_id for item in acq.failed_requests} == {
        "water_temperature_daily_mean",
        "water_temperature_daily_max",
    }


def test_shared_daily_triplet_decodes_once_caches_subset_and_preserves_unmeasured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    decode_calls = 0
    real_decode = ie_parse_mod._decode_year_json_blocks

    def counting_decode(content: bytes) -> Any:
        nonlocal decode_calls
        decode_calls += 1
        return real_decode(content)

    monkeypatch.setattr(ie_parse_mod, "_decode_year_json_blocks", counting_decode)

    stage_url = daily_year_json_url("30061", "S")
    stage_payload = [
        {
            "stationparameter_name": "S",
            "ts_shortname": "WEB.Day.Mean",
            "ts_unitsymbol": "m",
            "rows": "3",
            "columns": "Timestamp,Value,Quality Code,Aggregation Accuracy %",
            "data": [
                ["2025-07-16T00:00:00.000Z", -0.249, 31, 100.0],
                ["2025-07-15T00:00:00.000Z", None, -1, 0.0],
                ["2025-07-14T00:00:00.000Z", 0.125, 254, 98.5],
            ],
        },
        {
            "stationparameter_name": "S",
            "ts_shortname": "WEB.Day.Min",
            "ts_unitsymbol": "m",
            "rows": "3",
            "columns": "Timestamp,Value,Quality Code,Aggregation Accuracy %",
            "data": [
                ["2025-07-14T00:00:00.000Z", 0.10, 31, 100.0],
                ["2025-07-15T00:00:00.000Z", None, -1, 0.0],
                ["2025-07-16T00:00:00.000Z", -0.30, 31, 100.0],
            ],
        },
        {
            "stationparameter_name": "S",
            "ts_shortname": "WEB.Day.Max",
            "ts_unitsymbol": "m",
            "rows": "3",
            "columns": "Timestamp,Value,Quality Code,Aggregation Accuracy %",
            "data": [
                ["2025-07-14T00:00:00.000Z", 0.20, 31, 100.0],
                ["2025-07-15T00:00:00.000Z", None, -1, 0.0],
                ["2025-07-16T00:00:00.000Z", -0.20, 31, 100.0],
            ],
        },
    ]
    req_all = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("30061",),
        products=(
            ProductId("stage_daily_mean"),
            ProductId("stage_daily_min"),
            ProductId("stage_daily_max"),
        ),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 7, 13)),
            WindowEndpoint.from_datetime(datetime(2025, 7, 17)),
        ),
        known_series=tuple(
            source_series("30061", pid, origin="catalogue")
            for pid in ("stage_daily_mean", "stage_daily_min", "stage_daily_max")
        ),
    )
    store = StoreRoot(tmp_path / "store")
    res = drive(
        req_all,
        _IeOpwStages(),
        provenance=_provenance(req_all),
        receipts=ReceiptMode.OMIT,
        transport=ReplayTransport((_envelope(stage_url, stage_payload),)),
        cache="reuse",
        store=store,
    )
    assert decode_calls == 1
    assert res.canonical_rows.height == 6
    mean_rows = res.canonical_rows.filter(pl.col("product_id") == "stage_daily_mean")
    assert mean_rows["time"].to_list() == [datetime(2025, 7, 14), datetime(2025, 7, 16)]
    assert mean_rows["value"].to_list() == pytest.approx([0.125, -0.249])

    ann = res.annotations.observation_tables[IE_OPW_DAILY_STAGE_SCHEMA.schema_id]
    assert ann.row_count == 9
    assert ann.unmeasured_count == 3
    mean_ann = ann.rows.filter(pl.col("product_id") == "stage_daily_mean")
    assert mean_ann["measured"].to_list() == [True, False, True]
    assert mean_ann["quality_code"].to_list() == [254, -1, 31]
    assert mean_ann["aggregation_accuracy_pct"].to_list() == pytest.approx([98.5, 0.0, 100.0])

    # Pre/post windows outside [2025-07-14, 2025-07-16] emit UNRESOLVED alongside interval SUCCESS.
    assert any(o.status is OutcomeStatus.SUCCESS and o.coverage == "interval" for o in res.outcomes)
    assert len([o for o in res.outcomes if o.status is OutcomeStatus.UNRESOLVED]) == 6

    # Re-querying a single subset product inside [2025-07-14, 2025-07-16] uses cache offline (0 HTTP, 0 JSON decodes).
    req_sub = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("30061",),
        products=(ProductId("stage_daily_max"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 7, 14)),
            WindowEndpoint.from_datetime(datetime(2025, 7, 16, 23, 59, 59, 999999)),
        ),
    )
    res_sub = drive(
        req_sub,
        _IeOpwStages(),
        provenance=_provenance(req_sub),
        receipts=ReceiptMode.OMIT,
        transport=ReplayTransport(()),
        cache="reuse",
        store=store,
    )
    assert decode_calls == 1
    assert res_sub.canonical_rows["value"].to_list() == pytest.approx([0.20, -0.20])
    sub_ann = res_sub.annotations.observation_tables[IE_OPW_DAILY_STAGE_SCHEMA.schema_id]
    assert sub_ann.unmeasured_count == 1
    assert sub_ann.rows["quality_code"].to_list() == [31, -1, 31]


def test_all_null_unmeasured_series_empty_arrays_and_complete_zip_unmeasured(tmp_path: Path) -> None:
    # 1. All-null year.json block (06015 pattern) -> OutcomeStatus.EMPTY, caches cleanly; data=[] -> UNRESOLVED.
    q_url = daily_year_json_url("06015", "Q")
    q_payload = [
        {
            "stationparameter_name": "Q",
            "ts_shortname": "WEB.Day.Mean",
            "ts_unitsymbol": "cumec",
            "rows": "2",
            "columns": "Timestamp,Value,Quality Code",
            "data": [
                ["2020-01-01T00:00:00.000Z", None, -1],
                ["2020-01-02T00:00:00.000Z", None, 255],
            ],
        },
        {
            "stationparameter_name": "Q",
            "ts_shortname": "WEB.Day.Min",
            "ts_unitsymbol": "cumec",
            "rows": "0",
            "columns": "Timestamp,Value,Quality Code",
            "data": [],
        },
        {
            "stationparameter_name": "Q",
            "ts_shortname": "WEB.Day.Max",
            "ts_unitsymbol": "cumec",
            "rows": "0",
            "columns": "Timestamp,Value,Quality Code",
            "data": [],
        },
    ]
    store = StoreRoot(tmp_path / "store-nulls")
    req_mean = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("06015",),
        products=(ProductId("discharge_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2020, 1, 2, 23, 59, 59, 999999)),
        ),
    )
    res_mean = drive(
        req_mean,
        _IeOpwStages(),
        provenance=_provenance(req_mean),
        receipts=ReceiptMode.OMIT,
        transport=ReplayTransport((_envelope(q_url, q_payload),)),
        cache="reuse",
        store=store,
    )
    assert res_mean.canonical_rows.is_empty()
    assert [o.status for o in res_mean.outcomes] == [OutcomeStatus.EMPTY]
    assert res_mean.annotations.observation_tables[IE_OPW_SERIES_SCHEMA.schema_id].unmeasured_count == 2
    res_mean_cached = drive(
        req_mean,
        _IeOpwStages(),
        provenance=_provenance(req_mean),
        receipts=ReceiptMode.OMIT,
        transport=ReplayTransport(()),
        cache="reuse",
        store=store,
    )
    assert res_mean_cached.canonical_rows.is_empty()
    assert res_mean_cached.annotations.observation_tables[IE_OPW_SERIES_SCHEMA.schema_id].rows[
        "quality_code"
    ].to_list() == [
        -1,
        255,
    ]

    # Empty data=[] must emit UNRESOLVED / INCOMPLETE and never lock an eternal empty cache.
    req_min = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("06015",),
        products=(ProductId("discharge_daily_min"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2020, 1, 2)),
        ),
    )
    res_min = drive(
        req_min,
        _IeOpwStages(),
        provenance=_provenance(req_min),
        receipts=ReceiptMode.OMIT,
        transport=ReplayTransport((_envelope(q_url, q_payload),)),
        cache="reuse",
        store=store,
    )
    assert [o.status for o in res_min.outcomes] == [OutcomeStatus.UNRESOLVED]
    assert res_min.inventories[0].completeness is InventoryCompleteness.INCOMPLETE

    # 2. Complete ZIP with unmeasured ;;-1 slots and #rows;0 empty zip.
    zip_tw_url = complete_zip_url("14124", "TWater")
    zip_tw = _zip_bytes(
        station="14124",
        parameter="TWater",
        ts_shortname="WEB.Cmd.P-Water-Temp",
        unit="°C",
        lines=(
            "2022-08-14T00:00:00.000Z;;-1",
            "2022-08-14T01:00:00.000Z;14.2;254",
        ),
    )
    zip_empty_q = _zip_bytes(station="06025", parameter="Q", ts_shortname="WEB.Cmd.Runoff", unit="cumec", lines=())
    req_tw = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("14124",),
        products=(ProductId("water_temperature_instantaneous"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2022, 8, 14, 0, 0)),
            WindowEndpoint.from_datetime(datetime(2022, 8, 14, 1, 0)),
        ),
    )
    res_tw = drive(
        req_tw,
        _IeOpwStages(),
        provenance=_provenance(req_tw),
        receipts=ReceiptMode.OMIT,
        transport=ReplayTransport((_envelope(zip_tw_url, zip_tw, content_type="application/zip"),)),
        cache="bypass",
    )
    assert res_tw.canonical_rows["value"].to_list() == pytest.approx([14.2])
    tw_ann = res_tw.annotations.observation_tables[IE_OPW_SERIES_SCHEMA.schema_id]
    assert tw_ann.rows["measured"].to_list() == [False, True]
    assert tw_ann.rows["quality_code"].to_list() == [-1, 254]

    req_empty_zip = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("06025",),
        products=(ProductId("discharge_instantaneous"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2022, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2022, 1, 2)),
        ),
    )
    res_empty_zip = drive(
        req_empty_zip,
        _IeOpwStages(),
        provenance=_provenance(req_empty_zip),
        receipts=ReceiptMode.OMIT,
        transport=ReplayTransport(
            (_envelope(complete_zip_url("06025", "Q"), zip_empty_q, content_type="application/zip"),)
        ),
        cache="bypass",
    )
    assert [o.status for o in res_empty_zip.outcomes] == [OutcomeStatus.UNRESOLVED]


def test_parse_strictness_unit_bool_nonfinite_and_per_product_isolation() -> None:
    cfg = config()
    fw = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2025, 1, 5)),
    )
    q_url = daily_year_json_url("01041", "Q")

    # Isolated failure inside parse_group: WEB.Day.Mean valid, WEB.Day.Min wrong unit, WEB.Day.Max missing.
    mixed_json = [
        {
            "stationparameter_name": "Q",
            "ts_shortname": "WEB.Day.Mean",
            "ts_unitsymbol": "cumec",
            "rows": "1",
            "columns": "Timestamp,Value,Quality Code",
            "data": [["2025-01-01T00:00:00.000Z", 1.5, 36]],
        },
        {
            "stationparameter_name": "Q",
            "ts_shortname": "WEB.Day.Min",
            "ts_unitsymbol": "l/s",
            "rows": "1",
            "columns": "Timestamp,Value,Quality Code",
            "data": [["2025-01-01T00:00:00.000Z", 1500.0, 36]],
        },
    ]
    req = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("01041",),
        products=(
            ProductId("discharge_daily_mean"),
            ProductId("discharge_daily_min"),
            ProductId("discharge_daily_max"),
        ),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2025, 1, 1, 23, 59, 59)),
        ),
    )
    res = drive(
        req,
        _IeOpwStages(),
        provenance=_provenance(req),
        receipts=ReceiptMode.OMIT,
        transport=ReplayTransport((_envelope(q_url, mixed_json),)),
        cache="bypass",
    )
    assert res.canonical_rows["product_id"].to_list() == ["discharge_daily_mean"]
    by_prod = {o.product_id: o.status for o in res.outcomes}
    assert by_prod == {
        "discharge_daily_mean": OutcomeStatus.SUCCESS,
        "discharge_daily_min": OutcomeStatus.FAILED,
        "discharge_daily_max": OutcomeStatus.NO_MATCH,
    }

    # Strict malformed payload checks never leak exceptions out of parse().
    bad_json_cases: list[bytes] = [
        b"{not-json",
        b"{}",
        json.dumps(
            [
                {
                    "stationparameter_name": "Q",
                    "ts_shortname": "WEB.Day.Mean",
                    "ts_unitsymbol": "cumec",
                    "columns": "Timestamp,Value,Quality Code",
                    "data": [["2025-01-01T00:00:00.000Z", True, 36]],
                }
            ]
        ).encode(),
        json.dumps(
            [
                {
                    "stationparameter_name": "Q",
                    "ts_shortname": "WEB.Day.Mean",
                    "ts_unitsymbol": "cumec",
                    "columns": "Timestamp,Value,Quality Code",
                    "data": [["2025-01-01T00:00:00.000Z", 1.0, True]],
                }
            ]
        ).encode(),
        json.dumps(
            [
                {
                    "stationparameter_name": "Q",
                    "ts_shortname": "WEB.Day.Mean",
                    "ts_unitsymbol": "cumec",
                    "columns": "Timestamp,Value,Quality Code",
                    "data": [["2025-01-01T00:00:00.000Z", 1.0, 36.5]],
                }
            ]
        ).encode(),
        json.dumps(
            [
                {
                    "stationparameter_name": "Q",
                    "ts_shortname": "WEB.Day.Mean",
                    "ts_unitsymbol": "cumec",
                    "columns": "Timestamp,Value,Quality Code",
                    "data": [["2025-01-01T01:00:00.000Z", 1.0, 36]],
                }
            ]
        ).encode(),
        json.dumps(
            [
                {
                    "stationparameter_name": "Q",
                    "ts_shortname": "WEB.Day.Mean",
                    "ts_unitsymbol": "cumec",
                    "columns": "Timestamp,Value,Quality Code",
                    "data": [["2025-01-01T00:00:00.000Z", 1.0, 36], ["2025-01-01T00:00:00.000Z", 2.0, 36]],
                }
            ]
        ).encode(),
        b'[{"stationparameter_name":"Q","ts_shortname":"WEB.Day.Mean","ts_unitsymbol":"cumec","columns":"Timestamp,Value,Quality Code","data":[["2025-01-01T00:00:00.000Z",NaN,36]]}]',
    ]
    for raw_bad in bad_json_cases:
        parsed = parse(
            Payload(
                source_coordinates=cfg.products[ProductId("discharge_daily_mean")].coordinates,
                station_products=(("01041", ProductId("discharge_daily_mean")),),
                fetch_window=fw,
                content=raw_bad,
                origin=_origin(q_url),
                prerequisite_calls=(),
            ),
            cfg,
        )
        assert parsed.rows.is_empty()
        assert parsed.outcomes[0].status is OutcomeStatus.FAILED
        assert parsed.issues[0].code == "source.unsupported_structure"

    # Malformed ZIP checks
    zip_url = complete_zip_url("01041", "Q")
    bad_zip_cases: list[bytes] = [
        b"not-a-zip",
        _zip_bytes(member_name="wrong.csv", lines=("2025-01-01T00:00:00.000Z;1.0;36",)),
        _zip_bytes(station="99999", lines=("2025-01-01T00:00:00.000Z;1.0;36",)),
        _zip_bytes(unit="l/s", lines=("2025-01-01T00:00:00.000Z;1.0;36",)),
        _zip_bytes(tz_line="#tz;UTC+1", lines=("2025-01-01T00:00:00.000Z;1.0;36",)),
        _zip_bytes(rows_count=2, lines=("2025-01-01T00:00:00.000Z;1.0;36",)),
        _zip_bytes(lines=("2025-01-01T00:00:00.000Z;NaN;36",)),
        _zip_bytes(lines=("2025-01-01T00:00:00.000Z;1.0;36.5",)),
        _zip_bytes(lines=("2025-01-01T00:00:00.000Z;1.0;36", "2025-01-01T00:00:00.000Z;2.0;36")),
    ]
    for raw_bad_zip in bad_zip_cases:
        parsed_zip = parse(
            Payload(
                source_coordinates=cfg.products[ProductId("discharge_instantaneous")].coordinates,
                station_products=(("01041", ProductId("discharge_instantaneous")),),
                fetch_window=fw,
                content=raw_bad_zip,
                origin=_origin(zip_url),
                prerequisite_calls=(),
            ),
            cfg,
        )
        assert parsed_zip.rows.is_empty()
        assert parsed_zip.outcomes[0].status is OutcomeStatus.FAILED
        assert parsed_zip.issues[0].code == "source.unsupported_structure"

    # Mismatched origin URL rejected as FAILED outcome.
    mismatch_parsed = parse(
        Payload(
            source_coordinates=cfg.products[ProductId("discharge_daily_mean")].coordinates,
            station_products=(("01041", ProductId("discharge_daily_mean")),),
            fetch_window=fw,
            content=json.dumps(mixed_json[:1]).encode(),
            origin=_origin(daily_year_json_url("07012", "Q")),
            prerequisite_calls=(),
        ),
        cfg,
    )
    assert mismatch_parsed.outcomes[0].status is OutcomeStatus.FAILED
