"""Estonia (`ee_est`) documentation checks over packaged catalogues and retained publisher captures."""

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
PAGE = ROOT / "docs/providers/ee_est.md"
VISION = ROOT / "planning/visions/2026-11-23-ee-est-user-documentation.md"
_SCOPE = "maintenance/observations/ee_est/retrieval"


def _response_from_capture(root: Path, group: str, name: str, request: TransportRequest) -> TransportResponse:
    base = root / _SCOPE / group / name
    body = base.with_suffix(".body").read_bytes()
    receipt = json.loads(base.with_suffix(".receipt.json").read_text())
    expected_url = str(receipt["url"])
    full_url = request.url
    assert expected_url.startswith(full_url)
    media_type = receipt.get("media_type")
    content_type = str(media_type) if isinstance(media_type, str) and media_type else None
    retrieved_at = datetime.fromisoformat(str(receipt["retrieved_at"]).replace("Z", "+00:00"))
    return TransportResponse(
        content=body,
        status_code=int(str(receipt["http_status"])),
        retrieved_at=retrieved_at,
        content_type=content_type,
        url=expected_url,
        request_parameters=dict(request.params or {}),
    )


def test_ee_est_page_selection_discovery_and_catalogue_claims_are_offline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        pytest.fail("Estonia offline discovery attempted network access")

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
    namespace: dict[str, object] = {}
    exec(
        compile(ast.Module(body=tree.body[:fetch_index], type_ignores=[]), "ee_est.md:selection", "exec"),
        namespace,
    )
    exec(compile(blocks[1], "ee_est.md:discovery", "exec"), namespace)

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
    ).rows() == [
        ("SJA8821000", "discharge_daily_mean", "SJA8821000:Q:MEAN", "discharge", "daily", "mean", "m3/s", "m3/s", None)
    ]

    candidates = namespace["candidates"]
    assert sorted(candidates["published_id"].to_list()) == sorted(  # type: ignore[index]
        [
            "SJA8821000:Q:MEAN",
            "SJA8821000:Q:MAXIMUM",
            "SJA8821000:Q:MINIMUM",
            "41061:Äravool avg",
            "41061:Äravool max",
            "41061:Äravool min",
        ]
    )

    hourly_series = rr.series(namespace["hourly_mean"])  # type: ignore[arg-type]
    assert hourly_series.select(
        "station_id", "product_id", "published_id", "frequency", "statistic", "time_zone"
    ).rows() == [("SJA8821000", "discharge_hourly_mean", "41061:Äravool avg", "hourly", "mean", "+00:00")]

    metadata = namespace["metadata"].row(0, named=True)  # type: ignore[attr-defined]
    assert metadata["station_name"] == "Ahja HJ"
    assert metadata["crs"] == "EPSG:4326"
    assert metadata["water_body_name_field"] == ["veekogu_nimi"]
    assert metadata["water_body_name_value"] == ["Ahja jõgi"]
    assert metadata["drainage_area_field"] == ["area"]
    assert metadata["drainage_area_value"] == ["896.51"]
    assert metadata["drainage_area_unit"] == ["km2"]
    assert metadata["elevation_field"] is None

    all_ee = rr.find(provider="ee_est")
    assert len(all_ee.locations) == 60
    all_series = rr.series(all_ee)
    assert all_series.height == 1032
    assert all_series["station_id"].n_unique() == 60
    assert all_series["product_id"].n_unique() == 18

    expected_header = (
        "| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |"
    )
    assert page.count(expected_header) == 1

    table_rows = re.findall(
        r"^\|\s*`(discharge|stage|temperature)`\s*\|\s*`([^`]+)`\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|$",
        page,
        re.MULTILINE,
    )
    assert len(table_rows) == 18

    freq_map = {"Daily": "daily", "Hourly": "hourly"}
    stat_map = {"Mean": "mean", "Minimum": "min", "Maximum": "max"}
    unit_map = {"m³/s": "m3/s", "cm": "cm", "m": "m", "°C": "degC"}
    covered_native_suffixes: set[str] = set()
    for qty, native_code, freq_label, stat_label, src_unit_label, ret_unit_label in table_rows:
        sub = all_series.filter(
            (all_series["quantity"] == qty) & (all_series["published_id"].str.ends_with(f":{native_code}"))
        )
        assert sub.height in (55, 56, 59)
        covered_native_suffixes.add(native_code)
        assert set(sub["frequency"].to_list()) == {freq_map[freq_label]}
        assert set(sub["statistic"].to_list()) == {stat_map[stat_label]}
        assert set(sub["source_unit"].to_list()) == {unit_map[src_unit_label]}
        assert set(sub["unit"].to_list()) == {unit_map[ret_unit_label]}
        assert set(sub["variant"].to_list()) == {None}
    assert len(covered_native_suffixes) == 18

    daily_series = all_series.filter(all_series["frequency"] == "daily")
    hourly_all = all_series.filter(all_series["frequency"] == "hourly")
    assert set(daily_series["time_zone"].to_list()) == {None}
    assert set(hourly_all["time_zone"].to_list()) == {"+00:00"}
    assert set(all_series["temporal_support"].to_list()) == {"interval"}

    stage_series = all_series.filter(all_series["quantity"] == "stage")
    assert set(stage_series["vertical_reference"].to_list()) == {"gauge_zero"}
    assert set(stage_series["vertical_datum"].to_list()) == {None}

    source_meta = rr.metadata(all_ee, view="source").filter(
        rr.metadata(all_ee, view="source")["state"] != "no_metadata"
    )
    role_fields = {
        role: sorted(source_meta.filter(source_meta["attribute_role"] == role)["source_field"].unique().to_list())
        for role in ("station_name", "water_body_name", "drainage_area", "elevation")
    }
    assert role_fields == {
        "station_name": ["nimi"],
        "water_body_name": ["veekogu_nimi"],
        "drainage_area": ["area"],
        "elevation": [],
    }

    descriptor = rr.describe("ee_est")
    assert descriptor["license"] == "CC BY 4.0"
    assert descriptor["citation"] == "Estonian Environment Agency (Keskkonnaagentuur)"

    assert "providers/ee_est.md" in (ROOT / "docs/README.md").read_text()
    assert "providers/ee_est.md" in (ROOT / "mkdocs.yml").read_text()
    station_metadata_doc = (ROOT / "docs/station-metadata.md").read_text()
    assert "[`ee_est`](providers/ee_est.md) | `nimi` | `veekogu_nimi` | `area` (km2) | — |" in station_metadata_doc
    assert "[Keskkonnaagentuur's terms](providers/ee_est.md#terms-and-citation)" in station_metadata_doc
    assert (
        "| Estonia | Estonian Environment Agency (Keskkonnaagentuur) | `ee_est` | 60 | Open |"
        in (ROOT / "README.md").read_text()
    )


@pytest.mark.recorded(_SCOPE)
def test_ee_est_page_retrieval_and_annotation_examples_match_recorded_responses(
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
            if request.url == "https://estmodel.envir.ee/stations/SJA8821000/measurements":
                return _response_from_capture(retained_evidence_root, "web", "em-sja8821000-q-mean-2026", request)
            raise AssertionError(f"Unexpected documentation request: {request.url}")

    transport = _DocReplayTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)

    namespace: dict[str, object] = {}
    output = io.StringIO()
    with redirect_stdout(output):
        exec(compile(code_intro, "ee_est.md:retrieval", "exec"), namespace)
    assert output.getvalue() == expected_intro

    output_ann = io.StringIO()
    with redirect_stdout(output_ann):
        exec(compile(code_ann, "ee_est.md:annotations", "exec"), namespace)
    assert output_ann.getvalue().splitlines()[-1] + "\n" == expected_ann
    assert "[('ee_est.estmodel', 'qualityFlag', 'String')]" in output_ann.getvalue()

    assert len(transport.calls) == 2
    result = namespace["result"]
    assert result.provenance.license == "CC BY 4.0"  # type: ignore[attr-defined]
    assert result.provenance.citation == "Estonian Environment Agency (Keskkonnaagentuur)"  # type: ignore[attr-defined]
    with pytest.raises(FatalContractError, match="time_zone is 'unknown'"):
        rr.to_utc(result)  # type: ignore[arg-type]
