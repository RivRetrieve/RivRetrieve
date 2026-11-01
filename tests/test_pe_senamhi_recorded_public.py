"""Public replay compares retained publisher rows without exposing their values."""

import json
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.transport import TransportResponse

_SCOPE = "maintenance/observations/pe_senamhi/retrieval"


class Replay:
    def __init__(self, root, member):
        self.content = (root / (member + ".body")).read_bytes()
        self.receipt = json.loads((root / (member + ".receipt.json")).read_bytes())
        self.calls = 0

    def send(self, request):
        source = urlsplit(self.receipt["url"])
        requested = urlsplit(request.url)
        matching = (requested.scheme, requested.netloc, requested.path) == (
            source.scheme,
            source.netloc,
            source.path,
        ) and dict(request.params) == dict(parse_qsl(source.query))
        assert matching, "Public request does not match retained selector"
        self.calls += 1
        return TransportResponse(
            content=self.content,
            status_code=self.receipt["http_status"],
            retrieved_at=datetime.fromisoformat(self.receipt["finished_at"]),
            content_type=next(
                (value for name, value in self.receipt["headers"] if name.lower() == "content-type"), None
            ),
            url=self.receipt["url"],
            request_parameters=dict(parse_qsl(source.query)),
        )


def select_product(station, product):
    selected = rr.find(provider="pe_senamhi", station=station)
    identities = rr.as_frame(selected).filter(pl.col("product_id") == product)["series_id"].to_list()
    assert identities, "Recorded route must be discoverable"
    return rr.pick(selected, series_id=identities)


@pytest.mark.recorded(_SCOPE)
@pytest.mark.parametrize(
    ("member", "station", "product", "start", "end", "fields"),
    [
        (
            "anchors/daily-ramis-05",
            "47251282",
            "phisis_daily_flow",
            "2024-02-28",
            "2024-03-01T23:59:59",
            ("current", "minimum", "maximum"),
        ),
        (
            "anchors/readings-47E0D438-202610",
            "47E0D438",
            "monthly_archive_n_nivelagua",
            "2026-10-03",
            "2026-10-29T23:59:59",
            ("N_NIVELAGUA",),
        ),
        (
            "anchors/readings-200322-202610",
            "200322",
            "monthly_archive_nivel_del_rio_promedio",
            "2026-10-03",
            "2026-10-29T23:59:59",
            ("NIVEL_DEL_RIO_PROMEDIO",),
        ),
    ],
)
def test_public_retained_rows_clipping_and_cache(
    retained_evidence_root, monkeypatch, member, station, product, start, end, fields
):
    replay = Replay(retained_evidence_root / _SCOPE, member)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selected = select_product(station, product)
    kwargs = {"start": start, "end": end, "on_issue": "ignore", "receipts": True}
    result = rr.fetch(selected, cache="reuse", **kwargs)
    source = json.loads(replay.content)["data"]
    first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
    expected = []
    if product.startswith("phisis_daily_"):
        for row in source["daily"]:
            timestamp = datetime.fromisoformat(row["date"])
            if first <= timestamp <= last:
                expected.extend((field, timestamp, row[field]) for field in fields)
    else:
        for row in source["readings"]:
            timestamp = (
                datetime.strptime(row["date"] + " " + row["time"], "%d/%m/%Y %H:%M")
                if row["time"]
                else datetime.strptime(row["date"], "%Y-%m-%d")
            )
            if first <= timestamp <= last:
                expected.extend(
                    (cell["column"], timestamp, cell["value"]) for cell in row["values"] if cell["column"] in fields
                )
    assert expected, "Selected retained interval must exercise observation parsing"
    identities = {series.series_id: series.identity.published_id for series in result.source_series}
    actual = [
        (identities[identity], timestamp, value)
        for identity, timestamp, value in result.data.select("series_id", "time", "value").iter_rows()
    ]
    matching = sorted(actual, key=lambda row: row[:2]) == sorted(expected, key=lambda row: row[:2])
    assert matching, "Public observations differ from independently decoded source fields"
    assert result.data["time_zone"].unique().to_list() == ["unknown"]
    assert replay.calls == 1
    original_bytes = len(result.receipts.entries) == 1 and result.receipts.entries[0].content == replay.content
    assert original_bytes, "Public receipt did not retain original source bytes"
    reused = rr.fetch(selected, cache="reuse", **kwargs)
    unchanged = result.data.equals(reused.data)
    assert unchanged, "Cache reuse changed source observations"
    assert replay.calls == 1
    bypassed = rr.fetch(selected, cache="bypass", **kwargs)
    unchanged = result.data.equals(bypassed.data)
    assert unchanged, "Bypass changed source observations"
    assert replay.calls == 2
