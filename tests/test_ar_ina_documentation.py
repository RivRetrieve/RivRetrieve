"""Argentina INA Alerta5 documentation checks over packaged catalogues and retained publisher captures."""

from __future__ import annotations

import ast
import io
import json
import re
import socket
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.providers.ar_ina.series import IN_SCOPE_SERIES_SPECS
from rivretrieve._internal.transport import TransportRequest, TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/providers/ar_ina.md"
_SCOPE = "maintenance/observations/ar_ina/retrieval"


def _response_from_capture(root: Path, group: str, name: str, *, actual_params: dict[str, str]) -> TransportResponse:
    base = root / _SCOPE / group / name
    body = base.with_suffix(".body").read_bytes()
    receipt = json.loads(base.with_suffix(".receipt.json").read_text())
    parsed = urlsplit(str(receipt["url"]))
    headers = receipt.get("response_headers")
    content_type = headers.get("content-type") if isinstance(headers, dict) else None
    status_code = int(str(receipt.get("status", receipt.get("http_status", 200))))
    acquired = datetime.fromisoformat(str(receipt["acquired_at"]).replace("Z", "+00:00"))
    return TransportResponse(
        content=body,
        status_code=status_code,
        retrieved_at=acquired,
        content_type=str(content_type) if content_type is not None else None,
        url=f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
        request_parameters=actual_params,
    )


def test_ar_ina_page_selection_discovery_and_catalogue_claims_are_offline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        pytest.fail("Argentina INA offline discovery attempted network access")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.chdir(tmp_path)

    page = PAGE.read_text(encoding="utf-8")
    assert "\u2014" not in page
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
        compile(ast.Module(body=tree.body[:fetch_index], type_ignores=[]), "ar_ina.md:selection", "exec"),
        namespace,
    )
    exec(compile(blocks[1], "ar_ina.md:discovery", "exec"), namespace)

    selected_series = rr.series(namespace["selection"])  # type: ignore[arg-type]
    assert selected_series.select(
        "station_id",
        "product_id",
        "variant",
        "quantity",
        "frequency",
        "statistic",
        "source_unit",
        "unit",
        "time_zone",
    ).rows() == [("8", "discharge_daily_mean", "26605", "discharge", "daily", "mean", "m^3/s", "m3/s", "UTC")]

    station_52 = namespace["station_52"]
    candidates = namespace["candidates"]
    assert sorted(candidates["product_id"].to_list()) == [  # type: ignore[index]
        "stage_daily_mean",
        "stage_hourly",
        "stage_instantaneous",
        "stage_monthly_max",
        "stage_monthly_mean",
        "stage_monthly_min",
    ]
    hourly_stage = rr.series(namespace["hourly_stage"])  # type: ignore[arg-type]
    hourly_by_freq = rr.series(rr.pick(station_52, frequency="hourly"))  # type: ignore[arg-type]
    assert hourly_stage.select("product_id", "variant", "frequency", "statistic").rows() == [
        ("stage_hourly", "31605", "hourly", None)
    ]
    assert hourly_by_freq["series_id"].to_list() == hourly_stage["series_id"].to_list()

    meta_8 = rr.metadata(namespace["selection"]).row(0, named=True)  # type: ignore[arg-type]
    assert meta_8["station_name"] == "Andresito"
    assert meta_8["water_body_name_value"] == ["IGUAZU"]
    assert meta_8["drainage_area_field"] is None
    assert meta_8["elevation_field"] is None

    # Verify packaged catalogue station counts, standard 6-column table, time zones, and stage references.
    all_ar = rr.find(provider="ar_ina")
    assert len(all_ar.locations) == 829
    with_coords = [loc for loc in all_ar.locations if loc.latitude is not None and loc.longitude is not None]
    without_coords = [loc for loc in all_ar.locations if loc.latitude is None and loc.longitude is None]
    assert len(with_coords) == 828
    assert all(loc.crs == "EPSG:4326" for loc in with_coords)
    assert [loc.station_id for loc in without_coords] == ["96"]

    all_series = rr.series(all_ar)
    assert all_series.height == 2_611
    assert all_series["station_id"].n_unique() == 829

    expected_header = (
        "| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |"
    )
    assert page.count(expected_header) == 1
    for internal_token in (
        "product_id",
        "result.outcomes",
        "discharge_daily_mean",
        "stage_4hourly",
        "stage_weekly_mean",
        "WindowDeclaration",
        "stop_extension",
        "verification-evidence",
    ):
        assert internal_token not in page

    table_rows = re.findall(
        r"^\|\s*`(discharge|stage)`\s*\|\s*`([^`]+)`[^|\n]*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|$",
        page,
        re.MULTILINE,
    )
    assert len(table_rows) == 13

    product_by_var_code = {spec.var_code: spec.product_id for spec in IN_SCOPE_SERIES_SPECS}
    freq_map = {"Daily": "daily", "Hourly": "hourly", "Monthly": "monthly", "Unknown": None}
    stat_map = {
        "Mean": "mean",
        "Instantaneous": "instantaneous",
        "Minimum": "min",
        "Maximum": "max",
        "Unknown": None,
    }
    unit_map = {"m³/s": "m3/s", "m": "m"}
    covered_product_ids: set[str] = set()
    for qty, var_code, freq_label, stat_label, src_unit_label, ret_unit_label in table_rows:
        pid = product_by_var_code[var_code]
        sub = all_series.filter(all_series["product_id"] == pid)
        assert sub.height > 0
        covered_product_ids.add(pid)
        assert set(sub["quantity"].to_list()) == {qty}
        assert set(sub["frequency"].to_list()) == {freq_map[freq_label]}
        assert set(sub["statistic"].to_list()) == {stat_map[stat_label]}
        assert set(sub["source_unit"].to_list()) == {src_unit_label}
        assert set(sub["unit"].to_list()) == {unit_map[ret_unit_label]}
    assert covered_product_ids == set(all_series["product_id"].unique().to_list())

    expected_counts = {
        "discharge_daily_mean": 82,
        "discharge_instantaneous": 32,
        "discharge_monthly_mean": 36,
        "discharge_monthly_min": 28,
        "discharge_monthly_max": 28,
        "stage_daily_mean": 756,
        "stage_instantaneous": 808,
        "stage_hourly": 3,
        "stage_4hourly": 391,
        "stage_weekly_mean": 32,
        "stage_monthly_mean": 249,
        "stage_monthly_min": 83,
        "stage_monthly_max": 83,
    }
    actual_counts = dict(all_series.group_by("product_id").len().iter_rows())
    assert actual_counts == expected_counts

    assert set(all_series["time_zone"].to_list()) == {"UTC"}
    assert set(all_series["day_definition"].to_list()) == {None}
    stage_series = all_series.filter(all_series["quantity"] == "stage")
    assert set(stage_series["vertical_reference"].to_list()) == {"gauge_zero"}
    assert set(stage_series["vertical_datum"].to_list()) == {None}

    all_meta = rr.metadata(all_ar)
    assert all_meta.height == 829
    assert all_meta["station_name"].null_count() == 0
    assert all_meta.filter(pl.col("water_body_name_value").list.get(0).is_not_null()).height == 353
    assert all_meta.filter(pl.col("water_body_name_value").list.get(0).is_null()).height == 476
    assert all_meta["drainage_area_field"].null_count() == 829
    assert all_meta["elevation_field"].null_count() == 829

    source_meta = rr.metadata(all_ar, view="source")
    for role in ("drainage_area", "elevation"):
        role_rows = source_meta.filter(pl.col("attribute_role") == role)
        assert set(role_rows["state"].to_list()) == {"no_metadata"}

    descriptor = rr.describe("ar_ina")
    assert descriptor["license"] == "Creative Commons Atribución 4.0 Internacional"
    assert "citation" not in descriptor

    assert "providers/ar_ina.md" in (ROOT / "docs/README.md").read_text(encoding="utf-8")
    assert "providers/ar_ina.md" in (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    assert "[`ar_ina`](providers/ar_ina.md)" in (ROOT / "docs/station-metadata.md").read_text(encoding="utf-8")
    assert "https://rivretrieve.github.io/providers/ar_ina/" in (ROOT / "README.md").read_text(encoding="utf-8")


@pytest.mark.recorded(_SCOPE)
def test_ar_ina_page_retrieval_example_matches_recorded_responses(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    page = PAGE.read_text(encoding="utf-8")
    matched = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.DOTALL)
    assert len(matched) == 1
    code, expected_output = matched[0]

    class _DocReplayTransport:
        calls: list[tuple[str, dict[str, str]]] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            params = {str(k): str(v) for k, v in (request.params or {}).items()}
            self.calls.append((request.url, params))
            if request.url == "https://alerta.ina.gob.ar/a5/obs/puntual/series/26605/observaciones" and params == {
                "timestart": "2023-12-30T00:00:00Z",
                "timeend": "2024-01-08T00:59:59.999999Z",
                "skip_nulls": "true",
            }:
                return _response_from_capture(
                    retained_evidence_root,
                    "retrieval",
                    "a5-obs-26605-var40-planned-20240101-20240105",
                    actual_params=params,
                )
            raise AssertionError(f"Unexpected documentation request: {request.url} {params}")

    transport = _DocReplayTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)

    namespace: dict[str, object] = {}
    output = io.StringIO()
    with redirect_stdout(output):
        exec(compile(code, "ar_ina.md:retrieval", "exec"), namespace)

    assert output.getvalue() == expected_output
    assert len(transport.calls) == 1
    result = namespace["result"]
    assert result.provenance.license == "Creative Commons Atribución 4.0 Internacional"  # type: ignore[attr-defined]
    assert result.provenance.citation is None  # type: ignore[attr-defined]
    assert set(result.data["time_zone"].to_list()) == {"+00:00"}  # type: ignore[attr-defined]
    utc_result = rr.to_utc(result)  # type: ignore[arg-type]
    assert set(utc_result.data["time_zone"].to_list()) == {"+00:00"}
    assert utc_result.data["time"].to_list() == result.data["time"].to_list()  # type: ignore[attr-defined]
