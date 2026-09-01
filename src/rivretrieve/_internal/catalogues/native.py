"""native table IO : SourceRows × RetrievedAt ↔ NativeTable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

from rivretrieve._internal.issues import FatalContractError

type SourceRows = pl.DataFrame

RETRIEVED_AT_DTYPE = pl.Datetime(time_unit="us", time_zone="UTC")


@dataclass(frozen=True, slots=True)
class RetrievedAt:
    value: datetime

    def __post_init__(self) -> None:
        if self.value.utcoffset() != timedelta(0):
            raise FatalContractError("retrieved_at must be a timezone-aware UTC datetime")


@dataclass(frozen=True, slots=True)
class NativeTable:
    data: pl.DataFrame

    def __post_init__(self) -> None:
        if "retrieved_at" not in self.data.columns:
            raise FatalContractError("native table must contain retrieved_at")
        if self.data.schema["retrieved_at"] != RETRIEVED_AT_DTYPE:
            raise FatalContractError("native table retrieved_at must be a UTC microsecond datetime")
        if self.data["retrieved_at"].null_count() != 0:
            raise FatalContractError("native table retrieved_at must not contain nulls")


def stamp_native_table(source_rows: SourceRows, retrieved_at: RetrievedAt) -> NativeTable:
    if "retrieved_at" in source_rows.columns:
        raise FatalContractError("source rows contain reserved column retrieved_at")
    data = source_rows.with_columns(pl.lit(retrieved_at.value).cast(RETRIEVED_AT_DTYPE).alias("retrieved_at"))
    return NativeTable(data)


def read_native_table(path: Path | str, *, expected_sha256: str | None = None) -> NativeTable:
    """Read a native table after optional raw-byte identity verification.

    Parameters
    ----------
    path
        Repository or supplied native-table path.
    expected_sha256
        Exact expected SHA-256 of the file bytes. When supplied, verification
        occurs before Parquet parsing.

    Returns
    -------
    NativeTable
        Parsed table satisfying the native-table invariants.

    Raises
    ------
    FatalContractError
        If the bytes do not have the expected identity or cannot be parsed.
    """
    import hashlib
    import io

    source_path = Path(path)
    verified_bytes: bytes | None = None
    if expected_sha256 is not None:
        try:
            verified_bytes = source_path.read_bytes()
        except OSError as exc:
            raise FatalContractError(f"Unable to read native table: {source_path}") from exc
        observed_sha256 = hashlib.sha256(verified_bytes).hexdigest()
        if observed_sha256 != expected_sha256:
            raise FatalContractError(
                f"native table digest mismatch: expected {expected_sha256}, observed {observed_sha256}"
            )
    try:
        data = pl.read_parquet(io.BytesIO(verified_bytes) if verified_bytes is not None else source_path)
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise FatalContractError(f"Unable to read native table: {source_path}") from exc
    return NativeTable(data)


def write_native_table(table: NativeTable, path: Path | str) -> None:
    output_path = Path(path)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        table.data.write_parquet(output_path)
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise FatalContractError(f"Unable to write native table: {output_path}") from exc
