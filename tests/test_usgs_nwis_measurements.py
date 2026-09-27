"""Authored measurement-representability controls through actual USGS fetch/cache.

Bodies are derivatives of a retained modern daily recording, not new publisher captures.
The replay HTTP envelope is authored. Original recording bytes are unchanged.
"""

import json
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime

import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.usgs_nwis.config import config
from rivretrieve._internal.providers.usgs_nwis.parse import parse
from tests.usgs_modern_recordings import ModernReplay, body

_MISSING = object()
_RAW_NUMBER = "__authored_raw_json_number__"


@pytest.fixture
def selection():
    return rr.find(provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean")


@pytest.fixture(scope="module")
def recording():
    return body("daily-07374000-docs-2023")


def _content(recording, value, *, numeric_token=None, sibling=True):
    document = json.loads(recording)
    affected = next(item for item in document["features"] if item["properties"]["time"] == "2023-01-01")
    properties = affected["properties"]
    properties.pop("value")
    if value is not _MISSING:
        properties["value"] = _RAW_NUMBER if numeric_token else value
    document["features"] = [affected]
    if sibling:
        healthy = {
            **affected,
            "id": "authored-independent-record",
            "properties": {
                **properties,
                "time_series_id": "authored-independent-series",
                "value": "42",
            },
        }
        document["features"].append(healthy)
    document["numberReturned"] = len(document["features"])
    content = json.dumps(document).encode()
    if numeric_token:
        encoded = json.dumps(_RAW_NUMBER).encode()
        assert content.count(encoded) == 1
        content = content.replace(encoded, numeric_token.encode())
    return content


def _install(monkeypatch, tmp_path, recording, value, *, numeric_token=None, sibling=True):
    content = _content(recording, value, numeric_token=numeric_token, sibling=sibling)
    calls = []

    class AuthoredTransport(ModernReplay):
        def __init__(self):
            super().__init__("daily-07374000-docs-2023")

        def send(self, request):
            response = super().send(request)
            calls.append(request)
            return replace(response, content=content)

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", AuthoredTransport)
    return content, calls


def _fetch(selection, policy):
    return rr.fetch(selection, start="2023-01-01", end="2023-01-01", cache="reuse", receipts=True, on_issue=policy)


def _parsed_content(content):
    product = ProductId("discharge_daily_mean")
    coordinates = replace(config().products[product].coordinates.value, monitoring_location_id="USGS-07374000")
    return parse(
        Payload(
            SourceCoordinates(coordinates),
            (("07374000", product),),
            _make_fetch_window(
                WindowEndpoint.from_datetime(datetime(2022, 12, 30)),
                WindowEndpoint.from_datetime(datetime(2023, 1, 3)),
            ),
            content,
            SourceCallOrigin(
                "https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily/items",
                {},
                200,
                UnknownOriginFact(),
                "application/geo+json",
                UnknownOriginFact(),
                UnknownOriginFact(),
            ),
            (),
        ),
        config(),
    )


INVALID_VALUES = [
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
    pytest.param(1.5, None, id="numeric-not-decimal-string"),
]


@pytest.mark.parametrize("value,numeric_token", INVALID_VALUES)
def test_invalid_measurement_parser_preserves_identified_sibling(recording, value, numeric_token):
    content = _content(recording, value, numeric_token=numeric_token)
    if numeric_token:
        assert numeric_token.encode() in content
    result = _parsed_content(content)
    healthy = next(s.series_id for s in result.series if s.identity.published_id == "authored-independent-series")
    assert result.rows["series_id"].to_list() == [healthy]
    assert result.rows["value"].to_list() == [42.0]
    failed = [outcome for outcome in result.outcomes if outcome.status == "unsupported"]
    assert len(failed) == 1
    assert failed[0].series_id and failed[0].facts_ids and failed[0].reason
    assert failed[0].series_id != healthy
    assert any(outcome.status == "success" and outcome.series_id == healthy for outcome in result.outcomes)
    assert result.issues


# Exercise policy/cache composition for absent, wrong-type and overflow states.
# Every original source representation remains in the parser matrix above.
@pytest.mark.parametrize(
    "value,numeric_token",
    [
        pytest.param(_MISSING, None, id="missing"),
        pytest.param(True, None, id="boolean"),
        pytest.param(None, "1e400", id="overflow"),
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
    healthy = next(s.series_id for s in again.source_series if s.identity.published_id == "authored-independent-series")
    assert again.data["series_id"].to_list() == [healthy]
    manifest_paths = list((tmp_path / "cache").rglob("manifest.json"))
    assert len(manifest_paths) == 1
    manifest = json.loads(manifest_paths[0].read_text())
    assert {coverage["series_id"] for coverage in manifest["coverage"]} == {healthy}


@pytest.mark.parametrize(
    "value,expected",
    [
        pytest.param("0", 0.0, id="zero"),
        pytest.param("-0.0", -0.0, id="signed-zero"),
        pytest.param("42", 42.0, id="finite-int"),
        pytest.param("1.5", 1.5, id="finite-string"),
        pytest.param("1.7e308", 1.7e308, id="large-finite-float"),
        pytest.param(None, None, id="explicit-null"),
        pytest.param("-999999", -999999.0, id="negative-number-not-sentinel"),
        pytest.param("-1", -1.0, id="negative-one-not-sentinel"),
    ],
)
def test_representable_measurement_retains_numeric_or_null_state_and_successful_coverage(
    monkeypatch, tmp_path, recording, selection, value, expected
):
    content, calls = _install(monkeypatch, tmp_path, recording, value, sibling=False)
    result = _fetch(selection, "raise")
    assert result.data.height == 1
    if expected is None:
        assert result.data["value"].null_count() == 1
    else:
        assert result.data["value"][0] == pytest.approx(expected * 0.028316846592)
    assert result.outcomes[0].status == "success"
    assert result.receipts.entries[0].content == content
    restored = rr.from_bundle(rr.to_bundle(result))
    assert_frame_equal(restored.data, result.data)
    cached = _fetch(selection, "raise")
    assert len(calls) == 1
    assert_frame_equal(cached.data, result.data)
