"""SYKE recorded observations exercise the real fetch/parse path against genuine responses."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import MappingProxyType

import polars as pl
import pytest

from rivretrieve._internal.engine import RenderedWindow, WindowEndpoint, _make_fetch_window
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.fi_syke.config import config
from rivretrieve._internal.providers.fi_syke.fetch import fetch
from rivretrieve._internal.providers.fi_syke.parse import parse
from rivretrieve._internal.providers.fi_syke.series import describe_series
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.source_series import admission

_DATA = Path("tests/test_data")


def _rendered(product: ProductId, start: str, stop: str) -> MappingProxyType:
    fetch_window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime.fromisoformat(start.removesuffix("Z"))),
        WindowEndpoint.from_datetime(datetime.fromisoformat(stop.removesuffix("Z"))),
    )
    return MappingProxyType({product: (RenderedWindow(start, stop, fetch_window),)})


@pytest.mark.recorded("tests/test_data/fi_syke_discharge_894_recent_page01.recording.json")
def test_official_discharge_recording(retained_evidence_root) -> None:
    product = ProductId("discharge_reported")
    recording = _DATA / "fi_syke_discharge_894_recent_page01.recording.json"
    rendered = _rendered(product, "2026-10-29T00:00:00Z", "2026-11-07T00:00:00Z")
    fetch_window = rendered[product][0].bounds
    result = fetch(
        ("894",), (product,), rendered, fetch_window, config(), ReplayTransport([retained_evidence_root / recording])
    )
    rows = parse(result.value[0], config()).rows
    assert rows.height == 9
    assert rows["source_unit"].unique().to_list() == ["m3/s"]
    assert rows.sort("time")["value"].to_list() == [
        17.00,
        17.39,
        17.59,
        17.59,
        18.51,
        19.04,
        19.03,
        19.03,
        18.80,
    ]


@pytest.mark.recorded("tests/test_data/fi_syke_stage_2471_recent_page01.recording.json")
def test_official_stage_recording_admits_cm_to_m_conversion(retained_evidence_root) -> None:
    product = ProductId("stage_reported")
    recording = _DATA / "fi_syke_stage_2471_recent_page01.recording.json"
    rendered = _rendered(product, "2026-10-15T00:00:00Z", "2026-11-07T00:00:00Z")
    fetch_window = rendered[product][0].bounds
    result = fetch(
        ("2471",), (product,), rendered, fetch_window, config(), ReplayTransport([retained_evidence_root / recording])
    )
    rows = parse(result.value[0], config()).rows
    assert rows.height == 14
    assert rows["source_unit"].unique().to_list() == ["cm"]
    # parse() rows carry the raw native value (cm); cm->m conversion (factor 0.01)
    # is an Admission fact applied downstream, not here -- matching au_bom's convention.
    sorted_rows = rows.sort("time")
    assert sorted_rows["value"][0] == pytest.approx(24475.0)
    assert sorted_rows["value"][-1] == pytest.approx(24469.0)
    fact = describe_series("2471", str(product)).facts[0]
    assert admission(fact).status == "supported"
    assert admission(fact).target_unit == "m"
    assert admission(fact).factor == 0.01


@pytest.mark.recorded("tests/test_data/fi_syke_temperature_1685_recent_page01.recording.json")
def test_official_water_temperature_recording_has_no_lippu_field(retained_evidence_root) -> None:
    product = ProductId("water_temperature_reported")
    recording = _DATA / "fi_syke_temperature_1685_recent_page01.recording.json"
    rendered = _rendered(product, "2026-10-29T00:00:00Z", "2026-11-07T00:00:00Z")
    fetch_window = rendered[product][0].bounds
    result = fetch(
        ("1685",), (product,), rendered, fetch_window, config(), ReplayTransport([retained_evidence_root / recording])
    )
    parsed = parse(result.value[0], config())
    assert parsed.rows.height == 10
    assert parsed.rows["source_unit"].unique().to_list() == ["°C"]
    assert not parsed.issues


@pytest.mark.recorded(
    *(f"tests/test_data/fi_syke_discharge_894_multipage_page{i:02d}.recording.json" for i in range(1, 10))
)
def test_genuine_nextlink_pagination_across_nine_real_pages(retained_evidence_root) -> None:
    product = ProductId("discharge_reported")
    recordings = [
        retained_evidence_root / _DATA / f"fi_syke_discharge_894_multipage_page{i:02d}.recording.json"
        for i in range(1, 10)
    ]
    rendered = _rendered(product, "1959-01-01T00:00:00Z", "1970-01-01T00:00:00Z")
    fetch_window = rendered[product][0].bounds
    result = fetch(("894",), (product,), rendered, fetch_window, config(), ReplayTransport(recordings))
    assert len(result.value) == 9
    assert not result.failed_requests
    rows = pl.concat([parse(payload, config()).rows for payload in result.value])
    assert rows.height == 4019
    sorted_rows = rows.sort("time")
    assert sorted_rows["time"][0] == datetime(1959, 1, 1)
    assert sorted_rows["time"][-1] == datetime(1970, 1, 1)
    # Genuine odata.nextLink pages are followed in order, not reassembled from a single call.
    pages = [read_recording(path) for path in recordings]
    assert [payload.content for payload in result.value] == [page.content for page in pages]
