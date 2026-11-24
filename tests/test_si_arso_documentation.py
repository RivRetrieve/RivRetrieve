"""Slovenia ARSO documentation checks over packaged catalogues and retained captures."""

from __future__ import annotations

import ast
import io
import json
import re
import socket
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.transport import TransportRequest, TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/providers/si_arso.md"
_SCOPE = "maintenance/observations/si_arso/retrieval"


def _response_from_capture(root: Path, group: str, name: str) -> TransportResponse:
    base = root / _SCOPE / group / name
    body = base.with_suffix(".body").read_bytes()
    receipt = json.loads(base.with_suffix(".receipt.json").read_text())
    url = str(receipt["url"])
    parsed = urlsplit(url)
    params = {key: vals[0] for key, vals in parse_qs(parsed.query, keep_blank_values=True).items()}
    headers = receipt.get("response_headers")
    content_type = headers.get("content-type") if isinstance(headers, dict) else None
    retrieved = datetime.fromisoformat(str(receipt["retrieved_at"]).replace("Z", "+00:00"))
    return TransportResponse(
        content=body,
        status_code=int(str(receipt["http_status"])),
        retrieved_at=retrieved,
        content_type=str(content_type) if content_type is not None else None,
        url=f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
        request_parameters=params,
    )


def test_si_arso_page_selection_discovery_and_catalogue_claims_are_offline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        pytest.fail("Slovenia ARSO offline discovery attempted network access")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.chdir(tmp_path)

    page = PAGE.read_text()
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
        compile(ast.Module(body=tree.body[:fetch_index], type_ignores=[]), "si_arso.md:selection", "exec"),
        namespace,
    )
    exec(compile(blocks[1], "si_arso.md:discovery", "exec"), namespace)

    selected_series = rr.series(namespace["selection"])  # type: ignore[arg-type]
    assert selected_series.select(
        "station_id", "product_id", "quantity", "frequency", "statistic", "source_unit", "unit", "time_zone"
    ).rows() == [("1060", "archive_discharge_daily", "discharge", "P1D", None, "m3/s", "m3/s", None)]

    candidates = namespace["candidates"]
    assert len(candidates) == 18  # type: ignore[arg-type]
    assert rr.series(namespace["op_10min"])["product_id"].to_list() == ["operational_discharge_10min"]  # type: ignore[arg-type]
    assert rr.series(namespace["op_30min"])["product_id"].to_list() == ["operational_discharge_30min"]  # type: ignore[arg-type]
    assert rr.series(namespace["op_hourly"])["product_id"].to_list() == ["operational_discharge_hourly"]  # type: ignore[arg-type]

    metadata = namespace["metadata"].row(0, named=True)  # type: ignore[attr-defined]
    assert metadata["station_name"] == "Gornja Radgona I"
    assert metadata["water_body_name_value"] == ["Mura"]
    assert metadata["drainage_area_value"] == ["10197.2"]
    assert metadata["drainage_area_unit"] == ["km2"]
    assert metadata["elevation_field"] is None

    # Verify packaged catalogue station counts, CRS/sentinel counts, tables, time zones, and stage references.
    all_si = rr.find(provider="si_arso")
    assert len(all_si.locations) == 619
    assert sum(1 for loc in all_si.locations if loc.crs == "EPSG:4326") == 612
    unknown_crs = sorted(loc.station_id for loc in all_si.locations if loc.crs == "unknown")
    assert unknown_crs == ["5049", "6310", "6570", "7290", "7450", "9090", "9290"]
    for sid in unknown_crs:
        assert f"`{sid}`" in page

    all_series = rr.series(all_si)
    assert all_series.height == 5628
    assert all_series["station_id"].n_unique() == 615
    unselectable = {loc.station_id for loc in all_si.locations} - set(all_series["station_id"].to_list())
    assert unselectable == {"5400", "5410", "5420", "9060"}

    all_meta = rr.metadata(all_si)
    assert all_meta.filter(pl.col("drainage_area_value").list.first() == "88888.88").height == 36
    assert all_meta.filter(pl.col("drainage_area_value").list.first() == "99999.99").height == 7

    expected_header = (
        "| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |"
    )
    assert page.count(expected_header) == 2
    for internal_token in ("product_id", "result.outcomes"):
        assert internal_token not in page

    table_rows = re.findall(
        r"^\|\s*`(discharge|stage|temperature)`\s*\|\s*`([^`]+)`(?:\s*\(`([^`]+)`\))?\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|$",
        page,
        re.MULTILINE,
    )
    assert len(table_rows) == 18

    freq_map = {
        "`P1D`": {"P1D"},
        "`P1M`": {"P1M"},
        "`PT10M` (`PT5M` at 8 gauges, `PT30M` at 2 gauges)": {"PT5M", "PT10M", "PT30M"},
        "`PT30M`": {"PT30M"},
        "`PT1H`": {"PT1H"},
    }
    stat_map = {"Minimum": "min", "Maximum": "max", "Unknown": None}
    unit_map = {"m3/s": "m3/s", "m³/s": "m3/s", "cm": "cm", "m": "m", "°C": "degC"}
    covered_product_ids: set[str] = set()
    for qty, col_a, col_b, freq_label, stat_label, src_unit_label, ret_unit_label in table_rows:
        if col_b:
            sub = all_series.filter(
                (pl.col("quantity") == qty) & (pl.col("variant") == col_a) & (pl.col("published_id") == col_b)
            )
        else:
            sub = all_series.filter(
                (pl.col("quantity") == qty) & pl.col("variant").is_null() & (pl.col("published_id") == col_a)
            )
        assert sub.height > 0, (qty, col_a, col_b)
        covered_product_ids.update(sub["product_id"].unique().to_list())
        assert set(sub["frequency"].to_list()) == freq_map[freq_label]
        assert set(sub["statistic"].to_list()) == {stat_map[stat_label]}
        assert set(sub["source_unit"].to_list()) == {src_unit_label}
        assert set(sub["unit"].to_list()) == {unit_map[ret_unit_label]}
    assert covered_product_ids == set(all_series["product_id"].unique().to_list())

    op_series = all_series.filter(pl.col("product_id").str.starts_with("operational_"))
    arch_series = all_series.filter(pl.col("product_id").str.starts_with("archive_"))
    assert set(op_series["time_zone"].to_list()) == {"UTC+01:00"}
    assert set(arch_series["time_zone"].to_list()) == {None}

    stage_series = all_series.filter(pl.col("quantity") == "stage")
    assert set(stage_series["vertical_reference"].to_list()) == {"gauge_zero"}
    assert set(stage_series["vertical_datum"].to_list()) == {None}

    descriptor = rr.describe("si_arso")
    assert "CC BY 4.0" in str(descriptor["license"])
    assert "Agencije Republike Slovenije za okolje" in str(descriptor["citation"])

    assert "providers/si_arso.md" in (ROOT / "docs/README.md").read_text()
    assert "providers/si_arso.md" in (ROOT / "mkdocs.yml").read_text()
    assert "[`si_arso`](providers/si_arso.md)" in (ROOT / "docs/station-metadata.md").read_text()
    assert (
        "| Slovenia | Agencija Republike Slovenije za okolje (ARSO) | `si_arso` | 615 | Open |"
        in (ROOT / "README.md").read_text()
    )


@pytest.mark.recorded(_SCOPE)
def test_si_arso_page_retrieval_example_matches_recorded_responses(
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
            if request.params.get("p_postaja") == "1060" and request.params.get("b_oddo_CSV") is not None:
                return _response_from_capture(retained_evidence_root, "access", "archive-1060-2024-oddo")
            raise AssertionError(f"Unexpected documentation request: {request.url} {request.params}")

    transport = _DocReplayTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)

    namespace: dict[str, object] = {}
    output = io.StringIO()
    with redirect_stdout(output):
        exec(compile(code, "si_arso.md:retrieval", "exec"), namespace)

    assert output.getvalue() == expected_output
    assert len(transport.calls) == 1
    result = namespace["result"]
    assert "CC BY 4.0" in str(result.provenance.license)  # type: ignore[attr-defined]
    assert "Agencije Republike Slovenije za okolje" in str(result.provenance.citation)  # type: ignore[attr-defined]
    with pytest.raises(FatalContractError, match="time_zone is 'unknown'"):
        rr.to_utc(result)  # type: ignore[arg-type]
