from __future__ import annotations

import json
from collections import Counter
from dataclasses import FrozenInstanceError
from typing import Any, cast

import polars as pl
import pytest

from rivretrieve._internal.engine import (
    Daily,
    DayDefinition,
    Instant,
    ProductConfig,
    ProviderConfig,
    SourceCoordinates,
    Unit,
    ZoneValue,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.usgs_nwis.config import (
    UsgsNwisSourceCoordinates,
    config,
)
from rivretrieve._internal.providers.usgs_nwis.module import _CATALOGUE_PATH


def test_config_declares_all_six_usgs_products() -> None:
    declared = config()
    expected = {
        "discharge_daily_mean": ("dv", "00060", "00003", Unit.FT3_S, Daily),
        "discharge_instantaneous": ("iv", "00060", None, Unit.FT3_S, Instant),
        "stage_daily_mean": ("dv", "00065", "00003", Unit.FT, Daily),
        "stage_daily_max": ("dv", "00065", "00001", Unit.FT, Daily),
        "stage_daily_min": ("dv", "00065", "00002", Unit.FT, Daily),
        "stage_instantaneous": ("iv", "00065", None, Unit.FT, Instant),
    }

    assert set(declared.products) == set(expected)
    for product_id, (endpoint, parameter_code, statistic_code, unit, semantics_type) in expected.items():
        product = declared.products[ProductId(product_id)]
        assert isinstance(product.coordinates, SourceCoordinates)
        coordinates = product.coordinates.value
        assert isinstance(coordinates, UsgsNwisSourceCoordinates)
        assert coordinates.endpoint == endpoint
        assert coordinates.parameter_code == parameter_code
        assert coordinates.statistic_code == statistic_code
        assert product.unit is unit
        assert type(product.semantics) is semantics_type
        if semantics_type is Daily:
            assert isinstance(product.semantics, Daily)
            assert product.semantics.day_definition == DayDefinition("unknown")

    assert declared.cache is None


def test_usgs_source_coordinates_are_named_immutable_and_slotted() -> None:
    coordinates = UsgsNwisSourceCoordinates("dv", "00060", "00003")

    assert isinstance(coordinates, UsgsNwisSourceCoordinates)
    assert coordinates.endpoint == "dv"
    assert coordinates.parameter_code == "00060"
    assert coordinates.statistic_code == "00003"
    attribute = "endpoint"
    with pytest.raises(FrozenInstanceError):
        setattr(coordinates, attribute, "iv")
    assert not hasattr(coordinates, "__dict__")


@pytest.mark.parametrize(
    ("args", "exception"),
    [
        ((), TypeError),
        (("dv",), TypeError),
        (("dv", "00060"), TypeError),
        ((object(), "00060", None), TypeError),
        (("DV", "00060", "00003"), ValueError),
        (("bad", "00060", "00003"), ValueError),
        (("iv", object(), None), TypeError),
        (("iv", "0060", None), ValueError),
        (("iv", "000600", None), ValueError),
        (("iv", "00A60", None), ValueError),
        (("dv", "00060", object()), TypeError),
        (("dv", "00060", None), ValueError),
        (("dv", "00060", "003"), ValueError),
        (("dv", "00060", "00A03"), ValueError),
        (("iv", "00060", "00003"), ValueError),
    ],
)
def test_usgs_source_coordinates_reject_incomplete_or_invalid_values(
    args: tuple[object, ...],
    exception: type[Exception],
) -> None:
    constructor = cast(Any, UsgsNwisSourceCoordinates)
    with pytest.raises(exception):
        constructor(*args)


def test_product_and_provider_declarations_reject_incomplete_or_invalid_values() -> None:
    coordinates = UsgsNwisSourceCoordinates("iv", "00060", None)
    source_coordinates = SourceCoordinates(coordinates)
    product = ProductConfig(
        coordinates=source_coordinates,
        unit=Unit.FT3_S,
        semantics=Instant(),
    )
    product_constructor = cast(Any, ProductConfig)
    provider_constructor = cast(Any, ProviderConfig)

    with pytest.raises(TypeError):
        product_constructor(unit=Unit.FT3_S, semantics=Instant())
    with pytest.raises(TypeError):
        product_constructor(coordinates=source_coordinates, semantics=Instant())
    with pytest.raises(TypeError):
        product_constructor(coordinates=source_coordinates, unit=Unit.FT3_S)
    with pytest.raises(TypeError):
        product_constructor(coordinates, Unit.FT3_S, Instant())
    with pytest.raises(TypeError):
        product_constructor(source_coordinates, "ft3/s", Instant())
    with pytest.raises(TypeError):
        product_constructor(source_coordinates, Unit.FT3_S, "instant")
    with pytest.raises(TypeError):
        provider_constructor(products={"discharge_instantaneous": product})
    with pytest.raises(TypeError):
        provider_constructor(zone=ZoneValue("unknown"))
    with pytest.raises(TypeError):
        provider_constructor("unknown", {"discharge_instantaneous": product})
    with pytest.raises(TypeError):
        provider_constructor(ZoneValue("unknown"), {"": product})
    with pytest.raises(TypeError):
        provider_constructor(
            ZoneValue("unknown"),
            {"discharge_instantaneous": object()},
        )


def test_packaged_catalogue_timezone_abbreviations_are_exact() -> None:
    frame = pl.read_parquet(_CATALOGUE_PATH / "stations.parquet")
    tz_values: list[str] = []

    assert frame.height == 26_231
    for raw_metadata in frame["metadata"]:
        parsed = json.loads(raw_metadata)
        assert isinstance(parsed, dict)
        metadata = cast(dict[str, object], parsed)
        tz_cd = metadata.get("tz_cd")
        assert isinstance(tz_cd, str)
        tz_values.append(tz_cd)

    assert len(tz_values) == 26_231
    assert Counter(tz_values) == {
        "EST": 8_172,
        "CST": 6_588,
        "MST": 5_686,
        "PST": 4_845,
        "AKST": 519,
        "HST": 421,
    }


@pytest.mark.parametrize("abbrev", ("EST", "CST", "MST", "PST", "AKST", "HST"))
def test_config_declares_unknown_zone_and_rejects_catalogue_abbreviations(abbrev: str) -> None:
    assert config().zone == ZoneValue("unknown")
    with pytest.raises(ValueError):
        ZoneValue(abbrev)
