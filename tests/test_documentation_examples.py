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

from rivretrieve._internal.authentication import ExchangeSpec
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from tests.test_br_ana_public_daily import _IDENTIFIER, _PASSWORD, _AuthenticatedReplay
from tests.usgs_modern_recordings import MANIFEST, ModernReplay, body, coordinates

ROOT = Path(__file__).resolve().parents[1]
DAILY_RECORDING = "daily-07374000-docs-2023"
INSTANT_RECORDING = "continuous-07374000-docs-quarter-hour-2023"
LITHUANIAN_RECORDINGS = [
    ROOT / f"tests/test_data/lt_lhmt_anyksciu-vms_daily_{month}.recording.json" for month in ("2022-12", "2023-01")
]


def blocks(page):
    snippets = re.findall(r"```python\n(.*?)```", (ROOT / page).read_text(), re.DOTALL)
    assert snippets, f"No Python examples in {page}"
    return snippets


def output_contracts(block):
    """Each print has literal output comments immediately after its closing line."""
    lines = block.splitlines()
    contracts = {}
    for node in ast.walk(ast.parse(block)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "print":
            continue
        end = node.end_lineno
        while end < len(lines) and not lines[end].strip():
            end += 1
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


class CountingReplay(ReplayTransport):
    """Keep transport call counts; never replace the public retrieval path."""

    def __init__(self, recording, *additional_recordings):
        super().__init__((recording, *additional_recordings))
        self.calls = []

    def send(self, request):
        self.calls.append(request)
        return super().send(request)


class NewcomerReplay(CountingReplay):
    """Route ANA through its credential protocol and all observations through exact replay."""

    def __init__(self):
        super().__init__(
            *(read_recording(path) for path in LITHUANIAN_RECORDINGS),
        )
        self.usgs = ModernReplay(DAILY_RECORDING, INSTANT_RECORDING)
        self.ana = _AuthenticatedReplay("stage_daily_mean_bruto")

    def send(self, request):
        if request.url.startswith("https://api.waterdata.usgs.gov/"):
            self.calls.append(request)
            return self.usgs.send(request)
        if request.url in (ExchangeSpec.ana().exchange_url, self.ana.recording.request.url):
            self.calls.append(request)
            return self.ana.send(request)
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

    replay = NewcomerReplay()
    monkeypatch.setenv("ANA_IDENTIFICADOR", _IDENTIFIER)
    monkeypatch.setenv("ANA_SENHA", _PASSWORD)
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
def test_newcomer_page_examples_execute(page, monkeypatch, tmp_path, request):
    if page == "README.md":
        request.getfixturevalue("reuse_packaged_catalogues")
    scope = execute_page(page, monkeypatch, tmp_path)
    assert scope["result"].data.height == 1
    assert scope["result"].data["station_id"].to_list() == ["07374000"]
    assert scope["result"].data["source_unit"].to_list() == ["ft^3/s"]
    assert scope["result"].source_series[0].variant == "c9d823a2491f4b639656a11b35a7625d"
    assert scope["result"].source_series[0].identity.description is None
    if page == "README.md":
        from polars.testing import assert_frame_equal

        from rivretrieve._internal.observations import ObservationDataSchema

        result = scope["result"]
        expected = pl.DataFrame(
            {
                "time": [datetime(2023, 1, 1)],
                "time_zone": ["unknown"],
                "station_id": ["07374000"],
                "product_id": ["discharge_daily_mean"],
                "value": [373000.0 * 0.028316846592],
            }
        )
        assert_frame_equal(result.data.select(expected.columns), expected)
        assert result.data.columns == list(ObservationDataSchema.polars_schema)
        assert result.source_series
        assert result.data["series_id"].n_unique() == 1
        assert result.data["unit"].to_list() == ["m3/s"]
        assert not result.issues
        assert not result.receipts.entries
        assert len(scope["_transport"].calls) == 1
        assert set(scope["rr"].series(scope["brazil"])["variant"]) == {"bruto", "consistido"}
        assert scope["rr"].series(scope["consistido"])["variant"].to_list() == ["consistido"]
    else:
        assert_usage_state(scope, tmp_path)


def assert_usage_state(scope, tmp_path):
    from folium import Marker
    from polars.testing import assert_frame_equal

    result = scope["result"]
    rr = scope["rr"]
    assert rr.series(scope["swiss"]).height > 0
    assert rr.series(scope["swiss_daily"]).is_empty()
    assert set(rr.series(scope["brazil"])["variant"]) == {"bruto", "consistido"}
    assert rr.series(scope["consistido"])["variant"].to_list() == ["consistido"]
    both = scope["brazil_result"]
    explicit = scope["consistido_result"]
    expected_issues = {("info", "source_status"), ("info", "provenance.citation_not_established")}
    assert {(issue.severity, issue.code) for issue in both.issues} == expected_issues
    assert {(issue.severity, issue.code) for issue in explicit.issues} == expected_issues
    assert both.data.height == 22
    assert both.data["series_id"].n_unique() == 2
    assert set(rr.series(both)["variant"]) == {"bruto", "consistido"}
    assert rr.series(explicit)["variant"].to_list() == ["consistido"]
    # Decode the exact monthly source cells independently of the provider parser.
    source = json.loads(scope["_transport"].ana.recording.content)["items"]
    expected_rows = []
    for item in source:
        if item["Mediadiaria"] != "1":
            continue
        variant = {"1": "bruto", "2": "consistido"}[item["nivelconsistencia"]]
        for day in range(10, 21):
            raw = item[f"Cota_{day:02d}"]
            value = None if raw is None or not raw.strip() else float(raw) / 100
            expected_rows.append(
                (datetime(2020, 1, day), "unknown", "15400000", f"stage_daily_mean_{variant}", "m", value)
            )
    expected = pl.DataFrame(
        expected_rows,
        schema={
            name: both.data.schema[name] for name in ("time", "time_zone", "station_id", "product_id", "unit", "value")
        },
        orient="row",
    )
    assert_frame_equal(
        both.data.select(expected.columns).sort("product_id", "time"), expected.sort("product_id", "time")
    )
    narrowed = rr.pick(both, variant="consistido")
    assert_frame_equal(explicit.data, narrowed.data)
    assert_frame_equal(
        rr.series(explicit).select("series_id", "variant"),
        rr.series(narrowed).select("series_id", "variant"),
    )
    assert scope["_transport"].ana.exchange_calls == 2
    assert scope["_transport"].ana.observation_calls >= 2
    singleton = scope["lithuanian_result"]
    assert not singleton.issues
    expected_singleton = pl.DataFrame(
        {"station_id": ["anyksciu-vms"], "time": [datetime(2023, 1, 1)], "unit": ["m3/s"], "value": [81.8]}
    )
    assert_frame_equal(singleton.data.select(expected_singleton.columns), expected_singleton)
    assert singleton.data["series_id"].n_unique() == 1
    assert [item.code for item in scope["no_variant"].issues] == ["selection.unresolved_inventory"]
    assert [item.code for item in scope["no_match"].issues] == ["selection.no_match"]
    assert_frame_equal(scope["restored_result"].data, result.data)
    assert scope["restored_result"].source_series == result.source_series
    assert scope["restored_result"].outcomes == result.outcomes
    assert scope["restored_gauges"].scope == scope["chosen_gauges"].scope
    assert scope["restored_gauges"].known_series == scope["chosen_gauges"].known_series
    instantaneous = scope["instant_result"]
    assert not instantaneous.issues
    assert instantaneous.data["time_zone"].to_list() == ["+00:00", "+00:00"]
    assert instantaneous.data["time"].to_list() == [datetime(2023, 1, 1), datetime(2023, 1, 1, 0, 15)]
    expected_utc = instantaneous.data.with_columns(
        pl.Series("time", [datetime(2023, 1, 1), datetime(2023, 1, 1, 0, 15)]),
        pl.lit("+00:00").alias("time_zone"),
    )
    assert_frame_equal(scope["utc_result"].data, expected_utc)
    assert scope["utc_result"].provenance is instantaneous.provenance
    assert scope["utc_result"].issues is instantaneous.issues
    assert scope["utc_result"].receipts is instantaneous.receipts
    assert_frame_equal(scope["cached_result"].data, result.data)
    assert scope["status"].store == tmp_path / "cache" / "usgs_nwis" / "store"
    calls = scope["_calls_by_block"]
    assert next(count for block, count in calls if "cached_result =" in block) == 1
    assert next(count for block, count in calls if "receipt_result =" in block) == 1
    fresh = scope["receipt_result"]
    assert fresh.receipts.entries[0].content == body(DAILY_RECORDING)
    assert fresh.receipts.entries[0].authorship.value == "publisher_payload"
    before = len(scope["_transport"].calls)
    cached = scope["rr"].fetch(
        scope["chosen_gauges"], start="2023-01-01", end="2023-01-01", cache="reuse", receipts=True
    )
    assert len(scope["_transport"].calls) == before
    assert_frame_equal(cached.data, result.data)
    assert cached.receipts.entries[0].authorship.value == "store_excerpt"
    assert cached.receipts.entries[0].format_version == 7
    excerpt = pl.read_parquet(io.BytesIO(cached.receipts.entries[0].content))
    assert excerpt.height >= cached.data.height
    assert fresh.provenance.retrieved_at == datetime.fromisoformat(MANIFEST[DAILY_RECORDING]["acquired_utc"])
    assert not fresh.provenance.served_intervals
    assert cached.provenance.retrieved_at is None
    assert cached.provenance.calls_made
    assert cached.provenance.served_intervals
    assert all(
        interval.retrieved_at == fresh.provenance.retrieved_at for interval in cached.provenance.served_intervals
    )
    assert not result.receipts.entries
    markers = [child for child in scope["station_map"]._children.values() if isinstance(child, Marker)]
    assert len(markers) == 1
    location = next(item for item in scope["chosen_gauges"].locations if item.station_id == "07374000")
    assert markers[0].location == [location.latitude, location.longitude]
    html = (tmp_path / "stations.html").read_text()
    assert "07374000" in html
    assert "L.marker(" in html


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_utc_unknown_refusal_and_synthetic_fixed_offset(monkeypatch, tmp_path):
    from polars.testing import assert_frame_equal

    from rivretrieve._internal.issues import FatalContractError

    scope = execute_page("README.md", monkeypatch, tmp_path)
    rr = scope["rr"]
    assert scope["result"].data["time_zone"].to_list() == ["unknown"]
    with pytest.raises(FatalContractError, match="unknown"):
        rr.to_utc(scope["result"])
    # Authored clock labels test the UTC operation, retaining real identity/fact context.
    original = scope["result"]
    synthetic = original.model_copy(
        update={
            "data": original.data.with_columns(
                pl.lit(datetime(2023, 1, 1, 12)).alias("time"),
                pl.lit("+02:00").alias("time_zone"),
            )
        }
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


class ScriptedModernReplay(ModernReplay):
    """Authored response controls over exact modern request coordinates."""

    def __init__(self, outcome):
        super().__init__(DAILY_RECORDING)
        self.outcome = outcome

    def send(self, request):
        response = super().send(request)
        if self.outcome == "empty":
            document = json.loads(response.content)
            document["features"] = []
            document["numberReturned"] = 0
            document["links"] = [link for link in document["links"] if link["rel"] != "next"]
            return replace(response, content=json.dumps(document).encode())
        if isinstance(self.outcome, int):
            return replace(
                response, status_code=self.outcome, content=b"Authored source failure", content_type="text/plain"
            )
        return response


def issue_scope(monkeypatch, tmp_path, outcome):
    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery

    replay = ScriptedModernReplay(outcome)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)
    daily_gauges = rr.find(provider="usgs_nwis", quantity="discharge", frequency="daily", statistic="mean")
    return {"rr": rr, "chosen_gauges": rr.pick(daily_gauges, station=["07374000"])}, replay


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_actual_issue_example_success(monkeypatch, tmp_path):
    scope, replay = issue_scope(monkeypatch, tmp_path, "success")
    checked = execute_block(issue_example(), scope, "usage-issues-success")
    assert len(checked) == 1
    assert len(replay.calls) == 1
    assert not scope["checked_result"].issues


@pytest.mark.parametrize("policy", ["warn", "ignore", "raise"])
@pytest.mark.parametrize("outcome", ["success", "empty", 404, 503])
@pytest.mark.usefixtures("reuse_packaged_catalogues")
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
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "fetch"
        and node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "chosen_gauges"
    ]
    call = next(
        call
        for call in calls
        if next((keyword.value.value for keyword in call.keywords if keyword.arg == "on_issue"), "warn") == policy
    )
    expression = compile(ast.Expression(call), "usage-policy-expression", "eval")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if policy == "raise" and isinstance(outcome, int):
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
    assert len(caught) == int(policy == "warn" and isinstance(outcome, int))
    assert all(issubclass(item.category, RuntimeWarning) for item in caught)
    if outcome in ("success", "empty"):
        assert not issues
        if outcome == "empty":
            assert result.provenance.calls_made
            assert any(item.status == "empty" for item in result.outcomes)
    else:
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == ("error" if outcome == 503 else "warning")
        assert issue.provider_id == "usgs_nwis"
        assert issue.details["station_id"] == "07374000"
        assert issue.details["status_code"] == outcome
        assert f"HTTP {outcome}" in issue.message
        if policy != "raise":
            assert len(result.provenance.calls_made) == 1
            call = result.provenance.calls_made[0]
            assert call["station_id"] == "07374000"
            assert call["product_id"] == "discharge_daily_mean"
            assert call["status_code"] == outcome
            assert coordinates(call["url"], call["request_parameters"]) == coordinates(
                MANIFEST[DAILY_RECORDING]["original_url"]
            )
            assert issue.details["failure_reason"]
            assert result.outcomes
            assert all(item.status in ("failed", "unresolved") and item.reason for item in result.outcomes)
            failed = [item for item in result.outcomes if item.status == "failed"]
            assert {item.series_id for item in failed} == {call["series_id"]}
            assert {item.series_id for item in result.outcomes} == {call["series_id"]}
            assert not result.provenance.served_intervals


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_usage_selection_bundle_roundtrip(monkeypatch, tmp_path):
    from polars.testing import assert_frame_equal

    import rivretrieve as rr

    monkeypatch.chdir(tmp_path)
    scope = {}
    for block in blocks("docs/usage.md")[:2]:
        execute_block(block, scope, "usage-selection")
    selected = scope["chosen_gauges"]
    restored = scope["restored_gauges"]
    assert restored.scope == selected.scope
    assert restored.known_series == selected.known_series
    assert restored.inventories == selected.inventories
    assert_frame_equal(rr.series(restored), rr.series(selected))
    with pytest.raises(ValueError, match="bundle"):
        rr.from_frame(rr.as_frame(selected))


@pytest.mark.parametrize("policy", ["warn", "ignore", "raise"])
@pytest.mark.parametrize("restriction", ["no_variant", "no_match"])
def test_documented_variant_restriction_policy(policy, restriction):
    """Execute the documented pick call against real catalogue scope, never a fabricated inventory."""
    import rivretrieve as rr
    from rivretrieve._internal.issues import IssuePolicyError

    scope = {"rr": rr}
    for block in blocks("docs/usage.md"):
        if "brazil =" in block:
            execute_block(block, scope, "usage-physical-facts")
    scope["lithuania"] = rr.find(
        provider="lt_lhmt", station="anyksciu-vms", quantity="discharge", frequency="daily", statistic="mean"
    )
    block = next(block for block in blocks("docs/usage.md") if f"{restriction} =" in block)
    call = ast.parse(block).body[0].value
    for keyword in call.keywords:
        if keyword.arg == "on_issue":
            keyword.value = ast.Constant(policy)
    expression = compile(ast.fix_missing_locations(ast.Expression(call)), "usage-variant-policy", "eval")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if policy == "raise":
            with pytest.raises(IssuePolicyError) as raised:
                eval(expression, scope)
            issues = raised.value.issues
        else:
            selected = eval(expression, scope)
            assert rr.series(selected).is_empty()
            issues = selected.issues
    assert len(caught) == int(policy == "warn")
    assert [item.code for item in issues] == [
        "selection.unresolved_inventory" if restriction == "no_variant" else "selection.no_match"
    ]
