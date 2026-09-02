import rivretrieve as rr
from rivretrieve._internal.engine import UnknownTemporalSupport
from rivretrieve._internal.providers.ba_fhmzbih.declaration import declaration
from rivretrieve._internal.providers.registration import LiveStages
from tests._catalogue import catalogue_path, catalogue_reader, provider_info


def test_ba_fhmzbih_catalogue_and_live_declaration():
    assert "ba_fhmzbih" in rr.providers()
    assert isinstance(declaration.observations, LiveStages)
    assert catalogue_reader("ba_fhmzbih").read_stations().data.height == 2
    products = catalogue_reader("ba_fhmzbih").read_products().data
    assert catalogue_reader("ba_fhmzbih").read_station_products().data.height == 3
    assert set(products.select("frequency", "statistic", "period_type", "period_anchor").iter_rows()) == {
        ("unknown", "unknown", "unknown", "unknown")
    }
    assert all(
        isinstance(product.semantics, UnknownTemporalSupport)
        for product in declaration.observations.stages.config.products.values()
    )
    assert set(rr.products("ba_fhmzbih")) == {
        "discharge_reported",
        "stage_reported",
        "water_temperature_reported",
    }
    assert provider_info("ba_fhmzbih").provider_id == "ba_fhmzbih"
    assert catalogue_path("ba_fhmzbih").exists()
