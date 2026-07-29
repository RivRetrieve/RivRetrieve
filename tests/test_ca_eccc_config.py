from dataclasses import FrozenInstanceError, fields
from typing import Any, cast, get_type_hints

import pytest

from rivretrieve._internal.engine import (
    CacheConfig,
    Daily,
    DayDefinition,
    SourceCoordinates,
    Unit,
    ZoneValue,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.ca_eccc import module as ca_eccc_module
from rivretrieve._internal.providers.ca_eccc.config import (
    HydatSourceCoordinates,
    config,
)
from rivretrieve._internal.providers.ca_eccc.parse import parse


def test_ca_eccc_config_declares_both_hydat_products() -> None:
    assert set(config.products) == {
        ProductId("discharge_daily_mean"),
        ProductId("stage_daily_mean"),
    }

    discharge = config.products[ProductId("discharge_daily_mean")]
    assert discharge.coordinates == SourceCoordinates(HydatSourceCoordinates("DLY_FLOWS", "FLOW", "FLOW_SYMBOL"))
    assert discharge.unit is Unit.M3_S
    assert discharge.semantics == Daily(DayDefinition("unknown"))

    stage = config.products[ProductId("stage_daily_mean")]
    assert stage.coordinates == SourceCoordinates(HydatSourceCoordinates("DLY_LEVELS", "LEVEL", "LEVEL_SYMBOL"))
    assert stage.unit is Unit.M
    assert stage.semantics == Daily(DayDefinition("unknown"))

    assert type(config.cache) is CacheConfig
    assert fields(CacheConfig) == ()
    for forbidden_attribute in ("path", "layout", "expiry", "refresh", "lifecycle"):
        assert not hasattr(config.cache, forbidden_attribute)

    assert ca_eccc_module.config is config
    assert not hasattr(ca_eccc_module, "fetch")
    assert ca_eccc_module.parse is parse


def test_ca_eccc_source_coordinates_are_named_and_immutable() -> None:
    coordinates = HydatSourceCoordinates(
        "DLY_FLOWS",
        "FLOW",
        "FLOW_SYMBOL",
    )

    assert tuple(field.name for field in fields(HydatSourceCoordinates)) == (
        "table_name",
        "value_prefix",
        "symbol_prefix",
    )
    assert get_type_hints(HydatSourceCoordinates) == {
        "table_name": str,
        "value_prefix": str,
        "symbol_prefix": str,
    }
    assert coordinates.table_name == "DLY_FLOWS"
    assert coordinates.value_prefix == "FLOW"
    assert coordinates.symbol_prefix == "FLOW_SYMBOL"
    assert not isinstance(coordinates, dict)
    assert not hasattr(coordinates, "__dict__")

    for field_name in ("table_name", "value_prefix", "symbol_prefix"):
        with pytest.raises(FrozenInstanceError):
            setattr(cast(Any, coordinates), field_name, "different")

    for product in config.products.values():
        assert isinstance(product.coordinates.value, HydatSourceCoordinates)


def test_ca_eccc_config_declares_unknown_day_definition_and_zone() -> None:
    assert config.zone == ZoneValue("unknown")
    assert config.zone.value == "unknown"
    assert config.zone.value not in {"UTC", "00:00"}

    for product_id in (
        ProductId("discharge_daily_mean"),
        ProductId("stage_daily_mean"),
    ):
        semantics = config.products[product_id].semantics
        assert type(semantics) is Daily
        assert semantics == Daily(DayDefinition("unknown"))
        assert isinstance(semantics, Daily)
        assert semantics.day_definition.value == "unknown"
        assert semantics.day_definition.value not in {"UTC", "00:00"}
