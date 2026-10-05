"""HYDAT compilation streams bounded source batches through the real provider path."""

from __future__ import annotations

import calendar
import sqlite3
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import polars as real_pl
import pytest

from rivretrieve._internal.providers.ca_eccc import bulk as ca_bulk
from rivretrieve._internal.providers.ca_eccc.bulk import HYDAT_SOURCE_SCHEMAS, HydatCompileRequest
from rivretrieve._internal.store import StoreRoot


def _representative_hydat(path: Path) -> None:
    connection = sqlite3.connect(path)
    for table, schema in HYDAT_SOURCE_SCHEMAS.items():
        connection.execute(f"CREATE TABLE {table} ({', '.join(f'{name} {kind}' for name, kind in schema)})")
        names = [name for name, _kind in schema]
        rows = []
        for month in range(1, 6):
            row: dict[str, object] = dict.fromkeys(names)
            row.update(
                STATION_NUMBER="02GA010",
                YEAR=2020,
                MONTH=month,
                FULL_MONTH=0,
                NO_DAYS=31 if month in (1, 3, 5) else (29 if month == 2 else 30),
            )
            prefix = "FLOW" if table == "DLY_FLOWS" else "LEVEL"
            no_days = row["NO_DAYS"]
            assert isinstance(no_days, int)
            for day in range(1, no_days + 1):
                row[f"{prefix}{day}"] = float(day)
            rows.append(tuple(row[name] for name in names))
        connection.executemany(
            f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})", rows
        )
    connection.commit()
    connection.close()


def _compile_rows(artifact: Path):
    """Inspect native partitions only after authoritative certified publication."""
    root = StoreRoot(artifact.parent / "compiled")
    ca_bulk.compile_hydat(
        HydatCompileRequest(
            artifact,
            root,
            "https://example.test/derived-Hydat.sqlite3",
            date(2026, 7, 17),
            datetime(2026, 9, 2, tzinfo=UTC),
            "0.1.49",
        )
    )
    return real_pl.concat(
        [
            real_pl.read_parquet(path).with_columns(
                real_pl.lit(path.parent.parent.name.removeprefix("product=")).alias("product")
            )
            for path in sorted(Path(root).rglob("part-*.parquet"))
        ]
    )


def test_real_hydat_compile_never_materializes_the_complete_row_list(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "Hydat.sqlite3"
    _representative_hydat(sqlite_path)
    artifact = tmp_path / "Hydat.zip"
    with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(sqlite_path, "Hydat.sqlite3")
    monkeypatch.setattr(ca_bulk, "HYDAT_MONTHS_PER_BATCH", 2, raising=False)
    original = real_pl.DataFrame
    observed_sizes: list[int] = []

    def bounded_frame(data=None, *args, **kwargs):
        if isinstance(data, list):
            observed_sizes.append(len(data))
            if len(data) > 62:
                raise AssertionError("HYDAT constructed the complete daily-row list before staging")
        return original(data, *args, **kwargs)

    monkeypatch.setattr(ca_bulk.pl, "DataFrame", bounded_frame)
    ca_bulk.compile_hydat(
        HydatCompileRequest(
            artifact,
            StoreRoot(tmp_path / "store"),
            "https://example.test/Hydat.zip",
            date(2026, 7, 17),
            datetime(2026, 9, 2, tzinfo=UTC),
            "0.1.49",
        )
    )

    assert observed_sizes
    assert max(observed_sizes) <= 62


@pytest.mark.parametrize(
    ("year", "month", "no_days", "first_value_day"),
    ((2013, 3, 20, 12), (2014, 5, 29, 3)),
)
def test_hydat_sparse_month_uses_calendar_cells_not_no_days_cutoff(
    tmp_path: Path, year: int, month: int, no_days: int, first_value_day: int
) -> None:
    sqlite_path = tmp_path / "Hydat.sqlite3"
    _representative_hydat(sqlite_path)
    connection = sqlite3.connect(sqlite_path)
    assignments = ["STATION_NUMBER='07HF001'", f"YEAR={year}", f"MONTH={month}", f"NO_DAYS={no_days}"]
    assignments.extend(
        f"LEVEL{day}={5 + day / 100}" if day >= first_value_day else f"LEVEL{day}=NULL" for day in range(1, 32)
    )
    connection.execute("UPDATE DLY_LEVELS SET " + ",".join(assignments) + " WHERE YEAR=2020 AND MONTH=1")
    connection.commit()
    connection.close()

    decoded = _compile_rows(sqlite_path)
    level = decoded.filter(
        (decoded["product"] == "stage_daily_mean")
        & (decoded["station_id"] == "07HF001")
        & (decoded["time"].dt.year() == year)
        & (decoded["time"].dt.month() == month)
    ).sort("time")

    assert level.height == calendar.monthrange(year, month)[1]
    first = level.filter(level["time"].dt.day() == first_value_day)
    assert first["value"].item() == pytest.approx(5 + first_value_day / 100)
    assert level.filter(level["time"].dt.day() == 1)["value_state"].item() == "published_null"
    assert level.filter(level["time"].dt.day() == calendar.monthrange(year, month)[1])["value"].item() is not None


def test_hydat_rejects_non_null_cells_beyond_calendar_month(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "Hydat.sqlite3"
    _representative_hydat(sqlite_path)
    connection = sqlite3.connect(sqlite_path)
    connection.execute("UPDATE DLY_LEVELS SET MONTH=2, NO_DAYS=28, LEVEL30=999 WHERE YEAR=2020 AND MONTH=1")
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="after the calendar month at day 30"):
        _compile_rows(sqlite_path)


@pytest.mark.parametrize("omission", ["day", "record"])
def test_hydat_real_decoder_reconciliation_refuses_omission(tmp_path: Path, monkeypatch, omission: str) -> None:
    sqlite_path = tmp_path / "Hydat.sqlite3"
    artifact = tmp_path / "Hydat.zip"
    _representative_hydat(sqlite_path)
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.write(sqlite_path, "Hydat.sqlite3")
    sqlite_path.unlink()
    original_unpivot = ca_bulk._unpivot_month
    original_rows = ca_bulk._iter_hydat_source_rows
    omitted = False

    if omission == "day":

        def omit_day(table, source, schema, output):
            nonlocal omitted
            expected = original_unpivot(table, source, schema, output)
            if not omitted:
                output.pop()
                omitted = True
            return expected

        monkeypatch.setattr(ca_bulk, "_unpivot_month", omit_day)
    else:

        def omit_record(connection, quoted_table):
            nonlocal omitted
            rows = iter(original_rows(connection, quoted_table))
            if not omitted:
                next(rows)
                omitted = True
            return rows

        monkeypatch.setattr(ca_bulk, "_iter_hydat_source_rows", omit_record)

    request = HydatCompileRequest(
        artifact,
        StoreRoot(tmp_path / "store"),
        "https://example.test/Hydat.zip",
        date(2026, 7, 17),
        datetime(2026, 9, 2, tzinfo=UTC),
        "0.1.49",
    )
    with pytest.raises(ValueError, match="publisher-record inventory|did not emit every expected row"):
        ca_bulk.compile_hydat(request)
    assert artifact.exists()


def test_hydat_identity_inventory_refuses_equal_count_month_substitution(tmp_path: Path, monkeypatch) -> None:
    sqlite_path = tmp_path / "Hydat.sqlite3"
    artifact = tmp_path / "Hydat.zip"
    _representative_hydat(sqlite_path)
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.write(sqlite_path, "Hydat.sqlite3")
    sqlite_path.unlink()
    original = ca_bulk._iter_hydat_source_rows

    def substitute(connection, quoted_table):
        records = list(original(connection, quoted_table))
        records[0] = records[2]
        return iter(records)

    monkeypatch.setattr(ca_bulk, "_iter_hydat_source_rows", substitute)
    request = HydatCompileRequest(
        artifact,
        StoreRoot(tmp_path / "store"),
        "https://example.test/Hydat.zip",
        date(2026, 7, 17),
        datetime(2026, 9, 2, tzinfo=UTC),
        "0.1.49",
    )
    from rivretrieve._internal.store.lifecycle import StoreTransactionError

    with pytest.raises(StoreTransactionError) as caught:
        ca_bulk.compile_hydat(request)
    assert type(caught.value.original) is ValueError
    assert (
        str(caught.value.original) == "duplicate source unit across observation batches: DLY_FLOWS:rowid=000000000003"
    )
    assert caught.value.__cause__ is caught.value.original
    assert caught.value.cleanup_errors == ()
    assert caught.value.committed_path is None
    assert caught.value.generation_id is None
    assert caught.value.transaction_id
    assert any(path.name.startswith(".store.workspace-") for path in caught.value.residue_paths)
    assert artifact.exists()
