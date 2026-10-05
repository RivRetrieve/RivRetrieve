"""compile_hydat : HydatCompileRequest × HYDATSQLite → ValidatedStore.
decode_hydat_batches : HYDATSQLite → ObservationBatchStream.

The compiler unpivots publisher monthly rows into native daily observations. It
preserves the publisher's values and quality cells; the shared store reader is the
only observation query path after the certified atomic publication succeeds.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import calendar
import hashlib
import math
import sqlite3
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Final

import polars as pl

from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.ca_eccc.series import source_series
from rivretrieve._internal.source_series import SourceSeries
from rivretrieve._internal.store import (
    ArtifactChecksum,
    Disposition,
    NativeObservationBatch,
    ObservationBatchStream,
    PublisherArtifact,
    SourceColumn,
    SourceColumnDisposition,
    SourceUnitContribution,
    SourceUnitCount,
    StoreCompileRequest,
    StoreRoot,
    ValidatedStore,
    certify_store_batches,
    source_unit_inventory_fingerprint,
)
from rivretrieve._internal.store.certification import compilation_transaction
from rivretrieve._internal.store.lifecycle import StoreTransaction

PROVIDER_ID: Final = ProviderId("ca_eccc")
HYDAT_MONTHS_PER_BATCH: Final = 512


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
    previous_source_vintage: date | None = None,
) -> DownloadedHydat:
    """Resolve and transfer the latest dated HYDAT release after shared consent checks.

    Public composition owns consent, disk-space refusal and the download operation. This source operation
    only knows HYDAT's dated URL vocabulary and transfers to the already-resolved
    publisher-artifact path supplied by the composition root. Missing releases
    (HTTP 404) allow an earlier date to be tried. Other HTTP failures stop the
    search. A release older than the previous certified store is refused before
    transfer, leaving that store unchanged.
    """
    if max_back_days < 0:
        raise ValueError("HYDAT probe horizon must be non-negative")
    target = Path(destination)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f'publisher artifact destination already exists: "{target}"')
    if not target.parent.is_dir():
        raise FileNotFoundError(f'publisher artifact parent does not exist: "{target.parent}"')
    for days_back in range(max_back_days + 1):
        vintage = today - timedelta(days=days_back)
        url = HYDAT_URL_TEMPLATE.format(vintage=vintage.strftime("%Y%m%d"))
        status = probe(url)
        if 200 <= status < 300:
            if previous_source_vintage is not None and vintage < previous_source_vintage:
                raise ValueError(
                    f"HYDAT release would regress from certified source vintage {previous_source_vintage} "
                    f"to {vintage}; the previous store is unchanged"
                )
            try:
                transfer(url, target)
                if not target.is_file():
                    raise OSError("HYDAT transfer returned without creating the artifact")
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            return DownloadedHydat(path=target, url=url, source_vintage=vintage)
        if status != 404:
            raise OSError(f"HYDAT release probe returned HTTP {status}: {url}")
    raise FileNotFoundError(f"no HYDAT release found within {max_back_days} days of {today.isoformat()}")


@dataclass(frozen=True, slots=True)
class HydatCompileRequest:
    """Publisher facts and resolved paths supplied by the composition root."""

    publisher_artifact: Path
    destination: StoreRoot
    publisher_url: str
    source_vintage: date
    built_at: datetime
    compiler_version: str
    transaction: StoreTransaction | None = None


@dataclass(frozen=True, slots=True)
class _HydatSchema:
    source_columns: tuple[SourceColumn, ...]
    dispositions: tuple[SourceColumnDisposition, ...]
    retained_names: tuple[str, ...]
    columns_by_table: dict[str, tuple[str, ...]]


def compile_hydat(request: HydatCompileRequest) -> ValidatedStore:
    """Certify and publish one complete HYDAT SQLite artifact.

    Success atomically replaces the previous store and deletes the SQLite artifact.
    Pre-commit failures restore both. A typed post-commit cleanup failure keeps the
    validated new store authoritative and reports residue.
    """
    with compilation_transaction(request.destination, request.transaction) as transaction:
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
        return certify_store_batches(
            compile_request,
            artifact,
            lambda path: decode_hydat_batches(_require_single_path(path), schema, workspace=transaction.workspace),
            transaction=transaction,
        )


def decode_hydat_batches(
    path: Path, declared_schema: _HydatSchema | None = None, *, workspace: Path | None = None
) -> ObservationBatchStream:
    """decode_hydat_batches : HYDATSQLite → ObservationBatchStream."""
    artifact = Path(path)
    schema = declared_schema or _declared_schema()

    def batches() -> Iterator[NativeObservationBatch]:
        with _sqlite_payload(artifact, workspace=workspace) as sqlite_path:
            observed = _inspect_schema(sqlite_path)
            if observed.source_columns != schema.source_columns:
                raise ValueError("HYDAT source schema changed between declaration and decoding")
            connection = _open_read_only(sqlite_path)
            try:
                for table in HYDAT_TABLES:
                    quoted = _quote_identifier(table.table_name)
                    rows: list[dict[str, object]] = []
                    units: list[SourceUnitCount] = []
                    contributions: list[SourceUnitContribution] = []
                    for source_row in _iter_hydat_source_rows(connection, quoted):
                        native = dict(source_row)
                        rowid = native.pop("__rivretrieve_rowid")
                        expected = calendar.monthrange(native["YEAR"], native["MONTH"])[1]
                        before = len(rows)
                        _unpivot_month(table, native, schema, rows)
                        actual = len(rows) - before
                        source_unit = f"{table.table_name}:rowid={rowid:012d}"
                        units.append(SourceUnitCount(source_unit, 1, expected))
                        contributions.append(SourceUnitContribution(source_unit, actual))
                        if len(units) == HYDAT_MONTHS_PER_BATCH:
                            yield NativeObservationBatch(
                                _hydat_frame(rows, schema),
                                tuple(units),
                                tuple(contributions),
                                _batch_series(rows),
                            )
                            rows = []
                            units = []
                            contributions = []
                    if rows:
                        yield NativeObservationBatch(
                            _hydat_frame(rows, schema),
                            tuple(units),
                            tuple(contributions),
                            _batch_series(rows),
                        )
            finally:
                connection.close()

    expected_records, expected_rows, inventory_sha256 = _expected_hydat_inventory(artifact, schema, workspace=workspace)
    return ObservationBatchStream(schema.source_columns, batches(), expected_records, expected_rows, inventory_sha256)


def _iter_hydat_source_rows(connection: sqlite3.Connection, quoted_table: str):
    return connection.execute(
        f"SELECT rowid AS __rivretrieve_rowid, * FROM {quoted_table} ORDER BY YEAR, STATION_NUMBER, MONTH, rowid"
    )


def _expected_hydat_inventory(
    artifact: Path, schema: _HydatSchema, *, workspace: Path | None = None
) -> tuple[int, int, str]:
    """Inventory exact monthly row identities independently from emission."""
    records = 0
    rows = 0
    with _sqlite_payload(artifact, workspace=workspace) as sqlite_path:
        observed = _inspect_schema(sqlite_path)
        if observed.source_columns != schema.source_columns:
            raise ValueError("HYDAT source schema changed before expected-cell census")
        connection = _open_read_only(sqlite_path)
        try:

            def units():
                nonlocal records, rows
                for table in HYDAT_TABLES:
                    quoted = _quote_identifier(table.table_name)
                    query = f"SELECT rowid, YEAR, MONTH FROM {quoted} ORDER BY rowid"
                    for rowid, year, month in connection.execute(query):
                        try:
                            expected = calendar.monthrange(year, month)[1]
                        except (TypeError, ValueError, OverflowError) as error:
                            raise ValueError(f"{table.table_name} has an invalid year/month") from error
                        records += 1
                        rows += expected
                        yield f"{table.table_name}:rowid={rowid:012d}", 1, expected

            inventory_sha256 = source_unit_inventory_fingerprint(units())
        finally:
            connection.close()
    return records, rows, inventory_sha256


def _require_single_path(path: Path | tuple[Path, ...]) -> Path:
    if not isinstance(path, Path):
        raise TypeError("HYDAT compilation requires exactly one publisher artifact")
    return path


def _hydat_frame(rows: list[dict[str, object]], schema: _HydatSchema) -> pl.DataFrame:
    return (
        pl.DataFrame(rows, infer_schema_length=None)
        .select(
            "product",
            "station_id",
            "time",
            "time_zone",
            "value",
            "value_state",
            "series_id",
            "facts_id",
            "source_unit",
            *schema.retained_names,
        )
        .with_columns(
            pl.col("product", "station_id", "time_zone", "value_state", "series_id", "facts_id", "source_unit").cast(
                pl.String
            ),
            pl.col("time").cast(pl.Datetime("us")),
            pl.col("value").cast(pl.Float64),
            *(
                pl.col(column.name).cast(_polars_source_type(column.type))
                for column in schema.source_columns
                if column.name in schema.retained_names
            ),
        )
    )


def _polars_source_type(declared: str) -> type[pl.DataType]:
    if declared == "TEXT":
        return pl.String
    if declared == "INTEGER":
        return pl.Int64
    if declared == "DOUBLE":
        return pl.Float64
    raise ValueError(f"unsupported HYDAT SQLite type: {declared}")


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
        valid_days = calendar.monthrange(year, month)[1]
    except (ValueError, OverflowError) as error:
        raise ValueError(f"{table.table_name} has an invalid year/month") from error

    for day in range(valid_days + 1, 32):
        value_tail = source[f"{table.value_prefix}{day}"]
        symbol_tail = source[f"{table.symbol_prefix}{day}"]
        if value_tail is not None or symbol_tail is not None:
            raise ValueError(
                f"{table.table_name} has a non-null value/symbol cell after the calendar month at day {day}"
            )

    retained = dict.fromkeys(schema.retained_names)
    for column in schema.columns_by_table[table.table_name]:
        qualified = f"{table.table_name}.{column}"
        if qualified in retained:
            retained[qualified] = source[column]

    for day in range(1, valid_days + 1):
        definition = source_series(station, str(table.product_id))
        facts = definition.facts[0]
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
            if not math.isfinite(value):
                raise ValueError(
                    f"{table.table_name}.{table.value_prefix}{day} has a non-finite numeric observation "
                    f"for station {station!r}, year {year}, month {month}"
                )
            value_state = "published_value"
        output.append(
            {
                "product": str(table.product_id),
                "station_id": station,
                "time": datetime(year, month, day),
                "time_zone": "unknown",
                "value": value,
                "value_state": value_state,
                "series_id": definition.series_id,
                "facts_id": facts.facts_id,
                "source_unit": facts.source_unit.value,
                **retained,
            }
        )
    return valid_days


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
            if name in {"STATION_NUMBER", "YEAR", "MONTH"} or (
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
def _sqlite_payload(artifact: Path, *, workspace: Path | None = None) -> Iterator[Path]:
    """Yield SQLite directly or the sole SQLite member of a complete HYDAT ZIP."""
    if not zipfile.is_zipfile(artifact):
        yield artifact
        return
    with zipfile.ZipFile(artifact) as archive:
        members = [name for name in archive.namelist() if Path(name).suffix.lower() == ".sqlite3"]
        if len(members) != 1:
            raise ValueError(f"HYDAT ZIP must contain exactly one SQLite member; found {members!r}")
        with tempfile.TemporaryDirectory(prefix="rivretrieve-hydat-", dir=workspace or artifact.parent) as directory:
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


def _batch_series(rows: list[dict[str, object]]) -> tuple[SourceSeries, ...]:
    pairs = {(str(row["station_id"]), str(row["product"])) for row in rows}
    return tuple(source_series(station, product) for station, product in sorted(pairs))
