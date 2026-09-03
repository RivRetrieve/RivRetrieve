from dataclasses import fields

from rivretrieve._internal.engine import CacheConfig, ObservationStoreConfig, Unit
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.ca_eccc.config import config


def test_ca_eccc_declares_bulk_store_and_native_products() -> None:
    assert config.cache == CacheConfig(store=ObservationStoreConfig(format_version=2))
    assert tuple(field.name for field in fields(CacheConfig)) == ("store",)
    assert config.products[ProductId("discharge_daily_mean")].unit is Unit.M3_S
    assert config.products[ProductId("stage_daily_mean")].unit is Unit.M
