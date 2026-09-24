"""Thailand documentation checks over captured ThaiWater bytes, not live verification."""

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.recordings import ReplayTransport

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/verification/thailand-provider"


def test_thailand_page_examples_match_recorded_response(monkeypatch, tmp_path):
    page = (ROOT / "docs/providers/th_thaiwater.md").read_text()
    blocks = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.S)
    assert len(blocks) == page.count("```python") == 2
    replay = ReplayTransport(sorted((EVIDENCE / "recordings").glob("*.recording.json")))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    namespace = {}
    for index, (code, expected) in enumerate(blocks, 1):
        output = io.StringIO()
        with redirect_stdout(output):
            exec(compile(code, f"th_thaiwater.md:block-{index}", "exec"), namespace)
        assert output.getvalue() == expected, index
    result = namespace["result"]
    assert result.data["value"].null_count() == 0
    assert result.data["time"].diff().drop_nulls().dt.total_minutes().unique().to_list() == [10]
    assert result.data["time_zone"].unique().to_list() == ["unknown"]
    for name in ("result", "discharge_result"):
        calls = namespace[name].provenance.calls_made
        assert [call["request_parameters"]["start_date"] for call in calls] == ["2024-05-30"]
        assert [call["request_parameters"]["end_date"] for call in calls] == ["2024-06-05"]
    facts = rr.series(result).select(
        "unit", "source_unit", "frequency", "statistic", "vertical_reference", "vertical_datum"
    )
    assert facts.rows() == [("m", "m", None, None, "above_sea_level", None)]
    with pytest.raises(FatalContractError, match="time_zone is 'unknown'"):
        rr.to_utc(result)


def test_thailand_page_catalogue_counts_and_index():
    selection = rr.find(provider="th_thaiwater")
    assert len(selection.locations) == 825
    station_products = pl.read_parquet(
        ROOT / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/station_products.parquet"
    )
    available = station_products.filter(pl.col("availability") == "available")
    assert available.group_by("product_id").len().sort("product_id").rows() == [
        ("discharge_reported", 283),
        ("stage_reported", 813),
    ]
    for quantity in ("stage", "discharge"):
        assert rr.series(rr.find(provider="th_thaiwater", quantity=quantity))["station_id"].n_unique() == 825
    native = pl.read_parquet(ROOT / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
    assert native.group_by("agency.agency_shortname.en").len().sort("len", descending=True).rows() == [
        ("HII", 329),
        ("RID", 328),
        ("FOP", 95),
        ("EGAT", 73),
    ]
    assert "providers/th_thaiwater.md" in (ROOT / "docs/README.md").read_text()
