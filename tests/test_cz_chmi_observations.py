"""CHMI recorded observations exercise the real three-stage provider path."""

import json
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    FetchWindow,
    ObservationRequest,
    RenderedWindow,
    RequestedWindow,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.cz_chmi.config import config
from rivretrieve._internal.providers.cz_chmi.declaration import declaration
from rivretrieve._internal.providers.cz_chmi.fetch import fetch
from rivretrieve._internal.providers.cz_chmi.parse import parse
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.recordings import ReplayTransport, read_recording

_DATA = Path(__file__).parent / "test_data"
_DQ = _DATA / "cz_chmi_0-203-1-000400_DQ_2023.recording.json"
_HQ = _DATA / "cz_chmi_0-203-1-000400_HQ_2023.recording.json"
_STATION = "0-203-1-000400"
_PRODUCTS = (
    ProductId("stage_daily_mean"),
    ProductId("discharge_daily_mean"),
    ProductId("water_temperature_daily_mean"),
    ProductId("stage_hourly_mean"),
    ProductId("discharge_hourly_mean"),
)


def _window(start: datetime = datetime(2023, 1, 1), end: datetime = datetime(2023, 12, 31, 23)) -> FetchWindow:
    return _make_fetch_window(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end))


def test_fetch_coalesces_five_products_into_exactly_two_annual_calls() -> None:
    replay = ReplayTransport([_DQ, _HQ])
    rendered = MappingProxyType({product: (RenderedWindow("2023", None),) for product in _PRODUCTS})
    result = fetch((_STATION,), _PRODUCTS, rendered, _window(), config(), replay)
    assert len(result.value) == 2
    assert [payload.station_products for payload in result.value] == [
        tuple((_STATION, product) for product in _PRODUCTS[:3]),
        tuple((_STATION, product) for product in _PRODUCTS[3:]),
    ]
    assert [payload.origin.url for payload in result.value] == [
        read_recording(_DQ).request.url,
        read_recording(_HQ).request.url,
    ]
    assert [payload.content for payload in result.value] == [read_recording(_DQ).content, read_recording(_HQ).content]


@pytest.mark.parametrize(
    ("recording", "products", "counts", "first", "last"),
    [
        (_DQ, _PRODUCTS[:3], [365, 365, 365], datetime(2023, 1, 1), datetime(2023, 12, 31)),
        (_HQ, _PRODUCTS[3:], [8760, 8760], datetime(2023, 1, 1), datetime(2023, 12, 31, 23)),
    ],
)
def test_parse_official_annual_recordings(
    recording: Path, products: tuple[ProductId, ...], counts: list[int], first: datetime, last: datetime
) -> None:
    replay = ReplayTransport([recording])
    rendered = MappingProxyType({product: (RenderedWindow("2023", None),) for product in products})
    fetched = fetch((_STATION,), products, rendered, _window(), config(), replay)
    rows = parse(fetched.value[0], config()).value
    assert rows.columns == ["station_id", "product_id", "time", "value", "time_zone"]
    for product, count in zip(products, counts, strict=True):
        series = rows.filter(pl.col("product_id") == product).sort("time")
        assert series.height == count
        assert series["time"][0] == first
        assert series["time"][-1] == last
        assert series["time_zone"].unique().to_list() == ["+00:00"]


def test_official_recording_literals_and_shared_conversion() -> None:
    daily = parse(
        fetch(
            (_STATION,),
            _PRODUCTS[:3],
            MappingProxyType({p: (RenderedWindow("2023", None),) for p in _PRODUCTS[:3]}),
            _window(),
            config(),
            ReplayTransport([_DQ]),
        ).value[0],
        config(),
    ).value
    hourly = parse(
        fetch(
            (_STATION,),
            _PRODUCTS[3:],
            MappingProxyType({p: (RenderedWindow("2023", None),) for p in _PRODUCTS[3:]}),
            _window(),
            config(),
            ReplayTransport([_HQ]),
        ).value[0],
        config(),
    ).value
    assert daily.group_by("product_id").len().sort("product_id")["len"].to_list() == [365, 365, 365]
    assert hourly.group_by("product_id").len().sort("product_id")["len"].to_list() == [8760, 8760]
    assert daily.filter(pl.col("product_id") == "stage_daily_mean").sort("time")["value"][[0, -1]].to_list() == [
        38.0,
        20.0,
    ]
    assert hourly.filter(pl.col("product_id") == "discharge_hourly_mean").sort("time")["value"][[0, -1]].to_list() == [
        0.869,
        0.197,
    ]


def test_real_driver_path_clips_and_returns_one_receipt_for_coalesced_daily_call() -> None:
    assert isinstance(declaration.observations, LiveStages)
    request = ObservationRequest(
        ProviderId("cz_chmi"),
        (_STATION,),
        tuple(_PRODUCTS[:3]),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2023, 6, 1)), WindowEndpoint.from_datetime(datetime(2023, 6, 2, 23))
        ),
    )
    result = drive(
        request,
        declaration.observations.stages,
        provenance=ObservationProvenance(source="recording", provider_id=ProviderId("cz_chmi")),
        receipts=ReceiptMode.INCLUDE,
        transport=ReplayTransport([_DQ]),
    )
    assert result.canonical_rows.height == 6
    assert len(result.receipts.entries) == 1
    stage = result.canonical_rows.filter(pl.col("product_id") == "stage_daily_mean").sort("time")
    assert stage["value"][0] == pytest.approx(0.13)


def test_coalesced_receipts_preserve_exact_publisher_bytes_origin_order_and_opt_out() -> None:
    assert isinstance(declaration.observations, LiveStages)
    request = ObservationRequest(
        ProviderId("cz_chmi"),
        (_STATION,),
        _PRODUCTS,
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2023, 6, 1)),
            WindowEndpoint.from_datetime(datetime(2023, 6, 2, 23)),
        ),
    )
    included = drive(
        request,
        declaration.observations.stages,
        provenance=ObservationProvenance(source="recording", provider_id=ProviderId("cz_chmi")),
        receipts=ReceiptMode.INCLUDE,
        transport=ReplayTransport([_DQ, _HQ]),
    )
    daily = read_recording(_DQ)
    hourly = read_recording(_HQ)
    assert [entry.content for entry in included.receipts.entries] == [daily.content, hourly.content]
    assert [entry.origin.url for entry in included.receipts.entries] == [daily.request.url, hourly.request.url]
    assert len({entry.origin.url for entry in included.receipts.entries}) == 2
    assert included.canonical_rows.columns == ["time", "time_zone", "station_id", "product_id", "value"]

    omitted = drive(
        request,
        declaration.observations.stages,
        provenance=ObservationProvenance(source="recording", provider_id=ProviderId("cz_chmi")),
        receipts=ReceiptMode.OMIT,
        transport=ReplayTransport([_DQ, _HQ]),
    )
    assert omitted.receipts.entries == ()


def test_parse_preserves_source_null_as_missing_value() -> None:
    fetched = fetch(
        (_STATION,),
        (_PRODUCTS[0],),
        MappingProxyType({_PRODUCTS[0]: (RenderedWindow("2023", None),)}),
        _window(),
        config(),
        ReplayTransport([_DQ]),
    ).value[0]
    document = json.loads(fetched.content)
    document["tsList"][0]["tsData"]["data"]["values"][0][1] = None
    from dataclasses import replace

    parsed = parse(replace(fetched, content=json.dumps(document).encode()), config()).value
    assert parsed["value"][0] is None


def test_parse_rejects_non_utc_and_does_not_invent_quality() -> None:
    recording = read_recording(_DQ)
    content = recording.content.replace(b"2023-01-01T00:00:00Z", b"2023-01-01T00:00:00+01:00", 1)
    fetched = fetch(
        (_STATION,),
        (_PRODUCTS[0],),
        MappingProxyType({_PRODUCTS[0]: (RenderedWindow("2023", None),)}),
        _window(),
        config(),
        ReplayTransport([_DQ]),
    ).value[0]
    from dataclasses import replace

    with pytest.raises(FatalContractError, match="UTC Z suffix"):
        parse(replace(fetched, content=content), config())
    assert "quality" not in parse(fetched, config()).value.columns


def test_public_selection_routes_to_czech_live_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(driver_module, "HttpClient", lambda: ReplayTransport([_HQ]))
    selection = rr.find(provider="cz_chmi", station=_STATION, product="discharge_hourly_mean")
    assert rr.as_frame(selection).select("provider_id", "station_id", "product_id").row(0) == (
        "cz_chmi",
        _STATION,
        "discharge_hourly_mean",
    )
    result = rr.fetch(selection, start="2023-06-01", end="2023-06-02T23:00:00", receipts=True, on_issue="ignore")
    assert result.data.height == 48
    assert len(result.receipts.entries) == 1
