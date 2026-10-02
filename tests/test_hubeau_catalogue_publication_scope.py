import pytest

from rivretrieve._internal.catalogues.native import read_native_table
from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import build_catalogue
from rivretrieve._internal.providers.fr_hubeau.origins import FRANCE_ORIGIN_DECLARATIONS
from tests.test_fr_hubeau_generate_catalogue import NATIVE_PATH, _availability, _refresh, _sample_payloads


@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_refresh_accepts_changed_complete_populations(retained_evidence_root):
    result = _refresh(*_sample_payloads(retained_evidence_root))
    assert not result.issues
    assert result.value.data.height == 4


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet")
def test_hubeau_catalogue_contains_only_its_publication_service(retained_evidence_root):
    # This assertion owns a generation boundary, not inspection of a cached projection.
    result = build_catalogue(
        read_native_table(retained_evidence_root / NATIVE_PATH), FRANCE_ORIGIN_DECLARATIONS, _availability()
    )
    assert set(result.products["product_id"]) == {
        "discharge_daily_mean",
        "discharge_daily_max",
        "stage_daily_max",
        "water_temperature_reported",
    }
    assert {source.source_id for source in result.acquisition_provenance.source_records} == {"fr_hubeau"}


@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_referentiel_stations_full.json",
    "tests/test_data/fr_hubeau_temperature_stations_full.json",
)
def test_native_refresh_rejects_unconsumed_pagination(retained_evidence_root):
    hydro, temperature = _sample_payloads(retained_evidence_root)
    hydro["next"] = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?page=2"
    result = _refresh(hydro, temperature)
    assert result.issues
    assert "pagination" in result.issues[0].message


@pytest.mark.derived("src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet")
def test_refreshed_native_build_retains_unknown_pairs_without_observation_claims(retained_evidence_root):
    import json
    from pathlib import Path

    import polars as pl

    from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import NativeInventoryCapture
    from tests.test_fr_hubeau_generate_catalogue import CURRENT_NATIVE_PATH

    manifest = Path(__file__).parents[1] / "maintenance/catalogue/fr_hubeau/inventory/native_capture.json"
    capture = NativeInventoryCapture.model_validate(json.loads(manifest.read_text()))
    result = build_catalogue(
        read_native_table(retained_evidence_root / CURRENT_NATIVE_PATH),
        FRANCE_ORIGIN_DECLARATIONS,
        _availability(),
        native_capture=capture,
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
