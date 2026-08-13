"""compile_hydat : HydatCompileRequest × HYDATSQLite → ValidatedStore.

The compiler unpivots publisher monthly rows into native daily observations. It
preserves the publisher's values and quality cells; the shared store reader is the
only observation query path after the certified atomic publication succeeds.
"""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import zipfile
from calendar import monthrange
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Final

import polars as pl

from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.store import (
    ArtifactChecksum,
    Disposition,
    NativeStoreMaterialization,
    PublisherArtifact,
    SourceColumn,
    SourceColumnDisposition,
    SourceUnitCount,
    StoreCompileRequest,
    StoreRoot,
    ValidatedStore,
    certify_store,
)

PROVIDER_ID: Final = ProviderId("ca_eccc")
FORMAT_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class HydatTable:
    table_name: str
    product_id: ProductId
    value_prefix: str
    symbol_prefix: str


HYDAT_TABLES: Final = (
    HydatTable("DLY_FLOWS", ProductId("discharge_daily_mean"), "FLOW", "FLOW_SYMBOL"),
    HydatTable("DLY_LEVELS", ProductId("stage_daily_mean"), "LEVEL", "LEVEL_SYMBOL"),
)


def _hydat_columns(table: HydatTable) -> tuple[tuple[str, str], ...]:
    monthly = [
        ("STATION_NUMBER", "TEXT"),
        ("YEAR", "INTEGER"),
        ("MONTH", "INTEGER"),
    ]
    if table.table_name == "DLY_LEVELS":
        monthly.append(("PRECISION_CODE", "INTEGER"))
    monthly.extend(
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
        monthly.extend(((f"{table.value_prefix}{day}", "DOUBLE"), (f"{table.symbol_prefix}{day}", "TEXT")))
    return tuple(monthly)


HYDAT_SOURCE_SCHEMAS: Final = {table.table_name: _hydat_columns(table) for table in HYDAT_TABLES}


HYDAT_URL_TEMPLATE: Final = "https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/Hydat_sqlite3_{vintage}.zip"


@dataclass(frozen=True, slots=True)
class DownloadedHydat:
    """Identity of the publisher artifact produced by an explicit download."""

    path: Path
    url: str
    source_vintage: date


HeadProbe = Callable[[str], int]
ArtifactTransfer = Callable[[str, Path], None]


def download_hydat(
    destination: Path,
    *,
    today: date,
    probe: HeadProbe,
    transfer: ArtifactTransfer,
    max_back_days: int = 365,
) -> DownloadedHydat:
    """Resolve and transfer the latest dated HYDAT release after shared consent checks.

    RR5 owns consent, disk-space refusal and the public verb. This source operation
    only knows HYDAT's dated URL vocabulary and transfers to the already-resolved
    publisher-artifact path supplied by the composition root.
    """
    if max_back_days < 0:
        raise ValueError("HYDAT probe horizon must be non-negative")
    target = Path(destination)
    if target.exists():
        raise FileExistsError(f'publisher artifact destination already exists: "{target}"')
    if not target.parent.is_dir():
        raise FileNotFoundError(f'publisher artifact parent does not exist: "{target.parent}"')
    for days_back in range(max_back_days + 1):
        vintage = today - timedelta(days=days_back)
        url = HYDAT_URL_TEMPLATE.format(vintage=vintage.strftime("%Y%m%d"))
        status = probe(url)
        if 200 <= status < 300:
            try:
                transfer(url, target)
                if not target.is_file():
                    raise OSError("HYDAT transfer returned without creating the artifact")
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            return DownloadedHydat(path=target, url=url, source_vintage=vintage)
    raise FileNotFoundError(f"no HYDAT release found within {max_back_days} days of {today.isoformat()}")


# The provider contract's short operation name.
download = download_hydat


@dataclass(frozen=True, slots=True)
class HydatCompileRequest:
    """Publisher facts and resolved paths supplied by the composition root."""

    publisher_artifact: Path
    destination: StoreRoot
    publisher_url: str
    source_vintage: date
    built_at: datetime
    compiler_version: str


@dataclass(frozen=True, slots=True)
class _HydatSchema:
    source_columns: tuple[SourceColumn, ...]
    dispositions: tuple[SourceColumnDisposition, ...]
    retained_names: tuple[str, ...]
    columns_by_table: dict[str, tuple[str, ...]]


def compile_hydat(request: HydatCompileRequest) -> ValidatedStore:
    """Certify and publish one complete HYDAT SQLite artifact.

    Success atomically replaces the previous store and deletes the SQLite artifact.
    All failures retain both, as required by ADR 0021.
    """
    artifact = Path(request.publisher_artifact)
    schema = _declared_schema()
    compile_request = StoreCompileRequest(
        destination=request.destination,
        provider_id=PROVIDER_ID,
        compiler_version=request.compiler_version,
        built_at=request.built_at,
        source_vintage=request.source_vintage,
        publisher_artifact=PublisherArtifact(
            url=request.publisher_url,
            sha256=_sha256(artifact),
        ),
        source_columns=schema.source_columns,
        source_column_dispositions=schema.dispositions,
    )
    return certify_store(
        compile_request,
        artifact,
        lambda path: decode_hydat(path, schema),
    )


# The provider contract calls its source-specific operation ``compile``. The longer
# spelling is retained to make direct imports unambiguous in tests and tooling.
compile = compile_hydat


def decode_hydat(path: Path, declared_schema: _HydatSchema | None = None) -> NativeStoreMaterialization:
    """Decode every published HYDAT daily cell without unit conversion."""
    with _sqlite_payload(path) as sqlite_path:
        schema = _inspect_schema(sqlite_path)
        if declared_schema is not None and schema.source_columns != declared_schema.source_columns:
            # certify_store also checks this boundary; failing here avoids materialising a
            # changed SQLite schema into memory.
            raise ValueError("HYDAT source schema changed between declaration and decoding")
        rows: list[dict[str, object]] = []
        units: list[SourceUnitCount] = []
        connection = _open_read_only(sqlite_path)
        try:
            for table in HYDAT_TABLES:
                quoted = _quote_identifier(table.table_name)
                cursor = connection.execute(f"SELECT rowid AS __rivretrieve_rowid, * FROM {quoted} ORDER BY rowid")
                for ordinal, source_row in enumerate(cursor, start=1):
                    native = dict(source_row)
                    rowid = native.pop("__rivretrieve_rowid")
                    emitted = _unpivot_month(table, native, schema, rows)
                    units.append(
                        SourceUnitCount(
                            source_unit=f"{table.table_name}:rowid={rowid!s}:ordinal={ordinal}",
                            accepted_rows=emitted,
                            emitted_rows=emitted,
                        )
                    )
        finally:
            connection.close()
    if not rows:
        raise ValueError("HYDAT contains no daily flow or level rows")
    frame = (
        pl.DataFrame(rows, infer_schema_length=None)
        .select(
            "product",
            "station_id",
            "time",
            "time_zone",
            "value",
            "value_state",
            *schema.retained_names,
        )
        .with_columns(
            pl.col("product", "station_id", "time_zone", "value_state").cast(pl.String),
            pl.col("time").cast(pl.Datetime("us")),
            pl.col("value").cast(pl.Float64),
        )
    )
    return NativeStoreMaterialization(
        rows=frame,
        observed_source_columns=schema.source_columns,
        source_units=tuple(units),
    )


def _unpivot_month(
    table: HydatTable,
    source: dict[str, object],
    schema: _HydatSchema,
    output: list[dict[str, object]],
) -> int:
    station = source["STATION_NUMBER"]
    year = source["YEAR"]
    month = source["MONTH"]
    no_days = source["NO_DAYS"]
    if not isinstance(station, str) or not station:
        raise ValueError(f"{table.table_name} has an invalid STATION_NUMBER")
    if type(year) is not int or type(month) is not int or type(no_days) is not int:
        raise TypeError(f"{table.table_name} YEAR, MONTH and NO_DAYS must be SQLite integers")
    try:
        calendar_days = monthrange(year, month)[1]
    except (ValueError, OverflowError) as error:
        raise ValueError(f"{table.table_name} has an invalid year/month") from error
    if no_days < 1 or no_days > calendar_days:
        raise ValueError(f"{table.table_name} has invalid NO_DAYS={no_days} for {year:04d}-{month:02d}")

    retained = dict.fromkeys(schema.retained_names)
    for column in schema.columns_by_table[table.table_name]:
        qualified = f"{table.table_name}.{column}"
        if qualified in retained:
            retained[qualified] = source[column]

    for day in range(1, no_days + 1):
        raw_value = source[f"{table.value_prefix}{day}"]
        if raw_value is None:
            value = None
            value_state = "published_null"
        elif isinstance(raw_value, str) and raw_value == "":
            value = None
            value_state = "published_blank"
        elif isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise TypeError(f"{table.table_name}.{table.value_prefix}{day} is not numeric, null, or blank")
        else:
            value = float(raw_value)
            value_state = "published_value"
        output.append(
            {
                "product": str(table.product_id),
                "station_id": station,
                "time": datetime(year, month, day),
                "time_zone": "unknown",
                "value": value,
                "value_state": value_state,
                **retained,
            }
        )
    return no_days


def _declared_schema() -> _HydatSchema:
    source_columns: list[SourceColumn] = []
    dispositions: list[SourceColumnDisposition] = []
    retained: list[str] = []
    by_table: dict[str, tuple[str, ...]] = {}
    for table in HYDAT_TABLES:
        observed = HYDAT_SOURCE_SCHEMAS[table.table_name]
        names = tuple(name for name, _type in observed)
        by_table[table.table_name] = names
        for name, declared_type in observed:
            qualified = f"{table.table_name}.{name}"
            source_columns.append(SourceColumn(qualified, declared_type))
            if name in {"STATION_NUMBER", "YEAR", "MONTH", "NO_DAYS"} or (
                name.startswith(table.value_prefix) and name[len(table.value_prefix) :].isdigit()
            ):
                dispositions.append(
                    SourceColumnDisposition(
                        source_column=qualified,
                        disposition=Disposition.RECONSTRUCTIBLE,
                        reconstruction_rule=(
                            "Recover exactly from product, station_id, time, value and value_state; "
                            "group rows by the retained monthly native cells."
                        ),
                        rationale=None,
                    )
                )
            else:
                dispositions.append(SourceColumnDisposition(qualified, Disposition.RETAINED, None, None))
                retained.append(qualified)
    return _HydatSchema(tuple(source_columns), tuple(dispositions), tuple(retained), by_table)


@contextmanager
def _sqlite_payload(artifact: Path) -> Iterator[Path]:
    """Yield SQLite directly or the sole SQLite member of a complete HYDAT ZIP."""
    if not zipfile.is_zipfile(artifact):
        yield artifact
        return
    with zipfile.ZipFile(artifact) as archive:
        members = [name for name in archive.namelist() if Path(name).suffix.lower() == ".sqlite3"]
        if len(members) != 1:
            raise ValueError(f"HYDAT ZIP must contain exactly one SQLite member; found {members!r}")
        with tempfile.TemporaryDirectory(prefix="rivretrieve-hydat-") as directory:
            destination = Path(directory) / "Hydat.sqlite3"
            with archive.open(members[0]) as source, destination.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
            yield destination


def _inspect_schema(path: Path) -> _HydatSchema:
    declared = _declared_schema()
    connection = _open_read_only(path)
    try:
        for table in HYDAT_TABLES:
            info = connection.execute(f"PRAGMA table_info({_quote_identifier(table.table_name)})").fetchall()
            if not info:
                raise ValueError(f"HYDAT table {table.table_name!r} does not exist")
            observed = tuple((str(row["name"]), str(row["type"]).upper() or "NONE") for row in info)
            expected = HYDAT_SOURCE_SCHEMAS[table.table_name]
            if observed != expected:
                raise ValueError(
                    f"HYDAT table {table.table_name!r} source schema is not declaration-closed: "
                    f"expected={expected!r}; observed={observed!r}"
                )
    finally:
        connection.close()
    return declared


def _open_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f'HYDAT publisher artifact does not exist: "{path}"')
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA schema_version").fetchone()
    except BaseException:
        connection.close()
        raise
    return connection


def _sha256(path: Path) -> ArtifactChecksum:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return ArtifactChecksum(f"sha256:{digest.hexdigest()}")


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
