"""Source-independent tests for ca_eccc HYDAT compiled-store annotations (#814)."""

from __future__ import annotations

import calendar
import sqlite3
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ObservationDataSchema
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ca_eccc.annotations import (
    CA_ECCC_DLY_FLOWS_SCHEMA,
    CA_ECCC_DLY_LEVELS_SCHEMA,
    HYDAT_DEFINITION_URL,
    PRECISION_CODE_FIELD,
    SYMBOL_FIELD,
)
from rivretrieve._internal.providers.ca_eccc.bulk import (
    HYDAT_SOURCE_SCHEMAS,
    HydatCompileRequest,
    compile_hydat,
)
from rivretrieve._internal.source_annotations import (
    CATALOG_SCHEMA,
    AnnotationBundle,
    AnnotationScope,
    ObservationAnnotationTable,
    with_annotations,
)
from rivretrieve._internal.store import Disposition, StoreRoot, validate_store
from rivretrieve._internal.store.integrity import audit_store

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _hydat_sqlite(path: Path, *, flow_rows: list[dict[str, object]], level_rows: list[dict[str, object]]) -> None:
    connection = sqlite3.connect(path)
    for table_name, extra_rows in (("DLY_FLOWS", flow_rows), ("DLY_LEVELS", level_rows)):
        schema = HYDAT_SOURCE_SCHEMAS[table_name]
        names = [name for name, _kind in schema]
        connection.execute(f"CREATE TABLE {table_name} ({', '.join(f'{name} {kind}' for name, kind in schema)})")
        records = []
        for overrides in extra_rows:
            row: dict[str, object] = dict.fromkeys(names)
            row["FULL_MONTH"] = 0
            row["NO_DAYS"] = 0
            row.update(overrides)
            records.append(tuple(row[name] for name in names))
        connection.executemany(
            f"INSERT INTO {table_name} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
            records,
        )
    connection.commit()
    connection.close()


def _compile_fixture(
    tmp_path: Path, *, flow_rows: list[dict[str, object]], level_rows: list[dict[str, object]]
) -> StoreRoot:
    sqlite_path = tmp_path / "Hydat.sqlite3"
    zip_path = tmp_path / "Hydat_sqlite3_20260717.zip"
    store = StoreRoot(tmp_path / "cache" / "ca_eccc" / "store")
    store.parent.mkdir(parents=True, exist_ok=True)
    _hydat_sqlite(sqlite_path, flow_rows=flow_rows, level_rows=level_rows)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(sqlite_path, "Hydat.sqlite3")
    sqlite_path.unlink()
    compile_hydat(
        HydatCompileRequest(
            publisher_artifact=zip_path,
            destination=store,
            publisher_url="https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/Hydat_sqlite3_20260717.zip",
            source_vintage=date(2026, 7, 17),
            built_at=datetime(2026, 11, 15, tzinfo=UTC),
            compiler_version="0.1.50",
        )
    )
    return store


def test_ca_eccc_annotation_schemas_share_symbol_field_and_bind_official_reference() -> None:
    assert CA_ECCC_DLY_FLOWS_SCHEMA.schema_id == "ca_eccc.dly_flows"
    assert CA_ECCC_DLY_FLOWS_SCHEMA.provider_id == "ca_eccc"
    assert CA_ECCC_DLY_FLOWS_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert CA_ECCC_DLY_FLOWS_SCHEMA.fields == (SYMBOL_FIELD,)

    assert CA_ECCC_DLY_LEVELS_SCHEMA.schema_id == "ca_eccc.dly_levels"
    assert CA_ECCC_DLY_LEVELS_SCHEMA.provider_id == "ca_eccc"
    assert CA_ECCC_DLY_LEVELS_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert CA_ECCC_DLY_LEVELS_SCHEMA.fields == (SYMBOL_FIELD, PRECISION_CODE_FIELD)

    assert CA_ECCC_DLY_FLOWS_SCHEMA.fields[0] is CA_ECCC_DLY_LEVELS_SCHEMA.fields[0]
    assert SYMBOL_FIELD.name == "symbol"
    assert SYMBOL_FIELD.dtype == "String"
    assert "DATA_SYMBOLS" in SYMBOL_FIELD.description
    assert SYMBOL_FIELD.reference_url == HYDAT_DEFINITION_URL

    assert PRECISION_CODE_FIELD.name == "precision_code"
    assert PRECISION_CODE_FIELD.dtype == "Int64"
    assert "PRECISION_CODES" in PRECISION_CODE_FIELD.description
    assert "8" in PRECISION_CODE_FIELD.description and "9" in PRECISION_CODE_FIELD.description
    assert PRECISION_CODE_FIELD.reference_url == HYDAT_DEFINITION_URL


def test_compiled_store_manifest_dispositions_partitions_and_cell_recovery(tmp_path: Path) -> None:
    flow_row = {
        "STATION_NUMBER": "02GA010",
        "YEAR": 2020,
        "MONTH": 2,
        "NO_DAYS": 3,
        "FLOW1": 10.5,
        "FLOW_SYMBOL1": " ",
        "FLOW2": None,
        "FLOW_SYMBOL2": "B",
        "FLOW3": 12.0,
        "FLOW_SYMBOL3": None,
    }
    level_jan = {
        "STATION_NUMBER": "02GA010",
        "YEAR": 2020,
        "MONTH": 1,
        "PRECISION_CODE": 8,
        "NO_DAYS": 2,
        "LEVEL1": 1.25,
        "LEVEL_SYMBOL1": "E",
        "LEVEL2": None,
        "LEVEL_SYMBOL2": "D",
    }
    level_feb = {
        "STATION_NUMBER": "02GA010",
        "YEAR": 2020,
        "MONTH": 2,
        "PRECISION_CODE": 9,
        "NO_DAYS": 1,
        "LEVEL1": 1.30,
        "LEVEL_SYMBOL1": None,
    }
    store = _compile_fixture(tmp_path, flow_rows=[flow_row], level_rows=[level_jan, level_feb])

    validated = validate_store(store, ProviderId("ca_eccc"))
    manifest = validated.manifest
    assert manifest.format_version == 10
    assert manifest.series_annotations == ()
    assert {schema.schema_id for schema in manifest.annotation_schemas} == {
        "ca_eccc.dly_flows",
        "ca_eccc.dly_levels",
    }

    by_col = {item.source_column: item for item in manifest.source_column_dispositions}
    assert len(by_col) == 147
    expected_retained = {
        f"{table}.{col}"
        for table in ("DLY_FLOWS", "DLY_LEVELS")
        for col in (
            "FULL_MONTH",
            "NO_DAYS",
            "MONTHLY_MEAN",
            "MONTHLY_TOTAL",
            "FIRST_DAY_MIN",
            "MIN",
            "FIRST_DAY_MAX",
            "MAX",
        )
    }
    expected_symbols = {f"DLY_FLOWS.FLOW_SYMBOL{d}" for d in range(1, 32)} | {
        f"DLY_LEVELS.LEVEL_SYMBOL{d}" for d in range(1, 32)
    }
    actual_retained = {name for name, item in by_col.items() if item.disposition is Disposition.RETAINED}
    actual_reconstructible = {name for name, item in by_col.items() if item.disposition is Disposition.RECONSTRUCTIBLE}
    assert actual_retained == expected_retained
    assert len(actual_reconstructible) == 131
    assert expected_symbols <= actual_reconstructible
    assert "DLY_LEVELS.PRECISION_CODE" in actual_reconstructible
    for name in expected_symbols | {"DLY_LEVELS.PRECISION_CODE"}:
        assert by_col[name].reconstruction_rule and by_col[name].reconstruction_rule.strip()

    # Unpivoted columns are absent from part-0.parquet; annotation partitions exist and pass audit.
    flow_part = store / "product=discharge_daily_mean/year=2020/part-0.parquet"
    level_part = store / "product=stage_daily_mean/year=2020/part-0.parquet"
    flow_ann_part = store / "product=discharge_daily_mean/year=2020/annotations=ca_eccc.dly_flows/rows.parquet"
    level_ann_part = store / "product=stage_daily_mean/year=2020/annotations=ca_eccc.dly_levels/rows.parquet"
    assert flow_ann_part.is_file() and level_ann_part.is_file()
    assert not any(col.endswith("PRECISION_CODE") or "_SYMBOL" in col for col in pl.read_parquet(flow_part).columns)
    assert not any(col.endswith("PRECISION_CODE") or "_SYMBOL" in col for col in pl.read_parquet(level_part).columns)

    audited = audit_store(store, ProviderId("ca_eccc"))
    assert audited.rows_checked == 29 + 31 + 29

    # Deterministic reconstruction of original monthly symbol and precision cells.
    flow_ann = pl.read_parquet(flow_ann_part)
    sym_by_date = {
        (row["station_id"], row["time"].month, row["time"].day): row["symbol"] for row in flow_ann.to_dicts()
    }
    valid_feb = calendar.monthrange(2020, 2)[1]
    assert valid_feb == 29
    reconstructed_flow_symbols = {
        f"FLOW_SYMBOL{day}": sym_by_date[("02GA010", 2, day)] if day <= valid_feb else None for day in range(1, 32)
    }
    assert reconstructed_flow_symbols["FLOW_SYMBOL1"] == " "
    assert reconstructed_flow_symbols["FLOW_SYMBOL2"] == "B"
    assert all(reconstructed_flow_symbols[f"FLOW_SYMBOL{d}"] is None for d in range(3, 32))

    level_ann = pl.read_parquet(level_ann_part)
    prec_by_month = {
        row["time"].month: row["precision_code"] for row in level_ann.select("time", "precision_code").to_dicts()
    }
    assert prec_by_month == {1: 8, 2: 9}
    monthly_precs = (
        level_ann.with_columns(pl.col("time").dt.month().alias("month"))
        .group_by("station_id", "month")
        .agg(pl.col("precision_code").unique().alias("codes"))
    )
    assert all(len(codes) == 1 for codes in monthly_precs["codes"].to_list())


def test_public_ca_eccc_annotations_discharge_stage_combined_nulls_pick_utc_and_bundles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flow_rows = [
        {
            "STATION_NUMBER": "02GA010",
            "YEAR": 2020,
            "MONTH": 1,
            "NO_DAYS": 3,
            "FLOW1": 11.0,
            "FLOW_SYMBOL1": " ",
            "FLOW2": None,
            "FLOW_SYMBOL2": "E",
            "FLOW3": 13.0,
            "FLOW_SYMBOL3": None,
        },
        # Unmarked month where every day has symbol=None
        {
            "STATION_NUMBER": "02GA010",
            "YEAR": 2020,
            "MONTH": 3,
            "NO_DAYS": 2,
            "FLOW1": 21.0,
            "FLOW_SYMBOL1": None,
            "FLOW2": 22.0,
            "FLOW_SYMBOL2": None,
        },
    ]
    level_rows = [
        {
            "STATION_NUMBER": "02GA010",
            "YEAR": 2020,
            "MONTH": 1,
            "PRECISION_CODE": 8,
            "NO_DAYS": 3,
            "LEVEL1": 1.1,
            "LEVEL_SYMBOL1": "A",
            "LEVEL2": None,
            "LEVEL_SYMBOL2": "D",
            "LEVEL3": 1.3,
            "LEVEL_SYMBOL3": " ",
        },
        # Mid-year PRECISION_CODE change and synthetic NULL PRECISION_CODE later in 2020
        {
            "STATION_NUMBER": "02GA010",
            "YEAR": 2020,
            "MONTH": 2,
            "PRECISION_CODE": 9,
            "NO_DAYS": 1,
            "LEVEL1": 1.5,
            "LEVEL_SYMBOL1": "B",
        },
        {
            "STATION_NUMBER": "02GA010",
            "YEAR": 2020,
            "MONTH": 3,
            "PRECISION_CODE": None,
            "NO_DAYS": 1,
            "LEVEL1": 1.6,
            "LEVEL_SYMBOL1": None,
        },
    ]
    _compile_fixture(tmp_path, flow_rows=flow_rows, level_rows=level_rows)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))

    canonical_cols = tuple(ObservationDataSchema.polars_schema)

    # 1. Window with all-null symbols still exposes ca_eccc.dly_flows schema & symbol column.
    unmarked_sel = rr.find(provider="ca_eccc", station="02GA010", quantity="discharge")
    unmarked_res = rr.fetch(unmarked_sel, start="2020-03-01", end="2020-03-03", cache="bypass", on_issue="raise")
    assert unmarked_res.issues == ()
    assert tuple(unmarked_res.data.columns) == canonical_cols
    assert rr.annotations(unmarked_res)["schema"].to_list() == ["ca_eccc.dly_flows"]
    assert unmarked_res.to_polars(annotations=True)["symbol"].to_list() == [None, None, None]

    # 2. Combined discharge + stage fetch shares one symbol column without cross-product null padding.
    both_sel = rr.find(provider="ca_eccc", station="02GA010")
    both_res = rr.fetch(both_sel, start="2020-01-01", end="2020-01-03", cache="bypass", on_issue="raise")
    assert tuple(both_res.data.columns) == canonical_cols
    assert tuple(both_res.to_polars().columns) == canonical_cols
    catalog = rr.annotations(both_res)
    assert catalog.schema == pl.Schema(CATALOG_SCHEMA)
    assert catalog.select("schema", "name", "dtype").rows() == [
        ("ca_eccc.dly_flows", "symbol", "String"),
        ("ca_eccc.dly_levels", "symbol", "String"),
        ("ca_eccc.dly_levels", "precision_code", "Int64"),
    ]
    assert all(count == 0 for count in catalog["unmeasured_count"].to_list())

    projected = both_res.to_polars(annotations=True).sort("product_id", "time")
    assert set(projected.columns) == {*canonical_cols, "symbol", "precision_code"}
    assert projected["precision_code"].dtype == pl.Int64
    flow_proj = projected.filter(pl.col("product_id") == "discharge_daily_mean")
    level_proj = projected.filter(pl.col("product_id") == "stage_daily_mean")
    assert flow_proj["value"].to_list() == [11.0, None, 13.0]
    assert flow_proj["symbol"].to_list() == [" ", "E", None]
    assert flow_proj["precision_code"].to_list() == [None, None, None]
    assert level_proj["value"].to_list() == [1.1, None, 1.3]
    assert level_proj["symbol"].to_list() == ["A", "D", " "]
    assert level_proj["precision_code"].to_list() == [8, 8, 8]

    # Single-field and sequence projection + pandas projection.
    assert both_res.to_polars(annotations="symbol").columns == [*canonical_cols, "symbol"]
    assert both_res.to_polars(annotations=["precision_code"]).columns == [
        *canonical_cols,
        "precision_code",
    ]
    pd_df = both_res.to_pandas(annotations=True)
    assert isinstance(pd_df, pd.DataFrame)
    assert {"symbol", "precision_code"} <= set(pd_df.columns)

    # 3. Stage across Jan-Mar captures mid-year PRECISION_CODE changes (8 -> 9 -> null) cleanly.
    stage_sel = rr.find(provider="ca_eccc", station="02GA010", quantity="stage")
    stage_res = rr.fetch(stage_sel, start="2020-01-31", end="2020-03-02", cache="bypass", on_issue="raise")
    stage_jan_feb_mar = (
        stage_res.to_polars(annotations=True)
        .filter(pl.col("time").is_in([datetime(2020, 1, 31), datetime(2020, 2, 1), datetime(2020, 3, 1)]))
        .sort("time")
    )
    assert stage_jan_feb_mar["precision_code"].to_list() == [8, 9, None]
    assert stage_jan_feb_mar["symbol"].to_list() == [None, "B", None]

    # 4. pick preserves only the selected product's observation annotations.
    picked_stage = rr.pick(both_res, quantity="stage")
    assert rr.annotations(picked_stage)["schema"].to_list() == ["ca_eccc.dly_levels", "ca_eccc.dly_levels"]
    assert rr.annotations(picked_stage, schema="ca_eccc.dly_levels")["measured"].to_list() == [True, True, True]

    # 5. to_utc refuses time_zone="unknown", and converts explicit-offset ca_eccc results + annotations to UTC.
    with pytest.raises(FatalContractError, match="unknown"):
        rr.to_utc(both_res)

    offset_data = both_res.data.with_columns(pl.lit("-06:00", dtype=pl.String).alias("time_zone"))
    offset_obs = {
        schema_id: ObservationAnnotationTable.from_rows(
            schema=table.schema,
            rows=table.rows.with_columns(pl.lit("-06:00", dtype=pl.String).alias("time_zone")),
            measurement_indices=table.measurement_indices,
        )
        for schema_id, table in both_res._annotations.observation_tables.items()
    }
    offset_res = with_annotations(
        both_res.model_copy(update={"data": offset_data}),
        AnnotationBundle(observation_tables=offset_obs, series_tables=both_res._annotations.series_tables),
    )
    utc_res = rr.to_utc(offset_res)
    assert utc_res.data["time_zone"].unique().to_list() == ["+00:00"]
    assert rr.annotations(utc_res, schema="ca_eccc.dly_flows")["time"].to_list() == [
        datetime(2020, 1, 1, 6),
        datetime(2020, 1, 2, 6),
        datetime(2020, 1, 3, 6),
    ]
    assert rr.annotations(utc_res, schema="ca_eccc.dly_levels")["precision_code"].to_list() == [8, 8, 8]

    # 6. Bundles round-trip annotations losslessly.
    payload = rr.to_bundle(both_res)
    restored = rr.from_bundle(payload)
    pl_testing.assert_frame_equal(restored.data, both_res.data)
    pl_testing.assert_frame_equal(rr.annotations(restored), rr.annotations(both_res))
    pl_testing.assert_frame_equal(restored.to_polars(annotations=True), both_res.to_polars(annotations=True))


def test_malformed_hydat_symbol_and_precision_types_fail_closed(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "bad_symbol.sqlite3"
    _hydat_sqlite(
        sqlite_path,
        flow_rows=[
            {"STATION_NUMBER": "02GA010", "YEAR": 2020, "MONTH": 1, "NO_DAYS": 1, "FLOW1": 1.0, "FLOW_SYMBOL1": b"E"}
        ],
        level_rows=[],
    )
    with pytest.raises(TypeError, match="FLOW_SYMBOL1"):
        _ = compile_hydat(
            HydatCompileRequest(
                sqlite_path,
                StoreRoot(tmp_path / "store1"),
                "https://example.test/Hydat.sqlite3",
                date(2026, 7, 17),
                datetime(2026, 11, 15, tzinfo=UTC),
                "0.1.50",
            )
        )

    bad_prec = tmp_path / "bad_precision.sqlite3"
    _hydat_sqlite(
        bad_prec,
        flow_rows=[],
        level_rows=[
            {
                "STATION_NUMBER": "02GA010",
                "YEAR": 2020,
                "MONTH": 1,
                "PRECISION_CODE": "eight",
                "NO_DAYS": 1,
                "LEVEL1": 1.0,
            }
        ],
    )
    with pytest.raises(TypeError, match="PRECISION_CODE"):
        _ = compile_hydat(
            HydatCompileRequest(
                bad_prec,
                StoreRoot(tmp_path / "store2"),
                "https://example.test/Hydat.sqlite3",
                date(2026, 7, 17),
                datetime(2026, 11, 15, tzinfo=UTC),
                "0.1.50",
            )
        )

    float_prec = tmp_path / "float_precision.sqlite3"
    _hydat_sqlite(
        float_prec,
        flow_rows=[],
        level_rows=[
            {"STATION_NUMBER": "02GA010", "YEAR": 2020, "MONTH": 1, "PRECISION_CODE": 8.5, "NO_DAYS": 1, "LEVEL1": 1.0}
        ],
    )
    with pytest.raises(TypeError, match="PRECISION_CODE"):
        _ = compile_hydat(
            HydatCompileRequest(
                float_prec,
                StoreRoot(tmp_path / "store3"),
                "https://example.test/Hydat.sqlite3",
                date(2026, 7, 17),
                datetime(2026, 11, 15, tzinfo=UTC),
                "0.1.50",
            )
        )

    tail_symbol = tmp_path / "tail_symbol.sqlite3"
    _hydat_sqlite(
        tail_symbol,
        flow_rows=[],
        level_rows=[
            {
                "STATION_NUMBER": "02GA010",
                "YEAR": 2020,
                "MONTH": 2,
                "PRECISION_CODE": 8,
                "NO_DAYS": 1,
                "LEVEL1": 1.0,
                "LEVEL30": None,
                "LEVEL_SYMBOL30": "E",
            }
        ],
    )
    with pytest.raises(ValueError, match="non-null value/symbol cell after the calendar month"):
        _ = compile_hydat(
            HydatCompileRequest(
                tail_symbol,
                StoreRoot(tmp_path / "store4"),
                "https://example.test/Hydat.sqlite3",
                date(2026, 7, 17),
                datetime(2026, 11, 15, tzinfo=UTC),
                "0.1.50",
            )
        )
