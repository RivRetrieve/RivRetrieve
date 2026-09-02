"""StoreReader : StoreQuery → StoreReadResult ⊎ StoreRefusal."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

import rivretrieve._internal.store.validation as validation
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.store import (
    ObservationStoreRefusedError,
    StorePresence,
    StoreQuery,
    StoreReader,
    StoreRoot,
)

FIXTURES = Path(__file__).parents[1] / "test_data" / "observation_store_conformance"


def _query(store: Path, *, station: str = "ca-001", product: str = "discharge") -> StoreQuery:
    return StoreQuery(
        store=StoreRoot(store.resolve()),
        provider_id=ProviderId("fixture_bulk"),
        stations=(station,),
        products=(ProductId(product),),
        start=datetime(2023, 1, 1),
        end=datetime(2024, 12, 31, 23, 59, 59),
    )


def test_unknown_revision_is_refused_before_a_partition_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / "store"
    shutil.copytree(FIXTURES / "valid_hydat_national", store)
    manifest_path = store / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["format_version"] = 87
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    parquet_opened = False

    def forbidden_open(_path: Path) -> object:
        nonlocal parquet_opened
        parquet_opened = True
        raise AssertionError("Parquet must not be opened for an unknown manifest revision")

    monkeypatch.setattr(validation, "_open_parquet", forbidden_open)
    with pytest.raises(ObservationStoreRefusedError) as raised:
        StoreReader().query(_query(store))

    assert not parquet_opened
    assert raised.value.refusal.defect == "unsupported format revision 87"
    assert 'rivretrieve.download("fixture_bulk")' in str(raised.value)


def test_reader_projects_native_rows_and_keeps_physical_value_state() -> None:
    store = FIXTURES / "valid_hydat_national"
    result = StoreReader().query(_query(store))

    assert result.rows.columns == ["station_id", "product_id", "time", "value", "time_zone"]
    assert result.rows["value"].to_list() == [3.5, None]
    assert result.physical_rows["value_state"].to_list() == ["published_value", "published_null"]
    assert result.physical_rows["source_quality"].to_list() == ["A", "E"]
    assert result.executed_query.products == (ProductId("discharge"),)
    assert result.executed_query.years == (2023, 2024)
    for predicate_column in ("product", "year", "station_id", "time"):
        assert predicate_column in result.optimized_plan


def test_reader_preserves_duplicate_source_rows() -> None:
    store = FIXTURES / "valid_source_duplicates"
    result = StoreReader().query(
        StoreQuery(
            store=StoreRoot(store.resolve()),
            provider_id=ProviderId("fixture_bulk"),
            stations=("at-001",),
            products=(ProductId("level"),),
            start=datetime(2024, 1, 1),
            end=datetime(2024, 12, 31),
        )
    )
    assert result.physical_rows.height == 2
    assert result.physical_rows.drop("product", "year").row(0) == result.physical_rows.drop("product", "year").row(1)


def test_status_reports_absence_or_validated_manifest_facts(tmp_path: Path) -> None:
    reader = StoreReader()
    missing = StoreRoot((tmp_path / "missing").resolve())
    absent = reader.status(missing, ProviderId("fixture_bulk"))
    assert absent.presence is StorePresence.ABSENT
    assert not absent.exists
    assert absent.source_vintage is None
    assert absent.partition_row_counts == {}

    store = StoreRoot((FIXTURES / "valid_hydat_national").resolve())
    present = reader.status(store, ProviderId("fixture_bulk"))
    assert present.presence is StorePresence.PRESENT
    assert present.exists
    assert present.format_version == 2
    assert present.manifest is not None
    assert present.compiler_version == present.manifest.compiler_version
    assert present.source_vintage is not None
    assert str(present.publisher_artifact_checksum).startswith("sha256:")
    assert present.partition_row_counts


def test_empty_query_result_has_engine_rows_schema() -> None:
    result = StoreReader().query(_query(FIXTURES / "valid_hydat_national", station="not-present"))
    assert result.rows.schema == {
        "station_id": pl.String,
        "product_id": pl.String,
        "time": pl.Datetime("us"),
        "value": pl.Float64,
        "time_zone": pl.String,
    }
