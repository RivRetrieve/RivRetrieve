"""Documentation contracts and replayable example verification for Ireland OPW (`ie_opw`)."""

from __future__ import annotations

import ast
import json
import re
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.providers.ie_opw.series import PRODUCT_SPECS
from rivretrieve._internal.selection import UnknownStationError
from rivretrieve._internal.transport import TransportRequest, TransportResponse

ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "docs/providers/ie_opw.md"
VISION_PATH = ROOT / "planning/visions/2026-11-24-ie-opw-user-documentation.md"

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_FREQUENCY_LABELS = {
    "P1D": "Daily",
    None: "Unknown",
}
_STATISTIC_LABELS = {
    "mean": "Mean",
    "min": "Minimum",
    "max": "Maximum",
    "instantaneous": "Instantaneous",
}


def _python_and_output_blocks(markdown: str) -> tuple[list[str], list[str]]:
    python_blocks = re.findall(r"```python\n(.*?)```", markdown, re.DOTALL)
    output_blocks = re.findall(r"Output:\s*\n+```text\n(.*?)```", markdown, re.DOTALL)
    return python_blocks, output_blocks


def _parse_retrieval_table(markdown: str) -> list[tuple[str, str, str, str, str, str]]:
    header = "| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |"
    lines = markdown.splitlines()
    start = lines.index(header)
    rows: list[tuple[str, str, str, str, str, str]] = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        assert len(cells) == 6, line
        rows.append((cells[0], cells[1], cells[2], cells[3], cells[4], cells[5]))
    return rows


def test_ie_opw_guide_is_linked_plain_and_matches_packaged_catalogue() -> None:
    guide = GUIDE_PATH.read_text(encoding="utf-8")
    vision = VISION_PATH.read_text(encoding="utf-8")

    for label, text in (("guide", guide), ("vision", vision)):
        assert "\u2014" not in text, f"{label} must not contain em dashes"
        assert " -- " not in text, f"{label} must not contain spaced double hyphens"
        assert "product_id" not in text, f"{label} must avoid internal column product_id"
        assert "result.outcomes" not in text, f"{label} must avoid internal attribute result.outcomes"

    docs_index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    mkdocs_cfg = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    metadata_doc = (ROOT / "docs/station-metadata.md").read_text(encoding="utf-8")

    assert "- [Ireland: OPW](providers/ie_opw.md)" in docs_index
    assert "- Ireland (OPW): providers/ie_opw.md" in mkdocs_cfg
    assert (
        "| [`ie_opw`](providers/ie_opw.md) | `station_name` | `WTO_OBJECT` | `CATCHMENT_SIZE` (km²) | — |"
        in metadata_doc
    )
    assert "[OPW's terms](providers/ie_opw.md#terms-and-citation)" in metadata_doc

    selected = rr.find(provider="ie_opw")
    catalogue_root = ROOT / "src/rivretrieve/_internal/providers/ie_opw/catalogue"
    stations = pl.read_parquet(catalogue_root / "stations.parquet")
    station_products = pl.read_parquet(catalogue_root / "station_products.parquet")
    series_frame = rr.as_frame(selected)

    assert stations.height == 385
    assert series_frame["station_id"].n_unique() == 385
    assert series_frame.height == 3_788
    assert station_products.filter(pl.col("availability") == "available").height == 3_788
    assert station_products.filter(pl.col("availability") == "unavailable").height == 832
    assert station_products.filter(pl.col("availability") == "unknown").height == 0

    # Verify documented EPA-numbered river stations kept and out-of-scope IDs excluded.
    kept_ids = set(stations["station_id"].to_list())
    assert {"01041", "07012", "06025", "09045", "10047", "10048", "10049", "10050", "30061"} <= kept_ids
    for excluded in ("80101", "30089", "06062", "29002"):
        with pytest.raises(UnknownStationError):
            rr.find(provider="ie_opw", station=excluded)

    meta_source = rr.metadata(selected, view="source")
    counts = dict(
        meta_source.group_by("attribute_role", "state")
        .len()
        .select(pl.concat_str(["attribute_role", "state"], separator=":"), "len")
        .iter_rows()
    )
    assert counts["station_name:value"] == 385
    assert counts["water_body_name:value"] == 383
    assert counts["water_body_name:source_null"] == 2
    assert counts["drainage_area:value"] == 380
    assert counts["drainage_area:source_null"] == 5
    assert counts["elevation:no_metadata"] == 385

    station_01041 = rr.metadata(rr.find(provider="ie_opw", station="01041")).row(0, named=True)
    assert station_01041["station_name"] == "Sandy Mills"
    assert station_01041["water_body_name_value"] == ["DEELE"]
    assert station_01041["drainage_area_value"] == ['"113.00"']
    assert station_01041["drainage_area_unit"] == ["km²"]
    assert station_01041["elevation_value"] is None

    descriptor = rr.describe("ie_opw")
    assert descriptor["license"] == "CC BY 4.0"
    assert (
        descriptor["citation"]
        == "Contains Irish Public Sector Information licensed under a Creative Commons Attribution 4.0 International (CC BY 4.0) licence (source http://waterlevel.ie/hydro-data/ - provided by the Office of Public Works.)"
    )


def test_ie_opw_six_column_retrieval_table_matches_all_12_products() -> None:
    guide = GUIDE_PATH.read_text(encoding="utf-8")
    rows = _parse_retrieval_table(guide)
    assert len(rows) == len(PRODUCT_SPECS) == 12

    packaged = rr.as_frame(rr.find(provider="ie_opw")).unique(subset=["product_id"])
    by_product = {row["product_id"]: row for row in packaged.iter_rows(named=True)}
    assert len(by_product) == 12

    seen_specs: list[tuple[str, str]] = []
    for qty_cell, source_cell, freq_cell, stat_cell, src_unit_cell, ret_unit_cell in rows:
        match = re.fullmatch(r"`([^`]+)`\s*\(`([^`]+)`\)", source_cell)
        assert match is not None, source_cell
        route_text, published_id = match.groups()
        spec = next(
            (
                item
                for item in PRODUCT_SPECS
                if f"{item.parameter}/{item.route}" == route_text and item.ts_shortname == published_id
            ),
            None,
        )
        assert spec is not None, f"Table row does not match any ProductSpec: {source_cell}"
        seen_specs.append((spec.parameter, spec.ts_shortname))

        row = by_product[spec.product_id]
        expected_qty = "temperature" if spec.quantity == "temperature" else spec.quantity
        assert qty_cell == f"`{expected_qty}`"
        assert freq_cell == _FREQUENCY_LABELS[row["frequency"]]
        assert stat_cell == _STATISTIC_LABELS[row["statistic"]]
        assert src_unit_cell == f"`{row['source_unit']}`"
        assert ret_unit_cell == f"`{row['unit']}`"

    assert len(set(seen_specs)) == 12


@pytest.mark.recorded("maintenance/observations/ie_opw/retrieval")
def test_ie_opw_documented_python_examples_execute_against_retained_evidence(
    retained_evidence_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    guide = GUIDE_PATH.read_text(encoding="utf-8")
    python_blocks, output_blocks = _python_and_output_blocks(guide)
    assert len(python_blocks) == 2
    assert len(output_blocks) == 1
    for block in python_blocks:
        ast.parse(block)

    web_root = retained_evidence_root / "maintenance/observations/ie_opw/retrieval/web"
    body = (web_root / "opw-01041-q-year-json.body").read_bytes()
    receipt = json.loads((web_root / "opw-01041-q-year-json.receipt.json").read_text(encoding="utf-8"))

    class _ReplayTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            assert request.url == receipt["url"]
            return TransportResponse(
                content=body,
                status_code=int(receipt["http_status"]),
                retrieved_at=datetime.fromisoformat(str(receipt["retrieved_at"])),
                content_type="application/json",
                url=request.url,
                request_parameters={},
            )

    monkeypatch.setattr(discovery, "HttpClient", _ReplayTransport)
    scope: dict[str, object] = {}
    exec(compile(python_blocks[0], str(GUIDE_PATH), "exec"), scope)
    assert capsys.readouterr().out == output_blocks[0]

    class _ForbidNetwork:
        def send(self, request: TransportRequest) -> TransportResponse:
            raise AssertionError(f"Offline example attempted HTTP call: {request.url}")

    monkeypatch.setattr(discovery, "HttpClient", _ForbidNetwork)
    offline_scope: dict[str, object] = {"rr": rr}
    exec(compile(python_blocks[1], str(GUIDE_PATH), "exec"), offline_scope)
    series_table = offline_scope["series_table"]
    station_info = offline_scope["station_info"]
    assert isinstance(series_table, pl.DataFrame) and series_table.height == 12
    assert isinstance(station_info, pl.DataFrame) and station_info.row(0, named=True)["station_name"] == "Sandy Mills"
