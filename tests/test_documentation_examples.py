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
from tests.test_br_ana_public_daily import _IDENTIFIER, _PASSWORD, _AuthenticatedReplay
from tests.usgs_modern_recordings import ModernReplay, body, coordinates, manifest

ROOT = Path(__file__).resolve().parents[1]
DAILY_RECORDING = "daily-07374000-docs-2023"


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


class DocumentationReplay:
    """Route documented downloads through exact USGS and authenticated ANA replay."""

    def __init__(self, retained_evidence_root: Path):
        self.calls = []
        self.usgs = ModernReplay(DAILY_RECORDING, evidence_root=retained_evidence_root)
        self.ana = _AuthenticatedReplay(retained_evidence_root, "stage_daily_mean_bruto")

    def send(self, request):
        self.calls.append(request)
        if request.url.startswith("https://api.waterdata.usgs.gov/"):
            return self.usgs.send(request)
        if request.url in (ExchangeSpec.ana().exchange_url, self.ana.recording.request.url):
            return self.ana.send(request)
        raise AssertionError(f"Unexpected documentation request: {request.url}")


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


def execute_page(page, monkeypatch, tmp_path, retained_evidence_root: Path):
    import rivretrieve._internal.discovery as discovery

    replay = DocumentationReplay(retained_evidence_root=retained_evidence_root)
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
@pytest.mark.recorded(
    "tests/recordings/br_ana",
    "tests/test_data/usgs_modern",
)
def test_newcomer_page_examples_execute(page, monkeypatch, tmp_path, request, retained_evidence_root: Path):
    if page == "README.md":
        request.getfixturevalue("reuse_packaged_catalogues")
    scope = execute_page(page, monkeypatch, tmp_path, retained_evidence_root=retained_evidence_root)
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
        assert_usage_state(scope, tmp_path, retained_evidence_root=retained_evidence_root)


def assert_usage_state(scope, tmp_path, retained_evidence_root: Path):
    from polars.testing import assert_frame_equal

    result = scope["result"]
    rr = scope["rr"]
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
    assert_frame_equal(scope["restored_result"].data, result.data)
    assert scope["restored_result"].source_series == result.source_series
    assert scope["restored_result"].outcomes == result.outcomes
    assert scope["restored_gauges"].scope == scope["chosen_gauges"].scope
    assert scope["restored_gauges"].known_series == scope["chosen_gauges"].known_series
    assert_frame_equal(scope["cached_result"].data, result.data)
    assert scope["status"].store == tmp_path / "cache" / "usgs_nwis" / "store"
    calls = scope["_calls_by_block"]
    assert next(count for block, count in calls if "cached_result =" in block) == 1
    assert next(count for block, count in calls if "receipt_result =" in block) == 1
    fresh = scope["receipt_result"]
    assert fresh.receipts.entries[0].content == body(DAILY_RECORDING, evidence_root=retained_evidence_root)
    assert fresh.receipts.entries[0].authorship.value == "publisher_payload"
    before = len(scope["_transport"].calls)
    cached = scope["rr"].fetch(
        scope["chosen_gauges"], start="2023-01-01", end="2023-01-01", cache="reuse", receipts=True
    )
    assert len(scope["_transport"].calls) == before
    assert_frame_equal(cached.data, result.data)
    assert cached.receipts.entries[0].authorship.value == "store_excerpt"
    assert cached.receipts.entries[0].format_version == 8
    excerpt = pl.read_parquet(io.BytesIO(cached.receipts.entries[0].content))
    assert excerpt.height >= cached.data.height
    original_acquired_at = datetime.fromisoformat(manifest(retained_evidence_root)[DAILY_RECORDING]["acquired_utc"])
    assert fresh.provenance.retrieved_at == original_acquired_at
    assert not fresh.provenance.served_intervals
    assert cached.provenance.retrieved_at == original_acquired_at
    assert cached.provenance.calls_made
    assert cached.provenance.served_intervals
    assert all(
        interval.retrieved_at == fresh.provenance.retrieved_at for interval in cached.provenance.served_intervals
    )
    assert not result.receipts.entries
    assert scope["outcome_details"] == [
        (item.station_id, item.series_id, item.requested_selector, item.status.value, item.reason)
        for item in result.outcomes
    ]
    assert_frame_equal(scope["returned_series"], rr.series(result))


@pytest.mark.usefixtures("reuse_packaged_catalogues")
@pytest.mark.recorded(
    "tests/recordings/br_ana",
    "tests/test_data/usgs_modern",
)
def test_utc_unknown_refusal_and_synthetic_fixed_offset(monkeypatch, tmp_path, retained_evidence_root: Path):
    from polars.testing import assert_frame_equal

    from rivretrieve._internal.issues import FatalContractError

    scope = execute_page("README.md", monkeypatch, tmp_path, retained_evidence_root=retained_evidence_root)
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


class ScriptedModernReplay(ModernReplay):
    """Authored response controls over exact modern request coordinates."""

    def __init__(self, outcome, retained_evidence_root: Path):
        super().__init__(DAILY_RECORDING, evidence_root=retained_evidence_root)
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


def issue_scope(monkeypatch, tmp_path, outcome, retained_evidence_root: Path):
    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery

    replay = ScriptedModernReplay(outcome, retained_evidence_root=retained_evidence_root)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)
    daily_gauges = rr.find(provider="usgs_nwis", quantity="discharge", frequency="daily", statistic="mean")
    return {"rr": rr, "chosen_gauges": rr.pick(daily_gauges, station=["07374000"])}, replay


@pytest.mark.parametrize("policy", ["warn", "ignore", "raise"])
@pytest.mark.parametrize("outcome", ["success", "empty", 404, 503])
@pytest.mark.usefixtures("reuse_packaged_catalogues")
@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_documented_issue_call_with_each_policy(monkeypatch, tmp_path, policy, outcome, retained_evidence_root: Path):
    """Run each page-authored fetch expression unchanged under transport scenarios."""
    from polars.testing import assert_frame_equal

    from rivretrieve._internal.issues import IssuePolicyError
    from rivretrieve._internal.observations import ObservationDataSchema

    scope, replay = issue_scope(monkeypatch, tmp_path, outcome, retained_evidence_root=retained_evidence_root)
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
    call = calls[0]
    call.keywords.append(ast.keyword(arg="on_issue", value=ast.Constant(policy)))
    ast.fix_missing_locations(call)
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
                manifest(retained_evidence_root)[DAILY_RECORDING]["original_url"]
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
    for block in blocks("docs/usage.md"):
        execute_block(block, scope, "usage-selection")
        if "restored_gauges" in scope:
            break
    selected = scope["chosen_gauges"]
    restored = scope["restored_gauges"]
    assert restored.scope == selected.scope
    assert restored.known_series == selected.known_series
    assert restored.inventories == selected.inventories
    assert_frame_equal(rr.series(restored), rr.series(selected))
    with pytest.raises(ValueError, match="bundle"):
        rr.from_frame(rr.as_frame(selected))


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_usage_variant_selection():
    import rivretrieve as rr

    scope = {"rr": rr}
    block = next(block for block in blocks("docs/usage.md") if "brazil =" in block)
    execute_block(block, scope, "usage-variants")
    assert set(rr.series(scope["brazil"])["variant"]) == {"bruto", "consistido"}
    assert rr.series(scope["consistido"])["variant"].to_list() == ["consistido"]


@pytest.mark.parametrize("page", ["README.md", "docs/usage.md"])
def test_documentation_output_contracts(page):
    """Check every displayed print has an expected output before replay."""
    for block in blocks(page):
        output_contracts(block)


def test_usage_recovery_example_preserves_observation_status(monkeypatch, tmp_path):
    import rivretrieve as rr
    import rivretrieve._internal.discovery as discovery

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)

    def no_source(*args, **kwargs):
        pytest.fail("local recovery example reached source transport")

    monkeypatch.setattr(discovery, "HttpClient", no_source)
    status = rr.cache_status("usgs_nwis")
    scope = {"rr": rr, "status": status}
    block = next(block for block in blocks("docs/usage.md") if "recovery = rr.recover_cache" in block)
    execute_block(block, scope, "usage-recovery")
    assert scope["status"] is status
    assert scope["recovery_status"].provider_id == "ca_eccc"
    assert scope["unfinished_paths"] == ()
    assert scope["cleanup_paths"] == ()
    assert not scope["resulting_status"].exists
