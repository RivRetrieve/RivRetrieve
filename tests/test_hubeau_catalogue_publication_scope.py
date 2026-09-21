from tests.test_fr_hubeau_generate_catalogue import _catalogue, _refresh, _sample_payloads


def test_native_refresh_accepts_changed_complete_populations():
    result = _refresh(*_sample_payloads())
    assert not result.issues
    assert result.value.data.height == 4


def test_hubeau_catalogue_contains_only_its_publication_service():
    result = _catalogue()
    assert set(result.products["product_id"]) == {
        "discharge_daily_mean",
        "discharge_daily_max",
        "stage_daily_max",
        "water_temperature_reported",
    }
    assert {source.source_id for source in result.acquisition_provenance.source_records} == {"fr_hubeau"}


def test_native_refresh_rejects_unconsumed_pagination():
    hydro, temperature = _sample_payloads()
    hydro["next"] = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?page=2"
    result = _refresh(hydro, temperature)
    assert result.issues
    assert "pagination" in result.issues[0].message


def test_refreshed_native_build_retains_unknown_pairs_without_observation_claims():
    import json
    from pathlib import Path

    import polars as pl

    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import NativeInventoryCapture, build_catalogue
    from rivretrieve._internal.providers.fr_hubeau.origins import FRANCE_ORIGIN_DECLARATIONS
    from tests.test_fr_hubeau_generate_catalogue import CURRENT_NATIVE_PATH, _availability

    manifest = Path(__file__).parents[1] / "maintenance/catalogue/fr_hubeau/inventory/native_capture.json"
    capture = NativeInventoryCapture.model_validate(json.loads(manifest.read_text()))
    result = build_catalogue(
        read_native_table(CURRENT_NATIVE_PATH), FRANCE_ORIGIN_DECLARATIONS, _availability(), native_capture=capture
    )
    previous = {pair.code_station for pair in _availability().pairs}
    new_pairs = result.station_products.filter(~pl.col("station_id").is_in(previous))
    assert new_pairs.height == 66
    assert set(new_pairs["availability"]) == {"unknown"}
    acquisitions = [item for source in result.acquisition_provenance.source_records for item in source.acquisitions]
    assert not any(
        item.acquisition_id.startswith("availability_" + station + "_")
        for station in new_pairs["station_id"].unique()
        for item in acquisitions
    )
