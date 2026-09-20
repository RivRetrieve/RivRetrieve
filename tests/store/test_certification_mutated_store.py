from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.store import StoreCertificationError, certify_store, compile_store
from tests.store.certification_support import artifact_and_request, complete, rows


def test_mutated_staged_store_fails_read_back_before_swap_or_delete(tmp_path: Path) -> None:
    artifact, request = artifact_and_request(tmp_path)
    destination = Path(request.destination)
    destination.mkdir()
    sentinel = destination / "previous-store"
    sentinel.write_text("unchanged")

    def mutating_writer(staged_request, decoded_rows):
        result = compile_store(staged_request, decoded_rows)
        partition = next(Path(staged_request.destination).glob("product=*/year=*/*.parquet"))
        staged = pl.read_parquet(partition).with_columns(pl.lit(99.0).alias("value"))
        staged.write_parquet(partition)
        return result

    with pytest.raises(StoreCertificationError, match="read-back differs"):
        certify_store(request, artifact, lambda _: complete(rows()), writer=mutating_writer)

    assert sentinel.read_text() == "unchanged"
    assert artifact.exists()
    assert not list(tmp_path.glob(".store.staging-*"))
