"""Recorded genuine-source tests for NRFA Step 4 retrieval behavior (#594)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal import driver as driver_module
from rivretrieve._internal.engine import (
    ObservationRequest,
    RenderedWindow,
    RequestedWindow,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ObservationProvenance, ObservationResult, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.uk_nrfa.config import (
    SHARED_ACQUISITION_PRODUCTS,
    config,
    window_declarations,
)
from rivretrieve._internal.providers.uk_nrfa.fetch import fetch
from rivretrieve._internal.providers.uk_nrfa.parse import parse
from rivretrieve._internal.providers.uk_nrfa.series import PEAK_REJECTED_PERIOD_PRODUCTS, decode_time_series_response
from rivretrieve._internal.source_acquisition import SourceResponseMeaning
from rivretrieve._internal.source_annotations import with_annotations
from rivretrieve._internal.source_series import InventoryCompleteness, OutcomeStatus
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
    _SystemClock,
)
from rivretrieve._internal.window_planning import plan_windows

_EVIDENCE_SCOPE = "maintenance/observations/uk_nrfa/retrieval"
_VERIFICATION_SCOPE = "maintenance/observations/uk_nrfa/verification"


def _nrfa_stages():
    resolved_config = config()
    resolved_windows = window_declarations()

    class _Stages:
        observation_source = "live"
        config = resolved_config
        window_declarations = resolved_windows
        shared_acquisition_products = SHARED_ACQUISITION_PRODUCTS
        fetch = staticmethod(fetch)
        parse = staticmethod(parse)

    return _Stages


def _content_type(receipt: dict[str, Any]) -> str | None:
    headers = receipt.get("headers") or {}
    for key, value in headers.items():
        if str(key).lower() == "content-type":
            return str(value)
    return None


class _ExactReceiptReplay:
    """Replay retained NRFA HTTP responses only when URL path and query params match."""

    def __init__(self, entries: tuple[tuple[Path, Path], ...]) -> None:
        self._records: list[tuple[tuple[str, str, str], dict[str, str], bytes, dict[str, Any]]] = []
        for body_path, receipt_path in entries:
            body = body_path.read_bytes()
            receipt = json.loads(receipt_path.read_bytes())
            parts = urlsplit(str(receipt["url"]))
            params = dict(parse_qsl(parts.query, keep_blank_values=True))
            self._records.append(((parts.scheme, parts.netloc, parts.path), params, body, receipt))
        self.calls: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        req_url = urlsplit(request.url)
        req_key = (req_url.scheme, req_url.netloc, req_url.path)
        req_params = {str(k): str(v) for k, v in (request.params or {}).items()}
        for rec_key, rec_params, body, receipt in self._records:
            if req_key == rec_key and req_params == rec_params:
                self.calls.append(request)
                status = int(receipt["status"])
                response = TransportResponse(
                    status_code=status,
                    content=body,
                    url=str(receipt["url"]),
                    request_parameters=rec_params,
                    retrieved_at=datetime.fromisoformat(str(receipt["retrieved_at"])),
                    content_type=_content_type(receipt),
                )
                if status >= 400:
                    raise TransportFailure(
                        request,
                        TransportFailureReason.HTTP_STATUS,
                        1,
                        status_code=status,
                        category=TransportFailureCategory.HTTP_STATUS,
                        response=response,
                    )
                return response
        raise AssertionError(
            f"Unexpected request without matching retained receipt: {request.url} params={req_params!r}"
        )


def _pair(root: Path, filename: str) -> tuple[Path, Path]:
    return root / filename, root / (filename + ".receipt.json")


@pytest.mark.recorded(_EVIDENCE_SCOPE)
@pytest.mark.parametrize(
    ("station", "product", "filename", "info_filename", "start", "end", "expected_status", "min_rows"),
    [
        (
            "39001",
            "gdf",
            "gdf-39001-2020-01.json",
            None,
            datetime(2020, 1, 1),
            datetime(2020, 1, 5, 23, 59, 59),
            OutcomeStatus.SUCCESS,
            1,
        ),
        (
            "39001",
            "ndf",
            "ndf-39001-1995-01.json",
            None,
            datetime(1995, 1, 1),
            datetime(1995, 1, 10, 23, 59, 59),
            OutcomeStatus.SUCCESS,
            1,
        ),
        (
            "39001",
            "gmf",
            "gmf-39001-full.json",
            None,
            datetime(1883, 1, 1),
            datetime(2025, 12, 31, 23, 59, 59),
            OutcomeStatus.SUCCESS,
            100,
        ),
        (
            "39001",
            "nmf",
            "nmf-39001-full.json",
            None,
            datetime(1883, 1, 1),
            datetime(2025, 12, 31, 23, 59, 59),
            OutcomeStatus.SUCCESS,
            100,
        ),
        (
            "39001",
            "gauging-flow",
            "gauging-flow-39001-2024-07-09.json",
            None,
            datetime(2024, 7, 9),
            datetime(2024, 7, 9, 23, 59, 59),
            OutcomeStatus.SUCCESS,
            1,
        ),
        (
            "39001",
            "gauging-stage",
            "gauging-stage-39001-2024-07-09.json",
            None,
            datetime(2024, 7, 9),
            datetime(2024, 7, 9, 23, 59, 59),
            OutcomeStatus.SUCCESS,
            1,
        ),
        (
            "82001",
            "amax-flow",
            "amax-flow-82001-1962-1985.json",
            "station-info-peak-82001.json",
            datetime(1962, 1, 1),
            datetime(1985, 12, 31, 23, 59, 59),
            OutcomeStatus.SUCCESS,
            1,
        ),
        (
            "6007",
            "amax-stage",
            "amax-stage-6007-2024-12-31.json",
            "station-info-peak-6007.json",
            datetime(2024, 12, 31),
            datetime(2024, 12, 31, 23, 59, 59),
            OutcomeStatus.SUCCESS,
            1,
        ),
        (
            "39001",
            "pot-flow",
            "pot-flow-39001-1883-2025.json",
            "station-info-peak-39001.json",
            datetime(1883, 1, 1),
            datetime(2025, 12, 31, 23, 59, 59),
            OutcomeStatus.SUCCESS,
            100,
        ),
        (
            "82001",
            "pot-stage",
            "pot-stage-82001-1962-1985.json",
            "station-info-peak-82001.json",
            datetime(1962, 1, 1),
            datetime(1985, 12, 31, 23, 59, 59),
            OutcomeStatus.SUCCESS,
            1,
        ),
        (
            "39001",
            "gdf",
            "empty-window-gdf-39001-2035.json",
            None,
            datetime(2035, 1, 1),
            datetime(2035, 12, 31, 23, 59, 59),
            OutcomeStatus.EMPTY,
            0,
        ),
        (
            "6007",
            "ndf",
            "unadvertised-ndf-6007-2020.json",
            None,
            datetime(2020, 1, 1),
            datetime(2020, 12, 31, 23, 59, 59),
            OutcomeStatus.EMPTY,
            0,
        ),
    ],
)
def test_recorded_exact_replay_covers_all_ten_products_and_empty_responses(
    retained_evidence_root: Path,
    station: str,
    product: str,
    filename: str,
    info_filename: str | None,
    start: datetime,
    end: datetime,
    expected_status: OutcomeStatus,
    min_rows: int,
) -> None:
    root = retained_evidence_root / _EVIDENCE_SCOPE
    entries = [_pair(root, filename)]
    if info_filename is not None:
        entries.append(_pair(root, info_filename))
    replay = _ExactReceiptReplay(tuple(entries))

    cfg = config()
    decls = window_declarations()
    fw = _make_fetch_window(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end))
    pid = ProductId(product)
    rendered = {pid: plan_windows(fw, decls.products[pid])}

    acquired = fetch((station,), (pid,), rendered, fw, cfg, replay)
    assert not acquired.failed_requests
    assert len(acquired.value) == (2 if info_filename is not None else 1)

    parsed_parts = [parse(payload, cfg) for payload in acquired.value]
    non_empty = [part for part in parsed_parts if part.outcomes]
    assert len(non_empty) == 1
    parsed = non_empty[0]
    assert parsed.outcomes[0].status is expected_status
    assert parsed.inventories[0].completeness is InventoryCompleteness.COMPLETE
    assert parsed.issues == ()
    assert parsed.rows.height >= min_rows
    assert set(parsed.rows["time_zone"]) <= {"unknown"}


@pytest.mark.recorded(_EVIDENCE_SCOPE, _VERIFICATION_SCOPE)
def test_recorded_drive_all_ten_products_peak_rejections_and_monthly_boundary(retained_evidence_root: Path) -> None:
    root = retained_evidence_root / _EVIDENCE_SCOPE
    verif_root = retained_evidence_root / _VERIFICATION_SCOPE
    stages = _nrfa_stages()

    # Verify gmf unwindowed acquisition retains 2020-02 and 2020-03 where partial-end-date query lost 2020-03.
    _, partial_rows, partial_bundle = decode_time_series_response(
        json.loads((root / "gmf-39001-partial-end-loss.json").read_bytes()),
        expected_station_id="39001",
        expected_product_id="gmf",
    )
    assert partial_rows["time"].dt.strftime("%Y-%m").to_list() == ["2020-01", "2020-02"]
    del partial_bundle

    replay_gmf = _ExactReceiptReplay((_pair(root, "gmf-39001-full.json"), _pair(root, "nmf-39001-full.json")))
    for product in ("gmf", "nmf"):
        req = ObservationRequest(
            ProviderId("uk_nrfa"),
            ("39001",),
            (ProductId(product),),
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2020, 1, 15, 0, 0, 0)),
                WindowEndpoint.from_datetime(datetime(2020, 3, 15, 0, 0, 0)),
            ),
        )
        out = driver_module.drive(
            req,
            stages,
            provenance=ObservationProvenance(source="recorded", provider_id=ProviderId("uk_nrfa"), request={}),
            transport=replay_gmf,
        )
        assert "start-date" not in (replay_gmf.calls[-1].params or {})
        assert out.annotations.schema_table("uk_nrfa.observations")["source_label"].to_list() == ["2020-02", "2020-03"]

    # Peak metadata annotations attach faithfully on 82001, 6007, and 39001 without filtering measurements.
    replay_82001 = _ExactReceiptReplay(
        (
            _pair(root, "station-info-peak-82001.json"),
            _pair(root, "amax-flow-82001-1962-1985.json"),
            _pair(root, "pot-stage-82001-1962-1985.json"),
        )
    )
    req_82001 = ObservationRequest(
        ProviderId("uk_nrfa"),
        ("82001",),
        (ProductId("amax-flow"), ProductId("pot-stage")),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1962, 1, 3)),
            WindowEndpoint.from_datetime(datetime(1985, 12, 29, 23, 59, 59)),
        ),
    )
    out_82001 = driver_module.drive(
        req_82001,
        stages,
        provenance=ObservationProvenance(source="recorded", provider_id=ProviderId("uk_nrfa"), request={}),
        receipts=ReceiptMode.INCLUDE,
        transport=replay_82001,
    )
    assert len(replay_82001.calls) == 3
    result_82001 = with_annotations(
        ObservationResult(
            data=out_82001.canonical_rows,
            source_series=out_82001.source_series,
            inventories=out_82001.inventories,
            outcomes=out_82001.outcomes,
            supporting_outcomes=out_82001.supporting_outcomes,
            scope=out_82001.scope,
            provenance=out_82001.provenance,
            issues=out_82001.issues,
            receipts=out_82001.receipts,
        ),
        out_82001.annotations,
    )
    series_82001 = {row["product_id"]: row for row in rr.series(result_82001, annotations=True).iter_rows(named=True)}
    assert 1962 in series_82001["amax-flow"]["rejected_amax_years"]
    assert "1963-09-05/1982-05-31" in series_82001["pot-stage"]["rejected_periods"]
    # Rejected years/periods do not suppress observations from that range.
    amax_years = result_82001.data.filter(pl.col("product_id") == "amax-flow")["time"].dt.year().to_list()
    assert 1964 in amax_years and 1964 in series_82001["amax-flow"]["rejected_amax_years"]
    pot_stage_times = result_82001.data.filter(pl.col("product_id") == "pot-stage")["time"].to_list()
    assert any(datetime(1963, 9, 5) <= dt <= datetime(1982, 5, 31) for dt in pot_stage_times)

    # Exercise remaining products (gdf, ndf, gauging-flow, gauging-stage) end-to-end through drive().
    replay_39001_other = _ExactReceiptReplay(
        (
            _pair(root, "gdf-39001-2020-01.json"),
            _pair(root, "ndf-39001-1995-01.json"),
            _pair(verif_root, "gauging-flow-39001-2024-07.json"),
            _pair(verif_root, "gauging-stage-39001-2024-07.json"),
        )
    )
    for prod, s_dt, e_dt, expected_unit in (
        ("gdf", datetime(2020, 1, 3), datetime(2020, 1, 3, 23, 59, 59), "m3/s"),
        ("ndf", datetime(1995, 1, 3), datetime(1995, 1, 8, 23, 59, 59), "m3/s"),
        ("gauging-flow", datetime(2024, 7, 9), datetime(2024, 7, 9, 23, 59, 59), "m3/s"),
        ("gauging-stage", datetime(2024, 7, 9), datetime(2024, 7, 9, 23, 59, 59), "m"),
    ):
        prod_req = ObservationRequest(
            ProviderId("uk_nrfa"),
            ("39001",),
            (ProductId(prod),),
            RequestedWindow(WindowEndpoint.from_datetime(s_dt), WindowEndpoint.from_datetime(e_dt)),
        )
        prod_out = driver_module.drive(
            prod_req,
            stages,
            provenance=ObservationProvenance(source="recorded", provider_id=ProviderId("uk_nrfa"), request={}),
            transport=replay_39001_other,
        )
        assert not prod_out.canonical_rows.is_empty()
        assert set(prod_out.canonical_rows["unit"]) == {expected_unit}
        assert set(prod_out.canonical_rows["time_zone"]) == {"unknown"}

    # Station 6007 amax-stage retains late-evening 22:30 event under microsecond RequestedWindow.
    replay_6007 = _ExactReceiptReplay(
        (
            _pair(verif_root, "station-info-peak-6007.json"),
            _pair(verif_root, "amax-stage-6007-2024-12.json"),
        )
    )
    req_6007 = ObservationRequest(
        ProviderId("uk_nrfa"),
        ("6007",),
        (ProductId("amax-stage"),),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 12, 31, 0, 0, 0, 1)),
            WindowEndpoint.from_datetime(datetime(2024, 12, 31, 23, 59, 59, 999999)),
        ),
    )
    out_6007 = driver_module.drive(
        req_6007,
        stages,
        provenance=ObservationProvenance(source="recorded", provider_id=ProviderId("uk_nrfa"), request={}),
        transport=replay_6007,
    )
    assert out_6007.canonical_rows["value"].to_list() == [2.757]
    assert out_6007.annotations.schema_table("uk_nrfa.observations")["source_label"].to_list() == [
        "2024-12-31T22:30:00"
    ]
    assert out_6007.annotations.schema_table("uk_nrfa.amax_rejection")["rejected_amax_years"].to_list() == [None]

    # Station 39001 peak metadata with excluded AMAX years + null rejected periods attaches to pot-flow.
    replay_39001 = _ExactReceiptReplay(
        (_pair(root, "station-info-peak-39001.json"), _pair(root, "pot-flow-39001-1883-2025.json"))
    )
    req_39001 = ObservationRequest(
        ProviderId("uk_nrfa"),
        ("39001",),
        (ProductId("pot-flow"),),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1883, 1, 3)),
            WindowEndpoint.from_datetime(datetime(2025, 12, 29, 23, 59, 59)),
        ),
    )
    out_39001 = driver_module.drive(
        req_39001,
        stages,
        provenance=ObservationProvenance(source="recorded", provider_id=ProviderId("uk_nrfa"), request={}),
        transport=replay_39001,
    )
    assert out_39001.canonical_rows.height == 535
    assert "uk_nrfa.amax_rejection" not in out_39001.annotations.series_tables
    assert set(PEAK_REJECTED_PERIOD_PRODUCTS) == {"amax-flow", "amax-stage", "pot-flow", "pot-stage"}


@pytest.mark.recorded(_EVIDENCE_SCOPE)
def test_recorded_partition_equivalence_and_gap_absence(retained_evidence_root: Path) -> None:
    root = retained_evidence_root / _EVIDENCE_SCOPE
    cfg = config()
    decls = window_declarations()

    def run_single(
        station: str, product: str, filename: str, start: datetime, end: datetime, info_file: str | None = None
    ):
        entries = [_pair(root, filename)]
        if info_file is not None:
            entries.append(_pair(root, info_file))
        replay = _ExactReceiptReplay(tuple(entries))
        fw = _make_fetch_window(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end))
        pid = ProductId(product)
        acquired = fetch((station,), (pid,), {pid: plan_windows(fw, decls.products[pid])}, fw, cfg, replay)
        assert not acquired.failed_requests
        for payload in acquired.value:
            parsed = parse(payload, cfg)
            if parsed.outcomes:
                return parsed
        raise AssertionError(f"Expected time-series parsed outcome for {filename}")

    gdf_full = run_single(
        "39001", "gdf", "gdf-39001-2018-2020.json", datetime(2018, 1, 1), datetime(2020, 12, 31, 23, 59, 59)
    )
    gdf_a = run_single(
        "39001", "gdf", "gdf-39001-2018-2019.json", datetime(2018, 1, 1), datetime(2019, 12, 31, 23, 59, 59)
    )
    gdf_b = run_single("39001", "gdf", "gdf-39001-2020.json", datetime(2020, 1, 1), datetime(2020, 12, 31, 23, 59, 59))
    assert gdf_full.rows.height == 1096
    pl_testing.assert_frame_equal(gdf_full.rows, pl.concat([gdf_a.rows, gdf_b.rows]))

    pot_full = run_single(
        "39001",
        "pot-flow",
        "pot-flow-39001-1883-2025.json",
        datetime(1883, 1, 1),
        datetime(2025, 12, 31, 23, 59, 59),
        "station-info-peak-39001.json",
    )
    pot_a = run_single(
        "39001",
        "pot-flow",
        "pot-flow-39001-1883-1970.json",
        datetime(1883, 1, 1),
        datetime(1970, 12, 31, 23, 59, 59),
        "station-info-peak-39001.json",
    )
    pot_b = run_single(
        "39001",
        "pot-flow",
        "pot-flow-39001-1971-2025.json",
        datetime(1971, 1, 1),
        datetime(2025, 12, 31, 23, 59, 59),
        "station-info-peak-39001.json",
    )
    assert pot_full.rows.height == 535
    pl_testing.assert_frame_equal(pot_full.rows, pl.concat([pot_a.rows, pot_b.rows]))

    # Absent date stays absent without fabricating null despite R5 interval header.
    gap = run_single(
        "39001", "gdf", "gdf-39001-gap-2024-09.json", datetime(2024, 9, 28), datetime(2024, 10, 2, 23, 59, 59)
    )
    assert gap.rows["time"].dt.strftime("%Y-%m-%d").to_list() == [
        "2024-09-28",
        "2024-09-29",
        "2024-10-01",
        "2024-10-02",
    ]


@pytest.mark.recorded(_EVIDENCE_SCOPE)
def test_recorded_failures_remain_distinct_from_empty_and_microseconds_never_rendered(
    retained_evidence_root: Path,
) -> None:
    root = retained_evidence_root / _EVIDENCE_SCOPE
    cfg = config()
    decls = window_declarations()

    # Invalid station HTTP 400 on /time-series and /station-info remain SourceResponseMeaning.UNSPECIFIED.
    replay_400_ts = _ExactReceiptReplay((_pair(root, "error-invalid-station-ts-999999.html"),))
    fw_400 = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2020, 1, 5, 23, 59, 59)),
    )
    failed_ts = fetch(
        ("999999",),
        (ProductId("gdf"),),
        {ProductId("gdf"): plan_windows(fw_400, decls.products[ProductId("gdf")])},
        fw_400,
        cfg,
        replay_400_ts,
    )
    assert not failed_ts.value
    assert len(failed_ts.failed_requests) == 1
    assert failed_ts.failed_requests[0].meaning is SourceResponseMeaning.UNSPECIFIED

    replay_400_info = _ExactReceiptReplay((_pair(root, "error-invalid-station-info-999999.html"),))
    failed_peak = fetch(
        ("999999",),
        (ProductId("amax-flow"),),
        {ProductId("amax-flow"): plan_windows(fw_400, decls.products[ProductId("amax-flow")])},
        fw_400,
        cfg,
        replay_400_info,
    )
    assert not failed_peak.value
    assert len(failed_peak.failed_requests) == 1
    assert failed_peak.failed_requests[0].meaning is SourceResponseMeaning.UNSPECIFIED

    # HTTP 200 0-byte reversed-date response is rejected as OutcomeStatus.FAILED rather than treated as empty.
    replay_rev = _ExactReceiptReplay((_pair(root, "error-reversed-dates-39001.bin"),))
    acquired_rev = fetch(
        ("39001",),
        (ProductId("gdf"),),
        {ProductId("gdf"): (RenderedWindow("2020-01-10", "2020-01-05"),)},
        fw_400,
        cfg,
        replay_rev,
    )
    assert len(acquired_rev.value) == 1
    parsed_rev = parse(acquired_rev.value[0], cfg)
    assert parsed_rev.outcomes[0].status is OutcomeStatus.FAILED
    assert parsed_rev.outcomes[0].series_id is None
    assert parsed_rev.issues[0].code == "source.unsupported_structure"

    # Window declarations render DATE strings (never microsecond timestamps like the retained 400 failure).
    micro_receipt = json.loads((root / "error-microsecond-date-39001.html.receipt.json").read_bytes())
    micro_params = dict(parse_qsl(urlsplit(str(micro_receipt["url"])).query))
    assert "." in micro_params["start-date"]
    micro_fw = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2020, 1, 1, 0, 0, 0, 1)),
        WindowEndpoint.from_datetime(datetime(2020, 1, 5, 23, 59, 59, 999999)),
    )
    planned = plan_windows(micro_fw, decls.products[ProductId("gdf")])
    assert planned == (RenderedWindow("2020-01-01", "2020-01-05"),)


@pytest.mark.usefixtures("reuse_packaged_catalogues")
@pytest.mark.recorded(_EVIDENCE_SCOPE, _VERIFICATION_SCOPE)
def test_recorded_public_fetch_across_all_ten_nrfa_products_and_shared_peaks(
    retained_evidence_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = retained_evidence_root / _EVIDENCE_SCOPE
    verif_root = retained_evidence_root / _VERIFICATION_SCOPE
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))

    cases: tuple[tuple[str, tuple[str, ...], str, str, tuple[tuple[Path, Path], ...], int], ...] = (
        ("39001", ("gdf",), "2020-01-03", "2020-01-03", (_pair(root, "gdf-39001-2020-01.json"),), 1),
        ("39001", ("ndf",), "1995-01-03", "1995-01-08", (_pair(root, "ndf-39001-1995-01.json"),), 1),
        ("39001", ("gmf",), "2020-01-01", "2020-03-31", (_pair(root, "gmf-39001-full.json"),), 1),
        ("39001", ("nmf",), "2020-01-01", "2020-03-31", (_pair(root, "nmf-39001-full.json"),), 1),
        (
            "39001",
            ("gauging-flow",),
            "2024-07-09",
            "2024-07-09",
            (_pair(verif_root, "gauging-flow-39001-2024-07.json"),),
            1,
        ),
        (
            "39001",
            ("gauging-stage",),
            "2024-07-09",
            "2024-07-09",
            (_pair(verif_root, "gauging-stage-39001-2024-07.json"),),
            1,
        ),
        (
            "39001",
            ("pot-flow",),
            "1883-01-03",
            "2025-12-29",
            (_pair(root, "station-info-peak-39001.json"), _pair(root, "pot-flow-39001-1883-2025.json")),
            2,
        ),
        (
            "82001",
            ("amax-flow", "pot-stage"),
            "1962-01-03",
            "1985-12-29",
            (
                _pair(root, "station-info-peak-82001.json"),
                _pair(root, "amax-flow-82001-1962-1985.json"),
                _pair(root, "pot-stage-82001-1962-1985.json"),
            ),
            3,
        ),
        (
            "6007",
            ("amax-stage",),
            "2024-12-31",
            "2024-12-31",
            (_pair(verif_root, "station-info-peak-6007.json"), _pair(verif_root, "amax-stage-6007-2024-12.json")),
            2,
        ),
    )

    observed_products: set[str] = set()
    for station, variants, start, end, entries, expected_calls in cases:
        replay = _ExactReceiptReplay(entries)
        monkeypatch.setattr(discovery, "HttpClient", lambda replay=replay: replay)
        selection = rr.pick(rr.find(provider="uk_nrfa", station=station), variant=list(variants))
        result = rr.fetch(selection, start=start, end=end, cache="bypass", receipts=True, on_issue="ignore")

        assert len(replay.calls) == expected_calls
        assert len(result.receipts.entries) == expected_calls
        assert set(result.data["product_id"].to_list()) == set(variants)
        assert set(result.data["station_id"].to_list()) == {station}
        assert set(result.data["time_zone"].to_list()) == {"unknown"}
        for variant in variants:
            observed_products.add(variant)
            expected_unit = "m" if variant.endswith("stage") else "m3/s"
            rows = result.data.filter(pl.col("product_id") == variant)
            assert set(rows["unit"].to_list()) == {expected_unit}
            assert set(rows["source_unit"].to_list()) == {expected_unit}

        meta = rr.annotations(result, schema="uk_nrfa.series_metadata")
        assert meta.height == len(variants)

        if station == "82001":
            # Only amax-flow attaches uk_nrfa.amax_rejection; both peak products attach peak_rejected_periods.
            assert [urlsplit(call.url).path for call in replay.calls].count("/nrfa/ws/station-info") == 1
            amax_rej = rr.annotations(result, schema="uk_nrfa.amax_rejection")
            assert amax_rej.height == 1
            assert amax_rej["rejected_amax_years"].to_list()[0]
            assert rr.series(result).filter(pl.col("series_id").is_in(amax_rej["series_id"].to_list()))[
                "product_id"
            ].to_list() == ["amax-flow"]
            periods_rej = rr.annotations(result, schema="uk_nrfa.peak_rejected_periods")
            assert periods_rej.height == 2
            assert set(
                rr.series(result)
                .filter(pl.col("series_id").is_in(periods_rej["series_id"].to_list()))["product_id"]
                .to_list()
            ) == {"amax-flow", "pot-stage"}
        elif station == "6007":
            amax_rej = rr.annotations(result, schema="uk_nrfa.amax_rejection")
            assert amax_rej.is_empty() or all(not years for years in amax_rej["rejected_amax_years"].to_list())

    assert len(observed_products) == 10


@pytest.mark.usefixtures("reuse_packaged_catalogues")
@pytest.mark.recorded(_EVIDENCE_SCOPE)
def test_recorded_public_gmf_unwindowed_preserves_trailing_partial_month_and_isolates_failure(
    retained_evidence_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = retained_evidence_root / _EVIDENCE_SCOPE
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))

    # Partial-end-month gmf (2020-01-15..2020-03-15) stays unwindowed and preserves 2020-02 and 2020-03.
    gmf_replay = _ExactReceiptReplay((_pair(root, "gmf-39001-full.json"),))
    monkeypatch.setattr(discovery, "HttpClient", lambda: gmf_replay)
    gmf_sel = rr.pick(rr.find(provider="uk_nrfa", station="39001"), variant="gmf")
    gmf_res = rr.fetch(gmf_sel, start="2020-01-15", end="2020-03-15", cache="bypass")
    assert gmf_res.data.sort("time")["time"].to_list() == [
        datetime(2020, 2, 1, 0, 0, 0),
        datetime(2020, 3, 1, 0, 0, 0),
    ]
    assert gmf_res.data.sort("time")["value"].to_list() == [230.0, 193.1]
    assert rr.annotations(gmf_res, schema="uk_nrfa.observations").sort("time")["source_label"].to_list() == [
        "2020-02",
        "2020-03",
    ]

    # Genuine gdf success remains intact when ndf replays a retained 0-byte failure witness under strict query matching.
    class _GdfOkNdfFailReplay(_ExactReceiptReplay):
        def __init__(self) -> None:
            super().__init__((_pair(root, "gdf-39001-2020-01.json"),))
            self._fail_body, self._fail_receipt = (
                root / "error-reversed-dates-39001.bin",
                root / "error-reversed-dates-39001.bin.receipt.json",
            )

        def send(self, request: TransportRequest) -> TransportResponse:
            params = {str(k): str(v) for k, v in (request.params or {}).items()}
            if params.get("data-type") == "ndf":
                self.calls.append(request)
                receipt = json.loads(self._fail_receipt.read_bytes())
                return TransportResponse(
                    status_code=int(receipt["status"]),
                    content=self._fail_body.read_bytes(),
                    url=request.url,
                    request_parameters=params,
                    retrieved_at=datetime.fromisoformat(str(receipt["retrieved_at"])),
                    content_type=_content_type(receipt),
                )
            return super().send(request)

    monkeypatch.setattr(discovery, "HttpClient", _GdfOkNdfFailReplay)
    pair_sel = rr.pick(rr.find(provider="uk_nrfa", station="39001"), variant=["gdf", "ndf"])
    partial = rr.fetch(pair_sel, start="2020-01-03", end="2020-01-03", cache="bypass", on_issue="ignore")
    assert set(partial.data["product_id"].to_list()) == {"gdf"}
    assert partial.data.height == 1
    assert partial.data["value"].to_list() == [130.7]
    outcomes = {
        outcome.product_id: outcome.status
        for outcome in partial.outcomes
        if outcome.status in (OutcomeStatus.SUCCESS, OutcomeStatus.FAILED)
    }
    assert outcomes == {"gdf": OutcomeStatus.SUCCESS, "ndf": OutcomeStatus.FAILED}
    assert any(issue.code == "source.unsupported_structure" for issue in partial.issues)


@pytest.mark.usefixtures("reuse_packaged_catalogues")
@pytest.mark.recorded(_EVIDENCE_SCOPE)
def test_recorded_public_thirty_day_cache_reuse_and_expiry_with_pinned_clock(
    retained_evidence_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = retained_evidence_root / _EVIDENCE_SCOPE
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))

    current_now = datetime(2026, 11, 17, 0, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(_SystemClock, "utcnow", lambda self: current_now)

    replay = _ExactReceiptReplay(
        (
            _pair(root, "station-info-peak-82001.json"),
            _pair(root, "amax-flow-82001-1962-1985.json"),
        )
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    sel = rr.pick(rr.find(provider="uk_nrfa", station="82001"), variant="amax-flow")

    initial = rr.fetch(sel, start="1962-01-03", end="1985-12-29", cache="reuse")
    assert len(replay.calls) == 2
    initial_height = initial.data.height
    assert initial_height == 22

    status_before = rr.cache_status("uk_nrfa")
    assert status_before.presence.value == "present"
    assert len(status_before.coverage) == 1
    audit_before = rr.audit_cache("uk_nrfa")
    assert audit_before.rows_checked == 22

    # Within 30 calendar days of 2026-11-16T13:47Z acquisition: cache hit with zero HTTP calls and intact annotations.
    replay.calls.clear()
    current_now = datetime(2026, 12, 16, 13, 0, 0, tzinfo=UTC)
    reused = rr.fetch(sel, start="1962-01-03", end="1985-12-29", cache="reuse")
    assert replay.calls == []
    pl_testing.assert_frame_equal(reused.data, initial.data)
    assert set(rr.annotations(reused)["schema"].to_list()) == {
        "uk_nrfa.observations",
        "uk_nrfa.series_metadata",
        "uk_nrfa.amax_rejection",
        "uk_nrfa.peak_rejected_periods",
    }

    # Past 30 calendar days: stale entry is evicted and re-fetched via HTTP.
    # Because the replayed response itself carries the 2026-11-16 acquisition timestamp, retention
    # immediately evicts it rather than persisting an already-expired snapshot back into the store.
    current_now = datetime(2026, 12, 17, 0, 0, 0, tzinfo=UTC)
    expired = rr.fetch(sel, start="1962-01-03", end="1985-12-29", cache="reuse")
    assert len(replay.calls) == 2
    pl_testing.assert_frame_equal(expired.data, initial.data)
    status_after = rr.cache_status("uk_nrfa")
    assert status_after.coverage == ()
    audit_after = rr.audit_cache("uk_nrfa")
    assert audit_after.rows_checked == 0


@pytest.mark.usefixtures("reuse_packaged_catalogues")
@pytest.mark.recorded(_EVIDENCE_SCOPE, _VERIFICATION_SCOPE)
def test_recorded_public_ni_station_flags_and_historical_depth(
    retained_evidence_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ret_root = retained_evidence_root / _EVIDENCE_SCOPE
    verif_root = retained_evidence_root / _VERIFICATION_SCOPE
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))

    # 1. Northern Ireland station (201002, Malin Head elevation datum) through public API + strict replay.
    ni_replay = _ExactReceiptReplay((_pair(verif_root, "gdf-201002-ni-2020-01.json"),))
    monkeypatch.setattr(discovery, "HttpClient", lambda: ni_replay)
    ni_sel = rr.pick(rr.find(provider="uk_nrfa", station="201002"), variant="gdf")
    ni_meta = rr.metadata(ni_sel, view="source")
    elev_row = ni_meta.filter(pl.col("attribute_role") == "elevation").row(0, named=True)
    assert elev_row["source_datum"] == "Malin Head"
    assert elev_row["source_value"] == "61.0"
    ni_res = rr.fetch(ni_sel, start="2020-01-03", end="2020-01-03", cache="bypass", on_issue="raise")
    assert ni_res.data["time"].to_list() == [datetime(2020, 1, 3, 0, 0, 0)]
    assert ni_res.data["value"].to_list() == [4.468]
    assert ni_res.data["unit"].to_list() == ["m3/s"]
    assert ni_res.data["time_zone"].to_list() == ["unknown"]
    assert rr.annotations(ni_res, schema="uk_nrfa.observations")["source_label"].to_list() == ["2020-01-03"]

    # 2. Mixed E and S quality flags preserved faithfully on 39001 without altering numeric values.
    flag_replay = _ExactReceiptReplay(
        (_pair(verif_root, "gdf-39001-flagged-2019-03.json"), _pair(ret_root, "gdf-39001-2020-01.json"))
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: flag_replay)
    thames_sel = rr.pick(rr.find(provider="uk_nrfa", station="39001"), variant="gdf")
    e_res = rr.fetch(thames_sel, start="2019-03-22", end="2019-03-25", cache="bypass", on_issue="raise")
    assert e_res.data.sort("time")["value"].to_list() == [53.42, 52.85, 52.28, 51.7]
    e_obs = rr.annotations(e_res, schema="uk_nrfa.observations").sort("time")
    assert e_obs["source_label"].to_list() == ["2019-03-22", "2019-03-23", "2019-03-24", "2019-03-25"]
    assert e_obs["flag"].to_list() == ["E", "E", "E", "E"]

    s_res = rr.fetch(thames_sel, start="2020-01-03", end="2020-01-03", cache="bypass", on_issue="raise")
    assert s_res.data["value"].to_list() == [130.7]
    s_obs = rr.annotations(s_res, schema="uk_nrfa.observations")
    assert s_obs["flag"].to_list() == ["S"]

    # 3. Historical depth to earliest advertised NRFA year (1883) preserves integer literals as Float64.
    early_replay = _ExactReceiptReplay((_pair(verif_root, "gdf-39001-1883-01.json"),))
    monkeypatch.setattr(discovery, "HttpClient", lambda: early_replay)
    early_res = rr.fetch(thames_sel, start="1883-01-03", end="1883-01-08", cache="bypass", on_issue="raise")
    assert early_res.data.sort("time")["value"].to_list() == [289.0, 289.0, 273.0, 268.0, 253.0, 234.0]
    assert rr.annotations(early_res, schema="uk_nrfa.observations").sort("time")["source_label"].to_list() == [
        "1883-01-03",
        "1883-01-04",
        "1883-01-05",
        "1883-01-06",
        "1883-01-07",
        "1883-01-08",
    ]
