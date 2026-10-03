from collections.abc import Mapping, Sequence
from datetime import datetime

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.engine import (
    CanonicalRowsSchema,
    Daily,
    DailyLabelTime,
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
    UnknownTemporalSupport,
    WindowEndpoint,
    ZoneValue,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceFact,
    PhysicalFacts,
    SourceIdentity,
    SourceSeries,
    known,
)


def _rows(records: Sequence[Mapping[str, object]], *, units: Mapping[str, Unit] | None = None) -> pl.DataFrame:
    units = units or {}
    return pl.DataFrame(
        [
            {
                **row,
                "series_id": f"{row['station_id']}:{row['product_id']}",
                "facts_id": f"{row['station_id']}:{row['product_id']}:facts",
                "source_unit": units.get(str(row["product_id"]), Unit.M).value,
            }
            for row in records
        ],
        schema=RowsSchema.polars_schema,
    )


def _series(rows: pl.DataFrame, config: ProviderConfig) -> tuple[SourceSeries, ...]:
    """Explicit response definitions for the test's source records."""
    definitions = []
    for row in rows.unique(subset=["station_id", "product_id"]).iter_rows(named=True):
        product = config.products.get(ProductId(row["product_id"]), _product())
        unit = row["source_unit"]
        quantity = "discharge" if unit in ("m3/s", "ft3/s", "l/s") else "temperature" if unit == "degC" else "stage"
        daily = isinstance(product.semantics, Daily)
        facts = PhysicalFacts(
            facts_id=row["facts_id"],
            quantity=known(quantity, "test source definition"),
            source_unit=known(unit, "test response unit"),
            normalized_unit=unit,
            frequency=(
                EvidenceFact()
                if isinstance(product.semantics, UnknownTemporalSupport)
                else known(
                    "daily" if daily else "hourly" if isinstance(product.semantics, Hourly) else "instantaneous",
                    "test source definition",
                )
            ),
            clipping_axis=ClippingAxis.CALENDAR_DATE if daily else ClippingAxis.SOURCE_TIMESTAMP,
            label_time=product.semantics.label_time.value if daily else None,
        )
        definitions.append(
            SourceSeries(
                series_id=row["series_id"],
                provider_id="test",
                station_id=row["station_id"],
                product_id=row["product_id"],
                identity=SourceIdentity(namespace="test", origin="response", evidence=("test payload",)),
                facts=(facts,),
            )
        )
    return tuple(definitions)


def _window(start: datetime, end: datetime) -> RequestedWindow:
    return RequestedWindow(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end))


def _product(
    unit: Unit = Unit.M,
    semantics: Instant | Daily | Hourly | UnknownTemporalSupport | None = None,
) -> ProductConfig:
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
        convert(
            rows,
            _config({}),
            _window(datetime(2023, 1, 1), datetime(2023, 1, 1)),
            series=(),
        )


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

    with pytest.raises(FatalContractError, match=r"undeclared product: missing-[az]"):
        provider_config = _config({"declared": _product()})
        native_rows = rows
        convert(
            (native_rows),
            (provider_config),
            _window(datetime(2023, 1, 15, 11), datetime(2023, 1, 15, 13)),
            series=_series(native_rows, provider_config),
        )


@pytest.mark.parametrize("zone", ["Europe/Oslo", "Etc/GMT+5", "+09:00", "-06:00"])
def test_convert_preserves_source_declared_iana_and_offset_zones_exactly(zone: str) -> None:
    from rivretrieve._internal.conversion import convert

    native_time = datetime(2023, 1, 15, 12)
    provider_config = _config({"level": _product()})
    native_rows = _rows(
        [{"station_id": "station-1", "product_id": "level", "time": native_time, "value": 2.0, "time_zone": zone}],
        units={key: value.unit for key, value in provider_config.products.items()},
    )
    result = convert(
        (native_rows),
        (provider_config),
        _window(datetime(2023, 1, 14), datetime(2023, 1, 16)),
        series=_series(native_rows, provider_config),
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
        provider_config = _config({"level": _product()})
        native_rows = rows
        convert(
            (native_rows),
            (provider_config),
            _window(datetime(2023, 1, 15, 11), datetime(2023, 1, 15, 13)),
            series=_series(native_rows, provider_config),
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

    provider_config = _config({"product": _product(unit)})
    native_rows = _rows(
        [
            {
                "station_id": "station-1",
                "product_id": "product",
                "time": datetime(2023, 1, 15, 12),
                "value": input_value,
                "time_zone": "+00:00",
            }
        ],
        units={key: value.unit for key, value in provider_config.products.items()},
    )
    result = convert(
        (native_rows),
        (provider_config),
        _window(
            datetime(2023, 1, 15, 11),
            datetime(2023, 1, 15, 13),
        ),
        series=_series(native_rows, provider_config),
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

    provider_config = _config({product_id: _product(unit) for product_id, unit in product_units.items()})
    native_rows = _rows(records, units={key: value.unit for key, value in provider_config.products.items()})
    result = convert(
        (native_rows),
        (provider_config),
        _window(
            datetime(2023, 1, 15, 11),
            datetime(2023, 1, 15, 13),
        ),
        series=_series(native_rows, provider_config),
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

    provider_config = _config({"level": _product()})
    native_rows = _rows(records, units={key: value.unit for key, value in provider_config.products.items()})
    result = convert(
        (native_rows),
        (provider_config),
        _window(datetime(2023, 1, 1, 12), datetime(2023, 1, 1, 13)),
        series=_series(native_rows, provider_config),
    )

    assert result.value["station_id"].to_list() == ["station-start", "station-end"]


def test_convert_compares_known_instant_rows_on_the_source_wall_clock_axis() -> None:
    from rivretrieve._internal.conversion import convert

    provider_config = _config({"level": _product()})
    native_rows = _rows(
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
        ],
        units={key: value.unit for key, value in provider_config.products.items()},
    )
    result = convert(
        (native_rows),
        (provider_config),
        _window(datetime(2020, 5, 31, 15), datetime(2020, 5, 31, 16)),
        series=_series(native_rows, provider_config),
    )

    assert result.value["time"].to_list() == [datetime(2020, 5, 31, 15, 30)]
    assert result.value["station_id"].to_list() == ["wrong"]


def test_convert_binds_naive_instant_endpoints_to_the_source_wall_clock_calendar() -> None:
    from rivretrieve._internal.conversion import convert

    provider_config = _config({"level": _product()})
    native_rows = _rows(
        [
            {
                "station_id": "station-1",
                "product_id": "level",
                "time": datetime(2020, 6, 1, 0, 30),
                "value": 1.0,
                "time_zone": "+09:00",
            }
        ],
        units={key: value.unit for key, value in provider_config.products.items()},
    )
    result = convert(
        (native_rows),
        (provider_config),
        _window(datetime(2020, 6, 1), datetime(2020, 6, 1, 1)),
        series=_series(native_rows, provider_config),
    )

    assert result.value["time"].to_list() == [datetime(2020, 6, 1, 0, 30)]


def test_convert_mixed_known_and_unknown_instants_clip_all_rows_on_wall_clock_axis_without_warning() -> None:
    from rivretrieve._internal.conversion import convert

    provider_config = _config({"level": _product()})
    native_rows = _rows(
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
        ],
        units={key: value.unit for key, value in provider_config.products.items()},
    )
    result = convert(
        (native_rows),
        (provider_config),
        _window(
            datetime(2023, 1, 1),
            datetime(2023, 1, 31, 23, 59),
        ),
        series=_series(native_rows, provider_config),
    )

    assert result.value["station_id"].to_list() == ["known-inside"]
    assert result.value["time_zone"].to_list() == ["+00:00"]
    assert result.issues == ()


def test_convert_daily_positive_offset_uses_zone_free_date_comparison() -> None:
    from rivretrieve._internal.conversion import convert

    provider_config = _config({"daily": _product(semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")))})
    native_rows = _rows(
        [
            {
                "station_id": "station-1",
                "product_id": "daily",
                "time": datetime(2020, 6, 1),
                "value": 1.0,
                "time_zone": "+09:00",
            }
        ],
        units={key: value.unit for key, value in provider_config.products.items()},
    )
    result = convert(
        (native_rows),
        (provider_config),
        _window(datetime(2020, 6, 1), datetime(2020, 6, 1)),
        series=_series(native_rows, provider_config),
    )

    assert result.value["time"].to_list() == [datetime(2020, 6, 1)]


def test_convert_daily_negative_offset_does_not_project_or_shift_the_requested_dates() -> None:
    from rivretrieve._internal.conversion import convert

    provider_config = _config({"daily": _product(semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")))})
    native_rows = _rows(
        [
            {
                "station_id": f"station-{label:%Y-%m-%d}",
                "product_id": "daily",
                "time": label,
                "value": 1.0,
                "time_zone": "-06:00",
            }
            for label in [datetime(2022, 12, 31), datetime(2023, 1, 1), datetime(2023, 1, 31)]
        ],
        units={key: value.unit for key, value in provider_config.products.items()},
    )
    result = convert(
        (native_rows),
        (provider_config),
        _window(datetime(2023, 1, 1), datetime(2023, 1, 31)),
        series=_series(native_rows, provider_config),
    )

    assert result.value["time"].to_list() == [datetime(2023, 1, 1), datetime(2023, 1, 31)]


def test_convert_daily_reads_naive_explicit_midnight_calendar_date() -> None:
    from rivretrieve._internal.conversion import convert

    endpoint = datetime(2023, 1, 31)
    provider_config = _config({"daily": _product(semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")))})
    native_rows = _rows(
        [
            {
                "station_id": "station-1",
                "product_id": "daily",
                "time": datetime(2023, 1, 31),
                "value": 1.0,
                "time_zone": "+00:00",
            }
        ],
        units={key: value.unit for key, value in provider_config.products.items()},
    )
    result = convert(
        (native_rows),
        (provider_config),
        _window(endpoint, endpoint),
        series=_series(native_rows, provider_config),
    )

    assert result.value.height == 1


def test_convert_clips_daily_unknown_zone_without_an_unknown_zone_warning() -> None:
    from rivretrieve._internal.conversion import convert

    provider_config = _config({"daily": _product(semantics=Daily(DayDefinition("09:00"), DailyLabelTime("00:00")))})
    native_rows = _rows(
        [
            {
                "station_id": f"station-{label:%Y-%m-%d}",
                "product_id": "daily",
                "time": label,
                "value": 1.0,
                "time_zone": "unknown",
            }
            for label in [datetime(2022, 12, 31), datetime(2023, 1, 1)]
        ],
        units={key: value.unit for key, value in provider_config.products.items()},
    )
    result = convert(
        (native_rows),
        (provider_config),
        _window(datetime(2023, 1, 1), datetime(2023, 1, 1)),
        series=_series(native_rows, provider_config),
    )

    assert result.value["time"].to_list() == [datetime(2023, 1, 1)]
    assert result.issues == ()


def test_convert_rejects_non_midnight_daily_labels() -> None:
    from rivretrieve._internal.conversion import convert

    with pytest.raises(FatalContractError, match=r"timestamp anchor 00:00"):
        provider_config = _config(
            {"daily": _product(semantics=Daily(DayDefinition("unknown"), DailyLabelTime("00:00")))}
        )
        native_rows = _rows(
            [
                {
                    "station_id": "station-1",
                    "product_id": "daily",
                    "time": datetime(2023, 1, 1, 0, 0, 1),
                    "value": 1.0,
                    "time_zone": "+00:00",
                }
            ],
            units={key: value.unit for key, value in provider_config.products.items()},
        )
        convert(
            (native_rows),
            (provider_config),
            _window(datetime(2023, 1, 1), datetime(2023, 1, 1)),
            series=_series(native_rows, provider_config),
        )


def test_daily_conversion_accepts_and_preserves_declared_1100_label_on_calendar_date_axis() -> None:
    from rivretrieve._internal.conversion import convert

    row_time = datetime(2023, 1, 2, 11)
    provider_config = _config({"daily": _product(semantics=Daily(DayDefinition("00:00"), DailyLabelTime("11:00")))})
    native_rows = _rows(
        [{"station_id": "nve", "product_id": "daily", "time": row_time, "value": 2.0, "time_zone": "+00:00"}],
        units={key: value.unit for key, value in provider_config.products.items()},
    )
    result = convert(
        (native_rows),
        (provider_config),
        _window(datetime(2023, 1, 2, 23), datetime(2023, 1, 2, 23)),
        series=_series(native_rows, provider_config),
    )

    assert result.value["time"].to_list() == [row_time]


def test_convert_empty_rows_returns_valid_empty_canonical_frame() -> None:
    from rivretrieve._internal.conversion import convert

    provider_config = _config({"level": _product()})
    native_rows = pl.DataFrame(schema=RowsSchema.polars_schema)
    result = convert(
        (native_rows),
        (provider_config),
        _window(datetime(2023, 1, 1), datetime(2023, 1, 31)),
        series=_series(native_rows, provider_config),
    )
    expected = pl.DataFrame(schema=CanonicalRowsSchema.polars_schema)

    assert_frame_equal(result.value, expected)
    assert result.issues == ()


def test_convert_returns_exact_canonical_column_order_and_native_time_dtype() -> None:
    from rivretrieve._internal.conversion import convert

    provider_config = _config({"level": _product(Unit.CM)})
    native_rows = _rows(
        [
            {
                "station_id": "station-1",
                "product_id": "level",
                "time": datetime(2023, 1, 15, 12),
                "value": 250.0,
                "time_zone": "Etc/GMT+5",
            }
        ],
        units={key: value.unit for key, value in provider_config.products.items()},
    )
    result = convert(
        (native_rows),
        (provider_config),
        _window(datetime(2023, 1, 15, 11), datetime(2023, 1, 15, 13)),
        series=_series(native_rows, provider_config),
    )
    expected = pl.DataFrame(
        {
            "time": [datetime(2023, 1, 15, 12)],
            "time_zone": ["Etc/GMT+5"],
            "station_id": ["station-1"],
            "product_id": ["level"],
            "value": [2.5],
            "series_id": ["station-1:level"],
            "facts_id": ["station-1:level:facts"],
            "source_unit": ["cm"],
            "quantity": ["stage"],
            "unit": ["m"],
        },
        schema=CanonicalRowsSchema.polars_schema,
    )

    assert result.value.columns == [
        "time",
        "time_zone",
        "station_id",
        "product_id",
        "series_id",
        "facts_id",
        "quantity",
        "source_unit",
        "unit",
        "value",
    ]
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
    provider_config = _config({"level": _product(semantics=Hourly(IntervalDefinition("unknown")))})
    native_rows = rows
    result = convert(
        (native_rows),
        (provider_config),
        _window(datetime(2023, 1, 1, 1), datetime(2023, 1, 1, 2)),
        series=_series(native_rows, provider_config),
    )
    assert result.value["time"].to_list() == [datetime(2023, 1, 1, 1), datetime(2023, 1, 1, 2)]


def test_hourly_frequency_without_known_anchor_preserves_off_hour_source_label() -> None:
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
    provider_config = _config({"level": _product(semantics=Hourly(IntervalDefinition("unknown")))})
    definitions = _series(rows, provider_config)
    assert definitions[0].facts[0].timestamp_anchor.value is None
    result = convert(rows, provider_config, _window(datetime(2023, 1, 1), datetime(2023, 1, 2)), series=definitions)
    assert result.value["time"].to_list() == [datetime(2023, 1, 1, 1, 30)]


def test_unknown_temporal_support_clips_only_on_the_source_label_axis() -> None:
    from rivretrieve._internal.conversion import convert

    provider_config = _config({"reported": _product(semantics=UnknownTemporalSupport())})
    native_rows = _rows(
        [
            {
                "station_id": "station-1",
                "product_id": "reported",
                "time": timestamp,
                "value": float(index),
                "time_zone": "unknown",
            }
            for index, timestamp in enumerate(
                (datetime(2026, 8, 1, 11, 50), datetime(2026, 8, 1, 12), datetime(2026, 8, 1, 12, 10))
            )
        ],
        units={key: value.unit for key, value in provider_config.products.items()},
    )
    result = convert(
        (native_rows),
        (provider_config),
        _window(datetime(2026, 8, 1, 12), datetime(2026, 8, 1, 12)),
        series=_series(native_rows, provider_config),
    )

    assert result.value.select("time", "time_zone").rows() == [(datetime(2026, 8, 1, 12), "unknown")]


@pytest.mark.parametrize(
    ("label", "timestamp", "accepted"),
    [
        ("11:00", datetime(2023, 1, 2, 10, 59, 59, 999999), False),
        ("11:00", datetime(2023, 1, 2, 11, 0, 0, 1), False),
        ("11:00:00.000001", datetime(2023, 1, 2, 11, 0, 0, 1), True),
    ],
)
def test_daily_conversion_compares_full_declared_label_precision(label, timestamp, accepted) -> None:
    from rivretrieve._internal.conversion import convert

    rows = _rows([{"station_id": "nve", "product_id": "daily", "time": timestamp, "value": 1.0, "time_zone": "+00:00"}])
    arguments = (
        rows,
        _config({"daily": _product(semantics=Daily(DayDefinition("00:00"), DailyLabelTime(label)))}),
        _window(datetime(2023, 1, 2), datetime(2023, 1, 2, 23, 59, 59, 999999)),
    )
    if accepted:
        assert convert(*arguments, series=_series(arguments[0], arguments[1])).value["time"].to_list() == [timestamp]
    else:
        with pytest.raises(FatalContractError, match="timestamp anchor"):
            convert(*arguments, series=_series(arguments[0], arguments[1]))


def test_conversion_uses_response_unit_evidence_not_transport_route_unit() -> None:
    from rivretrieve._internal.conversion import convert

    rows = _rows(
        [
            {
                "station_id": "station",
                "product_id": "level",
                "time": datetime(2026, 1, 1),
                "time_zone": "unknown",
                "value": 200.0,
            }
        ],
        units={"level": Unit.CM},
    )
    config = _config({"level": _product(Unit.FT)})
    definitions = _series(rows, config)
    result = convert(rows, config, _window(datetime(2026, 1, 1), datetime(2026, 1, 2)), series=definitions)
    assert result.value["source_unit"].to_list() == ["cm"]
    assert result.value["unit"].to_list() == ["m"]
    assert result.value["value"].to_list() == [2.0]
