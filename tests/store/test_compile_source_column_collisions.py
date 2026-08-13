"""Revision-1 compilation refuses provider-native names owned by the engine."""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.store import (
    ArtifactChecksum,
    Disposition,
    PublisherArtifact,
    SourceColumn,
    SourceColumnDisposition,
    StoreCompileRequest,
    StoreRoot,
    compile_store,
)


def test_compile_refuses_native_value_column_collision(tmp_path: Path) -> None:
    destination = StoreRoot(tmp_path / "store")
    source_columns = (SourceColumn("value", "String"),)
    request = StoreCompileRequest(
        destination=destination,
        provider_id=ProviderId("fixture"),
        compiler_version="0.1.49",
        built_at=datetime(2026, 8, 13, tzinfo=UTC),
        source_vintage=date(2024, 2, 1),
        publisher_artifact=PublisherArtifact(
            "https://example.com/fixture.csv",
            ArtifactChecksum("sha256:" + "1" * 64),
        ),
        source_columns=source_columns,
        source_column_dispositions=(SourceColumnDisposition("value", Disposition.RETAINED, None, None),),
    )
    rows = pl.DataFrame(
        {
            "product": ["discharge"],
            "station_id": ["fixture-1"],
            "time": [datetime(2024, 1, 1)],
            "time_zone": ["UTC"],
            "value": [12.4],
            "value_state": ["published_value"],
        },
        schema={
            "product": pl.String,
            "station_id": pl.String,
            "time": pl.Datetime("us"),
            "time_zone": pl.String,
            "value": pl.Float64,
            "value_state": pl.String,
        },
    )

    with pytest.raises(ValueError, match="collide with engine fields"):
        compile_store(request, rows)

    assert not Path(destination).exists()
