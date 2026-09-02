import json
import shutil
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance, verify_provenance_recordings
from rivretrieve._internal.catalogues.artifact import CorruptCatalogArtifactError, load_packaged_catalogue_artifact
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ba_fhmzbih.generate_catalogue import main
from rivretrieve._internal.providers.ba_fhmzbih.origins import build_acquisition_provenance


def test_bosnia_provenance_withholds_unresolved_issuers_exactly() -> None:
    provenance = build_acquisition_provenance()
    bound = {fact for binding in provenance.fact_bindings for fact in binding.facts}
    withheld = {fact for item in provenance.withheld_facts for fact in item.facts}
    assert "source.station:4024.identity_location" in bound
    assert "source.observation:4024.values_quality" in bound
    assert len([fact for fact in withheld if fact.startswith("station:")]) == 58
    assert len([fact for fact in withheld if fact.startswith("observation:")]) == 58
    assert len([fact for fact in withheld if fact.startswith("station_product:")]) == 177
    row_locators = [locator for group in provenance.withheld_facts for locator in group.catalogue_rows]
    assert len(row_locators) == 235
    assert {locator.product_id for locator in row_locators if locator.carrier == "station_product"} == {
        "discharge_reported",
        "stage_reported",
        "water_temperature_reported",
    }
    assert set(provenance.fact_universe) == bound | withheld


def test_bosnia_terms_recording_and_native_bytes_are_verified(tmp_path: Path) -> None:
    verify_provenance_recordings(build_acquisition_provenance(), Path.cwd())
    evidence = Path("tests/test_data/ba_fhmzbih_terms_absence.html")
    target = tmp_path / evidence
    target.parent.mkdir(parents=True)
    target.write_bytes(evidence.read_bytes() + b"x")
    with pytest.raises(FatalContractError, match="ba_fhmzbih_terms_absence digest mismatch"):
        verify_provenance_recordings(build_acquisition_provenance(), tmp_path)
    native = tmp_path / "native.parquet"
    shutil.copy2("src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet", native)
    native.write_bytes(native.read_bytes() + b"x")
    with pytest.raises(FatalContractError, match="native table digest mismatch"):
        main(["--native", str(native), "--out", str(tmp_path / "out")])


def test_bosnia_row_scoped_fact_rejects_a_detached_locator_in_real_loader(tmp_path: Path) -> None:
    source = Path("src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue")
    mutated = tmp_path / "catalogue"
    shutil.copytree(source, mutated)
    document = json.loads((mutated / "provenance.json").read_text())
    withheld = next(item for item in document["withheld_facts"] if item["facts"] == ["station:1010.identity_location"])
    withheld["catalogue_rows"][0]["station_id"] = "DOES_NOT_EXIST"
    stations = pl.read_parquet(mutated / "stations.parquet")
    exposed = stations.row(0, named=True)
    exposed["station_id"] = "1010"
    pl.concat((stations, pl.DataFrame([exposed], schema=stations.schema))).write_parquet(mutated / "stations.parquet")
    (mutated / "provenance.json").write_text(json.dumps(document))

    with pytest.raises(CorruptCatalogArtifactError, match="scoped fact identity|catalogue row locator"):
        load_packaged_catalogue_artifact(mutated, on_issue="raise")


def test_bosnia_row_scoped_fact_model_rejects_a_detached_locator() -> None:
    document = json.loads(Path("src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/provenance.json").read_text())
    withheld = next(item for item in document["withheld_facts"] if item["facts"] == ["station:1010.identity_location"])
    withheld["catalogue_rows"][0]["station_id"] = "DOES_NOT_EXIST"

    with pytest.raises(ValidationError, match="scoped fact identity|catalogue row locator"):
        AcquisitionProvenance.model_validate(document)


def test_bosnia_row_scoped_fact_model_requires_its_locator() -> None:
    document = json.loads(Path("src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/provenance.json").read_text())
    withheld = next(item for item in document["withheld_facts"] if item["facts"] == ["station:1010.identity_location"])
    withheld["catalogue_rows"] = []

    with pytest.raises(ValidationError, match="catalogue row locator|scoped fact identity"):
        AcquisitionProvenance.model_validate(document)


def test_bosnia_real_loader_rejects_exposed_row_when_withheld_locator_is_removed(tmp_path: Path) -> None:
    source = Path("src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue")
    mutated = tmp_path / "catalogue"
    shutil.copytree(source, mutated)
    document = json.loads((mutated / "provenance.json").read_text())
    withheld = next(item for item in document["withheld_facts"] if item["facts"] == ["station:1010.identity_location"])
    withheld["catalogue_rows"] = []
    stations = pl.read_parquet(mutated / "stations.parquet")
    exposed = stations.row(0, named=True)
    exposed["station_id"] = "1010"
    pl.concat((stations, pl.DataFrame([exposed], schema=stations.schema))).write_parquet(mutated / "stations.parquet")
    (mutated / "provenance.json").write_text(json.dumps(document))

    with pytest.raises(CorruptCatalogArtifactError, match="catalogue row locator|scoped fact identity"):
        load_packaged_catalogue_artifact(mutated, on_issue="raise")
