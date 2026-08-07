from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any, cast

import pytest

from rivretrieve._internal.engine import (
    Daily,
    DayDefinition,
    Instant,
    ProductConfig,
    ProviderConfig,
    SourceCoordinates,
    StopConvention,
    Unit,
    WindowDeclaration,
    WindowGranularity,
    WindowRenderingVocabulary,
    ZoneValue,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.usgs_nwis import module as usgs_nwis_module
from rivretrieve._internal.providers.usgs_nwis.config import (
    UsgsNwisSourceCoordinates,
    config,
    window_declarations,
)


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


def test_usgs_window_declarations_cover_every_configured_product_with_date_inclusive_rendering() -> None:
    declarations = window_declarations()
    expected = WindowDeclaration(WindowGranularity("date"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE)

    assert set(declarations.products) == set(config().products)
    assert all(declaration == expected and declaration.size is None for declaration in declarations.products.values())
    assert usgs_nwis_module.window_declarations is declarations


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


@pytest.mark.parametrize("abbrev", ("EST", "CST", "MST", "PST", "AKST", "HST"))
def test_config_declares_unknown_zone_and_rejects_catalogue_abbreviations(abbrev: str) -> None:
    assert config().zone == ZoneValue("unknown")
    with pytest.raises(ValueError):
        ZoneValue(abbrev)
