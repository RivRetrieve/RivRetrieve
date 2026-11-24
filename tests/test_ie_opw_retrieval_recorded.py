"""Recorded replay of retained Ireland OPW (``ie_opw``) HTTP captures across all 12 products."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit  # noqa: TID251 - URL parsing for retained receipt replay only

import polars as pl
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
from rivretrieve._internal.providers.ie_opw.annotations import (
    IE_OPW_DAILY_STAGE_SCHEMA,
    IE_OPW_SERIES_SCHEMA,
)
from rivretrieve._internal.providers.ie_opw.config import config, window_declarations
from rivretrieve._internal.providers.ie_opw.fetch import fetch
from rivretrieve._internal.providers.ie_opw.parse import parse, parse_group
from rivretrieve._internal.providers.ie_opw.series import PRODUCT_SPECS, SHARED_DAILY_PRODUCTS, source_series
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, ReplayTransport
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.transport import TRANSPORT_POLICY, HttpMethod, TransportRequest, TransportResponse
from tests.test_internal_driver import _provenance

_SCOPE = "maintenance/observations/ie_opw/retrieval"

_RECORDING_SLUGS: tuple[str, ...] = (
    "opw-01041-q-year-json",
    "opw-01041-s-year-json",
    "opw-01041-twater-year-json",
    "opw-01041-q-complete-zip",
    "opw-01041-s-complete-zip",
    "opw-01041-twater-complete-zip",
    "opw-03055-twater-year-json",
    "opw-06015-q-year-json",
    "opw-06025-q-year-json",
    "opw-06025-q-complete-zip",
    "opw-07012-q-year-json",
    "opw-07012-s-year-json",
    "opw-07012-q-complete-zip",
    "opw-07012-s-complete-zip",
    "opw-14124-twater-complete-zip",
    "opw-18121-twater-year-json",
    "opw-30061-s-year-json",
    "opw-30061-s-complete-zip",
    "opw-99999-missing-404",
)


@dataclass(frozen=True)
class _IeOpwStages:
    observation_source: str = "live"
    config: ProviderConfig = config()
    window_declarations: ProductWindowDeclarations = window_declarations()
    shared_acquisition_products: tuple[frozenset[ProductId], ...] = SHARED_DAILY_PRODUCTS
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)
    parse_group = staticmethod(parse_group)


def _envelope_from_capture(root: Path, slug: str, *, subdir: str = "web") -> RecordingEnvelope:
    base = root / _SCOPE / subdir / slug
    body = base.with_suffix(".body").read_bytes()
    receipt = json.loads(base.with_suffix(".receipt.json").read_text())
    url = str(receipt["url"])
    parts = urlsplit(url)
    params = (
        {key: vals[0] for key, vals in parse_qs(parts.query, keep_blank_values=True).items()} if parts.query else None
    )
    req_headers = dict(receipt.get("request_headers") or {})
    ordinary_headers = {**req_headers, "User-Agent": TRANSPORT_POLICY.user_agent}
    retrieved_raw = str(receipt.get("retrieved_at") or receipt.get("acquired_at")).replace("Z", "+00:00")
    media_type = receipt.get("media_type")
    return RecordingEnvelope(
        request=RecordedRequest(
            HttpMethod.GET,
            f"{parts.scheme}://{parts.netloc}{parts.path}",
            params,
            ordinary_headers=ordinary_headers,
        ),
        content=body,
        status_code=int(str(receipt["http_status"])),
        retrieved_at=datetime.fromisoformat(retrieved_raw),
        content_type=str(media_type) if isinstance(media_type, str) and media_type else None,
    )


class _CountingReplay(ReplayTransport):
    def __init__(self, envelopes: tuple[RecordingEnvelope, ...]) -> None:
        super().__init__(envelopes)
        self.calls: int = 0

    def send(self, request: TransportRequest) -> TransportResponse:
        self.calls += 1
        return super().send(request)


def _replay(root: Path) -> _CountingReplay:
    return _CountingReplay(tuple(_envelope_from_capture(root, slug) for slug in _RECORDING_SLUGS))


@pytest.mark.recorded(_SCOPE)
def test_recorded_all_12_products_at_01041_ist_day_and_shared_cache_reuse(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    replay = _replay(retained_evidence_root)
    store = StoreRoot(tmp_path / "store-01041")
    daily_products = tuple(ProductId(spec.product_id) for spec in PRODUCT_SPECS if spec.route == "year.json")
    daily_req = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("01041",),
        products=daily_products,
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 7, 15, 0, 0)),
            WindowEndpoint.from_datetime(datetime(2025, 7, 15, 23, 59, 59, 999999)),
        ),
        known_series=tuple(source_series("01041", str(pid), origin="catalogue") for pid in daily_products),
    )
    daily_res = drive(
        daily_req,
        _IeOpwStages(),
        provenance=_provenance(daily_req),
        receipts=ReceiptMode.INCLUDE,
        transport=replay,
        cache="reuse",
        store=store,
    )
    assert replay.calls == 3
    assert daily_res.canonical_rows.height == 9
    assert daily_res.canonical_rows["time_zone"].unique().to_list() == ["+00:00"]
    assert daily_res.canonical_rows.filter(pl.col("product_id") == "discharge_daily_mean")[
        "value"
    ].item() == pytest.approx(3.859)
    assert daily_res.canonical_rows.filter(pl.col("product_id") == "stage_daily_mean")["value"].item() == pytest.approx(
        4.15
    )
    assert daily_res.canonical_rows.filter(pl.col("product_id") == "water_temperature_daily_mean")[
        "value"
    ].item() == pytest.approx(16.6)
    assert set(daily_res.annotations.observation_tables) == {
        IE_OPW_SERIES_SCHEMA.schema_id,
        IE_OPW_DAILY_STAGE_SCHEMA.schema_id,
    }
    assert daily_res.annotations.observation_tables[IE_OPW_DAILY_STAGE_SCHEMA.schema_id].rows[
        "aggregation_accuracy_pct"
    ].to_list() == pytest.approx([100.0, 100.0, 100.0])

    # Single-product subset query reuses cached triplet with 0 HTTP calls.
    sub_req = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("01041",),
        products=(ProductId("stage_daily_max"),),
        window=daily_req.window,
    )
    sub_res = drive(
        sub_req,
        _IeOpwStages(),
        provenance=_provenance(sub_req),
        receipts=ReceiptMode.OMIT,
        transport=_CountingReplay(()),
        cache="reuse",
        store=store,
    )
    assert sub_res.canonical_rows["value"].item() == pytest.approx(4.507)

    # All 3 instantaneous *_complete.zip routes at 01041 across 2025-07-15 & 2026-10-25 DST transition.
    inst_products = (
        ProductId("discharge_instantaneous"),
        ProductId("stage_instantaneous"),
        ProductId("water_temperature_instantaneous"),
    )
    inst_req = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("01041",),
        products=inst_products,
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2026, 10, 25, 0, 0)),
            WindowEndpoint.from_datetime(datetime(2026, 10, 25, 23, 59, 59, 999999)),
        ),
        known_series=tuple(source_series("01041", str(pid), origin="catalogue") for pid in inst_products),
    )
    inst_res = drive(
        inst_req,
        _IeOpwStages(),
        provenance=_provenance(inst_req),
        receipts=ReceiptMode.OMIT,
        transport=replay,
        cache="bypass",
    )
    assert inst_res.canonical_rows.filter(pl.col("product_id") == "discharge_instantaneous").height == 96
    assert inst_res.canonical_rows.filter(pl.col("product_id") == "stage_instantaneous").height == 96
    assert inst_res.canonical_rows.filter(pl.col("product_id") == "water_temperature_instantaneous").height == 24


@pytest.mark.recorded(_SCOPE)
def test_recorded_1940s_depth_negative_od_unmeasured_slots_empty_and_404(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    replay = _replay(retained_evidence_root)

    # 1. Boyne at Slane Castle (07012) back to 1940-06-27 (both daily year.json and 3.03M complete.zip).
    req_1940_daily = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("07012",),
        products=(ProductId("discharge_daily_mean"), ProductId("stage_daily_mean")),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1940, 6, 27)),
            WindowEndpoint.from_datetime(datetime(1940, 6, 28, 23, 59, 59)),
        ),
    )
    res_1940_daily = drive(
        req_1940_daily, _IeOpwStages(), provenance=_provenance(req_1940_daily), transport=replay, cache="bypass"
    )
    assert res_1940_daily.canonical_rows.height == 4
    assert res_1940_daily.canonical_rows["time"].min() == datetime(1940, 6, 27, 0, 0)

    req_1940_zip = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("07012",),
        products=(ProductId("discharge_instantaneous"), ProductId("stage_instantaneous")),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1940, 6, 27, 13, 0)),
            WindowEndpoint.from_datetime(datetime(1940, 6, 27, 15, 0)),
        ),
    )
    res_1940_zip = drive(
        req_1940_zip, _IeOpwStages(), provenance=_provenance(req_1940_zip), transport=replay, cache="bypass"
    )
    assert res_1940_zip.canonical_rows.filter(pl.col("product_id") == "discharge_instantaneous")[
        "time"
    ].min() == datetime(1940, 6, 27, 13, 0)
    assert res_1940_zip.canonical_rows.filter(pl.col("product_id") == "stage_instantaneous").height > 0

    # 2. Wolfe Tone Br (30061) negative Ordnance Datum stage in daily and complete.zip.
    req_30061 = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("30061",),
        products=(ProductId("stage_daily_min"), ProductId("stage_instantaneous")),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2026, 11, 23)),
        ),
    )
    res_30061 = drive(req_30061, _IeOpwStages(), provenance=_provenance(req_30061), transport=replay, cache="bypass")
    assert (
        res_30061.canonical_rows.filter((pl.col("product_id") == "stage_daily_min") & (pl.col("value") < 0)).height > 0
    )
    assert (
        res_30061.canonical_rows.filter((pl.col("product_id") == "stage_instantaneous") & (pl.col("value") < 0)).height
        > 0
    )

    # 3. 06015 all-null, 06025 historic + empty #rows;0 ZIP, 14124 ;;-1 ZIP, 18121 empty data:[], and 99999 HTTP 404.
    req_06015 = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("06015",),
        products=(ProductId("discharge_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2019, 7, 24)),
            WindowEndpoint.from_datetime(datetime(2024, 4, 15, 23, 59, 59)),
        ),
    )
    res_06015 = drive(req_06015, _IeOpwStages(), provenance=_provenance(req_06015), transport=replay, cache="bypass")
    assert res_06015.canonical_rows.is_empty()
    assert [o.status for o in res_06015.outcomes] == [OutcomeStatus.EMPTY]
    assert res_06015.annotations.observation_tables[IE_OPW_SERIES_SCHEMA.schema_id].unmeasured_count == 1728

    req_06025 = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("06025",),
        products=(ProductId("discharge_daily_mean"), ProductId("discharge_instantaneous")),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1972, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2026, 11, 22, 23, 59, 59)),
        ),
    )
    res_06025 = drive(req_06025, _IeOpwStages(), provenance=_provenance(req_06025), transport=replay, cache="bypass")
    assert res_06025.canonical_rows.height == 2094
    assert [o.status for o in res_06025.outcomes] == [OutcomeStatus.SUCCESS, OutcomeStatus.UNRESOLVED]
    assert res_06025.annotations.observation_tables[IE_OPW_SERIES_SCHEMA.schema_id].unmeasured_count == 17956

    req_14124 = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("14124",),
        products=(ProductId("water_temperature_instantaneous"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2022, 8, 14)),
            WindowEndpoint.from_datetime(datetime(2025, 10, 7, 12, 0)),
        ),
    )
    res_14124 = drive(req_14124, _IeOpwStages(), provenance=_provenance(req_14124), transport=replay, cache="bypass")
    assert res_14124.annotations.observation_tables[IE_OPW_SERIES_SCHEMA.schema_id].unmeasured_count == 94

    req_18121 = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("18121",),
        products=(ProductId("water_temperature_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2025, 12, 31)),
        ),
    )
    res_18121 = drive(req_18121, _IeOpwStages(), provenance=_provenance(req_18121), transport=replay, cache="bypass")
    assert [o.status for o in res_18121.outcomes] == [OutcomeStatus.UNRESOLVED]

    req_03055 = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("03055",),
        products=(ProductId("water_temperature_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2016, 2, 7)),
            WindowEndpoint.from_datetime(datetime(2026, 11, 23, 23, 59, 59)),
        ),
    )
    res_03055 = drive(
        req_03055,
        _IeOpwStages(),
        provenance=_provenance(req_03055),
        transport=replay,
        cache="reuse",
        store=StoreRoot(tmp_path / "store-03055"),
    )
    assert res_03055.canonical_rows.height == 3942
    assert res_03055.annotations.observation_tables[IE_OPW_SERIES_SCHEMA.schema_id].unmeasured_count == 1

    req_404 = ObservationRequest(
        provider_id=ProviderId("ie_opw"),
        stations=("01041", "39999"),
        products=(ProductId("discharge_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 7, 15)),
            WindowEndpoint.from_datetime(datetime(2025, 7, 15, 23, 59, 59)),
        ),
    )
    # Use ReplayTransport with a 404 envelope bound at stations/0/39999/Q/year.json.
    envelope_404 = RecordingEnvelope(
        request=RecordedRequest(
            HttpMethod.GET,
            "https://waterlevel.ie/hydro-data/data/internet/stations/0/39999/Q/year.json",
            None,
            ordinary_headers={"User-Agent": TRANSPORT_POLICY.user_agent},
        ),
        content=(retained_evidence_root / _SCOPE / "web" / "opw-99999-missing-404.body").read_bytes(),
        status_code=404,
        retrieved_at=datetime(2026, 11, 23, 20, 40, tzinfo=UTC),
        content_type="text/html",
    )
    res_404 = drive(
        req_404,
        _IeOpwStages(),
        provenance=_provenance(req_404),
        transport=_CountingReplay(
            (_envelope_from_capture(retained_evidence_root, "opw-01041-q-year-json"), envelope_404)
        ),
        cache="bypass",
    )
    assert res_404.canonical_rows["station_id"].to_list() == ["01041"]
    assert {o.station_id: o.status for o in res_404.outcomes}["39999"] is OutcomeStatus.FAILED
