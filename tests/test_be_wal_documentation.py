"""Belgium - Wallonia (`be_wal`) documentation checks over packaged catalogues and retained KiWIS captures."""

from __future__ import annotations

import ast
import io
import json
import re
import socket
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.providers.be_wal.series import PRODUCT_BY_ID, PRODUCT_SPECS
from rivretrieve._internal.transport import TransportRequest, TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/providers/be_wal.md"
VISION = ROOT / "planning/visions/2026-11-24-be-wal-user-documentation.md"
_SCOPE = "maintenance/observations/be_wal/retrieval"


def _response_from_capture(root: Path, group: str, name: str, request: TransportRequest) -> TransportResponse:
    base = root / _SCOPE / group / name
    body = base.with_suffix(".body").read_bytes()
    receipt = json.loads(base.with_suffix(".receipt.json").read_text())
    expected = urlsplit(str(receipt["url"]))
    expected_params = {key: vals[0] for key, vals in parse_qs(expected.query, keep_blank_values=True).items()}
    actual_params = dict(request.params or {})
    assert request.url == f"{expected.scheme}://{expected.netloc}{expected.path}"
    assert actual_params == expected_params
    media_type = receipt.get("media_type")
    content_type = str(media_type) if isinstance(media_type, str) and media_type else None
    retrieved_at = datetime.fromisoformat(str(receipt["retrieved_at"]).replace("Z", "+00:00"))
    return TransportResponse(
        content=body,
        status_code=int(str(receipt["http_status"])),
        retrieved_at=retrieved_at,
        content_type=content_type,
        url=request.url,
        request_parameters=actual_params,
    )


def test_be_wal_page_selection_discovery_and_catalogue_claims_are_offline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        pytest.fail("Wallonia offline discovery attempted network access")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.chdir(tmp_path)

    page = PAGE.read_text()
    vision = VISION.read_text()
    assert "\u2014" not in page
    assert "\u2014" not in vision
    for internal_token in ("product_id", "result.outcomes"):
        assert internal_token not in page

    blocks = re.findall(r"```python\n(.*?)```", page, re.DOTALL)
    assert len(blocks) == 3

    tree = ast.parse(blocks[0])
    fetch_index = next(
        index
        for index, statement in enumerate(tree.body)
        if isinstance(statement, ast.Assign)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == "fetch"
    )
    namespace: dict[str, Any] = {}
    exec(
        compile(ast.Module(body=tree.body[:fetch_index], type_ignores=[]), "be_wal.md:selection", "exec"),
        namespace,
    )
    exec(compile(blocks[1], "be_wal.md:discovery", "exec"), namespace)

    selected_series = rr.series(namespace["selection"])
    assert selected_series.select(
        "station_id",
        "product_id",
        "published_id",
        "quantity",
        "frequency",
        "statistic",
        "source_unit",
        "unit",
        "time_zone",
    ).rows() == [("6228", "discharge_daily_mean", "298610010", "discharge", "P1D", "mean", "m³/s", "m3/s", "+01:00")]

    candidates = namespace["candidates"]
    assert candidates.height == 13

    hourly_series = rr.series(namespace["hourly_mean"])
    assert hourly_series.select(
        "station_id", "product_id", "published_id", "frequency", "statistic", "time_zone"
    ).rows() == [("6228", "discharge_hourly_mean", "298620010", "PT1H", "mean", "+01:00")]

    metadata = namespace["metadata"].row(0, named=True)
    assert metadata["station_name"] == "CHAUDFONTAINE Pisc"
    assert metadata["crs"] == "EPSG:4326"
    assert metadata["water_body_name_field"] == ["river_name"]
    assert metadata["water_body_name_value"] == ["Vesdre"]
    assert metadata["drainage_area_field"] == ["CATCHMENT_SIZE"]
    assert metadata["drainage_area_value"] == ["683.26"]
    assert metadata["drainage_area_unit"] == ["km2"]
    assert metadata["elevation_field"] is None

    all_be = rr.find(provider="be_wal")
    assert len(all_be.locations) == 338
    all_series = rr.series(all_be)
    assert all_series.height == 8198
    assert all_series["station_id"].n_unique() == 338
    assert all_series["product_id"].n_unique() == 62

    expected_header = (
        "| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |"
    )
    assert page.count(expected_header) == 1

    table_rows = re.findall(
        r"^\|\s*`(discharge|stage|temperature)`\s*\|\s*`([^`]+)`\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|$",
        page,
        re.MULTILINE,
    )
    assert len(table_rows) == 62

    freq_map: dict[str, str | None] = {
        "Unknown": None,
        "`PT1H`": "PT1H",
        "`P1D`": "P1D",
        "`P1M`": "P1M",
        "`P1Y`": "P1Y",
    }
    stat_map: dict[str, str | None] = {
        "Unknown": None,
        "Mean": "mean",
        "Minimum": "min",
        "Maximum": "max",
    }
    unit_map = {"m³/s": "m3/s", "m": "m", "°C": "degC"}

    spec_by_native = {spec.native_id: spec for spec in PRODUCT_SPECS}
    covered_native_ids: set[str] = set()
    for qty, native_id, freq_label, stat_label, src_unit_label, ret_unit_label in table_rows:
        spec = spec_by_native[native_id]
        covered_native_ids.add(native_id)
        assert qty == spec.quantity
        assert freq_map[freq_label] == spec.frequency
        assert stat_map[stat_label] == spec.statistic
        assert spec.source_unit == src_unit_label
        assert spec.normalized_unit == unit_map[ret_unit_label]
        sub = all_series.filter(all_series["product_id"] == spec.product_id)
        assert not sub.is_empty()
        assert set(sub["frequency"].to_list()) == {spec.frequency}
        assert set(sub["statistic"].to_list()) == {spec.statistic}
        assert set(sub["source_unit"].to_list()) == {spec.source_unit}
        assert set(sub["unit"].to_list()) == {spec.normalized_unit}
    assert len(covered_native_ids) == 62

    assert set(all_series["time_zone"].to_list()) == {"+01:00"}
    assert set(all_series.filter(all_series["frequency"].is_null())["temporal_support"].to_list()) == {None}
    assert set(all_series.filter(all_series["frequency"].is_not_null())["temporal_support"].to_list()) == {"interval"}

    stage_series = all_series.filter(all_series["quantity"] == "stage")
    gauge_zero_products = [pid for pid, spec in PRODUCT_BY_ID.items() if spec.family == "stage"]
    asl_products = [pid for pid, spec in PRODUCT_BY_ID.items() if spec.family == "stage_absolute"]
    assert set(stage_series.filter(stage_series["product_id"].is_in(gauge_zero_products))["vertical_reference"]) == {
        "gauge_zero"
    }
    assert set(stage_series.filter(stage_series["product_id"].is_in(asl_products))["vertical_reference"]) == {
        "above_sea_level"
    }
    assert set(stage_series["vertical_datum"].to_list()) == {None}

    source_meta = rr.metadata(all_be, view="source").filter(
        rr.metadata(all_be, view="source")["state"] != "no_metadata"
    )
    role_fields = {
        role: sorted(source_meta.filter(source_meta["attribute_role"] == role)["source_field"].unique().to_list())
        for role in ("station_name", "water_body_name", "drainage_area", "elevation")
    }
    assert role_fields == {
        "station_name": ["station_name"],
        "water_body_name": ["river_name"],
        "drainage_area": ["CATCHMENT_SIZE"],
        "elevation": [],
    }

    descriptor = rr.describe("be_wal")
    assert "license" not in descriptor
    assert (
        descriptor["citation"]
        == "« Sources des données : Service public de Wallonie » ou « Sources des données : SPW »"
    )

    assert "providers/be_wal.md" in (ROOT / "docs/README.md").read_text()
    assert "providers/be_wal.md" in (ROOT / "mkdocs.yml").read_text()
    station_metadata_doc = (ROOT / "docs/station-metadata.md").read_text()
    assert (
        "| [`be_wal`](providers/be_wal.md) | `station_name` | `river_name` | `CATCHMENT_SIZE` (km2) | — |"
        in station_metadata_doc
    )
    assert "[SPW Hydrométrie's terms](providers/be_wal.md#terms-and-citation)" in station_metadata_doc
    assert (
        "| Belgium (Wallonia) | Service public de Wallonie (SPW), Hydrométrie | `be_wal` | 338 | Open |"
        in (ROOT / "README.md").read_text()
    )


@pytest.mark.recorded(_SCOPE)
def test_be_wal_page_retrieval_and_annotation_examples_match_recorded_responses(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    page = PAGE.read_text()
    matched = re.findall(
        r"```python\n((?:(?!```).)*?)```\n\nOutput:\n\n```text\n(.*?)```",
        page,
        re.DOTALL,
    )
    assert len(matched) == 2
    code_intro, expected_intro = matched[0]
    code_ann, expected_ann = matched[1]

    class _DocReplayTransport:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls.append(request.url)
            if request.url == "https://hydrometrie.wallonie.be/services/KiWIS/KiWIS":
                return _response_from_capture(retained_evidence_root, "web", "edge-6228-q20-flood-200-2021", request)
            raise AssertionError(f"Unexpected documentation request: {request.url}")

    transport = _DocReplayTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)

    namespace: dict[str, Any] = {}
    output = io.StringIO()
    with redirect_stdout(output):
        exec(compile(code_intro, "be_wal.md:retrieval", "exec"), namespace)
    assert output.getvalue() == expected_intro

    output_ann = io.StringIO()
    with redirect_stdout(output_ann):
        exec(compile(code_ann, "be_wal.md:annotations", "exec"), namespace)
    assert output_ann.getvalue().splitlines()[-1] + "\n" == expected_ann
    assert "[('be_wal.quality', 'quality_code', 'Int64'), ('be_wal.quality', 'quality_code_name', 'String')]" in (
        output_ann.getvalue()
    )

    assert len(transport.calls) == 2
    result = namespace["result"]
    assert result.provenance.license is None
    assert (
        result.provenance.citation
        == "« Sources des données : Service public de Wallonie » ou « Sources des données : SPW »"
    )
    assert rr.to_utc(result).data["time_zone"].unique().to_list() == ["+00:00"]
