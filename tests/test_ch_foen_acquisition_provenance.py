import json
import shutil
from pathlib import Path

import pytest

from rivretrieve._internal.acquisition_provenance import verify_provenance_recordings
from rivretrieve._internal.catalogues.artifact import CorruptCatalogArtifactError, load_packaged_catalogue_artifact
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ch_foen.generate_catalogue import main
from rivretrieve._internal.providers.ch_foen.origins import build_acquisition_provenance


def test_swiss_provenance_separates_bafu_from_existenz() -> None:
    provenance = build_acquisition_provenance()
    assert {source.source_id for source in provenance.source_records} == {"ch_bafu", "ch_existenz"}
    bindings = {item.fact_group: item.source_id for item in provenance.fact_bindings}
    assert {
        "bafu_station_product_values": "ch_bafu",
        "existenz_transport_and_absence": "ch_existenz",
    }.items() <= bindings.items()
    assert {statement.kind for source in provenance.source_records for statement in source.statements} == {
        "license",
        "citation",
        "terms",
    }


def test_swiss_terms_recordings_and_native_bytes_are_verified(tmp_path: Path) -> None:
    verify_provenance_recordings(build_acquisition_provenance(), Path.cwd())
    for name in ("ch_foen_terms_bafu.html", "ch_foen_terms_existenz.html"):
        source = Path("tests/test_data") / name
        target = tmp_path / source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    target = tmp_path / "tests/test_data/ch_foen_terms_existenz.html"
    target.write_bytes(target.read_bytes() + b"x")
    with pytest.raises(FatalContractError, match="ch_foen_terms_existenz digest mismatch"):
        verify_provenance_recordings(build_acquisition_provenance(), tmp_path)
    native = tmp_path / "native.parquet"
    shutil.copy2("src/rivretrieve/_internal/providers/ch_foen/catalogue/native.parquet", native)
    native.write_bytes(native.read_bytes() + b"x")
    with pytest.raises(FatalContractError, match="native table digest mismatch"):
        main(["--native", str(native), "--out", str(tmp_path / "out")])


def test_swiss_real_loader_rejects_runtime_capture_for_catalogue_facts(tmp_path: Path) -> None:
    source = Path("src/rivretrieve/_internal/providers/ch_foen/catalogue")
    copied = tmp_path / "catalogue"
    shutil.copytree(source, copied)
    document = json.loads((copied / "provenance.json").read_text())
    acquisition = document["source_records"][0]["acquisitions"][0]
    acquisition.update(
        {
            "method": "runtime_http_request",
            "instant_type": "runtime",
            "retrieved_at_start": None,
            "retrieved_at_end": None,
        }
    )
    (copied / "provenance.json").write_text(json.dumps(document))
    with pytest.raises(CorruptCatalogArtifactError, match="runtime acquisitions may bind only runtime observation"):
        load_packaged_catalogue_artifact(copied, on_issue="raise")
