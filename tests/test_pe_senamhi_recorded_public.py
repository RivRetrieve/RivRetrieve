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
        if member.startswith("access/"):
            self.status = self.receipt["status"]
            self.retrieved_at = datetime.fromisoformat(self.receipt["acquired_at"])
            self.headers = self.receipt["response_headers"].items()
        else:
            self.status = self.receipt["http_status"]
            self.retrieved_at = datetime.fromisoformat(self.receipt["finished_at"])
            self.headers = self.receipt["headers"]
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
            status_code=self.status,
            retrieved_at=self.retrieved_at,
            content_type=next((value for name, value in self.headers if name.lower() == "content-type"), None),
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
            "access/hydrogram-daily-level-2024-240103",
            "240103",
            "phisis_daily_level_above_sea_level",
            "2024-06-01",
            "2024-06-02T23:59:59",
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
            "anchors/readings-200322-202609",
            "200322",
            "monthly_archive_nivel_del_rio_promedio",
            "2026-09-03",
            "2026-09-28T23:59:59",
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
    present = bool(expected)
    assert present, "Selected retained interval must exercise observation parsing"
    identities = {series.series_id: series.identity.published_id for series in result.source_series}
    actual = [
        (identities[identity], timestamp, value)
        for identity, timestamp, value in result.data.select("series_id", "time", "value").iter_rows()
    ]
    matching = sorted(actual, key=lambda row: row[:2]) == sorted(expected, key=lambda row: row[:2])
    assert matching, "Public observations differ from independently decoded source fields"
    assert result.data["time_zone"].unique().to_list() == ["unknown"]
    level = product == "phisis_daily_level_above_sea_level"
    assert result.data["quantity"].unique().to_list() == ["discharge" if product == "phisis_daily_flow" else "stage"]
    assert result.data["source_unit"].unique().to_list() == (
        ["m.s.n.m"] if level else ["m3/s"] if product == "phisis_daily_flow" else ["m"]
    )
    assert result.data["unit"].unique().to_list() == ["m3/s" if product == "phisis_daily_flow" else "m"]
    for series in result.source_series:
        for facts in series.facts:
            assert facts.vertical_reference.value == ("above_sea_level" if level else None)
            assert facts.vertical_datum.value is None
            assert facts.frequency.value is None
            assert facts.statistic.value is None
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


class PartitionReplay:
    def __init__(self, root, members):
        self.partitions = tuple(Replay(root, member) for member in members)
        self.pending = iter(self.partitions)

    def send(self, request):
        return next(self.pending).send(request)


@pytest.mark.recorded(_SCOPE)
def test_public_retained_hourly_point_uses_owned_partition(retained_evidence_root, monkeypatch):
    replay = PartitionReplay(
        retained_evidence_root / _SCOPE,
        (
            "integration/hourly-ramis-20240829-end-second",
            "boundaries/hourly-end-second-0",
            "boundaries/hourly-end-second-1",
        ),
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    timestamp = datetime(2024, 8, 31)
    result = rr.fetch(
        select_product("47251282", "phisis_hourly_flow"),
        start=timestamp,
        end=timestamp,
        cache="bypass",
        receipts=True,
        on_issue="ignore",
    )
    # The Aug31 acquisition owns Aug30–31; Sep2's genuine prefix is not its observation.
    source = json.loads(replay.partitions[1].content)["data"]["hourly"]
    expected = [
        (datetime.fromisoformat(row["time"]), row["value"])
        for row in source
        if datetime.fromisoformat(row["time"]) == timestamp
    ]
    present = bool(expected)
    assert present, "Retained hourly point must contain a source observation"
    matching = result.data.select("time", "value").rows() == expected
    assert matching, "Public hourly point differs from its owning source partition"
    assert len(result.source_series) == 1
    assert result.source_series[0].identity.published_id == "value"
    assert result.data["time_zone"].unique().to_list() == ["unknown"]
    assert all(partition.calls == 1 for partition in replay.partitions)
    preserved = [entry.content for entry in result.receipts.entries] == [
        partition.content for partition in replay.partitions
    ]
    assert preserved, "Hourly receipts changed original partition bytes"


@pytest.mark.recorded(_SCOPE)
def test_public_retained_future_month_values_survive_clipping(retained_evidence_root, monkeypatch):
    replay = PartitionReplay(
        retained_evidence_root / _SCOPE,
        ("integration/readings-213600-202611", "anchors/readings-213600-202612"),
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    first, last = datetime(2026, 12, 1), datetime(2026, 12, 2, 23, 59, 59)
    result = rr.fetch(
        select_product("213600", "monthly_archive_nivel_del_rio_promedio"),
        start=first,
        end=last,
        cache="bypass",
        receipts=True,
        on_issue="ignore",
    )
    december = replay.partitions[1]
    captured = datetime.fromisoformat(december.receipt["finished_at"])
    assert captured.date() < first.date(), "The original must witness values dated after acquisition"
    expected = [
        (datetime.strptime(row["date"], "%Y-%m-%d"), cell["value"])
        for row in json.loads(december.content)["data"]["readings"]
        if first <= datetime.strptime(row["date"], "%Y-%m-%d") <= last
        for cell in row["values"]
        if cell["column"] == "NIVEL_DEL_RIO_PROMEDIO"
    ]
    nonnull = any(value is not None for _, value in expected)
    assert nonnull, "Retained future field must contain published values"
    matching = sorted(result.data.select("time", "value").rows(), key=lambda row: row[0]) == sorted(
        expected, key=lambda row: row[0]
    )
    assert matching, "Public future observations differ from original source values"
    assert len(result.source_series) == 1
    assert result.source_series[0].identity.published_id == "NIVEL_DEL_RIO_PROMEDIO"
    assert result.data["time_zone"].unique().to_list() == ["unknown"]
    assert all(partition.calls == 1 for partition in replay.partitions)
    preserved = [entry.content for entry in result.receipts.entries] == [
        partition.content for partition in replay.partitions
    ]
    assert preserved, "Monthly receipts changed original partition bytes"
