"""Colombia IDEAM documentation checks over packaged catalogues and retained publisher captures."""

from __future__ import annotations

import ast
import io
import json
import re
import socket
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.transport import TransportRequest, TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/providers/co_ideam.md"
VISION = ROOT / "planning/visions/2026-11-09-co-ideam-user-documentation.md"
_SCOPE = "maintenance/observations/co_ideam/retrieval"


def _response_from_capture(root: Path, group: str, name: str, request: TransportRequest) -> TransportResponse:
    base = root / _SCOPE / group / name
    body = base.with_suffix(".body").read_bytes()
    receipt = json.loads(base.with_suffix(".receipt.json").read_text())
    expected_url = str(receipt["url"])
    assert request.url == expected_url
    assert dict(request.params or {}) == {}
    media_type = receipt.get("media_type")
    content_type = str(media_type) if isinstance(media_type, str) and media_type else None
    retrieved_at = datetime.fromisoformat(str(receipt["retrieved_at"]).replace("Z", "+00:00"))
    return TransportResponse(
        content=body,
        status_code=int(str(receipt["http_status"])),
        retrieved_at=retrieved_at,
        content_type=content_type,
        url=expected_url,
        request_parameters={},
    )


def test_co_ideam_page_selection_discovery_and_catalogue_claims_are_offline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        pytest.fail("Colombia IDEAM offline discovery attempted network access")

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
    assert len(blocks) == 2

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
    exec(
        compile(ast.Module(body=tree.body[:fetch_index], type_ignores=[]), "co_ideam.md:selection", "exec"),
        namespace,
    )
    exec(compile(blocks[1], "co_ideam.md:discovery", "exec"), namespace)

    selected_series = rr.series(namespace["selection"])  # type: ignore[arg-type]
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
    ).rows() == [("0011017010", "q_media_d", "Q_MEDIA_D", "discharge", "daily", "mean", "m3/s", "m3/s", None)]

    candidates = namespace["candidates"]
    assert sorted(candidates["published_id"].to_list()) == sorted(  # type: ignore[index]
        [
            "CAUDAL_H",
            "Q_MEDIA_D",
            "Q_MX_D",
            "Q_MN_D",
            "Q_MEDIA_M",
            "Q_MX_M",
            "Q_MN_M",
            "Q_MEDIA_A",
            "Q_MX_A",
            "Q_MN_A",
        ]
    )

    subdaily_series = rr.series(namespace["subdaily"])  # type: ignore[arg-type]
    assert subdaily_series.select("station_id", "product_id", "published_id", "frequency", "statistic").rows() == [
        ("0011017010", "caudal_h", "CAUDAL_H", None, None)
    ]

    metadata = namespace["metadata"].row(0, named=True)  # type: ignore[attr-defined]
    assert metadata["station_name"] == "AGUASAL [11017010]"
    assert metadata["crs"] == "unknown"
    assert metadata["water_body_name_field"] == ["Corriente"]
    assert metadata["water_body_name_value"] == ["ANDAGUEDA"]
    assert metadata["drainage_area_field"] is None
    assert metadata["elevation_field"] == ["Altitud"]
    assert metadata["elevation_value"] == ['"75"']
    assert metadata["elevation_unit"] == [None]
    assert metadata["elevation_datum"] == [None]

    all_co = rr.find(provider="co_ideam")
    assert len(all_co.locations) == 1372
    all_series = rr.series(all_co)
    assert all_series["station_id"].n_unique() == 1372
    assert all_series["product_id"].n_unique() == 20

    expected_header = (
        "| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |"
    )
    assert page.count(expected_header) == 1

    table_rows = re.findall(
        r"^\|\s*`(discharge|stage)`\s*\|\s*`([^`]+)`\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|$",
        page,
        re.MULTILINE,
    )
    assert len(table_rows) == 20

    freq_map = {"Daily": "daily", "Monthly": "monthly", "Yearly": "yearly", "Unknown": None}
    stat_map = {"Mean": "mean", "Minimum": "min", "Maximum": "max", "Unknown": None}
    unit_map = {"m³/s": "m3/s", "cm": "cm", "m": "m"}
    covered_published_ids: set[str] = set()
    for qty, published_id, freq_label, stat_label, src_unit_label, ret_unit_label in table_rows:
        sub = all_series.filter((all_series["quantity"] == qty) & (all_series["published_id"] == published_id))
        assert sub.height > 0
        covered_published_ids.add(published_id)
        assert set(sub["frequency"].to_list()) == {freq_map[freq_label]}
        assert set(sub["statistic"].to_list()) == {stat_map[stat_label]}
        assert set(sub["source_unit"].to_list()) == {unit_map[src_unit_label]}
        assert set(sub["unit"].to_list()) == {unit_map[ret_unit_label]}
        assert set(sub["variant"].to_list()) == {None}
    assert covered_published_ids == set(all_series["published_id"].unique().to_list())

    assert set(all_series["time_zone"].to_list()) == {None}
    assert set(all_series["temporal_support"].to_list()) == {None}

    stage_series = all_series.filter(all_series["quantity"] == "stage")
    assert set(stage_series["vertical_reference"].to_list()) == {"gauge_zero"}
    assert set(stage_series["vertical_datum"].to_list()) == {None}

    source_meta = rr.metadata(all_co, view="source").filter(
        rr.metadata(all_co, view="source")["state"] != "no_metadata"
    )
    role_fields = {
        role: sorted(source_meta.filter(source_meta["attribute_role"] == role)["source_field"].unique().to_list())
        for role in ("station_name", "water_body_name", "drainage_area", "elevation")
    }
    assert role_fields == {
        "station_name": ["Nombre"],
        "water_body_name": ["Corriente"],
        "drainage_area": [],
        "elevation": ["Altitud"],
    }

    descriptor = rr.describe("co_ideam")
    assert descriptor["license"] == "Creative Commons Attribution | Share Alike 4.0 International"
    assert descriptor["citation"] == "Instituto de Hidrología, Meteorología y Estudios Ambientales - IDEAM, Bogotá D.C."

    assert "providers/co_ideam.md" in (ROOT / "docs/README.md").read_text()
    assert "providers/co_ideam.md" in (ROOT / "mkdocs.yml").read_text()
    station_metadata_doc = (ROOT / "docs/station-metadata.md").read_text()
    assert "[`co_ideam`](providers/co_ideam.md) | `Nombre` | `Corriente` | — | `Altitud` |" in station_metadata_doc
    assert "[IDEAM's terms](providers/co_ideam.md#terms-and-citation)" in station_metadata_doc
    assert (
        "| Colombia | Instituto de Hidrología, Meteorología y Estudios Ambientales (IDEAM) | `co_ideam` | 1,372 | Open |"
        in (ROOT / "README.md").read_text()
    )


@pytest.mark.recorded(_SCOPE)
def test_co_ideam_page_retrieval_example_matches_recorded_responses(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    page = PAGE.read_text()
    matched = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.DOTALL)
    assert len(matched) == 1
    code, expected_output = matched[0]

    class _DocReplayTransport:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls.append(request.url)
            if request.url.endswith("/Q_MEDIA_D/0011017010-Q_MEDIA_D.csv"):
                return _response_from_capture(retained_evidence_root, "access", "s3-0011017010-q-media-d", request)
            raise AssertionError(f"Unexpected documentation request: {request.url}")

    transport = _DocReplayTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)

    namespace: dict[str, object] = {}
    output = io.StringIO()
    with redirect_stdout(output):
        exec(compile(code, "co_ideam.md:retrieval", "exec"), namespace)

    assert output.getvalue() == expected_output
    assert len(transport.calls) == 1
    result = namespace["result"]
    assert result.provenance.license == "Creative Commons Attribution | Share Alike 4.0 International"  # type: ignore[attr-defined]
    assert (
        result.provenance.citation  # type: ignore[attr-defined]
        == "Instituto de Hidrología, Meteorología y Estudios Ambientales - IDEAM, Bogotá D.C."
    )
    with pytest.raises(FatalContractError, match="time_zone is 'unknown'"):
        rr.to_utc(result)  # type: ignore[arg-type]
