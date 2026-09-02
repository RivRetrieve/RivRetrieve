from collections.abc import Mapping, Sequence
from datetime import datetime

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.catalogues.schemas import (
    CatalogueSchema,
)
from rivretrieve._internal.catalogues.schemas import (
    validate_catalogue as real_validate_catalogue,
)
from rivretrieve._internal.engine import (
    CanonicalRowsSchema,
    Daily,
    DayDefinition,
    Hourly,
    Instant,
    IntervalDefinition,
    ProductConfig,
    ProviderConfig,
    RequestedWindow,
    RowsSchema,
    SourceCoordinates,
    Unit,
    WindowEndpoint,
    ZoneValue,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import OnIssue, ProductId


def _rows(records: Sequence[Mapping[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(records, schema=RowsSchema.polars_schema)


def _window(start: datetime, end: datetime) -> RequestedWindow:
    return RequestedWindow(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end))


def _product(unit: Unit = Unit.M, semantics: Instant | Daily | Hourly | None = None) -> ProductConfig:
    return ProductConfig(
        coordinates=SourceCoordinates("unused"),
        unit=unit,
        semantics=semantics if semantics is not None else Instant(),
    )


def _config(products: dict[str, ProductConfig]) -> ProviderConfig:
    return ProviderConfig(
        zone=ZoneValue("unknown"),
        products={ProductId(product_id): product for product_id, product in products.items()},
    )


def test_convert_validates_rows_schema_before_product_work() -> None:
    from rivretrieve._internal.conversion import convert

    rows = pl.DataFrame(
        {
            "station_id": ["station-1"],
            "product_id": ["undeclared"],
            "time": [datetime(2023, 1, 1)],
            "value": [1.0],
        },
        schema={
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "time": pl.Datetime(),
            "value": pl.Float64,
        },
    )

    with pytest.raises(FatalContractError, match="time_zone"):
        convert(rows, _config({}), _window(datetime(2023, 1, 1), datetime(2023, 1, 1)))


def test_convert_invokes_real_rows_and_canonical_validators_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rivretrieve._internal.conversion as conversion

    calls: list[str] = []

    def recording_validator(
        frame: pl.DataFrame,
        schema: CatalogueSchema,
        *,
        on_issue: OnIssue,
    ) -> list[Issue]:
        calls.append(schema.name)
        return real_validate_catalogue(frame, schema, on_issue=on_issue)

    monkeypatch.setattr(conversion, "validate_catalogue", recording_validator)
    rows = _rows(
        [
            {
                "station_id": "station-1",
                "product_id": "level",
                "time": datetime(2023, 1, 15, 12),
                "value": 2.0,
                "time_zone": "+00:00",
            }
        ]
    )

    conversion.convert(
        rows,
        _config({"level": _product()}),
        _window(datetime(2023, 1, 15, 11), datetime(2023, 1, 15, 13)),
    )

    assert calls == ["Rows", "CanonicalRows"]


def test_convert_rejects_undeclared_products() -> None:
    from rivretrieve._internal.conversion import convert

    rows = _rows(
        [
            {
                "station_id": "station-1",
                "product_id": product_id,
                "time": datetime(2023, 1, 15, 12),
                "value": 2.0,
                "time_zone": "+00:00",
            }
            for product_id in ("declared", "missing-z", "missing-a")
        ]
    )

    with pytest.raises(FatalContractError, match=r"missing-a, missing-z"):
        convert(
            rows,
            _config({"declared": _product()}),
            _window(datetime(2023, 1, 15, 11), datetime(2023, 1, 15, 13)),
        )


@pytest.mark.parametrize("zone", ["Europe/Oslo", "Etc/GMT+5", "+09:00", "-06:00"])
def test_convert_preserves_source_declared_iana_and_offset_zones_exactly(zone: str) -> None:
    from rivretrieve._internal.conversion import convert

    native_time = datetime(2023, 1, 15, 12)
    result = convert(
        _rows(
            [
                {
                    "station_id": "station-1",
                    "product_id": "level",
                    "time": native_time,
                    "value": 2.0,
                    "time_zone": zone,
                }
            ]
        ),
        _config({"level": _product()}),
        _window(datetime(2023, 1, 14), datetime(2023, 1, 16)),
    )

    assert result.value["time_zone"].to_list() == [zone]
    assert result.value["time"].to_list() == [native_time]


@pytest.mark.parametrize("zone", ["Z", "UTC", "GMT", "EST", "CST", "MST", "PST", "AKST", "HST"])
def test_convert_rejects_invalid_zone_values_without_translation(zone: str) -> None:
    from rivretrieve._internal.conversion import convert

    rows = _rows(
        [
            {
                "station_id": "station-1",
                "product_id": "level",
                "time": datetime(2023, 1, 15, 12),
                "value": 2.0,
                "time_zone": zone,
            }
        ]
    )

    with pytest.raises(ValueError, match="zone value"):
        convert(
            rows,
            _config({"level": _product()}),
            _window(datetime(2023, 1, 15, 11), datetime(2023, 1, 15, 13)),
        )


@pytest.mark.parametrize(
    ("unit", "input_value", "expected"),
    [
        (Unit.M, 2.0, 2.0),
        (Unit.CM, 200.0, 2.0),
        (Unit.FT, 2.0, 0.6096),
        (Unit.MM, 2000.0, 2.0),
        (Unit.M3_S, 2.0, 2.0),
        (Unit.FT3_S, 2.0, 0.056633693184),
        (Unit.L_S, 2000.0, 2.0),
        (Unit.DEG_C, 2.0, 2.0),
    ],
)
def test_convert_converts_all_eight_units(unit: Unit, input_value: float, expected: float) -> None:
    from rivretrieve._internal.conversion import convert

    result = convert(
        _rows(
            [
                {
                    "station_id": "station-1",
                    "product_id": "product",
                    "time": datetime(2023, 1, 15, 12),
                    "value": input_value,
                    "time_zone": "+00:00",
                }
            ]
        ),
        _config({"product": _product(unit)}),
        _window(
            datetime(2023, 1, 15, 11),
            datetime(2023, 1, 15, 13),
        ),
    )

    assert result.value["value"].item() == pytest.approx(expected)


def test_convert_preserves_null_measurements_for_every_unit() -> None:
    from rivretrieve._internal.conversion import convert

    product_units = {
        "m": Unit.M,
        "cm": Unit.CM,
        "ft": Unit.FT,
        "mm": Unit.MM,
        "m3-s": Unit.M3_S,
        "ft3-s": Unit.FT3_S,
        "l-s": Unit.L_S,
        "deg-c": Unit.DEG_C,
    }
    records = [
        {
            "station_id": f"station-{product_id}",
            "product_id": product_id,
            "time": datetime(2023, 1, 15, 12),
            "value": None,
            "time_zone": "+00:00",
        }
        for product_id in product_units
    ]

    result = convert(
        _rows(records),
        _config({product_id: _product(unit) for product_id, unit in product_units.items()}),
        _window(
            datetime(2023, 1, 15, 11),
            datetime(2023, 1, 15, 13),
        ),
    )

    assert result.value.height == 8
    assert result.value["value"].null_count() == 8


def test_convert_instant_window_is_closed_at_both_endpoints() -> None:
    from rivretrieve._internal.conversion import convert

    records = [
        {
            "station_id": station_id,
            "product_id": "level",
            "time": timestamp,
            "value": value,
            "time_zone": "+00:00",
        }
        for station_id, timestamp, value in [
            ("station-before", datetime(2023, 1, 1, 11, 59, 59), 1.0),
            ("station-start", datetime(2023, 1, 1, 12), 2.0),
            ("station-end", datetime(2023, 1, 1, 13), 3.0),
            ("station-after", datetime(2023, 1, 1, 13, 0, 1), 4.0),
        ]
    ]

    result = convert(
        _rows(records),
        _config({"level": _product()}),
        _window(datetime(2023, 1, 1, 12), datetime(2023, 1, 1, 13)),
    )

    assert result.value["station_id"].to_list() == ["station-start", "station-end"]


def test_convert_compares_known_instant_rows_on_the_source_wall_clock_axis() -> None:
    from rivretrieve._internal.conversion import convert

    result = convert(
        _rows(
            [
                {
                    "station_id": "correct",
                    "product_id": "level",
                    "time": datetime(2020, 6, 1, 0, 30),
                    "value": 1.0,
                    "time_zone": "+09:00",
                },
                {
                    "station_id": "wrong",
                    "product_id": "level",
                    "time": datetime(2020, 5, 31, 15, 30),
                    "value": 2.0,
                    "time_zone": "+09:00",
                },
            ]
        ),
        _config({"level": _product()}),
        _window(datetime(2020, 5, 31, 15), datetime(2020, 5, 31, 16)),
    )

    assert result.value["time"].to_list() == [datetime(2020, 5, 31, 15, 30)]
    assert result.value["station_id"].to_list() == ["wrong"]


def test_convert_binds_naive_instant_endpoints_to_the_source_wall_clock_calendar() -> None:
    from rivretrieve._internal.conversion import convert

    result = convert(
        _rows(
            [
                {
                    "station_id": "station-1",
                    "product_id": "level",
                    "time": datetime(2020, 6, 1, 0, 30),
                    "value": 1.0,
                    "time_zone": "+09:00",
                }
            ]
        ),
        _config({"level": _product()}),
        _window(datetime(2020, 6, 1), datetime(2020, 6, 1, 1)),
    )

    assert result.value["time"].to_list() == [datetime(2020, 6, 1, 0, 30)]


def test_convert_mixed_known_and_unknown_instants_clip_all_rows_on_wall_clock_axis_without_warning() -> None:
    from rivretrieve._internal.conversion import convert

    result = convert(
        _rows(
            [
                {
                    "station_id": "known-inside",
                    "product_id": "level",
                    "time": datetime(2023, 1, 15),
                    "value": 1.0,
                    "time_zone": "+00:00",
                },
                {
                    "station_id": "known-outside",
                    "product_id": "level",
                    "time": datetime(2023, 2, 15),
                    "value": 2.0,
                    "time_zone": "+00:00",
                },
                {
                    "station_id": "unknown-outside",
                    "product_id": "level",
                    "time": datetime(2022, 12, 15),
                    "value": 3.0,
                    "time_zone": "unknown",
                },
            ]
        ),
        _config({"level": _product()}),
        _window(
            datetime(2023, 1, 1),
            datetime(2023, 1, 31, 23, 59),
        ),
    )

    assert result.value["station_id"].to_list() == ["known-inside"]
    assert result.value["time_zone"].to_list() == ["+00:00"]
    assert result.issues == ()


def test_convert_daily_positive_offset_uses_zone_free_date_comparison() -> None:
    from rivretrieve._internal.conversion import convert

    result = convert(
        _rows(
            [
                {
                    "station_id": "station-1",
                    "product_id": "daily",
                    "time": datetime(2020, 6, 1),
                    "value": 1.0,
                    "time_zone": "+09:00",
                }
            ]
        ),
        _config({"daily": _product(semantics=Daily(DayDefinition("unknown")))}),
        _window(datetime(2020, 6, 1), datetime(2020, 6, 1)),
    )

    assert result.value["time"].to_list() == [datetime(2020, 6, 1)]


def test_convert_daily_negative_offset_does_not_project_or_shift_the_requested_dates() -> None:
    from rivretrieve._internal.conversion import convert

    result = convert(
        _rows(
            [
                {
                    "station_id": f"station-{label:%Y-%m-%d}",
                    "product_id": "daily",
                    "time": label,
                    "value": 1.0,
                    "time_zone": "-06:00",
                }
                for label in [
                    datetime(2022, 12, 31),
                    datetime(2023, 1, 1),
                    datetime(2023, 1, 31),
                ]
            ]
        ),
        _config({"daily": _product(semantics=Daily(DayDefinition("unknown")))}),
        _window(datetime(2023, 1, 1), datetime(2023, 1, 31)),
    )

    assert result.value["time"].to_list() == [datetime(2023, 1, 1), datetime(2023, 1, 31)]


def test_convert_daily_reads_naive_explicit_midnight_calendar_date() -> None:
    from rivretrieve._internal.conversion import convert

    endpoint = datetime(2023, 1, 31)
    result = convert(
        _rows(
            [
                {
                    "station_id": "station-1",
                    "product_id": "daily",
                    "time": datetime(2023, 1, 31),
                    "value": 1.0,
                    "time_zone": "+00:00",
                }
            ]
        ),
        _config({"daily": _product(semantics=Daily(DayDefinition("unknown")))}),
        _window(endpoint, endpoint),
    )

    assert result.value.height == 1


def test_convert_clips_daily_unknown_zone_without_an_unknown_zone_warning() -> None:
    from rivretrieve._internal.conversion import convert

    result = convert(
        _rows(
            [
                {
                    "station_id": f"station-{label:%Y-%m-%d}",
                    "product_id": "daily",
                    "time": label,
                    "value": 1.0,
                    "time_zone": "unknown",
                }
                for label in [datetime(2022, 12, 31), datetime(2023, 1, 1)]
            ]
        ),
        _config({"daily": _product(semantics=Daily(DayDefinition("09:00")))}),
        _window(datetime(2023, 1, 1), datetime(2023, 1, 1)),
    )

    assert result.value["time"].to_list() == [datetime(2023, 1, 1)]
    assert result.issues == ()


def test_convert_rejects_non_midnight_daily_labels() -> None:
    from rivretrieve._internal.conversion import convert

    with pytest.raises(FatalContractError, match=r"station-1.*daily"):
        convert(
            _rows(
                [
                    {
                        "station_id": "station-1",
                        "product_id": "daily",
                        "time": datetime(2023, 1, 1, 0, 0, 1),
                        "value": 1.0,
                        "time_zone": "+00:00",
                    }
                ]
            ),
            _config({"daily": _product(semantics=Daily(DayDefinition("unknown")))}),
            _window(datetime(2023, 1, 1), datetime(2023, 1, 1)),
        )


def test_convert_empty_rows_returns_valid_empty_canonical_frame() -> None:
    from rivretrieve._internal.conversion import convert

    result = convert(
        pl.DataFrame(schema=RowsSchema.polars_schema),
        _config({"level": _product()}),
        _window(datetime(2023, 1, 1), datetime(2023, 1, 31)),
    )
    expected = pl.DataFrame(schema=CanonicalRowsSchema.polars_schema)

    assert_frame_equal(result.value, expected)
    assert result.issues == ()


def test_convert_returns_exact_canonical_column_order_and_native_time_dtype() -> None:
    from rivretrieve._internal.conversion import convert

    result = convert(
        _rows(
            [
                {
                    "station_id": "station-1",
                    "product_id": "level",
                    "time": datetime(2023, 1, 15, 12),
                    "value": 250.0,
                    "time_zone": "Etc/GMT+5",
                }
            ]
        ),
        _config({"level": _product(Unit.CM)}),
        _window(datetime(2023, 1, 15, 11), datetime(2023, 1, 15, 13)),
    )
    expected = pl.DataFrame(
        {
            "time": [datetime(2023, 1, 15, 12)],
            "time_zone": ["Etc/GMT+5"],
            "station_id": ["station-1"],
            "product_id": ["level"],
            "value": [2.5],
        },
        schema=CanonicalRowsSchema.polars_schema,
    )

    assert result.value.columns == ["time", "time_zone", "station_id", "product_id", "value"]
    assert result.value.schema["time"] == pl.Datetime()
    assert result.value.schema["time_zone"] == pl.Utf8
    assert result.value["time_zone"].null_count() == 0
    assert_frame_equal(result.value, expected)


def test_hourly_interval_means_clip_on_source_label_axis_without_inferring_anchor() -> None:
    from rivretrieve._internal.conversion import convert

    rows = _rows(
        [
            {
                "station_id": "s",
                "product_id": "level",
                "time": datetime(2023, 1, 1, hour),
                "value": float(hour),
                "time_zone": "+00:00",
            }
            for hour in (0, 1, 2)
        ]
    )
    result = convert(
        rows,
        _config({"level": _product(semantics=Hourly(IntervalDefinition("unknown")))}),
        _window(datetime(2023, 1, 1, 1), datetime(2023, 1, 1, 2)),
    )
    assert result.value["time"].to_list() == [datetime(2023, 1, 1, 1), datetime(2023, 1, 1, 2)]


def test_hourly_interval_mean_requires_an_on_hour_source_label() -> None:
    from rivretrieve._internal.conversion import convert

    rows = _rows(
        [
            {
                "station_id": "s",
                "product_id": "level",
                "time": datetime(2023, 1, 1, 1, 30),
                "value": 1.0,
                "time_zone": "+00:00",
            }
        ]
    )
    with pytest.raises(FatalContractError, match="on-hour label"):
        convert(
            rows,
            _config({"level": _product(semantics=Hourly(IntervalDefinition("unknown")))}),
            _window(datetime(2023, 1, 1), datetime(2023, 1, 2)),
        )
