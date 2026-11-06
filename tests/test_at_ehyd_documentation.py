"""Austria eHYD documentation checks over packaged catalogues and retained publisher captures."""

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

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.transport import TransportRequest, TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/providers/at_ehyd.md"
_SCOPE = "maintenance/observations/at_ehyd/retrieval"


def _response_from_capture(root: Path, group: str, name: str) -> TransportResponse:
    base = root / _SCOPE / group / name
    body = base.with_suffix(".body").read_bytes()
    receipt = json.loads(base.with_suffix(".receipt.json").read_text())
    url = str(receipt["url"])
    parsed = urlsplit(url)
    params = {key: vals[0] for key, vals in parse_qs(parsed.query, keep_blank_values=True).items()}
    headers = receipt.get("response_headers")
    content_type = headers.get("content-type") if isinstance(headers, dict) else None
    acquired = datetime.fromisoformat(str(receipt["acquired_at"]).replace("Z", "+00:00"))
    return TransportResponse(
        content=body,
        status_code=int(str(receipt["http_status"])),
        retrieved_at=acquired,
        content_type=str(content_type) if content_type is not None else None,
        url=f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
        request_parameters=params,
    )


def test_at_ehyd_page_selection_discovery_and_catalogue_claims_are_offline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        pytest.fail("Austria eHYD offline discovery attempted network access")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.chdir(tmp_path)

    page = PAGE.read_text()
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
        compile(ast.Module(body=tree.body[:fetch_index], type_ignores=[]), "at_ehyd.md:selection", "exec"),
        namespace,
    )
    exec(compile(blocks[1], "at_ehyd.md:discovery", "exec"), namespace)

    selected_series = rr.series(namespace["selection"])  # type: ignore[arg-type]
    assert selected_series.select(
        "station_id", "product_id", "quantity", "frequency", "statistic", "source_unit", "unit", "time_zone"
    ).rows() == [("209486", "owf_abfl_tagesmittel", "discharge", "daily", "mean", "m³/s", "m3/s", None)]

    candidates = namespace["candidates"]
    assert sorted(candidates["product_id"].to_list()) == [  # type: ignore[index]
        "owf_abfl_monatsmaxima",
        "owf_abfl_monatsminima",
        "owf_abfl_tagesmittel",
        "pegel_bgis_abfluss",
        "pegel_longterm_abfluss",
    ]
    all_discharge = namespace["all_discharge"]
    subhourly_by_variant = rr.series(rr.pick(all_discharge, variant="data"))  # type: ignore[arg-type]
    subhourly_by_tz = rr.series(rr.pick(all_discharge, time_zone="UTC+01:00"))  # type: ignore[arg-type]
    current_year_by_variant = rr.series(rr.pick(all_discharge, variant="current_value"))  # type: ignore[arg-type]
    assert subhourly_by_variant["product_id"].to_list() == ["pegel_bgis_abfluss"]
    assert subhourly_by_tz["series_id"].to_list() == subhourly_by_variant["series_id"].to_list()
    assert current_year_by_variant["product_id"].to_list() == ["pegel_longterm_abfluss"]

    metadata = namespace["metadata"].row(0, named=True)  # type: ignore[attr-defined]
    assert metadata["station_name"] == "Böheimkirchen"
    assert metadata["water_body_name_value"] == ["Perschling", "Perschling"]
    assert metadata["drainage_area_value"] == ['"55,3"']
    assert metadata["drainage_area_unit"] == ["km²"]
    assert metadata["elevation_field"] is None

    # Verify packaged catalogue station counts, standard 6-column tables, time zones, and stage references.
    all_at = rr.find(provider="at_ehyd")
    assert len(all_at.locations) == 746
    all_series = rr.series(all_at)
    assert all_series["station_id"].n_unique() == 744
    unselectable = {loc.station_id for loc in all_at.locations} - set(all_series["station_id"].to_list())
    assert unselectable == {"207480", "230102"}

    expected_header = (
        "| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |"
    )
    assert page.count(expected_header) == 2
    for internal_token in ("product_id", "pegel_bgis", "pegel_longterm", "owf_*", "result.outcomes"):
        assert internal_token not in page

    table_rows = re.findall(
        r"^\|\s*`(discharge|stage|temperature)`\s*\|\s*`([^`]+)`[^|\n]*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|\s*([^|\n]+?)\s*\|$",
        page,
        re.MULTILINE,
    )
    assert len(table_rows) == 11

    freq_map = {"Daily": "daily", "Monthly": "monthly", "Unknown": None}
    stat_map = {"Mean": "mean", "Minimum": "min", "Maximum": "max", "Unknown": None}
    unit_map = {"m³/s": "m3/s", "m": "m", "°C": "degC"}
    covered_product_ids: set[str] = set()
    for qty, variant_id, freq_label, stat_label, src_unit_label, ret_unit_label in table_rows:
        sub = all_series.filter((all_series["quantity"] == qty) & (all_series["published_id"] == variant_id))
        assert sub.height > 0
        covered_product_ids.update(sub["product_id"].unique().to_list())
        assert set(sub["unit"].to_list()) == {unit_map[ret_unit_label]}
        assert set(sub["statistic"].to_list()) == {stat_map[stat_label]}
        if variant_id == "owf_wasserst_monatsminima":
            assert freq_label == "Monthly (Unknown at `207340`)"
            assert set(sub.filter(sub["station_id"] != "207340")["frequency"].to_list()) == {"monthly"}
            assert sub.filter(sub["station_id"] == "207340")["frequency"].to_list() == [None]
        else:
            assert set(sub["frequency"].to_list()) == {freq_map[freq_label]}
        expected_src_units = {part.strip() for part in src_unit_label.split(",")}
        assert set(sub["source_unit"].to_list()) <= expected_src_units
    assert covered_product_ids == set(all_series["product_id"].unique().to_list())

    bgis_series = all_series.filter(all_series["product_id"].str.starts_with("pegel_bgis_"))
    non_bgis_series = all_series.filter(~all_series["product_id"].str.starts_with("pegel_bgis_"))
    assert set(bgis_series["time_zone"].to_list()) == {"UTC+01:00"}
    assert set(non_bgis_series["time_zone"].to_list()) == {None}

    stage_series = all_series.filter(all_series["quantity"] == "stage")
    assert set(stage_series["vertical_reference"].to_list()) == {"gauge_zero"}
    assert set(stage_series["vertical_datum"].to_list()) == {None}

    all_meta = rr.metadata(all_at)
    assert all_meta.height == 744
    assert all_meta["elevation_field"].null_count() == 744
    assert all_meta.filter(all_meta["station_name"].is_null()).height == 51
    source_elev = rr.metadata(all_at, view="source").filter(
        rr.metadata(all_at, view="source")["attribute_role"] == "elevation"
    )
    assert set(source_elev["state"].to_list()) == {"no_metadata"}

    descriptor = rr.describe("at_ehyd")
    assert descriptor["license"] == "CC BY 4.0"
    assert descriptor["citation"] == "Datenquelle: ehyd.gv.at"

    assert "providers/at_ehyd.md" in (ROOT / "docs/README.md").read_text()
    assert "providers/at_ehyd.md" in (ROOT / "mkdocs.yml").read_text()
    assert "[`at_ehyd`](providers/at_ehyd.md)" in (ROOT / "docs/station-metadata.md").read_text()
    assert "https://rivretrieve.github.io/providers/at_ehyd/" in (ROOT / "README.md").read_text()


@pytest.mark.recorded(_SCOPE)
def test_at_ehyd_page_retrieval_example_matches_recorded_responses(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    page = PAGE.read_text()
    matched = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.DOTALL)
    assert len(matched) == 1
    code, expected_output = matched[0]

    class _DocReplayTransport:
        calls: list[tuple[str, dict[str, str]]] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            params = {str(k): str(v) for k, v in (request.params or {}).items()}
            self.calls.append((request.url, params))
            if request.url.endswith("/Messstellen/info") and params == {"hzbnr": "209486"}:
                return _response_from_capture(retained_evidence_root, "access", "messstellen-info-209486")
            if request.url.endswith("/MessstellenExtraData/owf") and params == {"id": "209486", "file": "5"}:
                return _response_from_capture(retained_evidence_root, "access", "owf-209486-file5-q-tagesmittel")
            if request.url.endswith("/Diagram/pegelBgis") and params == {"hzbnr": "209486"}:
                return _response_from_capture(retained_evidence_root, "access", "pegel-bgis-209486")
            raise AssertionError(f"Unexpected documentation request: {request.url} {params}")

    transport = _DocReplayTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)

    namespace: dict[str, object] = {}
    output = io.StringIO()
    with redirect_stdout(output):
        exec(compile(code, "at_ehyd.md:retrieval", "exec"), namespace)

    assert output.getvalue() == expected_output
    assert len(transport.calls) == 2
    result = namespace["result"]
    assert result.provenance.license == "CC BY 4.0"  # type: ignore[attr-defined]
    assert result.provenance.citation == "Datenquelle: ehyd.gv.at"  # type: ignore[attr-defined]

    # Also verify the documented sub-hourly telemetry (variant="data") MEZ (+01:00) preservation and rr.to_utc (+00:00).
    all_q = rr.find(provider="at_ehyd", station="209486", quantity="discharge")
    bgis_res = rr.fetch(
        rr.pick(all_q, variant="data"),
        start="2026-10-30",
        end="2026-10-31",
        cache="bypass",
    )
    assert set(bgis_res.data["time_zone"].to_list()) == {"+01:00"}
    assert set(rr.to_utc(bgis_res).data["time_zone"].to_list()) == {"+00:00"}
