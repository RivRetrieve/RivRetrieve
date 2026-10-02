"""USGS provider introduction, replayed from its dated live public-API receipts."""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import polars as pl
import polars.testing as pt
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.transport import HttpMethod, TransportResponse
from tests.usgs_modern_recordings import coordinates

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/providers/usgs_nwis.md"


@pytest.mark.recorded("docs/verification/usgs-provider")
def test_usgs_provider_page_exact_snippets_and_displayed_outputs(retained_evidence_root, monkeypatch, capsys):
    recordings = {}
    for path in (retained_evidence_root / "docs/verification/usgs-provider").glob("*-receipt-*-origin.json"):
        origin = json.loads(path.read_text())
        content = path.with_name(path.name.replace("-origin", "")).read_bytes()
        assert hashlib.sha256(content).hexdigest() == origin["sha256"]
        recordings[coordinates(origin["url"], origin["request_parameters"])] = (origin, content)
    calls = []

    class Replay:
        def send(self, request):
            assert request.method is HttpMethod.GET
            key = coordinates(request.url, request.params)
            assert key in recordings, f"No exact documentation recording for {key}"
            origin, content = recordings[key]
            calls.append(key)
            return TransportResponse(
                content=content,
                status_code=origin["status_code"],
                retrieved_at=datetime.fromisoformat(origin["retrieved_at"]),
                content_type=origin["content_type"],
                url=request.url,
                request_parameters=request.params or {},
            )

    monkeypatch.setattr(discovery, "HttpClient", Replay)
    namespace = {}
    examples = re.findall(r"```python\n(.*?)```\s+Output:\s+```text\n(.*?)```", PAGE.read_text(), re.S)
    assert len(examples) == 3
    for code, output in examples:
        exec(compile(code, str(PAGE), "exec"), namespace)
        assert capsys.readouterr().out == output
    assert len(calls) == 3
    all_result = namespace["all_result"]
    chosen_result = namespace["chosen_result"]
    chosen_id = chosen_result.data["series_id"].unique().item()
    pt.assert_frame_equal(all_result.data.filter(pl.col("series_id") == chosen_id), chosen_result.data)
    for name in ("result", "all_result", "chosen_result"):
        result = namespace[name]
        assert result.data["unit"].unique().to_list() == ["m3/s"]
        assert result.data["time_zone"].unique().to_list() == ["unknown"]
        assert not result.receipts.entries
        assert not result.issues


def test_usgs_provider_offline_prevalence_and_singleton(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Packaged inspection must remain offline")

    monkeypatch.setattr(discovery, "HttpClient", forbidden)
    frame = rr.series(rr.find(provider="usgs_nwis"))
    groups = frame.group_by("station_id", "quantity", "frequency", "statistic").agg(
        pl.col("variant").n_unique().alias("series_count")
    )
    assert frame["station_id"].n_unique() == 26201
    assert groups.filter(pl.col("series_count") > 1)["station_id"].n_unique() == 575
    daily = groups.filter(
        (pl.col("quantity") == "discharge") & (pl.col("frequency") == "daily") & (pl.col("statistic") == "mean")
    )
    assert daily.height == 24495
    assert daily.filter(pl.col("series_count") > 1).height == 134
    singleton = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    assert rr.series(singleton)["variant"].to_list() == ["c9d823a2491f4b639656a11b35a7625d"]
