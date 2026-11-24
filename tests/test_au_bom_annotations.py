"""Source-independent tests for au_bom quality-code source annotations (#809)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.engine import Payload, WindowEndpoint, _make_fetch_window
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.au_bom.annotations import AU_BOM_QUALITY_SCHEMA
from rivretrieve._internal.providers.au_bom.config import config
from rivretrieve._internal.providers.au_bom.parse import parse
from rivretrieve._internal.source_annotations import AnnotationScope
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportRequest, TransportResponse
from tests.test_au_bom_retrieval import _origin

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_DISCHARGE_DAILY = ProductId("discharge_daily_mean_24hr")
_RETRIEVED_AT = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def _values_json(blocks: list[tuple[str, str, list[list[object]]]]) -> bytes:
    """Build a getTimeseriesValues payload from (ts_id, columns, rows) blocks."""
    return json.dumps(
        [{"ts_id": ts_id, "rows": str(len(rows)), "columns": columns, "data": rows} for ts_id, columns, rows in blocks]
    ).encode("utf-8")


def _payload(content: bytes, station: str = "410730") -> Payload:
    fetch_win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2026, 9, 1)), WindowEndpoint.from_datetime(datetime(2026, 9, 3))
    )
    return Payload(
        config().products[_DISCHARGE_DAILY].coordinates,
        ((station, _DISCHARGE_DAILY),),
        fetch_win,
        content,
        _origin(),
        (),
    )


def test_au_bom_quality_schema_shape() -> None:
    assert AU_BOM_QUALITY_SCHEMA.schema_id == "au_bom.quality"
    assert AU_BOM_QUALITY_SCHEMA.provider_id == "au_bom"
    assert AU_BOM_QUALITY_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert [field.name for field in AU_BOM_QUALITY_SCHEMA.fields] == ["Quality_Code", "Quality_Code_Name"]
    assert [field.dtype for field in AU_BOM_QUALITY_SCHEMA.fields] == ["Int64", "String"]
    for field in AU_BOM_QUALITY_SCHEMA.fields:
        assert field.description
        assert field.reference_url == "https://www.bom.gov.au/waterdata/"


def test_parse_values_preserves_null_code_and_null_name_independently() -> None:
    columns = "Timestamp,Value,Quality Code,Quality Code Name"
    content = _values_json(
        [
            (
                "1573010",
                columns,
                [
                    ["2026-09-01T00:00:00.000+10:00", 1.5, 10, "quality-A"],
                    ["2026-09-02T00:00:00.000+10:00", 1.6, -1, None],
                    ["2026-09-03T00:00:00.000+10:00", None, None, None],
                ],
            )
        ]
    )
    parsed = parse(_payload(content), config())
    assert parsed.issues == ()
    table = parsed.annotations.observation_tables["au_bom.quality"]
    assert table.row_count == 3
    assert table.unmeasured_count == 0
    assert table.rows["measured"].to_list() == [True, True, True]
    assert table.rows["Quality_Code"].to_list() == [10, -1, None]
    assert table.rows["Quality_Code_Name"].to_list() == ["quality-A", None, None]
    assert table.measurement_indices == (0, 1, 2)


def test_parse_values_block_without_quality_columns_gets_no_annotation_rows() -> None:
    content = _values_json(
        [
            ("1573010", "Timestamp,Value", [["2026-09-01T00:00:00.000+10:00", 1.5]]),
        ]
    )
    parsed = parse(_payload(content), config())
    assert parsed.rows.height == 1
    assert parsed.annotations.is_empty


def _assert_isolated_structure_failure(parsed, match: str) -> None:
    """A malformed values response is an isolated FAILED outcome, never a raised exception (#965)."""
    assert parsed.rows.height == 0
    assert len(parsed.outcomes) == 1
    assert parsed.outcomes[0].status is OutcomeStatus.FAILED
    assert match in parsed.outcomes[0].reason
    assert len(parsed.issues) == 1
    assert parsed.issues[0].severity == "error"
    assert parsed.issues[0].code == "source.unsupported_structure"
    assert match in parsed.issues[0].message


def test_parse_values_rejects_quality_code_without_quality_code_name() -> None:
    content = _values_json(
        [
            ("1573010", "Timestamp,Value,Quality Code", [["2026-09-01T00:00:00.000+10:00", 1.5, 10]]),
        ]
    )
    _assert_isolated_structure_failure(parse(_payload(content), config()), "Quality Code Name")


def test_parse_values_rejects_a_non_integer_quality_code() -> None:
    columns = "Timestamp,Value,Quality Code,Quality Code Name"
    content = _values_json([("1573010", columns, [["2026-09-01T00:00:00.000+10:00", 1.5, "ten", "quality-A"]])])
    _assert_isolated_structure_failure(parse(_payload(content), config()), "Quality Code")


def test_parse_values_rejects_a_non_string_quality_code_name() -> None:
    columns = "Timestamp,Value,Quality Code,Quality Code Name"
    content = _values_json([("1573010", columns, [["2026-09-01T00:00:00.000+10:00", 1.5, 10, 7]])])
    _assert_isolated_structure_failure(parse(_payload(content), config()), "Quality Code Name")


def test_parse_values_duplicate_ts_id_keeps_annotations_aligned_to_their_own_rows() -> None:
    columns = "Timestamp,Value,Quality Code,Quality Code Name"
    content = _values_json(
        [
            ("470345010", columns, [["2026-09-01T00:00:00.000+10:00", 1.887, 10, "quality-A"]]),
            ("381776010", columns, [["2026-09-01T00:00:00.000+10:00", 1.9, -1, "quality-E"]]),
        ]
    )
    parsed = parse(_payload(content, station="138020A"), config())
    table = parsed.annotations.observation_tables["au_bom.quality"]
    assert table.row_count == 2
    paired = dict(
        zip(
            parsed.rows["series_id"].to_list(),
            zip(table.rows["Quality_Code"], table.rows["Quality_Code_Name"], strict=True),
            strict=True,
        )
    )
    live_series_id = next(item.series_id for item in parsed.series if item.identity.published_id == "470345010")
    retired_series_id = next(item.series_id for item in parsed.series if item.identity.published_id == "381776010")
    assert paired[live_series_id] == (10, "quality-A")
    assert paired[retired_series_id] == (-1, "quality-E")


def test_public_fetch_annotations_round_trip_through_to_polars_and_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    station = "410730"
    list_bytes = json.dumps(
        [
            ["ts_id", "ts_name", "parametertype_name", "ts_unitsymbol", "station_no"],
            ["1598010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Level", "m", station],
        ]
    ).encode("utf-8")
    values_bytes = _values_json(
        [
            (
                "1598010",
                "Timestamp,Value,Quality Code,Quality Code Name",
                [["2026-09-01T00:00:00.000+10:00", 0.745, 10, "quality-A"]],
            )
        ]
    )

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            if params.get("request") == "getTimeseriesList":
                return TransportResponse(list_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)
            return TransportResponse(values_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)

    monkeypatch.setattr(discovery, "HttpClient", _Transport)
    selection = rr.find(provider="au_bom", station=station, quantity="stage", frequency="daily", statistic="mean")
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-01", cache="bypass")

    catalog = rr.annotations(result)
    row = catalog.filter(catalog["schema"] == "au_bom.quality")
    assert set(row["name"]) == {"Quality_Code", "Quality_Code_Name"}
    assert row["row_count"].unique().to_list() == [1]

    annotated = result.to_polars(annotations=True).select("time", "value", "Quality_Code", "Quality_Code_Name")
    assert annotated.row(0) == (datetime(2026, 9, 1), 0.745, 10, "quality-A")
