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
from tests.store.certification_support import fixture_series


@pytest.mark.parametrize("native_name", ["value", "product"])
def test_compile_refuses_native_engine_column_collision(tmp_path: Path, native_name: str) -> None:
    destination = StoreRoot(tmp_path / "store")
    source_columns = (SourceColumn(native_name, "String"),)
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
        source_column_dispositions=(SourceColumnDisposition(native_name, Disposition.RETAINED, None, None),),
    )
    rows = pl.DataFrame(
        {
            "product": ["discharge"],
            "station_id": ["fixture-1"],
            "time": [datetime(2024, 1, 1)],
            "time_zone": ["UTC"],
            "value": [12.4],
            "value_state": ["published_value"],
            "series_id": [fixture_series("fixture-1", "fixture").series_id],
            "facts_id": [fixture_series().facts[0].facts_id],
            "source_unit": ["m3/s"],
        },
        schema={
            "product": pl.String,
            "station_id": pl.String,
            "time": pl.Datetime("us"),
            "time_zone": pl.String,
            "value": pl.Float64,
            "value_state": pl.String,
            "series_id": pl.String,
            "facts_id": pl.String,
            "source_unit": pl.String,
        },
    )

    with pytest.raises(ValueError, match="collide with engine fields"):
        compile_store(request, rows)

    assert not Path(destination).exists()
