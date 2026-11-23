"""Recorded replay of retained original Argentina INA Alerta5 HTTP captures across all 13 products."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit  # noqa: TID251 - URL parsing for receipt replay only

import pytest

from rivretrieve._internal.assembly import _AssemblyResult
from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    ObservationRequest,
    Payload,
    ProductWindowDeclarations,
    ProviderConfig,
    RequestedWindow,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ReceiptMode
from rivretrieve._internal.primitives import CacheMode, ProductId, ProviderId
from rivretrieve._internal.providers.ar_ina.config import (
    ArInaSourceCoordinates,
    config,
    window_declarations,
)
from rivretrieve._internal.providers.ar_ina.fetch import fetch, resolve_series_lookup
from rivretrieve._internal.providers.ar_ina.parse import parse
from rivretrieve._internal.providers.ar_ina.series import SPECS_BY_PRODUCT_ID, source_series
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    OutcomeStatus,
    admission,
)
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.transport import TransportRequest, TransportResponse
from tests.test_internal_driver import _provenance

_SCOPE = "maintenance/observations/ar_ina/retrieval"


@dataclass(frozen=True)
class _ArInaStages:
    config: ProviderConfig = config()
    window_declarations: ProductWindowDeclarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


def _capture(root: Path, group: str, name: str) -> tuple[bytes, dict[str, object]]:
    base = root / _SCOPE / group / name
    return base.with_suffix(".body").read_bytes(), json.loads(base.with_suffix(".receipt.json").read_text())


def _response_from_capture(root: Path, group: str, name: str) -> TransportResponse:
    body, receipt = _capture(root, group, name)
    url = str(receipt["url"])
    parsed = urlsplit(url)
    params = {key: vals[0] for key, vals in parse_qs(parsed.query, keep_blank_values=True).items()}
    headers = receipt.get("response_headers")
    content_type = headers.get("content-type") if isinstance(headers, dict) else None
    status = int(str(receipt.get("status", receipt.get("http_status", 200))))
    acquired = datetime.fromisoformat(str(receipt["acquired_at"]).replace("Z", "+00:00"))
    return TransportResponse(
        content=body,
        status_code=status,
        retrieved_at=acquired,
        content_type=str(content_type) if content_type is not None else None,
        url=f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
        request_parameters=params,
    )


def _origin_from_receipt(receipt: dict[str, object]) -> SourceCallOrigin:
    url = str(receipt["url"])
    parsed = urlsplit(url)
    params = {key: vals[0] for key, vals in parse_qs(parsed.query, keep_blank_values=True).items()}
    headers = receipt.get("response_headers")
    content_type = headers.get("content-type") if isinstance(headers, dict) else None
    status = int(str(receipt.get("status", receipt.get("http_status", 200))))
    acquired = datetime.fromisoformat(str(receipt["acquired_at"]).replace("Z", "+00:00"))
    return SourceCallOrigin(
        url=f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
        request_parameters=params,
        status_code=status,
        retrieved_at=acquired,
        content_type=str(content_type) if content_type is not None else UnknownOriginFact(),
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )


class _ExactReplayTransport:
    """Match rendered driver requests against exact retained publisher URLs and query parameters."""

    def __init__(self, responses: list[TransportResponse]) -> None:
        self._by_key: dict[tuple[str, tuple[tuple[str, str], ...]], TransportResponse] = {}
        for response in responses:
            norm_params = tuple(sorted((str(k), str(v)) for k, v in response.request_parameters.items()))
            self._by_key[(response.url, norm_params)] = response
        self.calls: list[tuple[str, tuple[tuple[str, str], ...]]] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        norm_params = tuple(sorted((str(k), str(v)) for k, v in (request.params or {}).items() if v is not None))
        key = (request.url, norm_params)
        self.calls.append(key)
        if key not in self._by_key:
            raise AssertionError(f"Unmatched recorded request: {key!r}; available={list(self._by_key)!r}")
        return self._by_key[key]


def _req_window(start: datetime, end: datetime) -> RequestedWindow:
    return RequestedWindow(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end))


def _drive_recorded(
    request: ObservationRequest,
    *,
    transport: _ExactReplayTransport,
    store: StoreRoot,
    cache: CacheMode = "reuse",
) -> _AssemblyResult:
    return drive(
        request,
        _ArInaStages(),
        provenance=_provenance(request),
        receipts=ReceiptMode.INCLUDE,
        transport=transport,
        cache=cache,
        store=store,
    )


@pytest.mark.recorded(_SCOPE)
def test_recorded_planned_windows_capped_spans_stop_extensions_lookups_and_cache_reuse(
    retained_evidence_root: Path,
    tmp_path: Path,
) -> None:
    transport = _ExactReplayTransport(
        [
            _response_from_capture(retained_evidence_root, "retrieval", name)
            for name in (
                "a5-obs-3346-var2-span1-20231130-20241128",
                "a5-obs-3346-var2-span2-20241129-20241207",
                "a5-obs-3307-var2-dense15m-2d-202401",
                "a5-obs-26605-var40-planned-20240101-20240105",
                "a5-obs-26605-var40-prerecord-1900-empty",
                "a5-obs-24674-var48-planned-20240101-20240102",
                "a5-obs-36030-var67-planned-20251006-20251007",
                "a5-obs-24667-var48-planned-empty",
                "a5-series-lookup-st8-var40-proc1",
                "a5-series-lookup-st8-var85-proc1-empty",
                "a5-series-lookup-st1-var48-proc1-zerocount",
            )
        ]
    )

    # 1. Two-span 365-day capped-span replay with .999999Z microsecond stop on station 1741 (series 3346) + cache="reuse".
    known_3346 = source_series("1741", "stage_instantaneous", published_series_id=3346)
    span_store = StoreRoot(tmp_path / "span_store")
    span_req = ObservationRequest(
        provider_id=ProviderId("ar_ina"),
        stations=("1741",),
        products=(ProductId("stage_instantaneous"),),
        window=_req_window(datetime(2023, 12, 2), datetime(2024, 12, 5)),
        known_series=(known_3346,),
    )
    span_res = _drive_recorded(span_req, transport=transport, store=span_store, cache="reuse")
    assert len(transport.calls) == 2
    assert {o.status for o in span_res.outcomes} == {OutcomeStatus.SUCCESS}
    assert span_res.canonical_rows.height > 400
    assert span_res.inventories[-1].completeness is InventoryCompleteness.COMPLETE

    span_reused = _drive_recorded(span_req, transport=transport, store=span_store, cache="reuse")
    assert len(transport.calls) == 2
    assert span_reused.canonical_rows.equals(span_res.canonical_rows)

    # 2. Dense 15-minute (:10-second) ina_delta stage on station 1701 (series 3307).
    known_3307 = source_series("1701", "stage_instantaneous", published_series_id=3307)
    dense_res = _drive_recorded(
        ObservationRequest(
            provider_id=ProviderId("ar_ina"),
            stations=("1701",),
            products=(ProductId("stage_instantaneous"),),
            window=_req_window(datetime(2024, 1, 3), datetime(2024, 1, 4)),
            known_series=(known_3307,),
        ),
        transport=transport,
        store=StoreRoot(tmp_path / "dense_store"),
    )
    assert [o.status for o in dense_res.outcomes] == [OutcomeStatus.SUCCESS]
    assert dense_res.canonical_rows.height >= 90
    assert any(ts.second == 10 for ts in dense_res.canonical_rows.get_column("time").to_list())

    # 3. Unknown-pair runtime lookup + 25h stop_extension daily discharge on station 8 (series 26605),
    #    plus pre-record 1900 EMPTY window.
    unknown_q_res = _drive_recorded(
        ObservationRequest(
            provider_id=ProviderId("ar_ina"),
            stations=("8",),
            products=(ProductId("discharge_daily_mean"),),
            window=_req_window(datetime(2024, 1, 1), datetime(2024, 1, 5)),
        ),
        transport=transport,
        store=StoreRoot(tmp_path / "unknown_q_store"),
    )
    assert [o.status for o in unknown_q_res.outcomes] == [OutcomeStatus.SUCCESS]
    assert unknown_q_res.canonical_rows.height == 4
    assert unknown_q_res.canonical_rows.sort("time").get_column("value").to_list()[0] == pytest.approx(839.95)
    obs_calls = [
        c for c in unknown_q_res.provenance.calls_made if str(c.get("url", "")).endswith("/26605/observaciones")
    ]
    assert len(obs_calls) == 1 and obs_calls[0]["prerequisite_acquisition_ids"]

    known_26605 = source_series("8", "discharge_daily_mean", published_series_id=26605)
    empty_1900 = _drive_recorded(
        ObservationRequest(
            provider_id=ProviderId("ar_ina"),
            stations=("8",),
            products=(ProductId("discharge_daily_mean"),),
            window=_req_window(datetime(1900, 1, 3), datetime(1900, 1, 8)),
            known_series=(known_26605,),
        ),
        transport=transport,
        store=StoreRoot(tmp_path / "empty_1900_store"),
    )
    assert [o.status for o in empty_1900.outcomes] == [OutcomeStatus.EMPTY]
    assert empty_1900.canonical_rows.is_empty()

    # 4. Short 2-day monthly window (31d1h stop_extension) recovers January monthly mean 1510.0 on series 24674,
    #    and short 2-day weekly window (7d1h stop_extension) recovers weekly mean on series 36030.
    known_24674 = source_series("8", "discharge_monthly_mean", published_series_id=24674)
    monthly_res = _drive_recorded(
        ObservationRequest(
            provider_id=ProviderId("ar_ina"),
            stations=("8",),
            products=(ProductId("discharge_monthly_mean"),),
            window=_req_window(datetime(2024, 1, 1), datetime(2024, 1, 2)),
            known_series=(known_24674,),
        ),
        transport=transport,
        store=StoreRoot(tmp_path / "monthly_store"),
    )
    assert [o.status for o in monthly_res.outcomes] == [OutcomeStatus.SUCCESS]
    assert monthly_res.canonical_rows.get_column("value").to_list() == [pytest.approx(1510.0)]

    known_36030 = source_series("151", "stage_weekly_mean", published_series_id=36030)
    weekly_res = _drive_recorded(
        ObservationRequest(
            provider_id=ProviderId("ar_ina"),
            stations=("151",),
            products=(ProductId("stage_weekly_mean"),),
            window=_req_window(datetime(2025, 10, 6), datetime(2025, 10, 7)),
            known_series=(known_36030,),
        ),
        transport=transport,
        store=StoreRoot(tmp_path / "weekly_store"),
    )
    assert [o.status for o in weekly_res.outcomes] == [OutcomeStatus.SUCCESS]
    assert weekly_res.canonical_rows.height == 1

    # 5. Absent series (st=8, var=85 -> NO_MATCH) vs zero-count published series 24667 (st=1, var=48 -> EMPTY).
    no_match_store = StoreRoot(tmp_path / "no_match_store")
    no_match_req = ObservationRequest(
        provider_id=ProviderId("ar_ina"),
        stations=("8",),
        products=(ProductId("stage_hourly"),),
        window=_req_window(datetime(2024, 1, 1), datetime(2024, 1, 2)),
    )
    no_match_res = _drive_recorded(no_match_req, transport=transport, store=no_match_store, cache="reuse")
    assert [o.status for o in no_match_res.outcomes] == [OutcomeStatus.NO_MATCH]
    calls_before = len(transport.calls)
    _drive_recorded(no_match_req, transport=transport, store=no_match_store, cache="reuse")
    assert len(transport.calls) == calls_before

    zero_count_res = _drive_recorded(
        ObservationRequest(
            provider_id=ProviderId("ar_ina"),
            stations=("1",),
            products=(ProductId("discharge_monthly_mean"),),
            window=_req_window(datetime(2024, 1, 1), datetime(2024, 1, 2)),
        ),
        transport=transport,
        store=StoreRoot(tmp_path / "zero_count_store"),
    )
    assert [o.status for o in zero_count_res.outcomes] == [OutcomeStatus.EMPTY]


@pytest.mark.recorded(_SCOPE)
def test_recorded_all_13_products_pre2009_dst_and_counterfeit_boundary_null_omission(
    retained_evidence_root: Path,
) -> None:
    cfg = config()
    wide_fw = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(1990, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2030, 1, 1)),
    )

    # 1. Parse all 13 in-scope product captures retained in access/.
    thirteen_captures = (
        ("a5-obs-26605-var40-qmd", "8", "discharge_daily_mean", 26605),
        ("a5-obs-857-var4-q", "8", "discharge_instantaneous", 857),
        ("a5-obs-24674-var48-qmm", "8", "discharge_monthly_mean", 24674),
        ("a5-obs-25775-var51-qmmin", "8", "discharge_monthly_min", 25775),
        ("a5-obs-25869-var52-qmmax", "8", "discharge_monthly_max", 25869),
        ("a5-obs-26250-var39-hmd", "8", "stage_daily_mean", 26250),
        ("a5-obs-8-var2-h", "8", "stage_instantaneous", 8),
        ("a5-obs-31605-var85-h1h", "52", "stage_hourly", 31605),
        ("a5-obs-38398-var101-hm4h", "2112", "stage_4hourly", 38398),
        ("a5-obs-35313-var67-hms", "9", "stage_weekly_mean", 35313),
        ("a5-obs-25486-var33-hmm", "8", "stage_monthly_mean", 25486),
        ("a5-obs-25587-var49-hmmin", "8", "stage_monthly_min", 25587),
        ("a5-obs-25681-var50-hmmax", "8", "stage_monthly_max", 25681),
    )
    seen_products: set[str] = set()
    for cap_name, station_id, product_id, pub_id in thirteen_captures:
        body, rcpt = _capture(retained_evidence_root, "access", cap_name)
        spec = SPECS_BY_PRODUCT_ID[product_id]
        parsed = parse(
            Payload(
                source_coordinates=SourceCoordinates(ArInaSourceCoordinates(spec.var_id, spec.proc_id, pub_id)),
                station_products=((station_id, ProductId(product_id)),),
                fetch_window=wide_fw,
                content=body,
                origin=_origin_from_receipt(rcpt),
                prerequisite_calls=(),
            ),
            cfg,
        )
        assert [o.status for o in parsed.outcomes] == [OutcomeStatus.SUCCESS]
        assert not parsed.rows.is_empty()
        assert admission(parsed.series[0].facts[0]).status == "supported"
        if cap_name == "a5-obs-25587-var49-hmmin":
            # Verify negative gauge-zero stage (-0.27 m) survives intact!
            assert min(v for v in parsed.rows.get_column("value").to_list() if v is not None) == pytest.approx(-0.27)
        seen_products.add(product_id)
    assert len(seen_products) == 13

    # 2. Verify pre-2009 Argentina DST 23h/25h captures (03:00Z and 02:00Z) parse cleanly.
    dst_captures = (
        ("a5-obs-26616-var40-qmd-dst-2008-spring", "19", "discharge_daily_mean", 26616),
        ("a5-obs-26616-var40-qmd-dst-2009-fall", "19", "discharge_daily_mean", 26616),
        ("a5-obs-35888-var40-qmd-bdhi-dst-2008", "2047", "discharge_daily_mean", 35888),
        ("a5-obs-24665-var48-qmm-dst-2008-2009", "19", "discharge_monthly_mean", 24665),
    )
    for cap_name, station_id, product_id, pub_id in dst_captures:
        body, rcpt = _capture(retained_evidence_root, "series", cap_name)
        spec = SPECS_BY_PRODUCT_ID[product_id]
        parsed_dst = parse(
            Payload(
                source_coordinates=SourceCoordinates(ArInaSourceCoordinates(spec.var_id, spec.proc_id, pub_id)),
                station_products=((station_id, ProductId(product_id)),),
                fetch_window=wide_fw,
                content=body,
                origin=_origin_from_receipt(rcpt),
                prerequisite_calls=(),
            ),
            cfg,
        )
        assert [o.status for o in parsed_dst.outcomes] == [OutcomeStatus.SUCCESS]
        hours = {ts.hour for ts in parsed_dst.rows.get_column("time").to_list()}
        assert {2, 3}.issubset(hours)

    # 3. Verify counterfeit boundary nulls in skip_nulls=false are omitted so skip_nulls=false and skip_nulls=true
    #    yield identical genuine database rows, while wide skip_nulls=true proves real values existed outside [06Z, 12Z].
    false_body, false_rcpt = _capture(
        retained_evidence_root, "retrieval", "a5-obs-31605-var85-boundary-skipnulls-false"
    )
    true_body, true_rcpt = _capture(retained_evidence_root, "retrieval", "a5-obs-31605-var85-boundary-skipnulls-true")
    wide_body, wide_rcpt = _capture(
        retained_evidence_root, "retrieval", "a5-obs-31605-var85-wide-0100-1600-skipnulls-true"
    )
    parsed_false = parse(
        Payload(
            source_coordinates=SourceCoordinates(ArInaSourceCoordinates(85, 1, 31605)),
            station_products=(("52", ProductId("stage_hourly")),),
            fetch_window=wide_fw,
            content=false_body,
            origin=_origin_from_receipt(false_rcpt),
            prerequisite_calls=(),
        ),
        cfg,
    )
    parsed_true = parse(
        Payload(
            source_coordinates=SourceCoordinates(ArInaSourceCoordinates(85, 1, 31605)),
            station_products=(("52", ProductId("stage_hourly")),),
            fetch_window=wide_fw,
            content=true_body,
            origin=_origin_from_receipt(true_rcpt),
            prerequisite_calls=(),
        ),
        cfg,
    )
    parsed_wide = parse(
        Payload(
            source_coordinates=SourceCoordinates(ArInaSourceCoordinates(85, 1, 31605)),
            station_products=(("52", ProductId("stage_hourly")),),
            fetch_window=wide_fw,
            content=wide_body,
            origin=_origin_from_receipt(wide_rcpt),
            prerequisite_calls=(),
        ),
        cfg,
    )
    assert parsed_false.rows.equals(parsed_true.rows)
    assert parsed_true.rows.height == 6
    assert [i.code for i in parsed_false.issues] == ["source.synthesized_grid_null"]
    assert parsed_false.issues[0].details is not None and parsed_false.issues[0].details["count"] == 6
    assert parsed_wide.rows.height == 15

    # 4. Verify unfiltered /obs/puntual/series?estacion_id=1&var_id=2 contains proc_id=4 simulated series,
    #    so resolve_series_lookup rejects it when called for observational stage_instantaneous (proc_id=1).
    allprocs_body, _ = _capture(retained_evidence_root, "retrieval", "a5-series-lookup-st1-var2-allprocs")
    with pytest.raises(ValueError, match="procedure 4"):
        resolve_series_lookup(
            allprocs_body,
            "1",
            ProductId("stage_instantaneous"),
            evidence="test-allprocs",
        )
