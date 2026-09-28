"""CHMI source member and daily-label failures retain independently named series."""

import json
from contextlib import nullcontext
from dataclasses import replace

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.engine import RenderedWindow
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.providers.cz_chmi.config import config
from rivretrieve._internal.providers.cz_chmi.fetch import fetch
from rivretrieve._internal.providers.cz_chmi.parse import parse
from rivretrieve._internal.recordings import ReplayTransport
from tests.test_cz_chmi_observations import _DQ, _HQ, _PRODUCTS, _STATION, _window
from tests.test_source_field_boundaries import AlteredResponseTransport


def _payload():
    return fetch(
        (_STATION,),
        _PRODUCTS[:3],
        {p: (RenderedWindow("2023", None),) for p in _PRODUCTS[:3]},
        _window(),
        config(),
        ReplayTransport([_DQ]),
    ).value[0]


@pytest.mark.parametrize(
    "member",
    [
        None,
        [],
        "HD",
        1,
        False,
        {},
        {"tsConID": None},
        {"tsConID": []},
        {"tsConID": {}},
        {"tsConID": 1},
        {"tsConID": False},
    ],
)
def test_unassignable_member_retains_named_daily_siblings(member):
    payload = _payload()
    expected = parse(payload, config())
    document = json.loads(payload.content)
    document["tsList"][0] = member
    result = parse(replace(payload, content=json.dumps(document).encode()), config())
    assert_frame_equal(result.rows, expected.rows.filter(pl.col("product_id") != "stage_daily_mean"))
    failed = [item for item in result.outcomes if item.status == "unsupported"]
    assert len(failed) == 1 and failed[0].product_id == "stage_daily_mean"
    assert "identity" in failed[0].reason


@pytest.mark.parametrize(
    "label",
    [
        "2023-01-01T12:00:00Z",
        "2023-01-01T00:01:00Z",
        "2023-01-01T00:00:01Z",
        "2023-01-01T00:00:00.000001Z",
        "2023-01-01T00:00:00+01:00Z",
        "2023-01-01T00:00:00+00:00Z",
        "2023-01-01T00:00:00+01:00",
        "2023-01-01T00:00:00",
        None,
        [],
        {},
        1,
    ],
)
def test_invalid_daily_label_retains_named_siblings(label):
    payload = _payload()
    expected = parse(payload, config())
    document = json.loads(payload.content)
    document["tsList"][0]["tsData"]["data"]["values"][0][0] = label
    result = parse(replace(payload, content=json.dumps(document).encode()), config())
    assert_frame_equal(result.rows, expected.rows.filter(pl.col("product_id") != "stage_daily_mean"))
    failed = [item for item in result.outcomes if item.status == "unsupported"]
    assert len(failed) == 1 and failed[0].product_id == "stage_daily_mean"
    assert "timestamp" in failed[0].reason


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
@pytest.mark.parametrize("defect", ["member", "noon"])
@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_public_malformed_daily_source_keeps_siblings_and_no_failed_coverage(monkeypatch, tmp_path, policy, defect):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    selection = rr.find(provider="cz_chmi", station=_STATION, frequency="daily")
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport([_DQ]))
    expected = rr.fetch(selection, start="2023-06-01", end="2023-06-02", cache="bypass", on_issue="ignore")
    mutated = []

    def alter(request, body):
        document = json.loads(body)
        if defect == "member":
            document["tsList"][0] = None
        else:
            document["tsList"][0]["tsData"]["data"]["values"][0][0] = "2023-01-01T12:00:00Z"
        content = json.dumps(document).encode()
        mutated.append(content)
        return content

    monkeypatch.setattr(discovery, "HttpClient", lambda: AlteredResponseTransport([_DQ], alter))
    context = (
        pytest.raises(IssuePolicyError)
        if policy == "raise"
        else pytest.warns(RuntimeWarning)
        if policy == "warn"
        else nullcontext()
    )
    with context:
        result = rr.fetch(
            selection, start="2023-06-01", end="2023-06-02", cache="refresh", receipts=True, on_issue=policy
        )
    if policy == "raise":
        return
    assert_frame_equal(result.data, expected.data.filter(pl.col("product_id") != "stage_daily_mean"))
    failed = [item for item in result.outcomes if item.status == "unsupported"]
    assert len(failed) == 1 and failed[0].product_id == "stage_daily_mean"
    assert any(issue.code == "unsupported_source_structure" for issue in result.issues)
    assert any(receipt.content == mutated[0] for receipt in result.receipts.entries)
    manifest = json.loads((tmp_path / "cz_chmi/store/manifest.json").read_text())
    assert all(item["series_id"] != failed[0].series_id for item in manifest["coverage"])


def test_recorded_hourly_nonmidnight_labels_remain_valid():
    products = _PRODUCTS[3:]
    payload = fetch(
        (_STATION,),
        products,
        {p: (RenderedWindow("2023", None),) for p in products},
        _window(),
        config(),
        ReplayTransport([_HQ]),
    ).value[0]
    result = parse(payload, config())
    assert result.rows.height == 17520
    assert result.rows.filter(pl.col("time").dt.hour() == 12).height == 730
    assert all(item.status == "success" for item in result.outcomes)
