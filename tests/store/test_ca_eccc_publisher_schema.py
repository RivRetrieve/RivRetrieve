"""HYDAT publisher-schema compatibility witnesses."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tests.store.test_ca_eccc_streaming import _compile_rows


def _publisher_columns(table: str) -> tuple[tuple[str, str], ...]:
    value_prefix = "FLOW" if table == "DLY_FLOWS" else "LEVEL"
    symbol_prefix = f"{value_prefix}_SYMBOL"
    columns: list[tuple[str, str]] = [
        ("STATION_NUMBER", "TEXT"),
        ("YEAR", "INTEGER"),
        ("MONTH", "INTEGER"),
    ]
    if table == "DLY_LEVELS":
        columns.append(("PRECISION_CODE", "INTEGER"))
    columns.extend(
        [
            ("FULL_MONTH", "INTEGER"),
            ("NO_DAYS", "INTEGER"),
            ("MONTHLY_MEAN", "DOUBLE"),
            ("MONTHLY_TOTAL", "DOUBLE"),
            ("FIRST_DAY_MIN", "INTEGER"),
            ("MIN", "DOUBLE"),
            ("FIRST_DAY_MAX", "INTEGER"),
            ("MAX", "DOUBLE"),
        ]
    )
    for day in range(1, 32):
        columns.extend(((f"{value_prefix}{day}", "DOUBLE"), (f"{symbol_prefix}{day}", "TEXT")))
    return tuple(columns)


def _publisher_shaped_hydat(path: Path) -> None:
    connection = sqlite3.connect(path)
    for table in ("DLY_FLOWS", "DLY_LEVELS"):
        schema = _publisher_columns(table)
        connection.execute(f"CREATE TABLE {table} (" + ",".join(f'"{name}" {kind}' for name, kind in schema) + ")")
        row = {name: None for name, _kind in schema}
        value_prefix = "FLOW" if table == "DLY_FLOWS" else "LEVEL"
        row.update(STATION_NUMBER="02GA010", YEAR=2024, MONTH=1, FULL_MONTH=0, NO_DAYS=1)
        row[f"{value_prefix}1"] = 12.4 if table == "DLY_FLOWS" else 1.2
        row[f"{value_prefix}_SYMBOL1"] = "E"
        connection.execute(
            f"INSERT INTO {table} VALUES (" + ",".join("?" for _ in schema) + ")",
            tuple(row[name] for name, _kind in schema),
        )
    connection.commit()
    connection.close()


def test_decoder_accepts_publisher_declared_double_columns(tmp_path: Path) -> None:
    artifact = tmp_path / "Hydat.sqlite3"
    _publisher_shaped_hydat(artifact)

    rows = _compile_rows(artifact)

    assert rows.filter(rows["value"].is_not_null()).select("product", "value").rows() == [
        ("discharge_daily_mean", 12.4),
        ("stage_daily_mean", 1.2),
    ]
