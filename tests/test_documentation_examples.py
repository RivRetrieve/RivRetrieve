"""Execute newcomer page examples against exact publisher transport recordings."""

import ast
import builtins
import inspect
import io
import json
import re
import warnings
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.recordings import ReplayTransport, read_recording

ROOT = Path(__file__).resolve().parents[1]
RECORDING = ROOT / "tests/test_data/usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"
INSTANT_RECORDING = ROOT / "tests/test_data/usgs_nwis_07374000_iv_00060_2023-01-01.recording.json"
LITHUANIAN_RECORDINGS = [
    ROOT / f"tests/test_data/lt_lhmt_anyksciu-vms_daily_{month}.recording.json" for month in ("2022-12", "2023-01")
]


def blocks(page):
    return re.findall(r"```python\n(.*?)```", (ROOT / page).read_text(), re.DOTALL)


def output_contracts(block):
    """Each print has literal output comments immediately after its closing line."""
    lines = block.splitlines()
    contracts = {}
    for node in ast.walk(ast.parse(block)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "print":
            continue
        end = node.end_lineno
        assert end < len(lines) and lines[end].strip() == "# Output:", (
            f"Missing output after print at line {node.lineno}"
        )
        output = []
        for line in lines[end + 1 :]:
            if not line.lstrip().startswith("# "):
                break
            output.append(line.lstrip()[2:])
        assert output, f"Empty output for print at line {node.lineno}"
        contracts[node.lineno] = "\n".join(output) + "\n"
    return contracts


@pytest.mark.parametrize("page", ["README.md", "docs/usage.md"])
def test_every_newcomer_print_has_visible_output(page):
    for block in blocks(page):
        output_contracts(block)


class CountingReplay(ReplayTransport):
    """Keep transport call counts; never replace the public retrieval path."""

    def __init__(self, recording, *additional_recordings):
        super().__init__((recording, *additional_recordings))
        self.calls = []

    def send(self, request):
        self.calls.append(request)
        return super().send(request)


def execute_block(block, scope, label):
    expected = output_contracts(block)
    checked = []

    def checked_print(*args, **kwargs):
        line = inspect.currentframe().f_back.f_lineno
        stream = io.StringIO()
        builtins.print(*args, **kwargs, file=stream)
        assert stream.getvalue() == expected[line], (label, line, stream.getvalue())
        checked.append(line)

    scope["print"] = checked_print
    exec(compile(block, label, "exec"), scope)
    return checked


def execute_page(page, monkeypatch, tmp_path):
    import rivretrieve._internal.discovery as discovery

    replay = CountingReplay(
        read_recording(RECORDING),
        read_recording(INSTANT_RECORDING),
        *(read_recording(path) for path in LITHUANIAN_RECORDINGS),
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)
    scope = {"_transport": replay, "_calls_by_block": []}
    checked = []
    for index, block in enumerate(blocks(page)):
        before = len(replay.calls)
        checked.extend(execute_block(block, scope, f"{page}:block-{index}"))
        scope["_calls_by_block"].append((block, len(replay.calls) - before))
    assert checked
    return scope


@pytest.mark.parametrize("page", ["README.md", "docs/usage.md"])
def test_newcomer_page_examples_execute(page, monkeypatch, tmp_path):
    scope = execute_page(page, monkeypatch, tmp_path)
    assert scope["result"].data.height == 1
    assert scope["result"].data["station_id"].to_list() == ["07374000"]
    if page == "README.md":
        assert len(scope["_transport"].calls) == 1
    else:
        assert_usage_state(scope, tmp_path)


def assert_usage_state(scope, tmp_path):
    from folium import Marker
    from polars.testing import assert_frame_equal

    result = scope["result"]
    assert len(scope["provider_results"]) == 2
    assert set(scope["provider_results"]) == {"usgs_nwis", "lt_lhmt"}
    lithuanian = scope["lithuanian_result"]
    expected_lithuanian = pl.DataFrame(
        {
            "time": [datetime(2023, 1, 1)],
            "time_zone": ["+00:00"],
            "station_id": ["anyksciu-vms"],
            "product_id": ["discharge_daily_mean"],
            "value": [81.8],
        }
    )
    assert_frame_equal(lithuanian.data, expected_lithuanian)
    assert not lithuanian.issues
    assert lithuanian.provenance.provider_id == "lt_lhmt"
    instantaneous = scope["instant_result"]
    assert not instantaneous.issues
    assert instantaneous.data["time_zone"].to_list() == ["-06:00", "-06:00"]
    assert instantaneous.data["time"].to_list() == [datetime(2023, 1, 1), datetime(2023, 1, 1, 0, 15)]
    expected_utc = instantaneous.data.with_columns(
        pl.Series("time", [datetime(2023, 1, 1, 6), datetime(2023, 1, 1, 6, 15)]),
        pl.lit("+00:00").alias("time_zone"),
    )
    assert_frame_equal(scope["utc_result"].data, expected_utc)
    assert scope["utc_result"].provenance is instantaneous.provenance
    assert scope["utc_result"].issues is instantaneous.issues
    assert scope["utc_result"].receipts is instantaneous.receipts
    assert_frame_equal(scope["provider_results"]["usgs_nwis"].data, result.data)
    assert_frame_equal(scope["cached_result"].data, result.data)
    assert scope["status"].store == tmp_path / "cache" / "usgs_nwis" / "store"
    calls = scope["_calls_by_block"]
    assert next(count for block, count in calls if "cached_result =" in block) == 1
    assert next(count for block, count in calls if "receipt_result =" in block) == 1
    fresh = scope["receipt_result"]
    assert fresh.receipts.entries[0].content == read_recording(RECORDING).content
    assert fresh.receipts.entries[0].authorship.value == "publisher_payload"
    before = len(scope["_transport"].calls)
    cached = scope["rr"].fetch(
        scope["chosen_gauges"], start="2023-01-01", end="2023-01-01", cache="reuse", receipts=True
    )
    assert len(scope["_transport"].calls) == before
    assert_frame_equal(cached.data, result.data)
    assert cached.receipts.entries[0].authorship.value == "store_excerpt"
    assert cached.receipts.entries[0].format_version == 4
    excerpt = pl.read_parquet(io.BytesIO(cached.receipts.entries[0].content))
    assert excerpt.height >= cached.data.height
    assert fresh.provenance.retrieved_at == read_recording(RECORDING).retrieved_at
    assert not fresh.provenance.served_intervals
    assert cached.provenance.retrieved_at is None
    assert not cached.provenance.calls_made
    assert cached.provenance.served_intervals
    assert all(
        interval.retrieved_at == fresh.provenance.retrieved_at for interval in cached.provenance.served_intervals
    )
    assert not result.receipts.entries
    markers = [child for child in scope["station_map"]._children.values() if isinstance(child, Marker)]
    assert len(markers) == 1
    gauge_frame = scope["rr"].as_frame(scope["chosen_gauges"])
    assert markers[0].location == list(gauge_frame.select("latitude", "longitude").row(0))
    html = (tmp_path / "stations.html").read_text()
    assert "07374000" in html
    assert "L.marker(" in html


def test_utc_unknown_refusal_and_synthetic_fixed_offset(monkeypatch, tmp_path):
    from polars.testing import assert_frame_equal

    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.observations import ObservationProvenance, ObservationResult, Receipts
    from rivretrieve._internal.primitives import ProviderId

    scope = execute_page("README.md", monkeypatch, tmp_path)
    rr = scope["rr"]
    assert scope["result"].data["time_zone"].to_list() == ["unknown"]
    with pytest.raises(FatalContractError, match="unknown"):
        rr.to_utc(scope["result"])
    synthetic = ObservationResult(
        data=pl.DataFrame(
            {
                "time": [datetime(2023, 1, 1, 12)],
                "time_zone": ["+02:00"],
                "station_id": ["example"],
                "product_id": ["stage_instantaneous"],
                "value": [1.0],
            }
        ),
        provenance=ObservationProvenance(source="synthetic", provider_id=ProviderId("example")),
        receipts=Receipts(provider_id=ProviderId("example"), entries=()),
    )
    converted = rr.to_utc(synthetic)
    expected = synthetic.data.with_columns(
        pl.lit(datetime(2023, 1, 1, 10)).alias("time"),
        pl.lit("+00:00").alias("time_zone"),
    )
    assert_frame_equal(converted.data, expected)
    assert converted.provenance is synthetic.provenance
    assert converted.issues is synthetic.issues
    assert converted.receipts is synthetic.receipts


def issue_example():
    return next(block for block in blocks("docs/usage.md") if "checked_result =" in block)


def scripted_recording(outcome):
    """Authored responses keep exact request identity; they are not agency evidence."""
    recording = read_recording(RECORDING)
    if outcome == "empty":
        document = json.loads(recording.content)
        document["value"]["timeSeries"] = []
        return replace(recording, content=json.dumps(document).encode())
    if isinstance(outcome, int):
        return replace(recording, status_code=outcome, content=b"Authored source failure", content_type="text/plain")
    return recording


def issue_scope(monkeypatch, tmp_path, outcome):
    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery

    replay = CountingReplay(scripted_recording(outcome))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)
    daily_gauges = rr.find(provider="usgs_nwis", product="discharge_daily_mean")
    return {"rr": rr, "chosen_gauges": rr.pick(daily_gauges, station=["07374000"])}, replay


def test_actual_issue_example_success(monkeypatch, tmp_path):
    scope, replay = issue_scope(monkeypatch, tmp_path, "success")
    checked = execute_block(issue_example(), scope, "usage-issues-success")
    assert len(checked) == 1
    assert len(replay.calls) == 1
    assert not scope["checked_result"].issues


@pytest.mark.parametrize("policy", ["warn", "ignore", "raise"])
@pytest.mark.parametrize("outcome", ["success", "empty", 404, 503])
def test_documented_issue_call_with_each_policy(monkeypatch, tmp_path, policy, outcome):
    """Run each page-authored fetch expression unchanged under transport scenarios."""
    from polars.testing import assert_frame_equal

    from rivretrieve._internal.issues import IssuePolicyError
    from rivretrieve._internal.observations import ObservationDataSchema

    scope, replay = issue_scope(monkeypatch, tmp_path, outcome)
    calls = [
        node
        for block in blocks("docs/usage.md")
        for node in ast.walk(ast.parse(block))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "fetch"
    ]
    call = next(
        call
        for call in calls
        if next((keyword.value.value for keyword in call.keywords if keyword.arg == "on_issue"), "warn") == policy
    )
    expression = compile(ast.Expression(call), "usage-policy-expression", "eval")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if policy == "raise" and outcome != "success":
            with pytest.raises(IssuePolicyError) as raised:
                eval(expression, scope)
            issues = raised.value.issues
        else:
            result = eval(expression, scope)
            issues = result.issues
            if outcome == "success":
                assert result.data.height == 1
            else:
                assert_frame_equal(result.data, pl.DataFrame(schema=ObservationDataSchema.polars_schema))
    assert len(replay.calls) == 1
    assert len(caught) == int(policy == "warn" and outcome != "success")
    assert all(issubclass(item.category, RuntimeWarning) for item in caught)
    if outcome == "success":
        assert not issues
    else:
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == ("error" if outcome == 503 else "warning")
        assert issue.provider_id == "usgs_nwis"
        assert issue.details["station_id"] == "07374000"
        if outcome == "empty":
            assert issue.code == "missing_data"
            assert issue.message == "No observation rows found"
            if policy != "raise":
                assert result.provenance.calls_made
        else:
            assert issue.details["status_code"] == outcome
            assert f"HTTP {outcome}" in issue.message
            if policy != "raise":
                assert not result.provenance.calls_made


def test_usage_selection_roundtrip_keeps_repeated_identity_strings(monkeypatch, tmp_path):
    from polars.testing import assert_frame_equal

    import rivretrieve as rr

    monkeypatch.chdir(tmp_path)
    scope = {}
    for block in blocks("docs/usage.md")[:2]:
        execute_block(block, scope, "usage-selection")
    frame = scope["frame"]
    assert frame["provider_id"].n_unique() == 1
    assert frame["product_id"].n_unique() == 1
    assert frame["station_id"].n_unique() == 3
    assert_frame_equal(rr.as_frame(rr.from_frame(frame)), frame)
    # Identity columns retain their relative order even with metadata between them.
    reordered = frame.select("latitude", "provider_id", "longitude", "station_id", "product_id")
    assert_frame_equal(rr.as_frame(rr.from_frame(reordered)), frame)
    assert_frame_equal(rr.as_frame(rr.from_frame(frame.with_columns(pl.lit(0.0).alias("latitude")))), frame)
    from rivretrieve._internal.issues import FatalContractError

    invalid_frames = [
        pl.concat([frame, frame.head(1)]),
        frame.with_columns(pl.lit(None, dtype=pl.String).alias("station_id")),
        frame.with_columns(pl.col("station_id").cast(pl.Int64)),
        frame.select("station_id", "provider_id", "product_id"),
    ]
    for invalid in invalid_frames:
        with pytest.raises(FatalContractError):
            rr.from_frame(invalid)
    assert rr.as_frame(scope["chosen_gauges"])["station_id"].to_list() == ["07374000"]
    assert rr.as_frame(scope["northern_gauges"])["station_id"].to_list() == ["01013500"]
