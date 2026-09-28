"""Exact production-query replay through public composition and real HTTP transport.

Recorded from Existenz on 2026-09-20 using its published shared read-only access.
The recording retains acquisition time, source URL, exact five-field padded
query, response bytes and credential header names, but no credential values.
"""

import csv
import io
import json
from datetime import datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest
import requests

import rivretrieve as rr
from rivretrieve._internal.observations import ReceiptAuthorship
from rivretrieve._internal.recordings import read_recording

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

DATA = Path(__file__).parent / "test_data"
ARCHIVE = read_recording(DATA / "ch_foen_2018_flux_january2024_full.recording.json")
REST = json.loads((DATA / "ch_foen_2018_historical_rest.json").read_text())


def expected_flow(*, clipped=True):
    # Independently decode the recorded source table.
    lines = ARCHIVE.content.decode().splitlines()
    header = next(csv.reader([lines[0]]))
    rows = []
    for values in csv.reader(io.StringIO(ARCHIVE.content.decode())):
        if not values or values == header:
            continue
        record = dict(zip(header, values, strict=True))
        if record["_field"] != "flow":
            continue
        label = datetime.fromisoformat(record["_time"]).replace(tzinfo=None)
        if clipped and not datetime(2024, 1, 1) <= label <= datetime(2024, 1, 31, 23, 59, 59, 999999):
            continue
        rows.append({"time": label, "value": float(record["_value"]), "source_unit": "m3/s"})
    return pl.DataFrame(rows, schema={"time": pl.Datetime("us"), "value": pl.Float64, "source_unit": pl.String}).sort(
        "time"
    )


def test_public_historical_archive_without_personal_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    routes = []

    def response(content, status, content_type):
        result = requests.Response()
        result.status_code = status
        result._content = content
        result.headers["Content-Type"] = content_type
        return result

    def get(url, **kwargs):
        assert url == REST["url"]
        assert kwargs["params"] == REST["params"]
        assert "Authorization" not in kwargs["headers"]
        routes.append("REST GET")
        return response(REST["body"].encode(), REST["status"], REST["content_type"])

    def post(url, **kwargs):
        assert url == ARCHIVE.request.url
        assert kwargs["params"] == dict(ARCHIVE.request.parameters)
        assert kwargs["data"] == ARCHIVE.request.body
        assert kwargs["allow_redirects"] is False
        has_token_auth = kwargs["headers"].get("Authorization", "").startswith("Token ")
        assert has_token_auth, "archive request lacks token authentication"
        routes.append("archive POST")
        return response(ARCHIVE.content, ARCHIVE.status_code, ARCHIVE.content_type)

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", post)
    selection = rr.find(provider="ch_foen", station="2018", quantity="discharge")
    result = rr.fetch(selection, start="2024-01-01", end="2024-01-31", receipts=True, on_issue="ignore")
    assert routes == ["archive POST"], f"Historical public retrieval selected {routes}"
    pl_testing.assert_frame_equal(result.data.select("time", "value", "source_unit").sort("time"), expected_flow())
    assert result.data.height == 4402
    assert result.data["time"].min() == datetime(2024, 1, 1)
    assert result.data["time"].max() == datetime(2024, 1, 31, 23, 50)
    assert result.data["unit"].unique().to_list() == ["m3/s"]
    assert result.data["time_zone"].unique().to_list() == ["+00:00"]
    assert any("flow_ls" in issue.message and "unresolved" in issue.message for issue in result.issues)
    assert len(result.receipts.entries) == 1
    assert result.receipts.entries[0].content == ARCHIVE.content
    assert result.receipts.entries[0].authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD
    assert result.provenance.calls_made[0]["request_parameters"] == {"org": "api.existenz.ch"}
