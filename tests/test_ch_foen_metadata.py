from rivretrieve._internal.providers.ch_foen.metadata import (
    ChFoenProductMetadata,
    ChFoenStationMetadata,
    ChFoenStationProductMetadata,
)


def test_ch_foen_station_metadata_validates_fixture_station() -> None:
    metadata = ChFoenStationMetadata(
        station_key="2016",
        native_id="2016",
        name="Brugg",
        water_body_name="Aare",
        water_body_type="river",
        chx=657000,
        chy=259360,
        latitude=47.4825,
        longitude=8.1949,
        country="Switzerland",
        source="Swiss Federal Office for the Environment FOEN / BAFU",
        api_source="Existenz.ch",
        api_url="https://api.existenz.ch/apiv1/hydro/locations",
        open_data_url="https://opendata.swiss",
        license_url="https://example.invalid/license",
        elevation_m=None,
        drainage_area_km2=None,
    )

    assert metadata.station_key == "2016"
    assert metadata.native_id == "2016"
    assert metadata.name == "Brugg"
    assert metadata.water_body_name == "Aare"
    assert metadata.latitude == 47.4825
    assert metadata.longitude == 8.1949


def test_ch_foen_station_metadata_preserves_extra_fields() -> None:
    metadata = ChFoenStationMetadata.model_validate(
        {
            "station_key": "2016",
            "native_id": "2016",
            "name": "Brugg",
            "water_body_name": "Aare",
            "water_body_type": "river",
            "chx": 657000,
            "chy": 259360,
            "latitude": 47.4825,
            "longitude": 8.1949,
            "country": "Switzerland",
            "source": "Swiss Federal Office for the Environment FOEN / BAFU",
            "api_source": "Existenz.ch",
            "api_url": "https://api.existenz.ch/apiv1/hydro/locations",
            "open_data_url": "https://opendata.swiss",
            "license_url": "https://example.invalid/license",
            "elevation_m": None,
            "drainage_area_km2": None,
            "source_specific": "kept",
        }
    )

    assert metadata.model_extra == {"source_specific": "kept"}


def test_ch_foen_station_metadata_allows_nullable_elevation_and_drainage_area() -> None:
    metadata = ChFoenStationMetadata(
        station_key="2016",
        native_id="2016",
        name="Brugg",
        water_body_name=None,
        water_body_type=None,
        chx=None,
        chy=None,
        latitude=47.4825,
        longitude=8.1949,
        country="Switzerland",
        source="Swiss Federal Office for the Environment FOEN / BAFU",
        api_source=None,
        api_url=None,
        open_data_url=None,
        license_url=None,
        elevation_m=None,
        drainage_area_km2=None,
    )

    assert metadata.elevation_m is None
    assert metadata.drainage_area_km2 is None


def test_ch_foen_product_metadata_validates_each_declared_product() -> None:
    rows = [
        ("DISCHARGE_DAILY_MEAN", "flow", ("flow", "flow_ls"), "flow_ls", True, "m3/s"),
        ("DISCHARGE_INSTANT", "flow", ("flow", "flow_ls"), "flow_ls", False, "m3/s"),
        ("STAGE_DAILY_MEAN", "height_abs", ("height_abs", "height"), "height", True, "m"),
        ("STAGE_INSTANT", "height_abs", ("height_abs", "height"), "height", False, "m"),
        ("WATER_TEMPERATURE_DAILY_MEAN", "temperature", ("temperature",), None, True, "degC"),
        ("WATER_TEMPERATURE_INSTANT", "temperature", ("temperature",), None, False, "degC"),
    ]

    products = [
        ChFoenProductMetadata(
            legacy_variable=legacy_variable,
            native_id=native_id,
            parameters=parameters,
            preferred_parameter=native_id,
            fallback_parameter=fallback_parameter,
            aggregate_daily=aggregate_daily,
            legacy_unit=legacy_unit,
            notes=None,
        )
        for legacy_variable, native_id, parameters, fallback_parameter, aggregate_daily, legacy_unit in rows
    ]

    assert [product.legacy_variable for product in products] == [row[0] for row in rows]


def test_ch_foen_station_product_metadata_validates_unknown_availability_basis() -> None:
    metadata = ChFoenStationProductMetadata(
        station_id="2016",
        product_id="discharge_daily_mean",
        native_parameters=("flow", "flow_ls"),
        availability_source="provider_station_catalogue_assumption",
        availability_note="Locations catalogue does not expose per-variable station availability.",
    )

    assert metadata.station_id == "2016"
    assert metadata.product_id == "discharge_daily_mean"
    assert metadata.native_parameters == ("flow", "flow_ls")
