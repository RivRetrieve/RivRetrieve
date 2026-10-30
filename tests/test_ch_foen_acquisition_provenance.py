import shutil
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.catalogues.artifact import CorruptCatalogArtifactError, load_packaged_catalogue_artifact
from tests._provenance import write_evidence_table


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
