"""Public recent retrieval replays one unchanged, request-matched source response."""

import json
from datetime import datetime
from pathlib import Path

import polars as pl
import polars.testing as pt
import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.transport import TransportResponse

_SCOPE = "maintenance/observations/ch_foen/official-retrieval"


@pytest.mark.recorded(_SCOPE)
@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_recent_public_retrieval_preserves_original_response(monkeypatch, retained_evidence_root: Path):
    root = retained_evidence_root / _SCOPE
    expected = json.loads((root / "expectations.json").read_text())["recent_public"]
    body = (root / f"{expected['name']}.body").read_bytes()
    receipt = json.loads((root / f"{expected['name']}.receipt.json").read_text())
    requests = []

    class Transport:
        def send(self, request):
            assert request.url == receipt["url"]
            assert request.method.value == receipt["method"]
            assert json.loads(request.body) == {"query": receipt["query"]}
            assert not any(key.lower() == "authorization" for key in request.headers)
            requests.append(request)
            return TransportResponse(
                body,
                receipt["status"],
                datetime.fromisoformat(receipt["acquired"]),
                "application/json",
                request.url,
                {},
            )

    monkeypatch.setattr(discovery, "HttpClient", Transport)
    candidates = rr.find(provider="ch_foen", station=expected["station"], quantity=expected["quantity"])
    recent = rr.series(candidates).filter(pl.col("product_id") == expected["product_id"])
    assert recent.height == 1
    selection = rr.find(provider="ch_foen", station=expected["station"], series_id=recent["series_id"][0])

    def fetch(cache):
        return rr.fetch(
            selection,
            start=expected["public_start"],
            end=expected["public_end"],
            cache=cache,
            receipts=True,
            on_issue="raise",
        )

    first = fetch("bypass")
    columns = ["time", "source_unit", "unit", "value"]
    expected_data = pl.DataFrame(
        [{**row, "time": datetime.fromisoformat(row["time"])} for row in expected["public_rows"]],
        schema={"time": pl.Datetime, "source_unit": pl.String, "unit": pl.String, "value": pl.Float64},
    )
    assert expected_data.height > 0
    pt.assert_frame_equal(first.data.select(columns).sort("time"), expected_data.sort("time"))
    assert first.data["series_id"].unique().to_list() == recent["series_id"].to_list()
    assert first.receipts.entries[0].content == body
    assert first.provenance.endpoints == (receipt["url"],)
    assert len(requests) == 1
