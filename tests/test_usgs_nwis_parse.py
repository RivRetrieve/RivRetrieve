from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.engine import (
    Payload,
    ProviderConfig,
    RowsSchema,
    SourceCoordinates,
    WindowEndpoint,
    ZoneValue,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.usgs_nwis.parse import parse

FIXTURE_PATH = Path("tests/test_data/usgs_nwis_07374000_dv_00060_2023-01-01.json")


def _payload(
    content: object,
    station_products: tuple[tuple[str, ProductId], ...] = (("payload-station", ProductId("payload-product")),),
) -> Payload:
    return Payload(
        SourceCoordinates(object()),
        station_products,
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2023, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2023, 1, 10, 23, 59, 59, 999999)),
        ),
        content,
    )


def _provider_config() -> ProviderConfig:
    return ProviderConfig(zone=ZoneValue("unknown"), products={})


def _content(
    entries: list[dict[str, object]],
    *,
    no_data_value: object = -999999.0,
    station_id: str = "json-station",
    product_id: str = "00060",
) -> bytes:
    return json.dumps(
        {
            "value": {
                "timeSeries": [
                    {
                        "sourceInfo": {"siteCode": [{"value": station_id}]},
                        "variable": {
                            "variableCode": [{"value": product_id}],
                            "noDataValue": no_data_value,
                        },
                        "values": [{"value": entries}],
                    }
                ]
            }
        }
    ).encode()


def test_parse_fixture_emits_exact_native_rows_from_payload_identity() -> None:
    result = parse(_payload(FIXTURE_PATH.read_bytes()), _provider_config())
    expected = pl.DataFrame(
        {
            "station_id": ["payload-station"] * 10,
            "product_id": ["payload-product"] * 10,
            "time": [datetime(2023, 1, day, 0, 0) for day in range(1, 11)],
            "value": [
                373000.0,
                373000.0,
                373000.0,
                377000.0,
                382000.0,
                386000.0,
                390000.0,
                393000.0,
                395000.0,
                397000.0,
            ],
            "time_zone": ["-06:00"] * 10,
        },
        schema=RowsSchema.polars_schema,
    )

    pl_testing.assert_frame_equal(result.value, expected)
    assert result.issues == ()
    assert validate_catalogue(result.value, RowsSchema, on_issue="raise") == []


def test_parse_fixture_preserves_wall_clock_offset_and_ignores_cst_trap() -> None:
    fixture = json.loads(FIXTURE_PATH.read_bytes())
    series = fixture["value"]["timeSeries"][0]
    source_entries = series["values"][0]["value"]
    assert series["sourceInfo"]["timeZoneInfo"]["defaultTimeZone"]["zoneAbbreviation"] == "CST"
    assert source_entries[4]["dateTime"] == "2023-01-05T00:00:00.000-06:00"

    result = parse(_payload(FIXTURE_PATH.read_bytes()), _provider_config())

    assert result.value["time"][4] == datetime(2023, 1, 5, 0, 0)
    assert result.value["time_zone"][4] == "-06:00"
    assert result.value["value"][4] == 382000.0
    assert result.value["time"].dtype == pl.Datetime()
    assert "CST" not in result.value["time_zone"].to_list()
    assert datetime(2023, 1, 5, 6, 0) not in result.value["time"].to_list()


def test_parse_uses_payload_pair_not_json_station_or_variable_identity() -> None:
    content = _content(
        [{"value": "7.5", "dateTime": "2023-01-01T00:00:00-06:00"}],
        station_id="json-station",
        product_id="00060",
    )
    payload = _payload(
        content,
        (("tagged-station", ProductId("tagged-product")),),
    )

    result = parse(payload, _provider_config())

    assert result.value["station_id"].to_list() == ["tagged-station"]
    assert result.value["product_id"].to_list() == ["tagged-product"]


@pytest.mark.parametrize(
    "station_products",
    [
        (),
        (
            ("station-1", ProductId("product-1")),
            ("station-2", ProductId("product-2")),
        ),
    ],
)
def test_parse_requires_exactly_one_station_product_pair(
    station_products: tuple[tuple[str, ProductId], ...],
) -> None:
    with pytest.raises(FatalContractError):
        parse(
            _payload(FIXTURE_PATH.read_bytes(), station_products),
            _provider_config(),
        )


def test_parse_normalizes_z_to_representable_positive_zero_offset() -> None:
    content = _content(
        [
            {
                "value": "1.5",
                "dateTime": "2023-01-01T00:00:00Z",
                "qualifiers": ["A"],
            }
        ]
    )

    result = parse(_payload(content), _provider_config())

    assert result.value["time"][0] == datetime(2023, 1, 1, 0, 0)
    assert result.value["value"][0] == 1.5
    assert result.value["time_zone"][0] == "+00:00"
    assert ZoneValue(result.value["time_zone"][0]) == ZoneValue("+00:00")
    with pytest.raises(ValueError):
        ZoneValue("Z")


@pytest.mark.parametrize(
    "timestamp",
    [
        "2023-01-01T00:00:00",
        "2023-01-01T00:00:00CST",
        "2023-01-01T00:00:00-0600",
        "2023-01-01T00:00:00-25:00",
        "not-a-time",
    ],
)
def test_parse_fails_loudly_on_unrepresentable_timestamp(timestamp: str) -> None:
    content = _content([{"value": "1.0", "dateTime": timestamp}])

    with pytest.raises(FatalContractError):
        parse(_payload(content), _provider_config())


@pytest.mark.parametrize(
    "content",
    [
        "{}",
        object(),
        b"{",
        b"[]",
        bytes([0xFF]),
    ],
)
def test_parse_rejects_broken_opaque_content(content: object) -> None:
    with pytest.raises(FatalContractError):
        parse(_payload(content), _provider_config())


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"   ",
        b"{}",
        b'{"value": {}}',
        b'{"value": {"timeSeries": []}}',
    ],
)
def test_parse_missing_series_returns_schema_correct_empty_rows_and_issue(content: bytes) -> None:
    result = parse(_payload(content), _provider_config())

    pl_testing.assert_frame_equal(
        result.value,
        pl.DataFrame(schema=RowsSchema.polars_schema),
    )
    assert validate_catalogue(result.value, RowsSchema, on_issue="raise") == []
    assert len(result.issues) == 1
    assert result.issues[0].code == "missing_data"
    assert result.issues[0].details == {"station_id": "payload-station"}


def test_parse_invalid_numeric_values_preserve_partial_success_and_issue() -> None:
    content = _content(
        [
            {"value": "10.25", "dateTime": "2023-01-01T00:00:00-06:00"},
            {"value": "not-a-number", "dateTime": "2023-01-02T00:00:00-06:00"},
            {"value": None, "dateTime": "2023-01-03T00:00:00-06:00"},
        ]
    )

    result = parse(_payload(content), _provider_config())

    assert result.value["value"].to_list() == [10.25]
    assert len(result.issues) == 1
    assert result.issues[0].code == "invalid_numeric_value"
    assert result.issues[0].details == {
        "dropped_entries": 2,
        "station_id": "payload-station",
    }
    assert "missing_data" not in [issue.code for issue in result.issues]


def test_parse_no_data_sentinel_preserves_partial_success_and_issue() -> None:
    content = _content(
        [
            {"value": "-999999", "dateTime": "2023-01-01T00:00:00-06:00"},
            {"value": "100.0", "dateTime": "2023-01-02T00:00:00-06:00"},
        ],
        no_data_value=-999999.0,
    )

    result = parse(_payload(content), _provider_config())

    assert result.value["value"].to_list() == [100.0]
    assert len(result.issues) == 1
    assert result.issues[0].code == "no_data_value"
    assert result.issues[0].details == {
        "dropped_entries": 1,
        "station_id": "payload-station",
    }
    assert "missing_data" not in [issue.code for issue in result.issues]


def test_parse_all_dropped_rows_preserve_all_issues_and_empty_schema() -> None:
    content = _content(
        [
            {"value": "not-a-number", "dateTime": "2023-01-01T00:00:00-06:00"},
            {"value": "-999999", "dateTime": "2023-01-02T00:00:00-06:00"},
        ]
    )

    result = parse(_payload(content), _provider_config())

    pl_testing.assert_frame_equal(
        result.value,
        pl.DataFrame(schema=RowsSchema.polars_schema),
    )
    assert [issue.code for issue in result.issues] == [
        "invalid_numeric_value",
        "no_data_value",
        "missing_data",
    ]


def test_parse_fixture_does_not_invent_a_qualifier_carrier() -> None:
    fixture = json.loads(FIXTURE_PATH.read_bytes())
    source_entries = fixture["value"]["timeSeries"][0]["values"][0]["value"]
    qualifiers = {qualifier for entry in source_entries for qualifier in entry.get("qualifiers", [])}
    assert {"A", "P", "e"} <= qualifiers

    result = parse(_payload(FIXTURE_PATH.read_bytes()), _provider_config())

    assert result.value.columns == [
        "station_id",
        "product_id",
        "time",
        "value",
        "time_zone",
    ]
    assert "qualifier" not in result.value.columns
    assert validate_catalogue(result.value, RowsSchema, on_issue="raise") == []
