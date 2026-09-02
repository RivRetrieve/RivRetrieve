import rivretrieve as rr
from rivretrieve._internal.providers.ba_fhmzbih.declaration import declaration
from rivretrieve._internal.providers.registration import LiveStages
from tests._catalogue import catalogue_path, catalogue_reader, provider_info


def test_ba_fhmzbih_catalogue_and_live_declaration():
    assert "ba_fhmzbih" in rr.providers()
    assert isinstance(declaration.observations, LiveStages)
    assert catalogue_reader("ba_fhmzbih").read_stations().data.height == 2
    assert catalogue_reader("ba_fhmzbih").read_station_products().data.height == 3
    assert set(rr.products("ba_fhmzbih")) == {
        "discharge_instantaneous",
        "stage_instantaneous",
        "water_temperature_instantaneous",
    }
    assert provider_info("ba_fhmzbih").provider_id == "ba_fhmzbih"
    assert catalogue_path("ba_fhmzbih").exists()
