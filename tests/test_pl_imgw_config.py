from rivretrieve._internal.engine import CacheConfig, ObservationStoreConfig, Unit
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.pl_imgw.config import config


def test_pl_imgw_declares_current_bulk_store_and_native_products() -> None:
    assert config.cache == CacheConfig(store=ObservationStoreConfig(format_version=5))
    assert config.products[ProductId("discharge_daily")].unit is Unit.M3_S
    assert config.products[ProductId("stage_daily")].unit is Unit.CM
    assert config.products[ProductId("water_temperature_daily")].unit is Unit.DEG_C
