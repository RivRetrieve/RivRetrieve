"""External bulk numeric representations are checked before certified publication.

The malformed SQL/CSV inputs here are authored format controls, not publisher
captures. Exact/derived publisher evidence remains covered by boundary probes.
"""

import hashlib
import math
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from zipfile import ZipFile

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ca_eccc.bulk import HydatCompileRequest, compile_hydat, decode_hydat
from rivretrieve._internal.providers.pl_imgw.bulk import ImgwCompileRequest, compile_imgw
from rivretrieve._internal.store import StoreQuery, StoreReader, StoreRoot
from tests.store.test_ca_eccc_provenance import _hydat

_BUILD = datetime(2026, 9, 2, tzinfo=UTC)
_IMG_URL = (
    "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/2022/codz_2022_01.zip"
)


def _hydat_archive(directory: Path, literal: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    sqlite = directory / "Hydat.sqlite3"
    _hydat(sqlite)
    with sqlite3.connect(sqlite) as connection:
        connection.execute(f"UPDATE DLY_FLOWS SET FLOW1 = {literal}")
    artifact = directory / "Hydat.zip"
    with ZipFile(artifact, "w") as archive:
        archive.write(sqlite, "Hydat.sqlite3")
    return artifact


def _imgw_archive(directory: Path, value: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    artifact = directory / "codz_2022_01.zip"
    with ZipFile(artifact, "w") as archive:
        archive.writestr(
            "codz_2022_01.csv", f"154210010;SEPOPOL;Lyna;2022;01;01;100;{value};7.0;11\r\n".encode("cp1250")
        )
    return artifact


def _compile(provider: str, artifact: Path, store: Path):
    if provider == "ca_eccc":
        return compile_hydat(
            HydatCompileRequest(
                artifact, StoreRoot(store), "https://example.invalid/Hydat.zip", date(2020, 1, 31), _BUILD, "0.1.0"
            )
        )
    return compile_imgw(ImgwCompileRequest(artifact, StoreRoot(store), _IMG_URL, date(2021, 11, 30), _BUILD, "0.1.0"))


def _read_flow(provider: str, store: Path):
    station, start, end = (
        ("02GA010", datetime(2020, 1, 1), datetime(2020, 1, 1))
        if provider == "ca_eccc"
        else ("154210010", datetime(2021, 11, 1), datetime(2021, 11, 1))
    )
    return StoreReader().query(
        StoreQuery(StoreRoot(store), ProviderId(provider), (station,), ("discharge_daily_mean",), start, end)
    )


def _digest_tree(store: Path):
    return {
        str(path.relative_to(store)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in store.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize(
    "literal", ["1e400", "-1e400", "9" * 400], ids=["positive-exponent", "negative-exponent", "huge-integer-literal"]
)
def test_hydat_production_compiler_refuses_nonfinite_native_sql_observation_without_publication(tmp_path, literal):
    artifact = _hydat_archive(tmp_path / "source", literal)
    store = tmp_path / "store"
    with sqlite3.connect(artifact.parent / "Hydat.sqlite3") as connection:
        native, storage_class = connection.execute("SELECT FLOW1, typeof(FLOW1) FROM DLY_FLOWS").fetchone()
    assert storage_class == "real" and not math.isfinite(native)
    original_bytes = artifact.read_bytes()
    try:
        with pytest.raises(ValueError, match="representable|non-finite|finite"):
            _compile("ca_eccc", artifact, store)
    finally:
        if store.exists():
            print("unsafe compiled native observation:", _read_flow("ca_eccc", store).rows["value"].to_list())
    assert not store.exists()
    assert artifact.read_bytes() == original_bytes


@pytest.mark.parametrize(
    "literal",
    ["1e400", "-1e400", "9" * 400, "NaN", "inf", "-Infinity"],
    ids=["positive-exponent", "negative-exponent", "huge-integer", "nan", "inf", "negative-infinity"],
)
def test_imgw_production_compiler_refuses_nonfinite_csv_observation_without_publication(tmp_path, literal):
    artifact = _imgw_archive(tmp_path / "source", literal)
    store = tmp_path / "store"
    original_bytes = artifact.read_bytes()
    try:
        with pytest.raises(ValueError, match="representable|non-finite|finite"):
            _compile("pl_imgw", artifact, store)
    finally:
        if store.exists():
            print("unsafe compiled native observation:", _read_flow("pl_imgw", store).rows["value"].to_list())
    assert not store.exists()
    assert artifact.read_bytes() == original_bytes


@pytest.mark.parametrize("provider", ["ca_eccc", "pl_imgw"])
def test_unrepresentable_refresh_preserves_previous_compiled_store_and_entire_artifact(tmp_path, provider):
    make = _hydat_archive if provider == "ca_eccc" else _imgw_archive
    store = tmp_path / "store"
    first = make(tmp_path / "first", "12.4")
    _compile(provider, first, store)
    before = _digest_tree(store)
    invalid = make(tmp_path / "invalid", "1e400")
    artifact_before = invalid.read_bytes()
    with pytest.raises(ValueError, match="representable|non-finite|finite"):
        _compile(provider, invalid, store)
    assert _digest_tree(store) == before
    assert invalid.read_bytes() == artifact_before
    assert _read_flow(provider, store).rows["value"].to_list() == [12.4]


@pytest.mark.parametrize(
    ("provider", "literal", "value", "state"),
    [
        ("ca_eccc", "12.4", 12.4, "published_value"),
        ("ca_eccc", "0", 0.0, "published_value"),
        ("ca_eccc", "-12.4", -12.4, "published_value"),
        ("ca_eccc", "1.7976931348623157e308", 1.7976931348623157e308, "published_value"),
        ("ca_eccc", "NULL", None, "published_null"),
        ("ca_eccc", "''", None, "published_blank"),
        ("pl_imgw", "12.4", 12.4, "published_value"),
        ("pl_imgw", "0", 0.0, "published_value"),
        ("pl_imgw", "-12.4", -12.4, "published_value"),
        ("pl_imgw", "1.7976931348623157e308", 1.7976931348623157e308, "published_value"),
        ("pl_imgw", "999.0", None, "published_null"),
        ("pl_imgw", "", None, "published_blank"),
    ],
)
def test_native_finite_zero_null_and_blank_states_survive_real_compiler_casts(
    tmp_path, provider, literal, value, state
):
    make = _hydat_archive if provider == "ca_eccc" else _imgw_archive
    artifact = make(tmp_path / "source", literal)
    store = tmp_path / "store"
    _compile(provider, artifact, store)
    read = _read_flow(provider, store)
    pl_testing.assert_frame_equal(
        read.physical_rows.select("value", "value_state"),
        pl.DataFrame(
            {"value": [value], "value_state": [state]}, schema={"value": pl.Float64, "value_state": pl.String}
        ),
    )
    assert read.rows.schema["value"] == pl.Float64
    if provider == "pl_imgw":
        assert read.physical_rows["IMGW_DAILY.flow_m3s"].to_list() == [literal]


def test_hydat_sqlite_integer_range_and_nan_binding_are_native_boundary_facts(tmp_path):
    sqlite = tmp_path / "Hydat.sqlite3"
    _hydat(sqlite)
    with sqlite3.connect(sqlite) as connection:
        connection.execute("UPDATE DLY_FLOWS SET FLOW1 = 9223372036854775807")
        native, storage_class = connection.execute("SELECT FLOW1, typeof(FLOW1) FROM DLY_FLOWS").fetchone()
        assert storage_class == "real" and isinstance(native, float) and math.isfinite(native)
        connection.execute("UPDATE DLY_FLOWS SET FLOW1 = ?", (float("nan"),))
        assert connection.execute("SELECT FLOW1, typeof(FLOW1) FROM DLY_FLOWS").fetchone() == (None, "null")
    decoded = decode_hydat(sqlite).rows
    row = decoded.filter((pl.col("product") == "discharge_daily_mean") & (pl.col("time") == datetime(2020, 1, 1)))
    assert row["value"].to_list() == [None]
    assert row["value_state"].to_list() == ["published_null"]
