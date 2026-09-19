from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.engine import (
    Instant,
    Payload,
    ProductConfig,
    ProviderConfig,
    RowsSchema,
    SourceCallOrigin,
    SourceCoordinates,
    Unit,
    UnknownOriginFact,
    UnknownTemporalSupport,
    WindowEndpoint,
    ZoneValue,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.usgs_nwis.config import config
from rivretrieve._internal.providers.usgs_nwis.parse import parse
from rivretrieve._internal.recordings import read_recording

IV_RECORDING_PATH = Path("tests/test_data/usgs_nwis_07374000_iv_00060_2023-03-12.recording.json")
CURRENT_DV_RECORDING_PATH = Path(
    "tests/test_data/usgs_nwis_07374000_dv_00060_00003_2023-01-01_2023-01-03.recording.json"
)


def _payload(
    content: bytes,
    station_products: tuple[tuple[str, ProductId], ...] = (("payload-station", ProductId("payload-product")),),
    *,
    start: datetime = datetime(2023, 1, 1),
    end: datetime = datetime(2023, 1, 3, 23, 59, 59, 999999),
) -> Payload:
    return Payload(
        SourceCoordinates(object()),
        station_products,
        _make_fetch_window(
            WindowEndpoint.from_datetime(start),
            WindowEndpoint.from_datetime(end),
        ),
        content,
        _origin(),
        (),
    )


def _origin() -> SourceCallOrigin:
    unknown = UnknownOriginFact()
    return SourceCallOrigin(unknown, unknown, unknown, unknown, unknown, unknown, unknown)


def _provider_config() -> ProviderConfig:
    product = ProductConfig(
        coordinates=SourceCoordinates(object()),
        unit=Unit.FT,
        semantics=Instant(),
    )
    return ProviderConfig(
        zone=ZoneValue("unknown"),
        products={
            ProductId("payload-product"): product,
            ProductId("tagged-product"): product,
        },
    )


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


def test_parse_rejects_temporal_support_not_declared_by_usgs() -> None:
    unsupported = ProductConfig(
        coordinates=SourceCoordinates(object()),
        unit=Unit.FT,
        semantics=UnknownTemporalSupport(),
    )
    provider_config = ProviderConfig(
        zone=ZoneValue("unknown"),
        products={ProductId("payload-product"): unsupported},
    )

    with pytest.raises(FatalContractError, match="does not declare unknown temporal support"):
        parse(_payload(_content([{"dateTime": "2023-01-01T00:00:00+00:00", "value": "1"}])), provider_config)


@pytest.mark.parametrize(
    "content",
    [
        _content([{"value": "1.0", "dateTime": "2023-01-01T00:00:00-06:00"}]),
        b"",
        b"{}",
    ],
    ids=("offset-bearing", "empty", "missing-series"),
)
def test_parse_rejects_undeclared_product_before_reading_content(content: bytes) -> None:
    with pytest.raises(FatalContractError, match="product is absent from provider config: undeclared"):
        parse(
            _payload(content, (("07374000", ProductId("undeclared")),)),
            config(),
        )


def test_parse_current_daily_recording_preserves_naive_period_labels_as_unknown_zone() -> None:
    recording = read_recording(CURRENT_DV_RECORDING_PATH)

    result = parse(
        _payload(
            recording.content,
            (("07374000", ProductId("discharge_daily_mean")),),
        ),
        config(),
    )

    assert result.value.select("time", "time_zone").rows() == [
        (datetime(2023, 1, day), "unknown") for day in range(1, 4)
    ]


def test_parse_refuses_naive_non_midnight_daily_timestamp() -> None:
    content = _content([{"value": "1.0", "dateTime": "2023-01-01T12:00:00"}])

    with pytest.raises(FatalContractError, match="naive daily.*midnight"):
        parse(
            _payload(content, (("07374000", ProductId("discharge_daily_mean")),)),
            config(),
        )


def test_parse_recording_emits_exact_native_rows_from_payload_identity() -> None:
    content = read_recording(IV_RECORDING_PATH).content
    entries = json.loads(content)["value"]["timeSeries"][0]["values"][0]["value"]
    payload = _payload(content, start=datetime(2023, 3, 12), end=datetime(2023, 3, 12, 23, 59, 59, 999999))
    assert payload.content is content
    result = parse(payload, _provider_config())
    expected = pl.DataFrame(
        {
            "station_id": ["payload-station"] * len(entries),
            "product_id": ["payload-product"] * len(entries),
            "time": [datetime.fromisoformat(entry["dateTime"]).replace(tzinfo=None) for entry in entries],
            "value": [float(entry["value"]) for entry in entries],
            "time_zone": [entry["dateTime"][-6:] for entry in entries],
        },
        schema=RowsSchema.polars_schema,
    )

    pl_testing.assert_frame_equal(result.value, expected)
    assert result.issues == ()
    assert validate_catalogue(result.value, RowsSchema, on_issue="raise") == []


def test_parse_recording_preserves_wall_clock_offsets_and_ignores_station_zone() -> None:
    content = read_recording(IV_RECORDING_PATH).content
    series = json.loads(content)["value"]["timeSeries"][0]
    assert series["sourceInfo"]["timeZoneInfo"]["defaultTimeZone"]["zoneAbbreviation"] == "CST"
    assert series["values"][0]["value"][8]["dateTime"] == "2023-03-12T03:00:00.000-05:00"

    result = parse(
        _payload(content, start=datetime(2023, 3, 12), end=datetime(2023, 3, 12, 23, 59, 59, 999999)),
        _provider_config(),
    )

    assert result.value["time"][8] == datetime(2023, 3, 12, 3)
    assert result.value["time_zone"][8] == "-05:00"
    assert result.value["value"][8] == 811000.0
    assert result.value["time"].dtype == pl.Datetime()
    assert result.value["time_zone"].to_list() == ["-06:00"] * 8 + ["-05:00"] * 84


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
            _payload(read_recording(IV_RECORDING_PATH).content, station_products),
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
        b"{",
        b"[]",
        bytes([0xFF]),
    ],
)
def test_parse_rejects_broken_opaque_content(content: bytes) -> None:
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


def test_parse_recording_does_not_invent_a_qualifier_carrier() -> None:
    fixture = json.loads(read_recording(IV_RECORDING_PATH).content)
    source_entries = fixture["value"]["timeSeries"][0]["values"][0]["value"]
    qualifiers = {qualifier for entry in source_entries for qualifier in entry.get("qualifiers", [])}
    assert qualifiers == {"A"}

    result = parse(_payload(read_recording(IV_RECORDING_PATH).content), _provider_config())

    assert result.value.columns == [
        "station_id",
        "product_id",
        "time",
        "value",
        "time_zone",
    ]
    assert "qualifier" not in result.value.columns
    assert validate_catalogue(result.value, RowsSchema, on_issue="raise") == []
