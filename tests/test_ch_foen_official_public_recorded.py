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


@pytest.mark.recorded(_SCOPE)
@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_archive_public_original_response_composition(monkeypatch, retained_evidence_root: Path):
    """Compose original archive bytes; retained fields and padded query bounds differ.

    This checks public result composition, not acquisition completeness.
    """
    root = retained_evidence_root / _SCOPE
    expected = json.loads((root / "expectations.json").read_text())["archive_public"]
    body = (root / f"{expected['name']}.body").read_bytes()
    receipt = json.loads((root / f"{expected['name']}.receipt.json").read_text())
    requests = []

    class Transport:
        def send(self, request):
            query = json.loads(request.body)["query"]
            assert request.url == receipt["url"]
            assert expected["route"] + "(" in query
            assert f'no: {{_eq: "{expected["station"]}"}}' in query
            assert f'parameterName: {{_eq: "{expected["parameter"]}"}}' in query
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
    selection = rr.find(
        provider="ch_foen",
        station=expected["station"],
        quantity=expected["quantity"],
        frequency=expected["frequency"],
        statistic=expected["statistic"],
    )
    result = rr.fetch(
        selection,
        start=expected["public_start"],
        end=expected["public_end"],
        cache="bypass",
        receipts=True,
        on_issue="raise",
    )
    expected_data = pl.DataFrame(
        [{**row, "time": datetime.fromisoformat(row["time"])} for row in expected["public_rows"]],
        schema={"time": pl.Datetime, "source_unit": pl.String, "unit": pl.String, "value": pl.Float64},
    )
    assert expected_data.height > 0
    pt.assert_frame_equal(result.data.select(expected_data.columns).sort("time"), expected_data.sort("time"))
    assert len(requests) == 1
    assert result.data["product_id"].unique().to_list() == [expected["product_id"]]
    original_rows = json.loads(body)["data"]["water"]["observations"][expected["route"]]
    original_variants = {row["tsName"] for row in original_rows}
    returned_ids = set(result.data["series_id"])
    assert {item.variant for item in result.source_series if item.series_id in returned_ids} == original_variants
    assert result.receipts.entries[0].content == body
    assert result.provenance.endpoints == (receipt["url"],)


@pytest.mark.recorded(_SCOPE)
@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_archive_public_exact_requests_preserve_rows_and_cache(monkeypatch, retained_evidence_root: Path, tmp_path):
    from rivretrieve._internal.source_series import stable_id

    root = retained_evidence_root / _SCOPE
    cases = json.loads((root / "expectations.json").read_text())["archive_public_cases"]
    assert cases
    cache_checked = False
    for expected in cases:
        body = (root / f"{expected['name']}.body").read_bytes()
        receipt = json.loads((root / f"{expected['name']}.receipt.json").read_text())
        requests = []

        class Transport:
            def send(self, request, *, requests=requests, receipt=receipt, expected=expected, body=body):
                assert not requests, "An already covered request must not contact the source again"
                assert request.url == receipt["url"]
                assert request.method.value == receipt["method"]
                assert json.loads(request.body) == {"query": receipt["query"]}
                assert receipt["query"] == expected["query"]
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
        monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / expected["name"]))
        selection = rr.find(
            provider="ch_foen",
            station=expected["station"],
            quantity=expected["quantity"],
            frequency=expected["frequency"],
            statistic=expected["statistic"],
        )

        result = rr.fetch(
            selection,
            start=expected["public_start"],
            end=expected["public_end"],
            cache="reuse",
            receipts=True,
            on_issue="raise",
        )
        rows = [
            {
                "station_id": expected["station"],
                "product_id": expected["product_id"],
                "series_id": stable_id(
                    "ch_foen", expected["station"], expected["route"], expected["parameter"], row["variant"]
                ),
                **{key: value for key, value in row.items() if key != "variant"},
                "time": datetime.fromisoformat(row["time"]),
            }
            for row in expected["public_rows"]
        ]
        expected_data = pl.DataFrame(
            rows,
            schema={
                "station_id": pl.String,
                "product_id": pl.String,
                "series_id": pl.String,
                "time": pl.Datetime,
                "source_unit": pl.String,
                "unit": pl.String,
                "value": pl.Float64,
            },
        )
        assert expected_data.height > 0
        columns = expected_data.columns
        pt.assert_frame_equal(result.data.select(columns).sort(columns), expected_data.sort(columns))
        variants = {row["variant"] for row in expected["public_rows"]}
        returned_ids = set(result.data["series_id"])
        definitions = [item for item in result.source_series if item.series_id in returned_ids]
        assert {item.variant for item in definitions} == variants
        for definition in definitions:
            assert definition.station_id == expected["station"]
            assert definition.product_id == expected["product_id"]
            assert definition.identity.namespace == f"foen.{expected['route']}.{expected['parameter']}"
            assert definition.identity.published_id == definition.variant
            assert definition.series_id == stable_id(
                "ch_foen", expected["station"], expected["route"], expected["parameter"], definition.variant
            )
        assert len(requests) == 1
        assert len(result.receipts.entries) == 1
        assert result.receipts.entries[0].content == body
        if not cache_checked and len(variants) > 1:
            cached = rr.fetch(
                rr.pick(selection, variant=sorted(variants)),
                start=expected["public_start"],
                end=expected["public_end"],
                cache="reuse",
                on_issue="raise",
            )
            pt.assert_frame_equal(cached.data.sort(columns), result.data.sort(columns))
            assert cached.provenance.retrieved_at == result.provenance.retrieved_at
            assert len(requests) == 1
            cache_checked = True
    assert cache_checked, "Retained cases must include a parallel-variant cache witness"
