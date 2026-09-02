from rivretrieve._internal.engine import Instant, StopConvention, Unit, ZoneValue
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.ch_foen.config import ChFoenSourceCoordinates, config, window_declarations


def test_three_instantaneous_products_and_exact_source_fallback_units() -> None:
    value = config()
    assert value.zone == ZoneValue("+00:00")
    assert set(value.products) == {
        ProductId("discharge_instantaneous"),
        ProductId("stage_instantaneous"),
        ProductId("water_temperature_instantaneous"),
    }
    expected = {
        "discharge_instantaneous": (("flow", Unit.M3_S),),
        "stage_instantaneous": (("height_abs", Unit.M), ("height", Unit.M)),
        "water_temperature_instantaneous": (("temperature", Unit.DEG_C),),
    }
    for product_id, alternatives in expected.items():
        product = value.products[ProductId(product_id)]
        assert isinstance(product.semantics, Instant)
        coordinates = product.coordinates.value
        assert isinstance(coordinates, ChFoenSourceCoordinates)
        assert tuple((field.name, field.unit) for field in coordinates.fields) == alternatives
    assert all(d.stop_convention is StopConvention.INCLUSIVE for d in window_declarations().products.values())
