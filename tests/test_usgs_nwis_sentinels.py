"""Authored WaterML sentinel controls replay retained DV bytes through real fetch/cache.

These derived bodies exercise source-boundary validation. They are not new source
captures. Their replay transport envelope is authored from the retained recording.
"""

import json
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.recordings import read_recording
from rivretrieve._internal.transport import TransportResponse

_ABSENT = object()
_DATA = Path(__file__).with_name("test_data")


@pytest.fixture
def selection():
    return rr.find(provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean")


@pytest.fixture(scope="module")
def recording():
    return read_recording(_DATA / "usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json")


def _install(monkeypatch, tmp_path, recording, sentinel, *, empty=False, value="1", valid_sibling=True):
    document = json.loads(recording.content)
    variables = document["value"]["timeSeries"]
    affected = variables[0]
    valid = deepcopy(affected)
    if sentinel is _ABSENT:
        affected["variable"].pop("noDataValue", None)
    else:
        affected["variable"]["noDataValue"] = sentinel
    if valid_sibling:
        affected["values"].append(deepcopy(affected["values"][0]))
        affected["values"][1]["method"][0]["methodID"] = 1
    for block in affected["values"]:
        block["value"] = [] if empty else [{"dateTime": "2023-01-01T00:00:00.000", "value": value}]
    if valid_sibling:
        valid["values"][0]["method"][0]["methodID"] = 0
        valid["values"][0]["value"] = [{"dateTime": "2023-01-01T00:00:00.000", "value": "42"}]
        variables.append(valid)
    content = json.dumps(document).encode()
    calls = []

    class AuthoredTransport:
        def send(self, request):
            assert request.url == recording.request.url
            assert dict(request.params) == dict(recording.request.parameters)
            calls.append(request)
            return TransportResponse(
                content, 200, recording.retrieved_at, recording.content_type, request.url, request.params
            )

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", AuthoredTransport)
    return content, calls


def _fetch(selection, policy):
    return rr.fetch(selection, start="2023-01-01", end="2023-01-01", cache="reuse", receipts=True, on_issue=policy)


_INVALID = [
    pytest.param(True, id="true"),
    pytest.param(False, id="false"),
    pytest.param("-999999", id="numeric-string"),
    pytest.param("invalid", id="string"),
    pytest.param({}, id="object"),
    pytest.param([], id="list"),
    pytest.param(None, id="null"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="positive-infinity"),
    pytest.param(float("-inf"), id="negative-infinity"),
    pytest.param(10**400, id="unrepresentable-integer"),
]


@pytest.mark.parametrize("sentinel", _INVALID)
@pytest.mark.parametrize("empty", [False, True], ids=["rows", "empty-blocks"])
@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_invalid_declared_sentinel_is_unsupported_before_rows_and_never_cached_as_success(
    monkeypatch, tmp_path, recording, selection, sentinel, empty, policy
):
    # False previously masked legitimate zero; True previously masked legitimate one.
    value = "0" if sentinel is False else "1"
    content, calls = _install(monkeypatch, tmp_path, recording, sentinel, empty=empty, value=value)
    context = (
        pytest.raises(IssuePolicyError)
        if policy == "raise"
        else pytest.warns(RuntimeWarning)
        if policy == "warn"
        else nullcontext()
    )
    with context as caught:
        first = _fetch(selection, policy)
    if policy == "raise":
        assert any("noDataValue" in issue.message for issue in caught.value.issues)
    else:
        assert first.data.height == 1
        assert first.data["value"][0] == pytest.approx(42 * 0.028316846592)
        assert first.receipts.entries[0].content == content
    again = _fetch(selection, "ignore")
    assert len(calls) == 2, "Malformed sentinel cannot authorize positive or empty coverage"
    assert again.data.height == 1
    unsupported = [outcome for outcome in again.outcomes if outcome.status == "unsupported"]
    assert len({outcome.series_id for outcome in unsupported}) == 2
    assert all(outcome.facts_ids and "noDataValue" in outcome.reason for outcome in unsupported)
    healthy = next(series.series_id for series in again.source_series if series.identity.published_id == "0")
    assert again.data["series_id"].to_list() == [healthy]
    # Inspect the real accumulated manifest: only the independent valid variable has coverage.
    manifests = list((tmp_path / "cache").rglob("manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text())
    assert {coverage["series_id"] for coverage in manifest["coverage"]} == {healthy}


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
@pytest.mark.parametrize(
    "sentinel,value,expected",
    [
        pytest.param(_ABSENT, "-999999", -999999 * 0.028316846592, id="absent-sentinel-finite-number"),
        pytest.param(_ABSENT, None, None, id="absent-sentinel-explicit-null"),
        pytest.param(-999999, "-999999", None, id="declared-integer-sentinel"),
        pytest.param(-999999.0, "-999999", None, id="declared-float-sentinel"),
        pytest.param(0, "0", None, id="declared-zero-sentinel"),
        pytest.param(-999999, None, None, id="explicit-null-with-sentinel"),
    ],
)
def test_absent_or_valid_sentinel_preserves_numbers_and_explicit_null_coverage(
    monkeypatch, tmp_path, recording, selection, sentinel, value, expected, policy
):
    content, calls = _install(monkeypatch, tmp_path, recording, sentinel, value=value, valid_sibling=False)
    first = _fetch(selection, policy)
    assert first.data.height == 1
    if expected is None:
        assert first.data["value"].null_count() == 1
    else:
        assert first.data["value"][0] == pytest.approx(expected)
    assert first.outcomes[0].status == "success"
    assert first.receipts.entries[0].content == content
    cached = _fetch(selection, policy)
    assert len(calls) == 1
    assert cached.data["value"].to_list() == first.data["value"].to_list()
