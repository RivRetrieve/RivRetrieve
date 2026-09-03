from dataclasses import FrozenInstanceError, fields
from typing import Any, cast

import pytest

from rivretrieve._internal.engine import (
    CacheConfig,
    Daily,
    DailyLabelTime,
    DayDefinition,
    Instant,
    ObservationStoreConfig,
    ProductConfig,
    ProviderConfig,
    SourceCoordinates,
    Unit,
    ZoneValue,
)
from rivretrieve._internal.primitives import ProductId


def _product() -> ProductConfig:
    return ProductConfig(
        coordinates=SourceCoordinates({"parameter": "00060"}),
        unit=Unit.M3_S,
        semantics=Instant(),
    )


def test_unit_enum_is_exactly_the_current_native_unit_vocabulary() -> None:
    assert [(member.name, member.value) for member in Unit] == [
        ("M3_S", "m3/s"),
        ("M", "m"),
        ("CM", "cm"),
        ("FT3_S", "ft3/s"),
        ("FT", "ft"),
        ("L_S", "l/s"),
        ("MM", "mm"),
        ("DEG_C", "degC"),
    ]
    assert Unit("m3/s") is Unit.M3_S
    with pytest.raises(ValueError):
        Unit("kg/s")


@pytest.mark.parametrize("raw", ["Europe/Oslo", "+05:30", "-06:00", "-00:00", "unknown"])
def test_zone_value_accepts_each_admitted_kind_without_promotion(raw: str) -> None:
    assert ZoneValue(raw).value == raw


@pytest.mark.parametrize(
    "raw",
    ["", "Z", "EST", "+25:00", "+01:60", "+5:00", "05:00", "+01:000", "Not/A_Real_Zone"],
)
def test_zone_value_rejects_null_empty_z_abbreviation_and_invalid_offsets(raw: str) -> None:
    factory = cast("Any", ZoneValue)
    with pytest.raises(TypeError):
        factory(None)
    with pytest.raises(ValueError):
        ZoneValue(raw)


def test_zone_unknown_is_explicit_and_never_a_default() -> None:
    assert ZoneValue("unknown").value == "unknown"
    factory = cast("Any", ZoneValue)
    with pytest.raises(TypeError):
        factory()
    with pytest.raises(TypeError):
        factory(None)


def test_instant_and_daily_are_distinct_immutable_semantics() -> None:
    instant = Instant()
    daily = Daily(day_definition=DayDefinition("09:00"), label_time=DailyLabelTime("11:00"))
    assert type(instant) is not type(daily)
    assert not isinstance(instant, Daily)
    assert not isinstance(daily, Instant)
    with pytest.raises(FrozenInstanceError):
        cast("Any", daily).day_definition = DayDefinition("00:00")


@pytest.mark.parametrize("raw", ["09:00", "unknown"])
def test_daily_retains_declared_day_definition_including_unknown(raw: str) -> None:
    day_definition = DayDefinition(raw)
    daily = Daily(day_definition=day_definition, label_time=DailyLabelTime("00:00"))
    assert daily.day_definition is day_definition
    assert daily.day_definition.value == raw


@pytest.mark.parametrize("raw", ["", "9:00", "24:00", "09:60"])
def test_day_definition_rejects_null_empty_and_malformed_values(raw: str) -> None:
    day_factory = cast("Any", DayDefinition)
    daily_factory = cast("Any", Daily)
    with pytest.raises(TypeError):
        day_factory(None)
    with pytest.raises(ValueError):
        DayDefinition(raw)
    with pytest.raises(TypeError):
        daily_factory(day_definition="unknown")


@pytest.mark.parametrize("raw", ["00:00", "11:00", "23:59:59", "12:34:56.123456"])
def test_daily_label_time_accepts_strict_source_clocks(raw: str) -> None:
    assert DailyLabelTime(raw).value == raw


@pytest.mark.parametrize("raw", ["", "1:00", "24:00", "11:60", "11:00:60", "11:00:00.", "11:00:00.1234567"])
def test_daily_label_time_rejects_ambiguous_or_invalid_clocks(raw: str) -> None:
    with pytest.raises(ValueError):
        DailyLabelTime(raw)


def test_cache_config_declares_only_the_compiled_store_revision() -> None:
    store = ObservationStoreConfig(format_version=1)
    cache = CacheConfig(store=store)
    assert fields(CacheConfig)[0].name == "store"
    assert cache.store is store
    for attribute in ("path", "expiry", "refresh", "lifecycle"):
        assert not hasattr(cache, attribute)


def test_complete_product_declaration_preserves_required_typed_fields() -> None:
    coordinates = SourceCoordinates({"parameter": "00060"})
    unit = Unit.M3_S
    semantics = Instant()
    product = ProductConfig(coordinates=coordinates, unit=unit, semantics=semantics)
    assert product.coordinates is coordinates
    assert product.unit is unit
    assert product.semantics is semantics
    with pytest.raises(FrozenInstanceError):
        cast("Any", product).unit = Unit.M


def test_product_config_rejects_every_missing_required_field_at_runtime() -> None:
    factory = cast("Any", ProductConfig)
    coordinates = SourceCoordinates({"parameter": "00060"})
    unit = Unit.M3_S
    semantics = Instant()
    invalid_keyword_sets = [
        {"unit": unit, "semantics": semantics},
        {"coordinates": coordinates, "semantics": semantics},
        {"coordinates": coordinates, "unit": unit},
        {"coordinates": coordinates},
        {"unit": unit},
        {"semantics": semantics},
        {},
    ]
    for keywords in invalid_keyword_sets:
        with pytest.raises(TypeError):
            factory(**keywords)


def test_product_config_rejects_unparsed_or_invalid_field_values_at_runtime() -> None:
    factory = cast("Any", ProductConfig)
    coordinates = SourceCoordinates({"parameter": "00060"})
    unit = Unit.M3_S
    semantics = Instant()
    for keywords in (
        {"coordinates": None, "unit": unit, "semantics": semantics},
        {"coordinates": coordinates, "unit": "m3/s", "semantics": semantics},
        {"coordinates": coordinates, "unit": unit, "semantics": "instant"},
        {"coordinates": coordinates, "unit": unit, "semantics": None},
    ):
        with pytest.raises(TypeError):
            factory(**keywords)


def test_provider_config_is_product_keyed_provider_wide_and_cache_optional() -> None:
    product_id = ProductId("discharge_instantaneous")
    product = _product()
    zone = ZoneValue("Europe/Oslo")
    without_cache = ProviderConfig(zone=zone, products={product_id: product})
    cache = CacheConfig()
    with_cache = ProviderConfig(zone=zone, products={product_id: product}, cache=cache)
    assert without_cache.zone is zone
    assert without_cache.products[product_id] is product
    assert without_cache.cache is None
    assert with_cache.cache is cache
    assert not hasattr(product, "zone")
    for attribute in ("coordinates", "unit", "semantics"):
        assert not hasattr(with_cache, attribute)


def test_provider_config_copies_and_freezes_the_product_mapping() -> None:
    product_id = ProductId("discharge_instantaneous")
    product = _product()
    products = {product_id: product}
    config = ProviderConfig(zone=ZoneValue("Europe/Oslo"), products=products)
    with pytest.raises(TypeError):
        cast("Any", config.products)["other"] = product
    products[ProductId("other")] = product
    assert dict(config.products) == {product_id: product}


def test_provider_config_rejects_missing_and_invalid_fields_at_runtime() -> None:
    factory = cast("Any", ProviderConfig)
    zone = ZoneValue("Europe/Oslo")
    product = _product()
    products = {ProductId("flow"): product}
    for keywords in (
        {"products": products},
        {"zone": zone},
        {"zone": "Europe/Oslo", "products": products},
        {"zone": zone, "products": []},
        {"zone": zone, "products": {ProductId("flow"): object()}},
        {"zone": zone, "products": {"": product}},
        {"zone": zone, "products": products, "cache": object()},
    ):
        with pytest.raises(TypeError):
            factory(**keywords)
