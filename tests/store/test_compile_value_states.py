"""RR2 fixture-source compiler acceptance tests."""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing

from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.store import (
    ArtifactChecksum,
    Disposition,
    PublisherArtifact,
    SourceColumn,
    SourceColumnDisposition,
    StoreCompileRequest,
    StoreQuery,
    StoreRoot,
    compile_store,
    read_store,
)
from tests.store.certification_support import fixture_series


def _compile(tmp_path: Path):
    source_columns = (
        SourceColumn("native_value", "Float64"),
        SourceColumn("quality", "String"),
    )
    dispositions = tuple(
        SourceColumnDisposition(column.name, Disposition.RETAINED, None, None) for column in source_columns
    )
    rows = pl.DataFrame(
        {
            "product": ["discharge"] * 3,
            "station_id": ["fixture-1"] * 3,
            "time": [datetime(2024, 1, day) for day in (2, 3, 4)],
            "time_zone": ["UTC"] * 3,
            "value": [None, None, 12.4],
            "value_state": ["published_null", "published_blank", "published_value"],
            "series_id": [fixture_series("fixture-1", "fixture").series_id] * 3,
            "facts_id": [fixture_series().facts[0].facts_id] * 3,
            "source_unit": ["m3/s"] * 3,
            "native_value": [None, None, 12.4],
            "quality": [None, None, "E"],
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
            "native_value": pl.Float64,
            "quality": pl.String,
        },
    )
    request = StoreCompileRequest(
        destination=StoreRoot(tmp_path / "store"),
        provider_id=ProviderId("fixture"),
        compiler_version="0.1.49",
        built_at=datetime(2026, 8, 13, tzinfo=UTC),
        source_vintage=date(2024, 2, 1),
        publisher_artifact=PublisherArtifact("https://example.com/fixture.csv", ArtifactChecksum("sha256:" + "1" * 64)),
        source_columns=source_columns,
        source_column_dispositions=dispositions,
        series=(fixture_series("fixture-1", "fixture"),),
    )
    compile_store(request, rows)
    return read_store(
        StoreQuery(
            request.destination,
            request.provider_id,
            ("fixture-1",),
            (ProductId("discharge"),),
            datetime(2024, 1, 1),
            datetime(2024, 1, 4),
        )
    )


def test_four_value_states_survive_compile(tmp_path: Path) -> None:
    result = _compile(tmp_path)
    expected = pl.DataFrame(
        {
            "time": [datetime(2024, 1, day) for day in (2, 3, 4)],
            "value": [None, None, 12.4],
            "value_state": ["published_null", "published_blank", "published_value"],
            "series_id": [fixture_series("fixture-1", "fixture").series_id] * 3,
            "facts_id": [fixture_series().facts[0].facts_id] * 3,
            "source_unit": ["m3/s"] * 3,
            "quality": [None, None, "E"],
        },
        schema={
            "time": pl.Datetime("us"),
            "value": pl.Float64,
            "value_state": pl.String,
            "series_id": pl.String,
            "facts_id": pl.String,
            "source_unit": pl.String,
            "quality": pl.String,
        },
    )
    pl_testing.assert_frame_equal(result.selected_rows.select(expected.columns), expected)
    assert datetime(2024, 1, 1) not in result.selected_rows["time"]
