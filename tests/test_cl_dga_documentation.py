"""Chile DGA documentation checks over packaged catalogues and retained publisher archives."""

from __future__ import annotations

import ast
import hashlib
import io
import json
import re
import shutil
import socket
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.cl_dga.bulk import (
    CL_DGA_COMPILER_VERSION,
    CL_DGA_DAILY_FILENAME,
    CL_DGA_DAILY_URL,
    CL_DGA_MONTHLY_FILENAME,
    CL_DGA_MONTHLY_URL,
    ClDgaCompileRequest,
    compile_cl_dga,
)
from rivretrieve._internal.providers.registration import DownloadedBulkArtifact
from rivretrieve._internal.store import StorePresence, StoreRoot
from rivretrieve._internal.transport import TransportRequest

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/providers/cl_dga.md"
_SCOPE = "maintenance/observations/cl_dga/retrieval"
_DAILY_WEB_STEM = "mapas2-caudal-diario-nacional-zip"
_MONTHLY_WEB_STEM = "mapas2-caudal-medio-mensual-nacional-zip"


def _verify_capture(web_root: Path, stem: str, expected_url: str) -> Path:
    body_path = web_root / f"{stem}.zip"
    receipt = json.loads((web_root / f"{stem}.receipt.json").read_text(encoding="utf-8"))
    raw = body_path.read_bytes()
    assert len(raw) == receipt["byte_size"]
    assert hashlib.sha256(raw).hexdigest() == receipt["sha256"]
    assert receipt["url"] == expected_url
    assert receipt["http_status"] == 200
    return body_path


def test_cl_dga_page_catalogue_links_and_offline_selection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        pytest.fail("Chile DGA offline discovery attempted network access")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.chdir(tmp_path)

    page = PAGE.read_text(encoding="utf-8")
    assert "\u2014" not in page
    for internal_token in (
        'product="',
        "product_id",
        "discharge_daily",
        "discharge_monthly_mean",
        "result.outcomes",
    ):
        assert internal_token not in page

    blocks = re.findall(r"```python\n(.*?)```", page, re.DOTALL)
    assert len(blocks) == 3
    for block in blocks:
        compile(block, str(PAGE), "exec")
    assert 'rr.download("cl_dga")' in blocks[0]

    expected_header = (
        "| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |"
    )
    assert expected_header in page

    table_rows = re.findall(
        r"^\|\s*`(discharge)`\s*\|\s*`([^`]+)`[^|\n]*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|$",
        page,
        re.MULTILINE,
    )
    assert len(table_rows) == 2

    all_cl = rr.find(provider="cl_dga")
    assert len(all_cl.locations) == 784
    all_series = rr.series(all_cl)

    freq_map = {"Daily": "daily", "Monthly": "monthly"}
    stat_map = {"Mean": "mean", "Unknown": None}
    unit_map = {"m³/s": "m3/s"}
    covered_published_ids: set[str] = set()
    for qty, published_id, freq_label, stat_label, src_unit_label, ret_unit_label in table_rows:
        sub = all_series.filter((all_series["quantity"] == qty) & (all_series["published_id"] == published_id))
        assert sub.height == 784
        covered_published_ids.add(published_id)
        assert set(sub["frequency"].to_list()) == {freq_map[freq_label]}
        assert set(sub["statistic"].to_list()) == {stat_map[stat_label]}
        assert set(sub["source_unit"].to_list()) == {unit_map[src_unit_label]}
        assert set(sub["unit"].to_list()) == {unit_map[ret_unit_label]}
        assert set(sub["variant"].to_list()) == {None}
    assert covered_published_ids == set(all_series["published_id"].unique().to_list())
    assert set(all_series["time_zone"].to_list()) == {None}
    assert set(all_series["temporal_support"].to_list()) == {None}

    tree = ast.parse(blocks[1])
    fetch_index = next(
        index
        for index, statement in enumerate(tree.body)
        if isinstance(statement, ast.Assign)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == "fetch"
    )
    namespace: dict[str, object] = {"rr": rr}
    exec(
        compile(ast.Module(body=tree.body[:fetch_index], type_ignores=[]), "cl_dga.md:selection", "exec"),
        namespace,
    )
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
    ).rows() == [("01050002", "discharge_daily", "Caudal_diario", "discharge", "daily", None, "m3/s", "m3/s", None)]

    mean_selection = rr.find(provider="cl_dga", station="01050002", statistic="mean")
    assert rr.series(mean_selection).select("product_id", "published_id", "frequency", "statistic").rows() == [
        ("discharge_monthly_mean", "Caudal_Medio_mensual", "monthly", "mean")
    ]

    source_meta = rr.metadata(all_cl, view="source").filter(
        rr.metadata(all_cl, view="source")["state"] != "no_metadata"
    )
    role_fields = {
        role: sorted(source_meta.filter(source_meta["attribute_role"] == role)["source_field"].unique().to_list())
        for role in ("station_name", "water_body_name", "drainage_area", "elevation")
    }
    assert role_fields == {
        "station_name": ["NOMBRE ESTACION"],
        "water_body_name": [],
        "drainage_area": [],
        "elevation": ["ALTITUD"],
    }
    zero_elev = source_meta.filter(
        (source_meta["station_id"] == "01001002") & (source_meta["attribute_role"] == "elevation")
    ).row(0, named=True)
    assert zero_elev["state"] == "source_null"
    assert zero_elev["source_datum"] is None
    elev_rows = source_meta.filter(source_meta["attribute_role"] == "elevation")
    assert elev_rows.filter(elev_rows["state"] == "value").height == 700
    assert elev_rows.filter(elev_rows["state"] == "source_null").height == 84

    descriptor = rr.describe("cl_dga")
    assert descriptor["name"] == "rivretrieve-cl_dga-catalogue"
    assert descriptor["creator"] == [
        {"@type": "sc:Organization", "name": "Dirección General de Aguas (DGA), Ministerio de Obras Públicas (MOP)"}
    ]
    assert "license" not in descriptor
    assert "citation" not in descriptor
    metadata_record_set = next(item for item in descriptor["recordSet"] if item["@id"] == "station_metadata")  # type: ignore[index]
    assert "mapas2.mop.gob.cl" in metadata_record_set["description"]
    assert "condiciones-de-uso" in metadata_record_set["description"]
    assert "MIT" in metadata_record_set["description"]

    assert "providers/cl_dga.md" in (ROOT / "docs/README.md").read_text(encoding="utf-8")
    assert "providers/cl_dga.md" in (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    station_metadata_doc = (ROOT / "docs/station-metadata.md").read_text(encoding="utf-8")
    assert "| [`cl_dga`](providers/cl_dga.md) | `NOMBRE ESTACION` | — | — | `ALTITUD` (m) |" in station_metadata_doc
    assert "(providers/cl_dga.md#terms-and-citation)" in station_metadata_doc
    assert (
        "| Chile | Dirección General de Aguas (DGA), Ministerio de Obras Públicas (MOP) | `cl_dga` | 784 | Bulk download |"
        in (ROOT / "README.md").read_text(encoding="utf-8")
    )
    assert "`cl_dga`" in (ROOT / "docs/usage.md").read_text(encoding="utf-8")


@pytest.mark.recorded(_SCOPE)
def test_cl_dga_page_examples_replay_retained_archives(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    page = PAGE.read_text(encoding="utf-8")
    matched = re.findall(
        r"```python\n(.*?)```\n\nOutput(?: for the verified copy)?:\n\n```text\n(.*?)```",
        page,
        re.DOTALL,
    )
    assert len(matched) == 2

    web_root = retained_evidence_root / _SCOPE / "web"
    daily_src = _verify_capture(web_root, _DAILY_WEB_STEM, CL_DGA_DAILY_URL)
    monthly_src = _verify_capture(web_root, _MONTHLY_WEB_STEM, CL_DGA_MONTHLY_URL)

    inputs_dir = tmp_path / "inputs"
    inputs_dir.mkdir()
    daily_copy = inputs_dir / CL_DGA_DAILY_FILENAME
    monthly_copy = inputs_dir / CL_DGA_MONTHLY_FILENAME
    shutil.copyfile(daily_src, daily_copy)
    shutil.copyfile(monthly_src, monthly_copy)

    cache_root = tmp_path / "cache"
    compile_cl_dga(
        ClDgaCompileRequest(
            publisher_artifacts=(
                DownloadedBulkArtifact(daily_copy, CL_DGA_DAILY_URL, None),
                DownloadedBulkArtifact(monthly_copy, CL_DGA_MONTHLY_URL, None),
            ),
            destination=StoreRoot(cache_root / "cl_dga" / "store"),
            built_at=datetime(2026, 11, 20, 15, 45, tzinfo=UTC),
            compiler_version=CL_DGA_COMPILER_VERSION,
        )
    )

    class _ForbidNetwork:
        def send(self, request: TransportRequest) -> object:
            raise AssertionError(f"Offline bulk documentation check attempted network access: {request.url}")

    monkeypatch.setattr(discovery, "HttpClient", _ForbidNetwork)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(cache_root))
    monkeypatch.chdir(tmp_path)

    namespace: dict[str, object] = {"rr": rr}
    for index, (code, expected_output) in enumerate(matched):
        output = io.StringIO()
        with redirect_stdout(output):
            exec(compile(code, f"cl_dga.md:example-{index}", "exec"), namespace)
        assert output.getvalue() == expected_output

    status = namespace["status"]
    assert status.presence is StorePresence.PRESENT  # type: ignore[attr-defined]
    assert status.source_vintage is None  # type: ignore[attr-defined]

    result = namespace["result"]
    assert result.data["time_zone"].unique().to_list() == ["unknown"]  # type: ignore[attr-defined]
    assert rr.annotations(result).is_empty()  # type: ignore[arg-type]
    assert result.provenance.license is None  # type: ignore[attr-defined]
    assert result.provenance.citation is None  # type: ignore[attr-defined]
    with pytest.raises(FatalContractError, match="time_zone is 'unknown'"):
        rr.to_utc(result)  # type: ignore[arg-type]

    monthly_sel = rr.find(provider="cl_dga", station="01050002", statistic="mean")
    feb_mid = rr.fetch(monthly_sel, start="2024-02-10", end="2024-02-20", on_issue="raise")
    assert feb_mid.data.select("time", "time_zone", "value", "unit").rows() == [
        (datetime(2024, 2, 1), "unknown", 0.369, "m3/s")
    ]
    year_span = rr.fetch(monthly_sel, start="2023-12-15", end="2024-01-10", on_issue="raise")
    assert year_span.data.select("time", "time_zone", "value", "unit").rows() == [
        (datetime(2023, 12, 1), "unknown", 0.234, "m3/s"),
        (datetime(2024, 1, 1), "unknown", 0.297, "m3/s"),
    ]
