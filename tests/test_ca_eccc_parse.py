from __future__ import annotations

from datetime import datetime

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.engine import (
    Daily,
    DayDefinition,
    FetchWindow,
    Instant,
    Payload,
    ProductConfig,
    ProviderConfig,
    RowsSchema,
    SourceCoordinates,
    Unit,
    WindowEndpoint,
    ZoneValue,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.ca_eccc.config import HydatSourceCoordinates, config
from rivretrieve._internal.providers.ca_eccc.parse import parse

FLOW = HydatSourceCoordinates("DLY_FLOWS", "FLOW", "FLOW_SYMBOL")
LEVEL = HydatSourceCoordinates("DLY_LEVELS", "LEVEL", "LEVEL_SYMBOL")
DISCHARGE = ProductId("discharge_daily_mean")


def _monthly_row(
    *,
    year: int = 2020,
    month: int = 1,
    no_days: int = 1,
    coordinates: HydatSourceCoordinates = FLOW,
    values: dict[int, object] | None = None,
    symbols: dict[int, object] | None = None,
) -> dict[str, object]:
    values = {} if values is None else values
    symbols = {} if symbols is None else symbols
    row: dict[str, object] = {
        "STATION_NUMBER": "02GA010",
        "YEAR": year,
        "MONTH": month,
        "NO_DAYS": no_days,
    }
    for day in range(1, 32):
        row[f"{coordinates.value_prefix}{day}"] = values.get(day)
        row[f"{coordinates.symbol_prefix}{day}"] = symbols.get(day)
    return row


def _payload(
    content: object,
    *,
    product_id: ProductId = DISCHARGE,
    coordinates: HydatSourceCoordinates = FLOW,
    station_products: tuple[tuple[str, ProductId], ...] | None = None,
) -> Payload:
    pairs = (("02GA010", product_id),) if station_products is None else station_products
    return Payload(
        source_coordinates=SourceCoordinates(coordinates),
        station_products=pairs,
        fetch_window=_fetch_window(),
        content=content,
    )


def _fetch_window() -> FetchWindow:
    return _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2010, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2010, 12, 31, 23, 59, 59, 999999)),
    )


def _single_flow() -> Payload:
    return _payload([_monthly_row(values={1: 16.0}, symbols={1: "B"})])


def test_parse_hydat_date_only_rows_are_naive_midnight() -> None:
    result = parse(
        _payload([_monthly_row(month=2, no_days=2, values={1: 16.0, 2: None})]),
        config,
    )
    expected = pl.DataFrame(
        {
            "station_id": ["02GA010", "02GA010"],
            "product_id": ["discharge_daily_mean", "discharge_daily_mean"],
            "time": [datetime(2020, 2, 1), datetime(2020, 2, 2)],
            "value": [16.0, None],
            "time_zone": ["unknown", "unknown"],
        },
        schema=RowsSchema.polars_schema,
    )

    pl_testing.assert_frame_equal(result.value, expected)
    assert result.issues == ()


def test_parse_hydat_never_fabricates_midnight_utc() -> None:
    result = parse(_single_flow(), config)

    assert result.value["time"].dtype == pl.Datetime()
    assert result.value["time"][0] == datetime(2020, 1, 1)
    assert result.value["time_zone"].to_list() == ["unknown"]
    aware = result.value.with_columns(pl.col("time").dt.replace_time_zone("UTC"))
    with pytest.raises(FatalContractError, match="Rows.time has dtype"):
        validate_catalogue(aware, RowsSchema, on_issue="raise")


def test_parse_hydat_uses_declared_unknown_zone_and_day_definition() -> None:
    semantics = config.products[ProductId("discharge_daily_mean")].semantics
    assert semantics == Daily(DayDefinition("unknown"))
    assert config.zone == ZoneValue("unknown")
    result = parse(_single_flow(), config)
    assert result.value["time_zone"].to_list() == ["unknown"]

    shifted_declaration = ProviderConfig(
        zone=ZoneValue("+02:00"),
        products={
            ProductId("discharge_daily_mean"): ProductConfig(
                coordinates=SourceCoordinates(FLOW),
                unit=Unit.M3_S,
                semantics=Daily(DayDefinition("03:00")),
            )
        },
    )
    shifted = parse(_single_flow(), shifted_declaration)
    assert shifted.value["time"][0] == datetime(2020, 1, 1)
    assert shifted.value["time_zone"].to_list() == ["+02:00"]


def test_parse_hydat_maps_flow_and_level_coordinates() -> None:
    flow = parse(_payload([_monthly_row(values={1: 16.0})]), config)
    level = parse(
        _payload(
            [_monthly_row(coordinates=LEVEL, values={1: 1.1})],
            product_id=ProductId("stage_daily_mean"),
            coordinates=LEVEL,
        ),
        config,
    )

    assert flow.value["product_id"].to_list() == ["discharge_daily_mean"]
    assert flow.value["value"].to_list() == [16.0]
    assert level.value["product_id"].to_list() == ["stage_daily_mean"]
    assert level.value["value"].to_list() == [1.1]


def test_parse_hydat_rows_validate_exact_rows_schema() -> None:
    result = parse(_single_flow(), config)

    assert result.value.columns == [
        "station_id",
        "product_id",
        "time",
        "value",
        "time_zone",
    ]
    assert result.value.schema == RowsSchema.polars_schema
    assert validate_catalogue(result.value, RowsSchema, on_issue="raise") == []


def test_parse_malformed_month_keeps_valid_rows_and_concatenates_issues() -> None:
    malformed_calendar = _monthly_row(values={1: 1.0})
    malformed_calendar["YEAR"] = "2020"
    result = parse(
        _payload(
            [
                object(),
                malformed_calendar,
                _monthly_row(values={1: 2.0}),
                _monthly_row(no_days=2, values={1: "not-numeric", 2: 3.0}),
            ]
        ),
        config,
    )

    assert result.value["value"].to_list() == [2.0, 3.0]
    assert result.value["time"].to_list() == [datetime(2020, 1, 1), datetime(2020, 1, 2)]
    assert [issue.code for issue in result.issues] == ["parse_error", "parse_error", "parse_error"]
    assert "missing_data" not in [issue.code for issue in result.issues]


def test_parse_invalid_day_index_is_an_issue_and_valid_days_survive() -> None:
    result = parse(
        _payload([_monthly_row(year=2023, month=2, no_days=30, values={28: 2.8, 30: 30.0})]),
        config,
    )

    assert len(result.value) == 28
    assert result.value["time"][-1] == datetime(2023, 2, 28)
    assert result.value["value"][-1] == 2.8
    assert [issue.code for issue in result.issues] == ["parse_error", "parse_error"]
    assert all(issue.message == "Dropped impossible HYDAT day index" for issue in result.issues)


@pytest.mark.parametrize(
    ("content", "expected_codes"),
    [
        ([], ["missing_data"]),
        (object(), ["parse_error", "missing_data"]),
        ([object()], ["parse_error", "missing_data"]),
    ],
)
def test_parse_empty_or_entirely_unparseable_payload_returns_issues(
    content: object,
    expected_codes: list[str],
) -> None:
    result = parse(_payload(content), config)

    pl_testing.assert_frame_equal(result.value, pl.DataFrame(schema=RowsSchema.polars_schema))
    assert [issue.code for issue in result.issues] == expected_codes


def test_parse_unknown_product_is_dropped_with_issues() -> None:
    result = parse(
        _payload(
            [_monthly_row(values={1: 5.0})],
            product_id=ProductId("derived_monthly_product"),
        ),
        config,
    )

    pl_testing.assert_frame_equal(result.value, pl.DataFrame(schema=RowsSchema.polars_schema))
    assert [issue.code for issue in result.issues] == ["parse_error", "missing_data"]


def test_parse_preserves_duplicates_and_does_not_use_the_fetch_window() -> None:
    duplicate_result = parse(
        _payload(
            [
                _monthly_row(values={1: 1.0}),
                _monthly_row(values={1: 2.0}),
            ]
        ),
        config,
    )

    assert duplicate_result.value["time"].to_list() == [
        datetime(2020, 1, 1),
        datetime(2020, 1, 1),
    ]
    assert duplicate_result.value["value"].to_list() == [1.0, 2.0]

    source_order_result = parse(
        _payload(
            [
                _monthly_row(month=3, values={1: 3.0}),
                _monthly_row(month=1, values={1: 1.0}),
            ]
        ),
        config,
    )

    assert source_order_result.value["time"].to_list() == [
        datetime(2020, 3, 1),
        datetime(2020, 1, 1),
    ]


def test_parse_does_not_interpret_or_add_hydat_quality_symbols() -> None:
    result = parse(_single_flow(), config)

    assert result.value["value"].to_list() == [16.0]
    assert result.value.columns == RowsSchema.polars_schema.names()
    assert "symbol" not in result.value.columns
    assert result.issues == ()


@pytest.mark.parametrize(
    "station_products",
    [
        (),
        (
            ("02GA010", ProductId("discharge_daily_mean")),
            ("02GA011", ProductId("discharge_daily_mean")),
        ),
    ],
)
def test_parse_rejects_broken_station_product_tags(
    station_products: tuple[tuple[str, ProductId], ...],
) -> None:
    with pytest.raises(FatalContractError, match="exactly one station-product pair"):
        parse(_payload([], station_products=station_products), config)


def test_parse_rejects_coordinate_and_declaration_seam_breaks() -> None:
    with pytest.raises(FatalContractError, match="must be HydatSourceCoordinates"):
        parse(
            Payload(
                SourceCoordinates(object()),
                (("02GA010", ProductId("discharge_daily_mean")),),
                _fetch_window(),
                [],
            ),
            config,
        )

    with pytest.raises(FatalContractError, match="do not match"):
        parse(_payload([], coordinates=LEVEL), config)

    instant_config = ProviderConfig(
        zone=ZoneValue("unknown"),
        products={
            ProductId("discharge_daily_mean"): ProductConfig(
                coordinates=SourceCoordinates(FLOW),
                unit=Unit.M3_S,
                semantics=Instant(),
            )
        },
    )
    with pytest.raises(FatalContractError, match="must declare Daily"):
        parse(_payload([]), instant_config)
