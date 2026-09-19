"""documentation examples : MarkdownPythonBlocks × PublicAPI → ExecutableContracts."""

import ast
import re
import runpy
from datetime import datetime
from pathlib import Path

import polars as pl
from polars.testing import assert_frame_equal

import rivretrieve as rr

ROOT = Path(__file__).resolve().parents[1]


def python_blocks(path: Path) -> list[str]:
    return re.findall(r"```python\n(.*?)```", path.read_text(), re.DOTALL)


def test_readme_uses_current_public_api():
    calls = []
    for block in python_blocks(ROOT / "README.md"):
        for node in ast.walk(ast.parse(block)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "rr"
            ):
                calls.append(node.func.attr)
    assert calls
    assert all(callable(getattr(rr, name, None)) for name in calls), calls
    assert "fetch" in calls


def test_readme_january_example_with_authored_partial_window_response(monkeypatch, capsys):
    import rivretrieve._internal.discovery as discovery
    from rivretrieve._internal.recordings import read_recording
    from rivretrieve._internal.transport import HttpMethod, TransportRequest, TransportResponse

    recording = read_recording(
        ROOT / "tests/test_data/usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"
    )

    class PartialWindowTransport:
        """Test response uses unchanged publisher bytes, not a January recording."""

        calls = 0

        def send(self, request: TransportRequest) -> TransportResponse:
            assert request.method == HttpMethod.GET
            assert request.url == "https://waterservices.usgs.gov/nwis/dv/"
            assert request.params == {
                "format": "json",
                "sites": "07374000",
                "startDT": "2022-12-30",
                "endDT": "2023-02-02",
                "parameterCd": "00060",
                "statCd": "00003",
            }
            assert request.body is None
            self.calls += 1
            return recording.to_transport_response()

    # Authored partial-window response: do not change the fixture's request identity
    # or claim these five publisher days prove full-January retrieval or availability.
    transport = PartialWindowTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    scope = {}
    for block in python_blocks(ROOT / "README.md"):
        exec(compile(block, "README.md", "exec"), scope)
    result = scope["result"]
    expected = pl.DataFrame(
        {
            "time": [datetime(2023, 1, day) for day in (1, 2, 3)],
            "time_zone": ["unknown"] * 3,
            "station_id": ["07374000"] * 3,
            "product_id": ["discharge_daily_mean"] * 3,
            "value": [373000.0 * 0.028316846592] * 3,
        }
    )
    assert_frame_equal(result.data, expected)
    assert not result.issues
    assert not result.receipts.entries
    assert transport.calls == 1
    assert capsys.readouterr().out == f"{result.data}\n{result.issues}\n"


def test_quickstart_workflow_replays_recorded_single_day(monkeypatch):
    import rivretrieve._internal.discovery as discovery
    from rivretrieve._internal.recordings import ReplayTransport, read_recording

    recording = read_recording(
        ROOT / "tests/test_data/usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"
    )
    replay = ReplayTransport((recording,))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    gauges = rr.find(provider="usgs_nwis", product="discharge_daily_mean")
    gauge = rr.pick(gauges, station="07374000")
    # Only this shorter public window matches the committed publisher recording.
    result = rr.fetch(gauge, start="2023-01-01", end="2023-01-01")
    expected = pl.DataFrame(
        {
            "time": [datetime(2023, 1, 1)],
            "time_zone": ["unknown"],
            "station_id": ["07374000"],
            "product_id": ["discharge_daily_mean"],
            "value": [373000.0 * 0.028316846592],
        }
    )
    assert_frame_equal(result.data, expected)
    assert not result.issues
    assert not result.receipts.entries


def test_camels_example_selects_documented_gauges_without_network(monkeypatch, capsys):
    def refuse_network(*args, **kwargs):
        raise AssertionError("Offline selection must not retrieve observations")

    monkeypatch.setattr(rr, "fetch", refuse_network)
    block = python_blocks(ROOT / "docs/examples/camels-us.md")[0]
    tree = ast.parse(block)
    fetch_index = next(
        index
        for index, statement in enumerate(tree.body)
        if isinstance(statement, ast.Assign)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and statement.value.func.attr == "fetch"
    )
    scope = {}
    exec(compile(ast.Module(body=tree.body[:fetch_index], type_ignores=[]), "camels-us.md", "exec"), scope)
    expected = pl.DataFrame(
        {
            "provider_id": ["usgs_nwis"] * 3,
            "station_id": ["01013500", "01022500", "01030500"],
            "product_id": ["discharge_daily_mean"] * 3,
        }
    )
    assert_frame_equal(rr.as_frame(scope["selection"]).select(expected.columns), expected)


PAGES = [
    "README.md",
    "docs/README.md",
    "docs/usage.md",
    "docs/architecture.md",
    "docs/reference.md",
    "docs/examples/camels-us.md",
]


def test_documentation_local_links_and_python_syntax():
    for name in PAGES:
        path = ROOT / name
        text = path.read_text()
        for block in python_blocks(path):
            ast.parse(block)
        for destination in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            if "://" in destination or destination.startswith("mailto:"):
                continue
            local, _, fragment = destination.partition("#")
            target = (path.parent / local).resolve() if local else path
            assert target.exists(), (name, destination)
            if fragment and target.suffix == ".md":
                headings = re.findall(r"^#{1,6} (.+)$", target.read_text(), re.MULTILINE)
                anchors = [re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-") for heading in headings]
                assert fragment in anchors, (name, destination, anchors)


def test_generated_reference_is_current():
    namespace = runpy.run_path(str(ROOT / "scripts/generate_reference.py"))
    assert (ROOT / "docs/reference.md").read_text() == namespace["render_reference"]()
