"""UK NRFA provider documentation checks against packaged catalogues and verified live output."""

from __future__ import annotations

import ast
import io
import json
import re
import socket
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.uk_nrfa.annotations import (
    UK_NRFA_AMAX_REJECTION_SCHEMA,
    UK_NRFA_OBSERVATIONS_SCHEMA,
    UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA,
    UK_NRFA_SERIES_METADATA_SCHEMA,
)
from rivretrieve._internal.providers.uk_nrfa.config import config
from rivretrieve._internal.selection import UnknownStationError
from rivretrieve._internal.transport import HttpMethod, TransportRequest, TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/providers/uk_nrfa.md"

_EXPECTED_LICENSE = (
    "Click-Through Licence for Access to UK National River Flow Archive Data Available "
    "from the UK Centre for Ecology & Hydrology"
)
_EXPECTED_CITATION = "Data from the UK National River Flow Archive"


def _deny_network(*args: object, **kwargs: object) -> None:
    pytest.fail("UK NRFA documentation test attempted real network access")


def test_uk_nrfa_page_selection_and_metadata_are_offline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _deny_network)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)

    page = PAGE.read_text(encoding="utf-8")
    blocks = re.findall(r"```python\n(.*?)```", page, re.DOTALL)
    assert len(blocks) == 1

    tree = ast.parse(blocks[0])
    fetch_index = next(
        index
        for index, statement in enumerate(tree.body)
        if isinstance(statement, ast.Assign)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == "fetch"
    )

    namespace: dict[str, object] = {}
    captured = io.StringIO()
    with redirect_stdout(captured):
        exec(
            compile(ast.Module(body=tree.body[:fetch_index], type_ignores=[]), "uk_nrfa.md:selection", "exec"),
            namespace,
        )

    assert captured.getvalue() == "['gdf', 'ndf']\n"

    selection = namespace["selection"]
    gdf = namespace["gdf"]
    assert rr.series(gdf).select(  # type: ignore[arg-type]
        "station_id",
        "product_id",
        "published_id",
        "variant",
        "quantity",
        "frequency",
        "statistic",
        "source_unit",
        "unit",
        "time_zone",
    ).rows() == [("39001", "gdf", "gdf", None, "discharge", "daily", "mean", "m3/s", "m3/s", None)]

    metadata = rr.metadata(selection).row(0, named=True)  # type: ignore[arg-type]
    assert metadata["station_name"] == "Thames at Kingston"
    assert metadata["water_body_name_value"] == ["Thames"]
    assert metadata["drainage_area_value"] == ["9948.0"]
    assert metadata["drainage_area_unit"] == ["km²"]
    assert metadata["elevation_value"] == ["4.7"]
    assert metadata["elevation_unit"] == ["m"]
    assert metadata["elevation_datum"] == ["Ordnance Datum"]


def test_uk_nrfa_page_example_and_documented_edge_behaviors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _deny_network)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)

    page = PAGE.read_text(encoding="utf-8")
    matched = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.DOTALL)
    assert len(matched) == 1
    code, expected_output = matched[0]

    gdf_header = {
        "id": "gdf",
        "name": "Gauged Daily Flow",
        "parameter": "Flow",
        "units": "m3/s",
        "measurement-type": "Mean",
        "period": "P1D",
    }
    five_day_payload = {
        "timestamp": "2026-11-18T13:54:00Z",
        "station": {"id": 39001, "name": "Thames at Kingston"},
        "data-type": gdf_header,
        "data-stream": [
            "2020-01-01",
            [157.3, "S"],
            "2020-01-02",
            [135.5, "S"],
            "2020-01-03",
            [130.7, "S"],
            "2020-01-04",
            [131.5, "S"],
            "2020-01-05",
            [129.6, "S"],
        ],
    }
    empty_payload = {
        "timestamp": "2026-11-18T13:54:00Z",
        "station": {"id": 39001, "name": "Thames at Kingston"},
        "data-type": gdf_header,
        "data-stream": [],
    }

    class _DocMockTransport:
        def __init__(self) -> None:
            self.calls: list[TransportRequest] = []
            self.next_payload: dict[str, object] = five_day_payload

        def send(self, request: TransportRequest) -> TransportResponse:
            assert request.method is HttpMethod.GET
            assert request.url == "https://nrfaapps.ceh.ac.uk/nrfa/ws/time-series"
            assert request.params is not None
            self.calls.append(request)
            return TransportResponse(
                content=json.dumps(self.next_payload).encode("utf-8"),
                status_code=200,
                retrieved_at=datetime(2026, 11, 18, 13, 54, 0, tzinfo=UTC),
                content_type="application/json",
                url=request.url,
                request_parameters=dict(request.params),
            )

    transport = _DocMockTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    namespace: dict[str, object] = {}
    captured = io.StringIO()
    with redirect_stdout(captured):
        exec(compile(code, "uk_nrfa.md:example", "exec"), namespace)

    assert captured.getvalue() == expected_output
    assert len(transport.calls) == 1
    assert transport.calls[0].params == {
        "station": "39001",
        "data-type": "gdf",
        "format": "json-object",
        "dates": "true",
        "flags": "true",
        "start-date": "2019-12-30",
        "end-date": "2020-01-07",
    }
    result = namespace["result"]
    assert result.data.height == 5  # type: ignore[attr-defined]
    assert result.issues == ()  # type: ignore[attr-defined]
    assert result.provenance.citation == _EXPECTED_CITATION  # type: ignore[attr-defined]
    assert result.provenance.license == _EXPECTED_LICENSE  # type: ignore[attr-defined]

    with pytest.raises(FatalContractError, match="time_zone is 'unknown'"):
        rr.to_utc(result)  # type: ignore[arg-type]

    transport.next_payload = empty_payload
    empty_res = rr.fetch(
        rr.pick(rr.find(provider="uk_nrfa", station="39001"), variant="gdf"),
        start="2020-01-01",
        end="2020-01-05",
        cache="bypass",
    )
    assert empty_res.data.is_empty()
    assert empty_res.issues == ()
    assert rr.series(empty_res)["outcomes"].to_list() == [["empty"]]
    assert empty_res.to_polars(annotations=True).height == 0
    with pytest.raises(ValueError, match="Unknown observation annotation field: 'flag'"):
        empty_res.to_polars(annotations=["flag"])

    with pytest.raises(UnknownStationError):
        rr.find(provider="uk_nrfa", station="999999")

    unadvertised = rr.find(provider="uk_nrfa", station="6007", variant="ndf", on_issue="ignore")
    assert any(issue.code == "selection.unresolved_inventory" for issue in unadvertised.issues)


def test_uk_nrfa_page_product_table_catalogue_claims_and_links(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _deny_network)
    monkeypatch.chdir(tmp_path)

    page = PAGE.read_text(encoding="utf-8")
    assert "\u2014" not in page, "docs/AGENTS.md forbids em dashes in docs/providers/uk_nrfa.md"
    assert "inventory_windows" not in page

    for public_attr in re.findall(r"\brr\.([A-Za-z_][A-Za-z0-9_]*)", page):
        assert hasattr(rr, public_attr), f"docs/providers/uk_nrfa.md references missing rr.{public_attr}"

    expected_header = (
        "| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |"
    )
    assert expected_header in page

    table_rows = re.findall(
        r"^\|\s*`(discharge|stage)`\s*\|\s*`([^`]+)`[^|\n]*\|\s*(Daily|Monthly|Unknown)\s*\|\s*(Mean|Maximum|Unknown)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|$",
        page,
        re.MULTILINE,
    )
    assert len(table_rows) == 10

    all_uk = rr.find(provider="uk_nrfa")
    assert len(all_uk.locations) == 1604
    all_series = rr.series(all_uk)
    assert all_series["station_id"].n_unique() == 1604
    assert all_series.height == 9052

    freq_map = {"Daily": "daily", "Monthly": "monthly", "Unknown": None}
    stat_map = {"Mean": "mean", "Maximum": "max", "Unknown": None}
    unit_map = {"m³/s": "m3/s", "m3/s": "m3/s", "m": "m"}
    covered_products: set[str] = set()
    for qty, product_id, freq_label, stat_label, src_unit_label, ret_unit_label in table_rows:
        sub = all_series.filter((pl.col("quantity") == qty) & (pl.col("published_id") == product_id))
        assert sub.height > 0
        covered_products.add(product_id)
        assert set(sub["product_id"].to_list()) == {product_id}
        assert set(sub["variant"].to_list()) == {None}
        assert set(sub["frequency"].to_list()) == {freq_map[freq_label]}
        assert set(sub["statistic"].to_list()) == {stat_map[stat_label]}
        assert set(sub["source_unit"].to_list()) == {unit_map[src_unit_label]}
        assert set(sub["unit"].to_list()) == {unit_map[ret_unit_label]}
        assert set(sub["time_zone"].to_list()) == {None}

    assert covered_products == set(all_series["product_id"].unique().to_list())

    stage_series = all_series.filter(pl.col("quantity") == "stage")
    flow_series = all_series.filter(pl.col("quantity") == "discharge")
    assert set(stage_series["vertical_reference"].to_list()) == {"gauge_zero"}
    assert set(stage_series["vertical_datum"].to_list()) == {None}
    assert set(flow_series["vertical_reference"].to_list()) == {None}

    product_counts = dict(all_series.group_by("product_id").len().iter_rows())
    assert product_counts == {
        "gdf": 1574,
        "gmf": 1574,
        "ndf": 123,
        "nmf": 336,
        "amax-flow": 949,
        "amax-stage": 917,
        "pot-flow": 894,
        "pot-stage": 865,
        "gauging-flow": 910,
        "gauging-stage": 910,
    }
    for formatted_count in ("1,604", "9,052", "1,574", "123", "336", "949", "917", "894", "865", "910"):
        assert formatted_count in page

    all_meta = rr.metadata(all_uk)
    assert all_meta.height == 1604
    assert all_meta.filter(pl.col("elevation_value").list.get(0).is_null()).height == 64
    elev_source = rr.metadata(all_uk, view="source").filter(pl.col("attribute_role") == "elevation")
    assert dict(elev_source.group_by("source_datum").len().iter_rows()) == {
        "Ordnance Datum": 1550,
        "Malin Head": 54,
    }
    for contextual_phrase in ("64 stations", "1,550 stations", "54 stations", "30 calendar days"):
        assert contextual_phrase in page

    assert config().cache.max_retention == timedelta(days=30)

    descriptor = rr.describe("uk_nrfa")
    assert descriptor["citation"] == _EXPECTED_CITATION
    assert descriptor["license"] == _EXPECTED_LICENSE
    assert _EXPECTED_CITATION in page
    assert _EXPECTED_LICENSE in page

    for schema in (
        UK_NRFA_OBSERVATIONS_SCHEMA,
        UK_NRFA_SERIES_METADATA_SCHEMA,
        UK_NRFA_AMAX_REJECTION_SCHEMA,
        UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA,
    ):
        assert schema.schema_id in page
        for field in schema.fields:
            assert field.name in page

    assert "providers/uk_nrfa.md" in (ROOT / "docs/README.md").read_text(encoding="utf-8")
    assert "providers/uk_nrfa.md" in (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    assert "[`uk_nrfa`](providers/uk_nrfa.md)" in (ROOT / "docs/station-metadata.md").read_text(encoding="utf-8")
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "`uk_nrfa` | 1,604 | Open" in readme_text
