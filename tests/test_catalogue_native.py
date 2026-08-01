from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.native import (
    NativeTable,
    RetrievedAt,
    read_native_table,
    stamp_native_table,
    write_native_table,
)
from rivretrieve._internal.issues import FatalContractError


def test_stamp_native_table_preserves_source_rows_and_appends_retrieval_instant() -> None:
    source = pl.DataFrame({"providerKey": [2, 1], "sourceValue": ["b", "a"]})
    instant = datetime(2026, 8, 1, 18, 31, 8, tzinfo=UTC)

    table = stamp_native_table(source, RetrievedAt(instant))

    expected = source.with_columns(
        pl.lit(instant).cast(pl.Datetime(time_unit="us", time_zone="UTC")).alias("retrieved_at")
    )
    pl_testing.assert_frame_equal(table.data, expected)


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 8, 1, 18, 31, 8),
        datetime(2026, 8, 1, 20, 31, 8, tzinfo=timezone(timedelta(hours=2))),
    ],
)
def test_retrieved_at_rejects_naive_or_non_utc_datetime(value: datetime) -> None:
    with pytest.raises(FatalContractError):
        RetrievedAt(value)


def test_stamp_native_table_rejects_reserved_source_column() -> None:
    source = pl.DataFrame({"retrieved_at": ["source-owned"]})

    with pytest.raises(FatalContractError):
        stamp_native_table(source, RetrievedAt(datetime(2026, 8, 1, tzinfo=UTC)))


@pytest.mark.parametrize(
    "data",
    [
        pl.DataFrame({"code": ["a"]}),
        pl.DataFrame(
            {"retrieved_at": [datetime(2026, 8, 1, tzinfo=UTC), None]},
            schema={"retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC")},
        ),
        pl.DataFrame({"retrieved_at": ["2026-08-01T00:00:00Z"]}),
        pl.DataFrame(
            {"retrieved_at": [datetime(2026, 8, 1)]},
            schema={"retrieved_at": pl.Datetime(time_unit="us")},
        ),
    ],
)
def test_native_table_rejects_invalid_retrieved_at_column(data: pl.DataFrame) -> None:
    with pytest.raises(FatalContractError):
        NativeTable(data)


def test_native_table_parquet_round_trip(tmp_path: Path) -> None:
    source = pl.DataFrame({"source": ["a", "b"], "measurement": [1.5, 2.5]})
    table = stamp_native_table(
        source,
        RetrievedAt(datetime(2026, 8, 1, 18, 31, 8, tzinfo=UTC)),
    )
    path = tmp_path / "nested" / "native.parquet"

    write_native_table(table, path)
    restored = read_native_table(path)

    pl_testing.assert_frame_equal(restored.data, table.data)
