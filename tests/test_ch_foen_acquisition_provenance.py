import shutil
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.acquisition_provenance import verify_provenance_recordings
from rivretrieve._internal.catalogues.artifact import CorruptCatalogArtifactError, load_packaged_catalogue_artifact
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ch_foen.generate_catalogue import main
from rivretrieve._internal.providers.ch_foen.origins import build_acquisition_provenance
from tests._provenance import write_evidence_table


def test_swiss_provenance_separates_bafu_from_existenz() -> None:
    provenance = build_acquisition_provenance()
    assert {source.source_id for source in provenance.source_records} == {"ch_bafu", "ch_existenz"}
    bindings = {item.fact_group: item.source_id for item in provenance.fact_bindings}
    assert {
        "bafu_station_values": "ch_bafu",
        "bafu_product_values": "ch_bafu",
        "bafu_observation_values": "ch_bafu",
        "bafu_temporal_support_not_identified": "ch_bafu",
        "existenz_absence": "ch_existenz",
        "existenz_transport": "ch_existenz",
    }.items() <= bindings.items()
    assert {statement.kind for source in provenance.source_records for statement in source.statements} == {
        "license",
        "citation",
        "terms",
    }


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/ch_foen/catalogue/native.parquet",
    "tests/test_data/ch_foen_2135_flux_2020-01-01.recording.json",
    "tests/test_data/ch_foen_2135_rest_2026-09-01.recording.json",
    "tests/test_data/ch_foen_bafu_current_hydrological_data.html",
    "tests/test_data/ch_foen_bafu_hydrology_data_service.html",
    "tests/test_data/ch_foen_parameters_2026-09-02.recording.json",
    "tests/test_data/ch_foen_terms_bafu.html",
    "tests/test_data/ch_foen_terms_existenz.html",
)
def test_swiss_terms_recordings_and_native_bytes_are_verified(retained_evidence_root: Path, tmp_path: Path) -> None:
    verify_provenance_recordings(build_acquisition_provenance(), retained_evidence_root)
    for name in (
        "ch_foen_terms_bafu.html",
        "ch_foen_terms_existenz.html",
        "ch_foen_parameters_2026-09-02.recording.json",
        "ch_foen_2135_rest_2026-09-01.recording.json",
        "ch_foen_2135_flux_2020-01-01.recording.json",
        "ch_foen_bafu_current_hydrological_data.html",
        "ch_foen_bafu_hydrology_data_service.html",
    ):
        source = Path("tests/test_data") / name
        target = tmp_path / source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((retained_evidence_root / source).read_bytes())
    target = tmp_path / "tests/test_data/ch_foen_terms_existenz.html"
    target.write_bytes(target.read_bytes() + b"x")
    with pytest.raises(FatalContractError, match="ch_foen_terms_existenz digest mismatch"):
        verify_provenance_recordings(build_acquisition_provenance(), tmp_path)
    native = tmp_path / "native.parquet"
    shutil.copy2(
        retained_evidence_root / "src/rivretrieve/_internal/providers/ch_foen/catalogue/native.parquet", native
    )
    native.write_bytes(native.read_bytes() + b"x")
    with pytest.raises(FatalContractError, match="native table digest mismatch"):
        main(
            ["--native", str(native), "--out", str(tmp_path / "out")] + ["--evidence-root", str(retained_evidence_root)]
        )


def test_swiss_real_loader_rejects_runtime_capture_for_catalogue_facts(tmp_path: Path) -> None:
    source = Path("src/rivretrieve/_internal/providers/ch_foen/catalogue")
    copied = tmp_path / "catalogue"
    shutil.copytree(source, copied)
    acquisitions = pl.read_parquet(copied / "provenance_acquisitions.parquet")
    changed = acquisitions.with_columns(
        pl.when(pl.col("acquisition_key") == 0)
        .then(pl.lit(value, dtype=acquisitions.schema[name]))
        .otherwise(pl.col(name))
        .alias(name)
        for name, value in {
            "method": "runtime_http_request",
            "instant_type": "runtime",
            "retrieved_at_start": None,
            "retrieved_at_end": None,
        }.items()
    )
    write_evidence_table(copied, "provenance_acquisitions.parquet", changed)
    with pytest.raises(CorruptCatalogArtifactError, match="runtime acquisitions may bind only runtime observation"):
        load_packaged_catalogue_artifact(copied, on_issue="raise")
