"""Official MLIT recordings exercise the real shared-engine path."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    FetchWindow,
    ObservationRequest,
    RenderedWindow,
    RequestedWindow,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.jp_mlit.config import config
from rivretrieve._internal.providers.jp_mlit.declaration import declaration
from rivretrieve._internal.providers.jp_mlit.fetch import _page, fetch
from rivretrieve._internal.providers.jp_mlit.parse import parse
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.recordings import ReplayTransport, read_recording

_DATA = Path(__file__).parent / "test_data"
_STATION = "301011281104010"
_PRODUCTS = tuple(map(ProductId, ("stage_hourly", "stage_daily", "discharge_hourly", "discharge_daily")))
_PATHS = tuple(
    path
    for product in _PRODUCTS
    for path in (
        _DATA / f"jp_mlit_{product}_2023_html.recording.json",
        _DATA / f"jp_mlit_{product}_2023_dat.recording.json",
    )
)
_WINDOWS = MappingProxyType(
    {
        product: (RenderedWindow("2023-01-01", "2023-01-31" if "hourly" in product else "2023-12-31"),)
        for product in _PRODUCTS
    }
)


def _window() -> FetchWindow:
    return _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2023, 1, 1)), WindowEndpoint.from_datetime(datetime(2023, 12, 31))
    )


def _fetched():
    return fetch((_STATION,), _PRODUCTS, _WINDOWS, _window(), config(), ReplayTransport(_PATHS)).value


def test_page_rejects_stage_html_when_exact_recorded_unit_is_mutated() -> None:
    content = read_recording(_PATHS[0]).content
    mutated = content.replace("単位：m".encode("euc-jp"), "単位：cm".encode("euc-jp"))

    with pytest.raises(UnsupportedSourceStructureError, match="unit"):
        _page(mutated, 2, _STATION)


@pytest.mark.parametrize(
    ("path_index", "kind", "original", "replacement"),
    [
        (0, 2, "単位：m", ""),
        (0, 2, "単位：m", "単位：m</TD></TR><TR><TD>単位：m"),
        (4, 6, "単位：m<SUP>3</SUP>/s", "単位：m"),
        (4, 6, "単位：m<SUP>3</SUP>/s", ""),
        (4, 6, "単位：m<SUP>3</SUP>/s", "単位：m3/s"),
        (4, 6, "単位：m<SUP>3</SUP>/s", "単位：m<SUP>3</SUP>/s</TD></TR><TR><TD>単位：m<SUP>3</SUP>/s"),
    ],
    ids=(
        "stage-missing",
        "stage-ambiguous",
        "discharge-other-product-unit",
        "discharge-missing",
        "discharge-flattened-markup",
        "discharge-ambiguous",
    ),
)
def test_page_rejects_wrong_missing_ambiguous_or_unstructured_units(
    path_index: int, kind: int, original: str, replacement: str
) -> None:
    content = read_recording(_PATHS[path_index]).content
    source = original.encode("euc-jp")
    assert content.count(source) == 1
    mutated = content.replace(source, replacement.encode("euc-jp"))

    with pytest.raises(UnsupportedSourceStructureError, match="exact publisher unit"):
        _page(mutated, kind, _STATION)


def test_page_rejects_discharge_unit_when_title_is_mutated_to_stage_product() -> None:
    content = read_recording(_PATHS[4]).content
    mutated = content.replace("時刻流量月表検索結果".encode("euc-jp"), "時刻水位月表検索結果".encode("euc-jp"))

    with pytest.raises(UnsupportedSourceStructureError, match="exact publisher unit"):
        _page(mutated, 2, _STATION)


def test_fetch_returns_all_eight_untouched_payloads_in_caller_order() -> None:
    payloads = _fetched()
    assert [(p.source_coordinates.value.kind, p.source_coordinates.value.role) for p in payloads] == [
        (2, "html"),
        (2, "dat"),
        (3, "html"),
        (3, "dat"),
        (6, "html"),
        (6, "dat"),
        (7, "html"),
        (7, "dat"),
    ]
    assert [p.content for p in payloads] == [read_recording(path).content for path in _PATHS]
    assert [p.origin.url for p in payloads] == [read_recording(path).request.url for path in _PATHS]


@pytest.mark.parametrize(
    ("index", "count", "first", "last", "first_value", "last_value"),
    [
        (1, 744, datetime(2023, 1, 1, 1), datetime(2023, 2, 1), 321.52, 321.58),
        (3, 365, datetime(2023, 1, 1), datetime(2023, 12, 31), 321.57, 321.52),
        (5, 192, datetime(2023, 1, 1, 1), datetime(2023, 1, 31, 12), 2.52, 1.99),
        (7, 365, datetime(2023, 1, 1), datetime(2023, 12, 31), 4.47, 3.61),
    ],
)
def test_exact_official_boundaries(
    index: int, count: int, first: datetime, last: datetime, first_value: float, last_value: float
) -> None:
    result = parse(_fetched()[index], config())
    rows = result.rows.sort("time")
    assert rows.columns == [
        "station_id",
        "product_id",
        "time",
        "value",
        "time_zone",
        "series_id",
        "facts_id",
        "source_unit",
    ]
    assert rows.height == count
    assert rows["time"][[0, -1]].to_list() == [first, last]
    assert rows["value"][[0, -1]].to_list() == pytest.approx([first_value, last_value])
    assert rows["time_zone"].unique().to_list() == ["unknown"]
    if index == 5:
        assert len(result.issues) == 1
        issue = result.issues[0]
        assert issue.details is not None
        assert (issue.code, issue.details["count"]) == ("source_missing", 552)


def test_html_parse_validates_and_returns_no_rows() -> None:
    for payload in _fetched()[::2]:
        assert parse(payload, config()).rows.is_empty()


def test_flags_control_observation_status_without_numeric_threshold() -> None:
    payload = _fetched()[1]
    negative = replace(payload, content=payload.content.replace(b"321.52", b"-9999.00", 1))
    assert parse(negative, config()).rows["value"][0] == -9999.0
    tentative = replace(payload, content=payload.content.replace(b"321.52, ", b"321.52,*", 1))
    parsed = parse(tentative, config())
    assert parsed.rows["value"][0] == 321.52
    assert parsed.issues[0].code == "source_tentative"
    unknown = replace(payload, content=payload.content.replace(b"321.52, ", b"321.52,?", 1))
    unsupported = parse(unknown, config())
    assert unsupported.rows.is_empty()
    assert unsupported.outcomes[0].status == "unsupported"
    assert "unknown native flag" in unsupported.outcomes[0].reason


@pytest.mark.parametrize(
    ("flag", "code"), [("$", "source_missing"), ("#", "source_closed_station"), ("-", "source_unregistered")]
)
def test_native_non_observation_flags_are_distinct_and_dropped(flag: str, code: str) -> None:
    payload = _fetched()[1]
    changed = replace(payload, content=payload.content.replace(b"321.52, ", f"321.52,{flag}".encode(), 1))
    result = parse(changed, config())
    assert result.rows.height == 743
    assert result.issues[0].code == code


def test_nonnumeric_usable_cell_fails_loud() -> None:
    payload = _fetched()[1]
    changed = replace(payload, content=payload.content.replace(b"321.52, ", b"unknown, ", 1))
    unsupported = parse(changed, config())
    assert unsupported.rows.is_empty()
    assert unsupported.outcomes[0].status == "unsupported"
    assert "nonnumeric" in unsupported.outcomes[0].reason


def _request() -> ObservationRequest:
    return ObservationRequest(
        ProviderId("jp_mlit"),
        (_STATION,),
        _PRODUCTS,
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2023, 1, 3)), WindowEndpoint.from_datetime(datetime(2023, 1, 29, 23))
        ),
    )


def test_shared_engine_pads_windows_clips_rows_and_preserves_eight_receipts() -> None:
    assert isinstance(declaration.observations, LiveStages)
    result = drive(
        _request(),
        declaration.observations.stages,
        provenance=ObservationProvenance(source="recording", provider_id=ProviderId("jp_mlit")),
        receipts=ReceiptMode.INCLUDE,
        transport=ReplayTransport(_PATHS),
    )
    assert result.canonical_rows.group_by("product_id").len().sort("product_id")["len"].to_list() == [27, 143, 27, 648]
    assert result.canonical_rows.columns == [
        "time",
        "time_zone",
        "station_id",
        "product_id",
        "series_id",
        "facts_id",
        "quantity",
        "source_unit",
        "unit",
        "value",
    ]
    assert len(result.receipts.entries) == 8
    assert [entry.content for entry in result.receipts.entries] == [read_recording(path).content for path in _PATHS]
    request_parameters = [entry.origin.request_parameters for entry in result.receipts.entries]
    assert all(isinstance(parameters, Mapping) for parameters in request_parameters)
    assert (
        len(
            {
                (entry.origin.url, tuple(parameters.items()))
                for entry, parameters in zip(result.receipts.entries, request_parameters, strict=True)
                if isinstance(parameters, Mapping)
            }
        )
        == 8
    )
    html = request_parameters[0]
    assert isinstance(html, Mapping)
    assert dict(html) == {"KIND": 2, "ID": _STATION, "BGNDATE": "20230101", "ENDDATE": "20230131", "KAWABOU": "NO"}
    omitted = drive(
        _request(),
        declaration.observations.stages,
        provenance=ObservationProvenance(source="recording", provider_id=ProviderId("jp_mlit")),
        receipts=ReceiptMode.OMIT,
        transport=ReplayTransport(_PATHS),
    )
    assert omitted.receipts.entries == ()


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_public_selection_uses_corrected_ids_and_exact_eight_call_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(_PATHS))
    selection = rr.find(provider="jp_mlit", station=_STATION)
    assert set(rr.as_frame(selection)["product_id"]) == set(_PRODUCTS)
    assert not any(product.endswith("_mean") for product in rr.as_frame(selection)["product_id"])
    result = rr.fetch(selection, start="2023-01-03", end="2023-01-29T23:00:00", receipts=True, on_issue="ignore")
    assert result.data.height == 845
    assert len(result.receipts.entries) == 8
