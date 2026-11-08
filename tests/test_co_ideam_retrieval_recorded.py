"""Recorded replay of retained original Colombia IDEAM S3 HTTP captures across all 20 products."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    ObservationRequest,
    ProductWindowDeclarations,
    ProviderConfig,
    RequestedWindow,
    WindowEndpoint,
)
from rivretrieve._internal.observations import ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.co_ideam.config import config, window_declarations
from rivretrieve._internal.providers.co_ideam.fetch import fetch
from rivretrieve._internal.providers.co_ideam.parse import parse
from rivretrieve._internal.providers.co_ideam.series import SERIES_SPECS, source_series
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, ReplayTransport
from rivretrieve._internal.source_series import InventoryCompleteness, OutcomeStatus, SeriesScope
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.transport import HttpMethod
from tests.test_internal_driver import _provenance

_SCOPE = "maintenance/observations/co_ideam/retrieval"


@dataclass(frozen=True)
class _CoIdeamStages:
    config: ProviderConfig = config()
    window_declarations: ProductWindowDeclarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


def _capture(root: Path, group: str, name: str) -> tuple[bytes, dict[str, object]]:
    base = root / _SCOPE / group / name
    return base.with_suffix(".body").read_bytes(), json.loads(base.with_suffix(".receipt.json").read_text())


def _envelope_from_capture(root: Path, group: str, name: str) -> RecordingEnvelope:
    body, receipt = _capture(root, group, name)
    url = str(receipt["url"])
    media_type = receipt.get("media_type")
    retrieved_raw = str(receipt["retrieved_at"]).replace("Z", "+00:00")
    return RecordingEnvelope(
        request=RecordedRequest(
            HttpMethod.GET,
            url,
            None,
            ordinary_headers={"User-Agent": "RivRetrieve"},
        ),
        content=body,
        status_code=int(str(receipt["http_status"])),
        retrieved_at=datetime.fromisoformat(retrieved_raw),
        content_type=str(media_type) if isinstance(media_type, str) and media_type else None,
    )


@pytest.mark.recorded(_SCOPE)
def test_recorded_all_20_products_at_0011017010_replay_with_receipts_and_hora_gaviria_shifts(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    station = "0011017010"
    envelopes = []
    products = []
    known = []
    for spec in SERIES_SPECS:
        name = f"s3-{station}-{spec.product_id.replace('_', '-')}"
        envelopes.append(_envelope_from_capture(retained_evidence_root, "access", name))
        products.append(ProductId(spec.product_id))
        known.append(source_series(station, spec.etiqueta))

    req = ObservationRequest(
        provider_id=ProviderId("co_ideam"),
        stations=(station,),
        products=tuple(products),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1992, 5, 1)),
            WindowEndpoint.from_datetime(datetime(2026, 11, 6)),
        ),
        known_series=tuple(known),
        scope=SeriesScope(provider_ids=("co_ideam",), station_ids=(station,)),
    )
    res = drive(
        req,
        _CoIdeamStages(),
        provenance=_provenance(req),
        transport=ReplayTransport(tuple(envelopes)),
        cache="bypass",
        store=StoreRoot(tmp_path / "store_0011017010"),
        receipts=ReceiptMode.INCLUDE,
    )
    assert res.issues == ()
    assert len(res.source_series) == 20
    assert {r.authorship.value for r in res.receipts.entries} >= {"publisher_payload"}
    assert set(res.canonical_rows["product_id"].unique().to_list()) == {spec.product_id for spec in SERIES_SPECS}

    # Verify 1992-1993 Hora Gaviria (+01:00) daily 01:00:00 and conventional 07:00/19:00 rows are preserved.
    q_daily = res.canonical_rows.filter(res.canonical_rows["product_id"] == "q_media_d")
    assert any(ts.hour == 1 for ts in q_daily["time"].to_list())
    assert set(q_daily["unit"].to_list()) == {"m3/s"}

    nv_hourly = res.canonical_rows.filter(res.canonical_rows["product_id"] == "nivel_h")
    assert {ts.hour for ts in nv_hourly["time"].to_list()} >= {7, 19}
    assert set(nv_hourly["unit"].to_list()) == {"m"}


@pytest.mark.recorded(_SCOPE)
def test_recorded_special_witnesses_fold_duplicates_zero_values_1row_85b_and_dst_calendar_start(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    # 1. Folded 1993-02-06 23:00:00 duplicate timestamps on 0011107010-NIVEL_H and 0035077140-CAUDAL_H.
    for station, prod, etiqueta, capture_name, exp_vals, exp_unit in (
        ("0011107010", "nivel_h", "NIVEL_H", "s3-0011107010-nivel-h", [4.15, 4.14], "m"),
        ("0035077140", "caudal_h", "CAUDAL_H", "s3-0035077140-caudal-h", [2.988, 2.988], "m3/s"),
    ):
        req_fold = ObservationRequest(
            provider_id=ProviderId("co_ideam"),
            stations=(station,),
            products=(ProductId(prod),),
            window=RequestedWindow(
                WindowEndpoint.from_datetime(datetime(1993, 2, 6, 22, 30)),
                WindowEndpoint.from_datetime(datetime(1993, 2, 6, 23, 30)),
            ),
            known_series=(source_series(station, etiqueta),),
        )
        res_fold = drive(
            req_fold,
            _CoIdeamStages(),
            provenance=_provenance(req_fold),
            transport=ReplayTransport((_envelope_from_capture(retained_evidence_root, "series", capture_name),)),
            cache="bypass",
            store=StoreRoot(tmp_path / f"fold_{station}"),
        )
        assert res_fold.canonical_rows["time"].to_list() == [
            datetime(1993, 2, 6, 23, 0),
            datetime(1993, 2, 6, 23, 0),
        ]
        assert res_fold.canonical_rows["value"].to_list() == pytest.approx(exp_vals)
        assert set(res_fold.canonical_rows["unit"].to_list()) == {exp_unit}

    # 2. Minimum 85-byte 1-row stage (0026157160-NV_MN_A: 1.0 cm -> 0.01 m) and discharge (0012047010-Q_MEDIA_A: 0.0 m3/s),
    # plus blank-approval 0011037020-Q_MX_M, 1934 historical 0021237020-Q_MEDIA_D, and zero-value 0016057010.
    for group, name, station, prod, etiqueta, win_start, win_end, check_fn in (
        (
            "retrieval",
            "s3-0026157160-nv-mn-a",
            "0026157160",
            "nv_mn_a",
            "NV_MN_A",
            datetime(2000, 1, 1),
            datetime(2020, 1, 1),
            lambda r: r.canonical_rows["value"].to_list() == pytest.approx([0.01]),
        ),
        (
            "retrieval",
            "s3-0012047010-q-media-a",
            "0012047010",
            "q_media_a",
            "Q_MEDIA_A",
            datetime(1990, 1, 1),
            datetime(2000, 1, 1),
            lambda r: r.canonical_rows["value"].to_list() == pytest.approx([0.0]),
        ),
        (
            "series",
            "s3-0011037020-q-mx-m",
            "0011037020",
            "q_mx_m",
            "Q_MX_M",
            datetime(1970, 1, 1),
            datetime(2025, 1, 1),
            lambda r: r.canonical_rows.height == 591,
        ),
        (
            "series",
            "s3-0016057010-q-media-d",
            "0016057010",
            "q_media_d",
            "Q_MEDIA_D",
            datetime(1970, 1, 1),
            datetime(2026, 11, 8),
            lambda r: (r.canonical_rows["value"] == 0.0).sum() == 15,
        ),
        (
            "series",
            "s3-0016057010-nv-media-d",
            "0016057010",
            "nv_media_d",
            "NV_MEDIA_D",
            datetime(1970, 1, 1),
            datetime(2026, 11, 8),
            lambda r: (r.canonical_rows["value"] == 0.0).sum() == 2,
        ),
        (
            "access",
            "s3-0021237020-q-media-d",
            "0021237020",
            "q_media_d",
            "Q_MEDIA_D",
            datetime(1934, 1, 1),
            datetime(1934, 1, 5),
            lambda r: r.canonical_rows["time"][0] == datetime(1934, 1, 1, 0, 0) and r.canonical_rows.height == 5,
        ),
    ):
        req_w = ObservationRequest(
            provider_id=ProviderId("co_ideam"),
            stations=(station,),
            products=(ProductId(prod),),
            window=RequestedWindow(WindowEndpoint.from_datetime(win_start), WindowEndpoint.from_datetime(win_end)),
            known_series=(source_series(station, etiqueta),),
        )
        res_w = drive(
            req_w,
            _CoIdeamStages(),
            provenance=_provenance(req_w),
            transport=ReplayTransport((_envelope_from_capture(retained_evidence_root, group, name),)),
            cache="bypass",
            store=StoreRoot(tmp_path / f"w_{name}"),
        )
        assert check_fn(res_w)

    # 3. Real Hora Gaviria first-row witness 0024057080-Q_MEDIA_D (first row 1992-08-01 01:00:00):
    # Option 1A expands CALENDAR_DATE covered_start to 1992-08-01 00:00:00 so cache="reuse" on 1992-08-01..03 is offline!
    dst_store = StoreRoot(tmp_path / "dst_0024057080")
    dst_known = source_series("0024057080", "Q_MEDIA_D")
    dst_scope = SeriesScope(provider_ids=("co_ideam",), station_ids=("0024057080",), product_ids=("q_media_d",))
    req_dst = ObservationRequest(
        provider_id=ProviderId("co_ideam"),
        stations=("0024057080",),
        products=(ProductId("q_media_d"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1992, 8, 1)),
            WindowEndpoint.from_datetime(datetime(1992, 8, 3)),
        ),
        known_series=(dst_known,),
        scope=dst_scope,
    )
    first_dst = drive(
        req_dst,
        _CoIdeamStages(),
        provenance=_provenance(req_dst),
        transport=ReplayTransport(
            (_envelope_from_capture(retained_evidence_root, "retrieval", "s3-0024057080-q-media-d"),)
        ),
        cache="reuse",
        store=dst_store,
    )
    assert first_dst.canonical_rows["value"].to_list() == pytest.approx([12.34, 13.4, 20.16])
    assert any(inv.completeness is InventoryCompleteness.COMPLETE for inv in first_dst.inventories)

    # Empty ReplayTransport(()) proves 0 network calls on second cache="reuse" read starting 1992-08-01!
    second_dst = drive(
        req_dst,
        _CoIdeamStages(),
        provenance=_provenance(req_dst),
        transport=ReplayTransport(()),
        cache="reuse",
        store=dst_store,
    )
    assert second_dst.canonical_rows["value"].to_list() == pytest.approx([12.34, 13.4, 20.16])


@pytest.mark.recorded(_SCOPE)
def test_recorded_two_snapshot_regeneration_revision_and_404_nosuchkey_handling(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    # 1. Real two-snapshot daily S3 regeneration on 0026177030-NV_MEDIA_D (2026-11-06 -> 2026-11-08):
    # 2026-11-05 revised in-place from 155.5 cm (1.555 m) to 157.625 cm (1.57625 m) and 2026-11-06..07 appended!
    station = "0026177030"
    prod = ProductId("nv_media_d")
    known = source_series(station, "NV_MEDIA_D")
    scope = SeriesScope(provider_ids=("co_ideam",), station_ids=(station,), product_ids=("nv_media_d",))
    store = StoreRoot(tmp_path / "regen_0026177030")

    snap_nov06 = _envelope_from_capture(retained_evidence_root, "access", "s3-0026177030-nv-media-d")
    snap_nov08 = _envelope_from_capture(retained_evidence_root, "retrieval", "s3-0026177030-nv-media-d-20261108")

    req_nov05 = ObservationRequest(
        provider_id=ProviderId("co_ideam"),
        stations=(station,),
        products=(prod,),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2026, 11, 3)),
            WindowEndpoint.from_datetime(datetime(2026, 11, 5)),
        ),
        known_series=(known,),
        scope=scope,
    )
    res_nov06 = drive(
        req_nov05,
        _CoIdeamStages(),
        provenance=_provenance(req_nov05),
        transport=ReplayTransport((snap_nov06,)),
        cache="reuse",
        store=store,
    )
    assert res_nov06.canonical_rows["value"].to_list() == pytest.approx([1.5975, 1.5775, 1.555])

    # Offline cache="reuse" hit within [1972-01-01, 2026-11-05] makes 0 network calls:
    res_cached = drive(
        req_nov05,
        _CoIdeamStages(),
        provenance=_provenance(req_nov05),
        transport=ReplayTransport(()),
        cache="reuse",
        store=store,
    )
    assert res_cached.canonical_rows["value"].to_list() == pytest.approx([1.5975, 1.5775, 1.555])

    # Extending window to 2026-11-07 hits the post-record UNRESOLVED tail -> fetches 2026-11-08 snapshot,
    # appends 2026-11-06..07 AND revises 2026-11-05 from 1.555 m -> 1.57625 m!
    req_nov07 = ObservationRequest(
        provider_id=ProviderId("co_ideam"),
        stations=(station,),
        products=(prod,),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2026, 11, 3)),
            WindowEndpoint.from_datetime(datetime(2026, 11, 7)),
        ),
        known_series=(known,),
        scope=scope,
    )
    res_nov08 = drive(
        req_nov07,
        _CoIdeamStages(),
        provenance=_provenance(req_nov07),
        transport=ReplayTransport((snap_nov08,)),
        cache="reuse",
        store=store,
    )
    assert res_nov08.canonical_rows["value"].to_list() == pytest.approx([1.5975, 1.5775, 1.57625, 2.01125, 2.425])

    # 2. Option 2A on retained Nutanix Objects HTTP 404 NoSuchKey XML captures:
    # Requesting available NV_MN_A + unavailable CAUDAL_H on 0026157160 returns NV_MN_A and isolates 404 on CAUDAL_H.
    env_ok_2615 = _envelope_from_capture(retained_evidence_root, "retrieval", "s3-0026157160-nv-mn-a")
    env_404_2615 = _envelope_from_capture(retained_evidence_root, "retrieval", "s3-404-0026157160-caudal-h")
    req_mixed = ObservationRequest(
        provider_id=ProviderId("co_ideam"),
        stations=("0026157160",),
        products=(ProductId("nv_mn_a"), ProductId("caudal_h")),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2009, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2009, 1, 1)),
        ),
        known_series=(source_series("0026157160", "NV_MN_A"),),
    )
    res_mixed = drive(
        req_mixed,
        _CoIdeamStages(),
        provenance=_provenance(req_mixed),
        transport=ReplayTransport((env_ok_2615, env_404_2615)),
        cache="bypass",
        store=StoreRoot(tmp_path / "mixed_404"),
    )
    assert res_mixed.canonical_rows["value"].to_list() == pytest.approx([0.01])
    assert any(i.code == "source.http_not_found" and i.severity == "warning" for i in res_mixed.issues)
    assert any(o.product_id == "caudal_h" and o.status is OutcomeStatus.FAILED for o in res_mixed.outcomes)

    # Also verify dead/placeholder 0010000000 and nonexistent 0099999999 404 captures.
    for group, name, dead_st in (
        ("retrieval", "s3-404-0010000000-q-media-d", "0010000000"),
        ("access", "s3-missing-0099999999-q-media-d-404", "0099999999"),
    ):
        req_dead = ObservationRequest(
            provider_id=ProviderId("co_ideam"),
            stations=(dead_st,),
            products=(ProductId("q_media_d"),),
            window=RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
                WindowEndpoint.from_datetime(datetime(2024, 1, 2)),
            ),
        )
        res_dead = drive(
            req_dead,
            _CoIdeamStages(),
            provenance=_provenance(req_dead),
            transport=ReplayTransport((_envelope_from_capture(retained_evidence_root, group, name),)),
            cache="bypass",
            store=StoreRoot(tmp_path / f"dead_{dead_st}"),
        )
        assert res_dead.canonical_rows.is_empty()
        assert [o.status for o in res_dead.outcomes] == [OutcomeStatus.FAILED]
        assert any(i.code == "source.http_not_found" for i in res_dead.issues)
