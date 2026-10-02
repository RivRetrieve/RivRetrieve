from __future__ import annotations

import shutil
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.catalogues.artifact import CorruptCatalogArtifactError, load_packaged_catalogue_artifact
from rivretrieve._internal.providers.ba_fhmzbih.declaration import declaration as bosnia
from rivretrieve._internal.providers.fr_hubeau.declaration import declaration as france
from rivretrieve._internal.providers.th_thaiwater.declaration import declaration as thailand

_CERTIFIED_PROVIDER_IDS = (
    "ba_fhmzbih",
    "ca_eccc",
    "ch_foen",
    "cz_chmi",
    "fr_hubeau",
    "fr_hydroportail",
    "lt_lhmt",
    "th_thaiwater",
    "usgs_nwis",
    "za_dws",
)


@pytest.mark.parametrize("provider_id", _CERTIFIED_PROVIDER_IDS)
def test_certified_provider_refuses_missing_provenance(provider_id: str, tmp_path: Path) -> None:
    catalogue = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers" / provider_id / "catalogue"
    for source in catalogue.iterdir():
        if source.name not in {"native.parquet", "provenance.json"}:
            shutil.copy2(source, tmp_path / source.name)

    with pytest.raises(CorruptCatalogArtifactError, match="acquisition provenance is required"):
        load_packaged_catalogue_artifact(tmp_path)


def test_bosnia_loader_admits_acquired_baseline_without_withholding() -> None:
    artifact = load_packaged_catalogue_artifact(bosnia.catalogue)
    assert artifact.stations.height == 60
    assert artifact.station_products.height == 180
    assert artifact.acquisition_provenance is not None
    assert artifact.acquisition_provenance.header.withheld_facts == ()


def test_france_loader_admits_all_evidenced_baseline_pairs(retained_evidence_root: Path) -> None:
    artifact = load_packaged_catalogue_artifact(france.catalogue)
    native = pl.read_parquet(
        retained_evidence_root / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet"
    )
    assert set(artifact.stations["station_id"]) == set(native["code_station"])
    expected = {
        (row["code_station"], product)
        for row in native.select("code_station", "source_endpoint").iter_rows(named=True)
        for product in (
            ("water_temperature_reported",)
            if row["source_endpoint"] == "temperature/station"
            else ("discharge_daily_mean", "discharge_daily_max", "stage_daily_max")
        )
    }
    assert set(artifact.station_products.select("station_id", "product_id").iter_rows()) == expected
    assert artifact.acquisition_provenance is not None
    assert not artifact.acquisition_provenance.header.withheld_facts


def test_thailand_loader_retains_every_acquired_pair() -> None:
    artifact = load_packaged_catalogue_artifact(thailand.catalogue)
    assert artifact.stations.height == 825
    assert artifact.station_products.height == 1650
    assert set(artifact.station_products["station_id"]) == set(artifact.stations["station_id"])
    assert artifact.acquisition_provenance is not None
    assert artifact.acquisition_provenance.header.withheld_facts == ()


def test_public_find_admits_previously_withheld_baseline_stations() -> None:
    for provider_id, station_id in (("ba_fhmzbih", "1010"), ("fr_hubeau", "01010000")):
        selection = rr.find(provider=provider_id, station=station_id)
        assert selection.series
        assert not selection.acquisition_provenance[0].header.withheld_facts

    selection = rr.find(provider="th_thaiwater", station="1", quantity="stage")
    assert rr.as_frame(selection).height == 1
    provenance = selection.acquisition_provenance[0]
    assert provenance.header.withheld_facts == ()
