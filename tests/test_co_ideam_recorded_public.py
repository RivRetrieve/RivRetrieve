"""Public replay of retained Colombia IDEAM S3 HTTP captures and boundary probes."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.boundary_probes import (
    FIRST_WALL_CLOCK_TIME,
    LAST_WALL_CLOCK_TIME,
    READING_COUNT,
    LiveBoundaryProbe,
    WallClockExpectation,
    run_manifest_boundary_probes,
)
from rivretrieve._internal.engine import WindowEndpoint, _make_fetch_window
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.co_ideam.declaration import declaration
from rivretrieve._internal.providers.co_ideam.fetch import s3_observation_csv_url
from rivretrieve._internal.providers.co_ideam.series import SERIES_SPECS
from rivretrieve._internal.providers.registration import LiveStages, load_manifest
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, ReplayTransport
from rivretrieve._internal.selection import UnknownStationError
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    HttpMethod,
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

_SCOPE = "maintenance/observations/co_ideam/retrieval"
_PROVIDER = ProviderId("co_ideam")
_DECLARED = load_manifest((_PROVIDER,))

assert isinstance(declaration.observations, LiveStages)
_STAGES = declaration.observations.stages

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_PROBE_EXPECTATIONS_0011017010: tuple[tuple[str, int, str, str], ...] = (
    ("caudal_h", 7739, "2016-01-01T06:00:00", "2026-09-30T18:00:00"),
    ("q_media_d", 17028, "1977-01-01T00:00:00", "2026-09-30T00:00:00"),
    ("q_mx_d", 3865, "2016-01-01T00:00:00", "2026-09-30T00:00:00"),
    ("q_mn_d", 3865, "2016-01-01T00:00:00", "2026-09-30T00:00:00"),
    ("q_media_m", 728, "1965-01-01T00:00:00", "2026-09-01T00:00:00"),
    ("q_mx_m", 609, "1976-01-01T00:00:00", "2026-09-01T00:00:00"),
    ("q_mn_m", 593, "1976-01-01T00:00:00", "2026-09-01T00:00:00"),
    ("q_media_a", 62, "1965-01-01T00:00:00", "2026-01-01T00:00:00"),
    ("q_mx_a", 51, "1976-01-01T00:00:00", "2026-01-01T00:00:00"),
    ("q_mn_a", 51, "1976-01-01T00:00:00", "2026-01-01T00:00:00"),
    ("nivel_h", 39893, "1977-01-01T06:00:00", "2026-09-30T18:00:00"),
    ("nv_media_d", 16568, "1977-01-01T00:00:00", "2026-09-30T00:00:00"),
    ("nv_mx_d", 3865, "2016-01-01T00:00:00", "2026-09-30T00:00:00"),
    ("nv_mn_d", 3865, "2016-01-01T00:00:00", "2026-09-30T00:00:00"),
    ("nv_media_m", 566, "1977-01-01T00:00:00", "2026-09-01T00:00:00"),
    ("nv_mx_m", 566, "1977-01-01T00:00:00", "2026-09-01T00:00:00"),
    ("nv_mn_m", 566, "1977-01-01T00:00:00", "2026-09-01T00:00:00"),
    ("nv_media_a", 50, "1977-01-01T00:00:00", "2026-01-01T00:00:00"),
    ("nv_mx_a", 50, "1977-01-01T00:00:00", "2026-01-01T00:00:00"),
    ("nv_mn_a", 50, "1977-01-01T00:00:00", "2026-01-01T00:00:00"),
)


def _load_capture(root: Path, group: str, name: str) -> tuple[bytes, dict[str, object]]:
    base = root / _SCOPE / group / name
    return base.with_suffix(".body").read_bytes(), json.loads(base.with_suffix(".receipt.json").read_text())


def _envelope_from_capture(root: Path, group: str, name: str) -> RecordingEnvelope:
    body, receipt = _load_capture(root, group, name)
    media_type = receipt.get("media_type")
    return RecordingEnvelope(
        request=RecordedRequest(
            HttpMethod.GET,
            str(receipt["url"]),
            None,
            ordinary_headers={"User-Agent": "RivRetrieve"},
        ),
        content=body,
        status_code=int(str(receipt["http_status"])),
        retrieved_at=datetime.fromisoformat(str(receipt["retrieved_at"]).replace("Z", "+00:00")),
        content_type=str(media_type) if isinstance(media_type, str) and media_type else None,
    )


def _response_matching_request(root: Path, group: str, name: str, request: TransportRequest) -> TransportResponse:
    body, receipt = _load_capture(root, group, name)
    expected_url = str(receipt["url"])
    assert request.url == expected_url
    assert dict(request.params or {}) == {}
    status_code = int(str(receipt["http_status"]))
    media_type = receipt.get("media_type")
    content_type = str(media_type) if isinstance(media_type, str) and media_type else None
    retrieved_at = datetime.fromisoformat(str(receipt["retrieved_at"]).replace("Z", "+00:00"))
    response = TransportResponse(
        content=body,
        status_code=status_code,
        retrieved_at=retrieved_at,
        content_type=content_type,
        url=expected_url,
        request_parameters={},
    )
    if status_code >= 400:
        raise TransportFailure(
            request,
            TransportFailureReason.HTTP_STATUS,
            1,
            status_code=status_code,
            category=TransportFailureCategory.HTTP_STATUS,
            response=response,
        )
    return response


def _decode_s3_csv_slice(
    content: bytes,
    start: datetime,
    end: datetime,
    *,
    calendar_date: bool,
    scale: float,
) -> list[tuple[datetime, float]]:
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    rows: list[tuple[datetime, float]] = []
    for item in reader:
        ts = datetime.strptime(item["fechaObservacion"], "%Y-%m-%d %H:%M:%S")
        in_window = (start.date() <= ts.date() <= end.date()) if calendar_date else (start <= ts <= end)
        if in_window:
            rows.append((ts, float(item["valorObservado"]) * scale))
    rows.sort(key=lambda pair: pair[0])
    return rows


def _select_products(station: str, *products: str) -> rr.Selection:
    selected = rr.find(provider="co_ideam", station=station)
    series_ids = rr.as_frame(selected).filter(pl.col("product_id").is_in(products))["series_id"].to_list()
    assert len(series_ids) == len(products)
    return rr.pick(selected, series_id=series_ids)


@pytest.mark.recorded(_SCOPE)
def test_each_colombia_ideam_product_has_an_exact_live_replay_boundary_probe(
    retained_evidence_root: Path,
) -> None:
    fetch_win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(1960, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2026, 11, 8)),
    )

    def _run_probe(product: ProductId, replay: ReplayTransport) -> pl.DataFrame:
        fetched = _STAGES.fetch(
            ("0011017010",),
            (product,),
            {product: ()},
            fetch_win,
            _STAGES.config,
            replay,
        )
        return _STAGES.parse(fetched.value[0], _STAGES.config).rows

    def _make_probe(product_id: str, count: int, first_ts: str, last_ts: str) -> LiveBoundaryProbe:
        prod = ProductId(product_id)
        return LiveBoundaryProbe(
            provider_id=_PROVIDER,
            product_id=prod,
            recordings=(
                _envelope_from_capture(
                    retained_evidence_root,
                    "access",
                    f"s3-0011017010-{product_id.replace('_', '-')}",
                ),
            ),
            assertions={
                READING_COUNT: count,
                FIRST_WALL_CLOCK_TIME: WallClockExpectation(first_ts, "unknown"),
                LAST_WALL_CLOCK_TIME: WallClockExpectation(last_ts, "unknown"),
            },
            run=lambda replay: _run_probe(prod, replay),
        )

    probes = tuple(
        _make_probe(product_id, count, first_ts, last_ts)
        for product_id, count, first_ts, last_ts in _PROBE_EXPECTATIONS_0011017010
    )
    results = run_manifest_boundary_probes(_DECLARED, probes)
    assert len(results) == 20


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_all_20_products_at_0011017010_clipping_units_and_cache(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    station = "0011017010"
    url_to_capture = {
        s3_observation_csv_url(station, spec.etiqueta): (
            spec.product_id,
            f"s3-{station}-{spec.product_id.replace('_', '-')}",
            spec.product_id.endswith("_d"),
            0.01 if spec.quantity == "stage" else 1.0,
        )
        for spec in SERIES_SPECS
    }

    class _Replay0011017010:
        def __init__(self) -> None:
            self.calls = 0

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls += 1
            _, capture_name, _, _ = url_to_capture[request.url]
            return _response_matching_request(retained_evidence_root, "access", capture_name, request)

    replay = _Replay0011017010()
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    selection = rr.find(provider="co_ideam", station=station)
    assert len(selection.series) == 20
    start_str, end_str = "2020-01-01", "2023-12-31T23:59:59"
    start_dt, end_dt = datetime.fromisoformat(start_str), datetime.fromisoformat(end_str)

    result = rr.fetch(selection, start=start_str, end=end_str, cache="reuse", receipts=True)
    assert replay.calls == 20
    assert result.issues == ()
    assert result.receipts is not None and len(result.receipts.entries) == 20
    assert result.data["time_zone"].unique().to_list() == ["unknown"]

    for _, (product_id, capture_name, is_calendar, scale) in url_to_capture.items():
        raw_bytes, _ = _load_capture(retained_evidence_root, "access", capture_name)
        expected = _decode_s3_csv_slice(raw_bytes, start_dt, end_dt, calendar_date=is_calendar, scale=scale)
        actual_df = result.data.filter(pl.col("product_id") == product_id).sort("time")
        assert actual_df.height == len(expected) > 0
        assert actual_df["time"].to_list() == [ts for ts, _ in expected]
        assert actual_df["value"].to_list() == pytest.approx([val for _, val in expected])
        if scale == 0.01:
            assert actual_df["source_unit"].unique().to_list() == ["cm"]
            assert actual_df["unit"].unique().to_list() == ["m"]
        else:
            assert actual_df["source_unit"].unique().to_list() == ["m3/s"]
            assert actual_df["unit"].unique().to_list() == ["m3/s"]

    # Repeat historical sub-window query across all 20 products hits local store offline (0 HTTP calls).
    sub_start, sub_end = "2021-06-01", "2022-06-30T23:59:59"
    reused = rr.fetch(selection, start=sub_start, end=sub_end, cache="reuse")
    assert replay.calls == 20
    q_bytes, _ = _load_capture(retained_evidence_root, "access", "s3-0011017010-q-media-d")
    expected_q = _decode_s3_csv_slice(
        q_bytes,
        datetime.fromisoformat(sub_start),
        datetime.fromisoformat(sub_end),
        calendar_date=True,
        scale=1.0,
    )
    reused_q = reused.data.filter(pl.col("product_id") == "q_media_d").sort("time")
    assert reused_q["time"].to_list() == [ts for ts, _ in expected_q]
    assert reused_q["value"].to_list() == pytest.approx([val for _, val in expected_q])


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_special_witnesses_hora_gaviria_regeneration_and_404_isolation(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))

    # 1. Real Hora Gaviria first-row witness 0024057080-Q_MEDIA_D (first row 1992-08-01 01:00:00):
    # Option 1A expands CALENDAR_DATE covered_start to 1992-08-01 00:00:00 so repeat cache="reuse" is offline.
    class _Dst0024057080:
        calls = 0

        def send(self, req: TransportRequest) -> TransportResponse:
            self.calls += 1
            return _response_matching_request(retained_evidence_root, "retrieval", "s3-0024057080-q-media-d", req)

    dst_replay = _Dst0024057080()
    monkeypatch.setattr(discovery, "HttpClient", lambda: dst_replay)
    sel_dst = rr.find(
        provider="co_ideam", station="0024057080", quantity="discharge", frequency="daily", statistic="mean"
    )
    first_dst = rr.fetch(sel_dst, start="1992-08-01", end="1992-08-03", cache="reuse", on_issue="raise")
    assert dst_replay.calls == 1
    assert first_dst.data["value"].to_list() == pytest.approx([12.34, 13.4, 20.16])
    second_dst = rr.fetch(sel_dst, start="1992-08-01", end="1992-08-03", cache="reuse", on_issue="raise")
    assert dst_replay.calls == 1
    assert second_dst.data["value"].to_list() == pytest.approx([12.34, 13.4, 20.16])

    # 2. Real two-snapshot S3 regeneration and Preliminar revision on 0026177030-NV_MEDIA_D (2026-11-06 -> 2026-11-08).
    class _Regen0026177030:
        def __init__(self) -> None:
            self.calls = 0
            self.nov08 = False

        def send(self, req: TransportRequest) -> TransportResponse:
            self.calls += 1
            if self.nov08:
                return _response_matching_request(
                    retained_evidence_root, "retrieval", "s3-0026177030-nv-media-d-20261108", req
                )
            return _response_matching_request(retained_evidence_root, "access", "s3-0026177030-nv-media-d", req)

    regen = _Regen0026177030()
    monkeypatch.setattr(discovery, "HttpClient", lambda: regen)
    sel_regen = rr.find(
        provider="co_ideam", station="0026177030", quantity="stage", frequency="daily", statistic="mean"
    )
    nov06_bytes, _ = _load_capture(retained_evidence_root, "access", "s3-0026177030-nv-media-d")
    nov08_bytes, _ = _load_capture(retained_evidence_root, "retrieval", "s3-0026177030-nv-media-d-20261108")
    exp_nov06 = _decode_s3_csv_slice(
        nov06_bytes, datetime(2026, 11, 3), datetime(2026, 11, 5), calendar_date=True, scale=0.01
    )
    exp_nov08 = _decode_s3_csv_slice(
        nov08_bytes, datetime(2026, 11, 3), datetime(2026, 11, 8), calendar_date=True, scale=0.01
    )

    res_nov06 = rr.fetch(sel_regen, start="2026-11-03", end="2026-11-05", cache="reuse", on_issue="raise")
    assert regen.calls == 1
    assert res_nov06.data.sort("time")["value"].to_list() == pytest.approx([v for _, v in exp_nov06])

    regen.nov08 = True
    res_nov08 = rr.fetch(sel_regen, start="2026-11-03", end="2026-11-08", cache="reuse", on_issue="raise")
    assert regen.calls == 2
    assert res_nov08.data.sort("time")["value"].to_list() == pytest.approx([v for _, v in exp_nov08])
    assert res_nov08.data.height > res_nov06.data.height
    assert (
        res_nov08.data.filter(pl.col("time") == datetime(2026, 11, 5))["value"].item()
        != res_nov06.data.filter(pl.col("time") == datetime(2026, 11, 5))["value"].item()
    )
    assert {o.status for o in res_nov08.outcomes} == {OutcomeStatus.SUCCESS, OutcomeStatus.UNRESOLVED}

    # 3. Folded 1993-02-06 23:00:00 duplicate timestamps and minimum 85-byte 1-row S3 files through public rr.fetch.
    for group, capture_name, station, prod, start_s, end_s, exp_vals in (
        (
            "series",
            "s3-0011107010-nivel-h",
            "0011107010",
            "nivel_h",
            "1993-02-06T22:30:00",
            "1993-02-06T23:30:00",
            [4.15, 4.14],
        ),
        (
            "series",
            "s3-0035077140-caudal-h",
            "0035077140",
            "caudal_h",
            "1993-02-06T22:30:00",
            "1993-02-06T23:30:00",
            [2.988, 2.988],
        ),
        ("retrieval", "s3-0026157160-nv-mn-a", "0026157160", "nv_mn_a", "2000-01-01", "2020-01-01", [0.01]),
        ("retrieval", "s3-0012047010-q-media-a", "0012047010", "q_media_a", "1990-01-01", "2000-01-01", [0.0]),
    ):
        monkeypatch.setattr(
            discovery,
            "HttpClient",
            lambda grp=group, cap=capture_name: type(
                "_Single",
                (),
                {"send": lambda self, req: _response_matching_request(retained_evidence_root, grp, cap, req)},
            )(),
        )
        sel_w = _select_products(station, prod)
        res_w = rr.fetch(sel_w, start=start_s, end=end_s, cache="bypass", on_issue="raise")
        assert sorted(res_w.data["value"].to_list()) == pytest.approx(sorted(exp_vals))

    # 4. Real Nutanix S3 404 NoSuchKey XML fault isolation when paired with sibling 0026157160-NV_MN_A:
    # remap retained 404 XML body onto sibling nv_media_d to prove sibling survival on public rr.fetch.
    class _Partial404At0026157160:
        def send(self, req: TransportRequest) -> TransportResponse:
            if req.url.endswith("0026157160-NV_MN_A.csv"):
                return _response_matching_request(retained_evidence_root, "retrieval", "s3-0026157160-nv-mn-a", req)
            body, rcpt = _load_capture(retained_evidence_root, "retrieval", "s3-404-0026157160-caudal-h")
            resp = TransportResponse(
                content=body,
                status_code=int(str(rcpt["http_status"])),
                retrieved_at=datetime.fromisoformat(str(rcpt["retrieved_at"]).replace("Z", "+00:00")),
                content_type="application/xml",
                url=req.url,
                request_parameters={},
            )
            raise TransportFailure(
                req,
                TransportFailureReason.HTTP_STATUS,
                1,
                status_code=404,
                category=TransportFailureCategory.HTTP_STATUS,
                response=resp,
            )

    monkeypatch.setattr(discovery, "HttpClient", _Partial404At0026157160)
    sel_partial = _select_products("0026157160", "nv_mn_a", "nv_media_d")
    res_partial = rr.fetch(sel_partial, start="2009-01-01", end="2009-12-31", cache="bypass", on_issue="ignore")
    assert res_partial.data["product_id"].to_list() == ["nv_mn_a"]
    assert res_partial.data["value"].to_list() == pytest.approx([0.01])
    assert [o.status for o in res_partial.outcomes if o.product_id == "nv_mn_a"] == [
        OutcomeStatus.SUCCESS,
        OutcomeStatus.UNRESOLVED,
    ]
    assert [o.status for o in res_partial.outcomes if o.product_id == "nv_media_d"] == [
        OutcomeStatus.FAILED,
    ]
    assert any(i.code == "source.http_not_found" and i.severity == "warning" for i in res_partial.issues)

    # Dead registry station without S3 hydrological series is rejected at public selection.
    with pytest.raises(UnknownStationError):
        rr.find(provider="co_ideam", station="0026077050")
