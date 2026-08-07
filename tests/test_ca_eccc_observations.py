from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal.engine import SourceQuery
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.observations import (
    ObservationDataSchema,
    RawPayload,
    RowAnnotationTableSchema,
    SeriesAnnotationTableSchema,
)
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ca_eccc import fetch as fetch_module
from rivretrieve._internal.providers.ca_eccc.config import HydatSourceCoordinates
from rivretrieve._internal.providers.ca_eccc.issue_codes import CaEcccObservationIssueCodes


def _create_hydat(path: Path) -> None:
    connection = sqlite3.connect(path)
    day_columns = ", ".join(f"FLOW{day} REAL, FLOW_SYMBOL{day} TEXT" for day in range(1, 32))
    connection.execute(
        f"CREATE TABLE DLY_FLOWS (STATION_NUMBER TEXT, YEAR INTEGER, MONTH INTEGER, NO_DAYS INTEGER, {day_columns})"
    )
    level_columns = ", ".join(f"LEVEL{day} REAL, LEVEL_SYMBOL{day} TEXT" for day in range(1, 32))
    connection.execute(
        f"CREATE TABLE DLY_LEVELS (STATION_NUMBER TEXT, YEAR INTEGER, MONTH INTEGER, NO_DAYS INTEGER, {level_columns})"
    )
    row: list[object] = ["02GA010", 2010, 1, 2]
    for day in range(1, 32):
        row.extend([16.0, ""] if day == 1 else [17.0, ""] if day == 2 else [None, None])
    placeholders = ", ".join("?" for _ in row)
    connection.execute(f"INSERT INTO DLY_FLOWS VALUES ({placeholders})", tuple(row))
    connection.commit()
    connection.close()


@pytest.fixture
def hydat_db(tmp_path: Path) -> Path:
    database = tmp_path / "Hydat.sqlite3"
    _create_hydat(database)
    return database


def _patch_cache(monkeypatch: pytest.MonkeyPatch, hydat_db: Path) -> None:
    monkeypatch.setattr(fetch_module, "default_cache_dir", lambda: Path("/unused/cache"))
    monkeypatch.setattr(fetch_module, "_find_sqlite", lambda _: hydat_db)


def _assert_empty_annotations(result) -> None:
    pl_testing.assert_frame_equal(
        result.row_annotations.data,
        pl.DataFrame(schema=RowAnnotationTableSchema.polars_schema),
    )
    pl_testing.assert_frame_equal(
        result.series_annotations.data,
        pl.DataFrame(schema=SeriesAnnotationTableSchema.polars_schema),
    )


def test_ca_eccc_registry_dispatch_uses_engine_driver(
    monkeypatch: pytest.MonkeyPatch,
    hydat_db: Path,
) -> None:
    _patch_cache(monkeypatch, hydat_db)
    calls: list[tuple[str, str]] = []
    real_query = fetch_module._query_station_product

    def recording_query(
        connection: sqlite3.Connection,
        coordinates: HydatSourceCoordinates,
        station_id: str,
        start_year: str,
        end_year: str,
    ) -> tuple[list[dict[str, object]], SourceQuery]:
        calls.append((start_year, end_year))
        return real_query(connection, coordinates, station_id, start_year, end_year)

    monkeypatch.setattr(fetch_module, "_query_station_product", recording_query)

    result = rr.provider("ca_eccc").observations(
        stations="02GA010",
        products="discharge_daily_mean",
        start="2010-01-01",
        end="2010-01-02",
        on_issue="ignore",
    )

    expected = pl.DataFrame(
        {
            "time": [datetime(2010, 1, 1), datetime(2010, 1, 2)],
            "station_id": ["02GA010", "02GA010"],
            "product_id": ["discharge_daily_mean", "discharge_daily_mean"],
            "value": [16.0, 17.0],
        },
        schema=ObservationDataSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.data, expected)
    assert result.provenance.source == "local"
    assert result.provenance.provider_id == ProviderId("ca_eccc")
    assert result.raw == RawPayload(provider_id=ProviderId("ca_eccc"))
    assert calls == [("2009", "2010")]
    _assert_empty_annotations(result)


def test_ca_eccc_all_missing_preserves_issue_policy(
    monkeypatch: pytest.MonkeyPatch,
    hydat_db: Path,
) -> None:
    _patch_cache(monkeypatch, hydat_db)

    result = rr.provider("ca_eccc").observations(
        stations="missing-station",
        products="discharge_daily_mean",
        start="2010-01-01",
        end="2010-01-02",
        on_issue="ignore",
    )

    pl_testing.assert_frame_equal(result.data, pl.DataFrame(schema=ObservationDataSchema.polars_schema))
    assert [issue.code for issue in result.issues] == [str(CaEcccObservationIssueCodes.MISSING_DATA)]
    _assert_empty_annotations(result)

    with pytest.raises(IssuePolicyError):
        rr.provider("ca_eccc").observations(
            stations="missing-station",
            products="discharge_daily_mean",
            start="2010-01-01",
            end="2010-01-02",
            on_issue="raise",
        )
