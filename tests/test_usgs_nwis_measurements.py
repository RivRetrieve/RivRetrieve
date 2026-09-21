"""Authored measurement-representability controls through actual USGS fetch/cache.

Bodies are derivatives of a retained DV recording, not new publisher captures.
The replay HTTP envelope is authored. Original recording bytes are unchanged.
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

_MISSING = object()
_RAW_NUMBER = "__authored_raw_json_number__"


@pytest.fixture
def selection():
    return rr.find(provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean")


@pytest.fixture(scope="module")
def recording():
    return read_recording(
        Path(__file__).with_name("test_data") / "usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"
    )


def _install(monkeypatch, tmp_path, recording, value, *, numeric_token=None, sibling=True):
    document = json.loads(recording.content)
    blocks = document["value"]["timeSeries"][0]["values"]
    healthy = deepcopy(blocks[0])
    observation = {"dateTime": "2023-01-01T00:00:00.000"}
    if value is not _MISSING:
        observation["value"] = _RAW_NUMBER if numeric_token else value
    blocks[0]["value"] = [observation]
    if sibling:
        healthy["method"][0]["methodID"] = 0
        healthy["value"] = [{"dateTime": "2023-01-01T00:00:00.000", "value": "42"}]
        blocks.append(healthy)
    content = json.dumps(document).encode()
    if numeric_token:
        encoded = json.dumps(_RAW_NUMBER).encode()
        assert content.count(encoded) == 1
        content = content.replace(encoded, numeric_token.encode())
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


@pytest.mark.parametrize(
    "value,numeric_token",
    [
        pytest.param(10**400, None, id="huge-positive-int"),
        pytest.param(-(10**400), None, id="huge-negative-int"),
        pytest.param(None, "1e400", id="standard-json-positive-overflow"),
        pytest.param(None, "-1e400", id="standard-json-negative-overflow"),
        pytest.param(float("inf"), None, id="nonstandard-json-positive-infinity"),
        pytest.param(float("-inf"), None, id="nonstandard-json-negative-infinity"),
        pytest.param(float("nan"), None, id="nonstandard-json-nan"),
        pytest.param("1e400", None, id="string-positive-overflow"),
        pytest.param("-1e400", None, id="string-negative-overflow"),
        pytest.param("NaN", None, id="string-nan"),
        pytest.param("Infinity", None, id="string-positive-infinity"),
        pytest.param("-Infinity", None, id="string-negative-infinity"),
        pytest.param("not-a-number", None, id="malformed-string"),
        pytest.param(True, None, id="true"),
        pytest.param(False, None, id="false"),
        pytest.param({}, None, id="object"),
        pytest.param([], None, id="list"),
        pytest.param(_MISSING, None, id="missing"),
    ],
)
@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_unrepresentable_measurement_is_isolated_and_cannot_authorize_coverage(
    monkeypatch, tmp_path, recording, selection, value, numeric_token, policy
):
    content, calls = _install(monkeypatch, tmp_path, recording, value, numeric_token=numeric_token)
    if numeric_token:
        assert numeric_token.encode() in content
    context = (
        pytest.raises(IssuePolicyError)
        if policy == "raise"
        else pytest.warns(RuntimeWarning)
        if policy == "warn"
        else nullcontext()
    )
    with context as caught:
        result = _fetch(selection, policy)
    if policy == "raise":
        assert any("observation" in issue.message.lower() for issue in caught.value.issues)
    else:
        assert result.data.height == 1
        assert result.data["value"][0] == pytest.approx(42 * 0.028316846592)
        assert result.receipts.entries[0].content == content
        failed = [o for o in result.outcomes if o.status == "unsupported"]
        assert len(failed) == 1 and failed[0].series_id is not None and failed[0].facts_ids
    again = _fetch(selection, "ignore")
    assert len(calls) == 2
    assert again.data.height == 1
    assert any(receipt.content == content for receipt in again.receipts.entries)
    failed = [o for o in again.outcomes if o.status == "unsupported"]
    assert failed
    healthy = next(s.series_id for s in again.source_series if s.identity.published_id == "0")
    assert again.data["series_id"].to_list() == [healthy]
    manifest_paths = list((tmp_path / "cache").rglob("manifest.json"))
    assert len(manifest_paths) == 1
    manifest = json.loads(manifest_paths[0].read_text())
    assert {coverage["series_id"] for coverage in manifest["coverage"]} == {healthy}


@pytest.mark.parametrize(
    "value,expected",
    [
        pytest.param(0, 0.0, id="zero"),
        pytest.param(-0.0, -0.0, id="signed-zero"),
        pytest.param(42, 42.0, id="finite-int"),
        pytest.param(1.5, 1.5, id="finite-float"),
        pytest.param("1.5", 1.5, id="finite-string"),
        pytest.param(1.7e308, 1.7e308, id="large-finite-float"),
        pytest.param(None, None, id="explicit-null"),
        pytest.param(-999999, None, id="numeric-declared-sentinel"),
        pytest.param("-999999", None, id="string-declared-sentinel"),
    ],
)
@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_representable_measurement_retains_numeric_or_null_state_and_successful_coverage(
    monkeypatch, tmp_path, recording, selection, value, expected, policy
):
    content, calls = _install(monkeypatch, tmp_path, recording, value, sibling=False)
    result = _fetch(selection, policy)
    assert result.data.height == 1
    if expected is None:
        assert result.data["value"].null_count() == 1
    else:
        assert result.data["value"][0] == pytest.approx(expected * 0.028316846592)
    assert result.outcomes[0].status == "success"
    assert result.receipts.entries[0].content == content
    cached = _fetch(selection, policy)
    assert len(calls) == 1
    assert cached.data["value"].to_list() == result.data["value"].to_list()
