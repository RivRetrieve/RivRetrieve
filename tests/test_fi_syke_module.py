from __future__ import annotations

from tests._catalogue import catalogue_reader


def test_fi_syke_station_coordinates_in_finland_range() -> None:
    result = catalogue_reader("fi_syke").read_stations()
    assert result.data["latitude"].null_count() == 0
    assert result.data["longitude"].null_count() == 0
    assert result.data["crs"].drop_nulls().unique().to_list() == ["EPSG:4258"]
    lats = result.data["latitude"].to_list()
    lons = result.data["longitude"].to_list()
    assert all(59.5 <= lat <= 70.2 for lat in lats), "All latitudes should be in Finland's range"
    assert all(19.0 <= lon <= 31.6 for lon in lons), "All longitudes should be in Finland's range"


def test_fi_syke_products_cover_the_three_admitted_quantities() -> None:
    result = catalogue_reader("fi_syke").read_products()
    assert sorted(result.data["product_id"].to_list()) == [
        "discharge_reported",
        "stage_reported",
        "water_temperature_reported",
    ]
    assert result.data["frequency"].to_list() == ["daily"] * 3


def test_fi_syke_each_station_is_witnessed_for_exactly_one_product() -> None:
    """station_id is Paikka_Id, SYKE's own quantity-specific observation point --
    confirmed via SYKE's public WFS (one feature per Paikka_Id, split per
    quantity) and independently via CAMELS-Finland. A gauge with both discharge
    and stage is two Paikka_Id stations, not one with two available products --
    Nro (SYKE's site code) is not a stable per-installation identity (checked
    live: the same Nro can name a site discontinued decades ago and an
    unrelated, currently active site tens of kilometres away)."""
    result = catalogue_reader("fi_syke").read_station_products()
    available = result.data.filter(result.data["availability"] == "available")
    counts = available.group_by("station_id").len()
    assert counts["len"].to_list() == [1] * counts.height
    assert available.height == catalogue_reader("fi_syke").read_stations().data.height


def test_fi_syke_stage_vertical_reference_is_above_sea_level() -> None:
    """Vedenkorkeus publishes an absolute water-surface elevation, not a small
    gauge-relative reading: active stage stations range -223 to 24,469 cm,
    matching Finland's coast-to-Lapland relief, independently corroborated by
    VedenkTasoTieto's per-site national-datum corrections (see
    research/fi-syke-series-identity.md, verification-evidence)."""
    descriptions = catalogue_reader("fi_syke").artifact.source_descriptions.descriptions
    by_product = {description.product_id: description.facts[0] for description in descriptions}
    assert by_product["stage_reported"].vertical_reference.value == "above_sea_level"
    assert by_product["discharge_reported"].vertical_reference.state == "not_established"
    assert by_product["water_temperature_reported"].vertical_reference.state == "not_established"


def test_fi_syke_catalogue_descriptions_admit_all_three_quantities() -> None:
    from rivretrieve._internal.catalogues.source_descriptions import content_identified_descriptions
    from rivretrieve._internal.providers.fi_syke.catalogue_series import describe_catalogue
    from rivretrieve._internal.source_series import admission

    artifact = catalogue_reader("fi_syke").artifact
    assert artifact.source_descriptions is not None
    assert content_identified_descriptions(describe_catalogue(artifact)) == artifact.source_descriptions
    by_product = {d.product_id: d.facts[0] for d in artifact.source_descriptions.descriptions}
    assert {k: f.quantity.value for k, f in by_product.items()} == {
        "discharge_reported": "discharge",
        "stage_reported": "stage",
        "water_temperature_reported": "temperature",
    }
    assert {k: admission(f).target_unit for k, f in by_product.items()} == {
        "discharge_reported": "m3/s",
        "stage_reported": "m",
        "water_temperature_reported": "degC",
    }
