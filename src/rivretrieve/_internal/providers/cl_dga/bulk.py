"""Chile DGA bulk history download and streaming observation compilation."""

from __future__ import annotations

import csv
import hashlib
import math
import sqlite3
import tempfile
import weakref
import zipfile
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import IO, Final

import polars as pl

from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.cl_dga.generate_catalogue import DAILY_HEADER, MONTHLY_HEADER
from rivretrieve._internal.providers.cl_dga.series import SERIES_MAPPINGS, source_series
from rivretrieve._internal.providers.registration import (
    BulkProbe,
    BulkTransfer,
    DownloadedBulkArtifact,
)
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
    ValueState,
    certify_store_batches,
    source_unit_inventory_fingerprint,
)
from rivretrieve._internal.store.certification import compilation_transaction
from rivretrieve._internal.store.lifecycle import StoreTransaction
from rivretrieve._internal.store.resources import (
    CompilationPhase,
    CompilationResources,
    CompilationSpaceEstimate,
    FreeSpaceProbe,
    available_bytes,
    compiled_store_growth,
    resolve_sqlite_temp_directory,
)

PROVIDER_ID: Final[ProviderId] = ProviderId("cl_dga")
CL_DGA_COMPILER_VERSION: Final[str] = "1"
CL_DGA_DAILY_FILENAME: Final[str] = "caudal_diario_historico.zip"
CL_DGA_MONTHLY_FILENAME: Final[str] = "caudal_medio_mensual_historico.zip"
CL_DGA_DAILY_URL: Final[str] = f"https://mapas2.mop.gob.cl/{CL_DGA_DAILY_FILENAME}"
CL_DGA_MONTHLY_URL: Final[str] = f"https://mapas2.mop.gob.cl/{CL_DGA_MONTHLY_FILENAME}"
CL_DGA_DAILY_MEMBER: Final[str] = "caudal_diario_historico.txt"
CL_DGA_MONTHLY_MEMBER: Final[str] = "caudal_medio_mensual_historico.txt"
CL_DGA_ROWS_PER_BATCH: Final[int] = 65_536
CL_DGA_SORT_ROWS_PER_FETCH: Final[int] = 4_096
CL_DGA_MAX_OPEN_SPILLS: Final[int] = 64

_POSIX_IFMT_MASK: Final[int] = 0o170000
_POSIX_IFLNK: Final[int] = 0o120000

_DOWNLOAD_SPECS: Final[tuple[tuple[str, str], ...]] = (
    (CL_DGA_DAILY_FILENAME, CL_DGA_DAILY_URL),
    (CL_DGA_MONTHLY_FILENAME, CL_DGA_MONTHLY_URL),
)


def _build_product_schema(
    prefix: str,
    product_id: str,
    header: tuple[str, ...],
) -> tuple[tuple[SourceColumn, ...], tuple[SourceColumnDisposition, ...], tuple[str, ...], tuple[int, ...]]:
    columns: list[SourceColumn] = []
    dispositions: list[SourceColumnDisposition] = []
    retained: list[str] = []
    retained_indices: list[int] = []
    for index, name in enumerate(header):
        qualified = f"{prefix}.{name}"
        columns.append(SourceColumn(qualified, "TEXT"))
        if name == "CODIGO ESTACION":
            dispositions.append(
                SourceColumnDisposition(
                    source_column=qualified,
                    disposition=Disposition.RECONSTRUCTIBLE,
                    reconstruction_rule=f"Identical to station_id on {product_id} rows.",
                    rationale=None,
                )
            )
        elif name == "Unidad":
            dispositions.append(
                SourceColumnDisposition(
                    source_column=qualified,
                    disposition=Disposition.RECONSTRUCTIBLE,
                    reconstruction_rule=f"Constant 'm3/s' matching {product_id} source_unit.",
                    rationale=None,
                )
            )
        else:
            dispositions.append(
                SourceColumnDisposition(
                    source_column=qualified,
                    disposition=Disposition.RETAINED,
                    reconstruction_rule=None,
                    rationale=None,
                )
            )
            retained.append(qualified)
            retained_indices.append(index)
    return tuple(columns), tuple(dispositions), tuple(retained), tuple(retained_indices)


_DAILY_COLS, _DAILY_DISPS, _DAILY_RETAINED_COLUMNS, _DAILY_RETAINED_INDICES = _build_product_schema(
    "caudal_diario",
    "discharge_daily",
    DAILY_HEADER,
)
_MONTHLY_COLS, _MONTHLY_DISPS, _MONTHLY_RETAINED_COLUMNS, _MONTHLY_RETAINED_INDICES = _build_product_schema(
    "caudal_medio_mensual",
    "discharge_monthly_mean",
    MONTHLY_HEADER,
)

CL_DGA_SOURCE_COLUMNS: Final[tuple[SourceColumn, ...]] = _DAILY_COLS + _MONTHLY_COLS
CL_DGA_SOURCE_DISPOSITIONS: Final[tuple[SourceColumnDisposition, ...]] = _DAILY_DISPS + _MONTHLY_DISPS
CL_DGA_RETAINED_COLUMNS: Final[tuple[str, ...]] = _DAILY_RETAINED_COLUMNS + _MONTHLY_RETAINED_COLUMNS

_ENGINE_COLUMN_TYPES: Final[dict[str, pl.DataType]] = {
    "product": pl.String(),
    "station_id": pl.String(),
    "time": pl.Datetime("us"),
    "time_zone": pl.String(),
    "value": pl.Float64(),
    "value_state": pl.String(),
    "series_id": pl.String(),
    "facts_id": pl.String(),
    "source_unit": pl.String(),
}
_BATCH_SCHEMA: Final[dict[str, pl.DataType]] = {
    **_ENGINE_COLUMN_TYPES,
    **dict.fromkeys(CL_DGA_RETAINED_COLUMNS, pl.String()),
}


def download_dga_history(
    destination: Path,
    *,
    today: date,
    transfer: BulkTransfer,
    probe: BulkProbe | None = None,
    previous_source_vintage: date | None = None,
) -> tuple[DownloadedBulkArtifact, ...]:
    """Download the historical daily and monthly DGA ZIPs over HTTPS without probing."""
    del today, probe, previous_source_vintage
    base = Path(destination)
    if base.exists() or base.is_symlink():
        raise FileExistsError(f'publisher artifact destination already exists: "{base}"')
    if not base.parent.is_dir():
        raise FileNotFoundError(f'publisher artifact parent does not exist: "{base.parent}"')

    targets = tuple((base.with_name(f"{base.name}-{filename}"), url) for filename, url in _DOWNLOAD_SPECS)
    for target, _url in targets:
        if target.exists() or target.is_symlink():
            raise FileExistsError(f'publisher artifact destination already exists: "{target}"')

    downloaded: list[DownloadedBulkArtifact] = []
    try:
        for target, url in targets:
            try:
                transfer(url, target)
                if target.is_symlink() or not target.is_file() or target.stat().st_size <= 0:
                    raise OSError(f"DGA transfer did not produce a non-empty file at {target.name}")
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            downloaded.append(DownloadedBulkArtifact(path=target, url=url, source_vintage=None))
    except BaseException:
        for item in downloaded:
            item.path.unlink(missing_ok=True)
        raise
    return tuple(downloaded)


@dataclass(frozen=True, slots=True)
class ClDgaCompileRequest:
    """Validated inputs for compiling the pair of undated Chile DGA ZIP archives."""

    publisher_artifacts: tuple[DownloadedBulkArtifact, ...]
    destination: StoreRoot
    built_at: datetime
    compiler_version: str
    transaction: StoreTransaction | None = None
    free_space_probe: FreeSpaceProbe = available_bytes

    def __post_init__(self) -> None:
        if len(self.publisher_artifacts) != 2:
            raise ValueError("Chile DGA compilation requires 2 publisher artifacts (daily and monthly)")
        expected = (
            (CL_DGA_DAILY_URL, CL_DGA_DAILY_FILENAME),
            (CL_DGA_MONTHLY_URL, CL_DGA_MONTHLY_FILENAME),
        )
        resolved_paths: list[Path] = []
        for artifact, (expected_url, expected_suffix) in zip(self.publisher_artifacts, expected, strict=True):
            if artifact.source_vintage is not None:
                raise ValueError("Chile DGA source_vintage must remain None until publisher dating is established")
            if artifact.url != expected_url:
                raise ValueError(f"Unexpected Chile DGA artifact URL {artifact.url!r}; expected {expected_url!r}")
            if not artifact.path.name.endswith(expected_suffix):
                raise ValueError(f"Chile DGA artifact path {artifact.path.name!r} must end with {expected_suffix!r}")
            resolved_paths.append(artifact.path.resolve())
        if len(set(resolved_paths)) != 2:
            raise ValueError("Duplicate Chile DGA publisher artifact path")


def _sha256(path: Path) -> ArtifactChecksum:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return ArtifactChecksum(f"sha256:{digest.hexdigest()}")


def compile_cl_dga(request: ClDgaCompileRequest) -> ValidatedStore:
    """Certify and publish the daily and monthly Chile DGA historical ZIPs into one store."""
    with compilation_transaction(request.destination, request.transaction) as transaction:
        artifacts = tuple(Path(item.path) for item in request.publisher_artifacts)
        provenance = tuple(PublisherArtifact(item.url, _sha256(item.path)) for item in request.publisher_artifacts)
        compile_request = StoreCompileRequest(
            destination=request.destination,
            provider_id=PROVIDER_ID,
            compiler_version=request.compiler_version,
            built_at=request.built_at,
            source_vintage=None,
            publisher_artifact=provenance[0],
            publisher_artifacts=provenance,
            source_columns=CL_DGA_SOURCE_COLUMNS,
            source_column_dispositions=CL_DGA_SOURCE_DISPOSITIONS,
        )
        resources = CompilationResources(PROVIDER_ID, transaction.workspace, request.free_space_probe)
        return certify_store_batches(
            compile_request,
            artifacts,
            lambda paths: decode_cl_dga_batches(paths, workspace=transaction.workspace, resources=resources),
            replay_decode=lambda paths: decode_cl_dga_batches(
                paths,
                workspace=transaction.workspace,
                resources=resources,
                phase=CompilationPhase.REPLAY,
            ),
            transaction=transaction,
        )


def _validate_single_zip_member(path: Path, expected_member: str, label: str) -> zipfile.ZipInfo:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) != 1 or infos[0].filename != expected_member or infos[0].is_dir():
            names = [info.filename for info in infos]
            raise ValueError(f"Expected single {label} ZIP member {expected_member!r}, found {names!r}")
        mode = (infos[0].external_attr >> 16) & _POSIX_IFMT_MASK
        if mode == _POSIX_IFLNK:
            raise ValueError(f"Refused symlink member {expected_member!r} in {label} ZIP")
        return infos[0]


def _parse_csv_row(line: str) -> list[str]:
    if '"' in line:
        return next(csv.reader([line]))
    return line.split(",")


def _validate_station_code(code: str) -> None:
    if len(code) != 8 or not (code.isascii() and code.isdigit()):
        raise ValueError(f"Invalid Chile DGA 8-digit station code: {code!r}")


def _validate_unit(unit: str) -> None:
    if unit != "m3/s":
        raise ValueError(f"Unexpected Chile DGA unit {unit!r}; expected 'm3/s'")


def _parse_value(raw: str) -> tuple[float | None, str]:
    if not raw:
        return None, ValueState.PUBLISHED_BLANK.value
    if raw[0].isspace() or raw[-1].isspace() or "_" in raw or raw[0] == "-":
        raise ValueError(f"Invalid Chile DGA discharge value {raw!r}")
    try:
        numeric = float(raw)
    except ValueError as error:
        raise ValueError(f"Non-numeric Chile DGA discharge value {raw!r}") from error
    if not math.isfinite(numeric) or numeric < 0.0:
        raise ValueError(f"Out-of-domain Chile DGA discharge value {raw!r}")
    return numeric, ValueState.PUBLISHED_VALUE.value


def _parse_daily_fecha(raw: str, cache: dict[str, tuple[int, datetime]]) -> tuple[int, datetime]:
    cached = cache.get(raw)
    if cached is not None:
        return cached
    if len(raw) != 10 or raw[2] != "/" or raw[5] != "/":
        raise ValueError(f"Invalid Chile DGA daily FECHA {raw!r}")
    day_s, month_s, year_s = raw[:2], raw[3:5], raw[6:10]
    if not (
        day_s.isascii()
        and day_s.isdigit()
        and month_s.isascii()
        and month_s.isdigit()
        and year_s.isascii()
        and year_s.isdigit()
    ):
        raise ValueError(f"Invalid Chile DGA daily FECHA {raw!r}")
    year_i, month_i, day_i = int(year_s), int(month_s), int(day_s)
    parsed = (year_i, datetime(year_i, month_i, day_i))
    if len(cache) < 65_536:
        cache[raw] = parsed
    return parsed


def _parse_monthly_ym(
    year_raw: str, month_raw: str, cache: dict[tuple[str, str], tuple[int, datetime]]
) -> tuple[int, datetime]:
    key = (year_raw, month_raw)
    cached = cache.get(key)
    if cached is not None:
        return cached
    if len(year_raw) != 4 or not (year_raw.isascii() and year_raw.isdigit()):
        raise ValueError(f"Invalid Chile DGA monthly Año {year_raw!r}")
    if month_raw not in {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"}:
        raise ValueError(f"Invalid Chile DGA monthly unpadded Mes {month_raw!r}")
    year_i = int(year_raw)
    parsed = (year_i, datetime(year_i, int(month_raw), 1))
    cache[key] = parsed
    return parsed


@dataclass(slots=True)
class _YearSpillState:
    path: Path
    row_count: int = 0
    bytes_written: int = 0
    hasher: hashlib._Hash = field(default_factory=hashlib.sha256)
    sorted_by_station: bool = True
    last_station_key: bytes | None = None
    unit_name: str = ""


class _SpillHandlePool:
    """Bounded LRU file-handle pool so arbitrary multi-decade spans stay under fd limits."""

    def __init__(self, max_open: int = CL_DGA_MAX_OPEN_SPILLS) -> None:
        self._max_open = max_open
        self._handles: OrderedDict[Path, IO[str]] = OrderedDict()

    def append_line(self, path: Path, line: str) -> None:
        handle = self._handles.get(path)
        if handle is None:
            if len(self._handles) >= self._max_open:
                _old_path, old_handle = self._handles.popitem(last=False)
                old_handle.close()
            handle = path.open("a", encoding="utf-8", newline="")
            self._handles[path] = handle
        else:
            self._handles.move_to_end(path)
        handle.write(line)

    def close_all(self) -> None:
        while self._handles:
            _path, handle = self._handles.popitem(last=False)
            handle.close()


def _decode_utf8_lf_line(raw_line: bytes, *, is_header: bool) -> str:
    if is_header and raw_line.startswith(b"\xef\xbb\xbf"):
        raise ValueError("UTF-8 BOM is not permitted in Chile DGA CSVs")
    if b"\r" in raw_line:
        raise ValueError("CR/CRLF line endings are not permitted in Chile DGA CSVs")
    trimmed = raw_line[:-1] if raw_line.endswith(b"\n") else raw_line
    try:
        return trimmed.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Invalid UTF-8 in Chile DGA CSV") from error


def _spill_product_archive(
    archive_path: Path,
    *,
    member: str,
    product_id: str,
    expected_header: tuple[str, ...],
    spill_dir: Path,
    pool: _SpillHandlePool,
) -> dict[int, _YearSpillState]:
    expected_cols = len(expected_header)
    years: dict[int, _YearSpillState] = {}
    daily_date_cache: dict[str, tuple[int, datetime]] = {}
    monthly_ym_cache: dict[tuple[str, str], tuple[int, datetime]] = {}

    with zipfile.ZipFile(archive_path) as archive, archive.open(member) as raw_stream:
        header_bytes = raw_stream.readline()
        if not header_bytes:
            raise ValueError(f"Empty Chile DGA CSV member {member!r}")
        header = _parse_csv_row(_decode_utf8_lf_line(header_bytes, is_header=True))
        if tuple(header) != expected_header:
            raise ValueError(f"Unexpected header in {member!r}: {header!r}")

        row_count = 0
        for raw_line in raw_stream:
            line = _decode_utf8_lf_line(raw_line, is_header=False)
            fields = _parse_csv_row(line)
            if len(fields) != expected_cols:
                raise ValueError(f"Ragged row in {member!r}: got {len(fields)} columns, expected {expected_cols}")
            row_count += 1
            station_id = fields[0]
            _validate_station_code(station_id)
            _validate_unit(fields[-1])

            if product_id == "discharge_daily":
                year, _ = _parse_daily_fecha(fields[10], daily_date_cache)
                _parse_value(fields[11])
            else:
                year, _ = _parse_monthly_ym(fields[10], fields[11], monthly_ym_cache)
                _parse_value(fields[12])

            state = years.get(year)
            if state is None:
                state = _YearSpillState(path=spill_dir / f"{product_id}-{year:04d}.csv")
                years[year] = state

            station_key = station_id.encode("utf-8")
            if state.last_station_key is not None and station_key < state.last_station_key:
                state.sorted_by_station = False
            state.last_station_key = station_key

            normalized_line = line + "\n"
            encoded_bytes = normalized_line.encode("utf-8")
            state.hasher.update(encoded_bytes)
            state.row_count += 1
            state.bytes_written += len(encoded_bytes)
            pool.append_line(state.path, normalized_line)

        if row_count == 0:
            raise ValueError(f"Header-only Chile DGA CSV member {member!r} has no observation rows")

    for year, state in years.items():
        state.unit_name = f"{product_id}/{year:04d}/{state.hasher.hexdigest()[:16]}"
    return years


def _iter_partition_lines(state: _YearSpillState, sort_dir: Path) -> Iterator[str]:
    if state.sorted_by_station:
        with state.path.open("r", encoding="utf-8", newline="") as handle:
            for line in handle:
                yield line.rstrip("\n")
        return

    sort_db = sort_dir / f"{state.path.stem}.sort.sqlite"
    connection = sqlite3.connect(sort_db)
    try:
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.execute("PRAGMA temp_store = FILE")
        connection.execute("CREATE TABLE rows (station_key BLOB NOT NULL, seq INTEGER PRIMARY KEY, line TEXT NOT NULL)")
        batch: list[tuple[bytes, str]] = []
        with state.path.open("r", encoding="utf-8", newline="") as handle:
            for raw_line in handle:
                line = raw_line.rstrip("\n")
                fields = _parse_csv_row(line)
                batch.append((fields[0].encode("utf-8"), line))
                if len(batch) >= CL_DGA_SORT_ROWS_PER_FETCH:
                    connection.executemany("INSERT INTO rows (station_key, line) VALUES (?, ?)", batch)
                    batch.clear()
            if batch:
                connection.executemany("INSERT INTO rows (station_key, line) VALUES (?, ?)", batch)
                batch.clear()
        cursor = connection.execute("SELECT line FROM rows ORDER BY station_key, seq")
        while fetched := cursor.fetchmany(CL_DGA_SORT_ROWS_PER_FETCH):
            for (line,) in fetched:
                yield line
    finally:
        connection.close()
        sort_db.unlink(missing_ok=True)


def _build_batch_frame(columns: dict[str, list[object]]) -> pl.DataFrame:
    return pl.DataFrame(columns, schema=_BATCH_SCHEMA)


def _new_empty_batch_columns() -> dict[str, list[object]]:
    columns: dict[str, list[object]] = {name: [] for name in _ENGINE_COLUMN_TYPES}
    for name in CL_DGA_RETAINED_COLUMNS:
        columns[name] = []
    return columns


def decode_cl_dga_batches(
    paths: Path | tuple[Path, ...],
    *,
    workspace: Path | None = None,
    resources: CompilationResources | None = None,
    phase: CompilationPhase = CompilationPhase.COMPILE,
) -> ObservationBatchStream:
    """Stream-validate and decode the daily and monthly Chile DGA ZIPs into sorted batches."""
    ordered = paths if isinstance(paths, tuple) else (paths,)
    if len(ordered) != 2:
        raise ValueError("Chile DGA decode requires both daily and monthly archive paths")
    daily_path, monthly_path = ordered
    daily_info = _validate_single_zip_member(daily_path, CL_DGA_DAILY_MEMBER, "daily")
    monthly_info = _validate_single_zip_member(monthly_path, CL_DGA_MONTHLY_MEMBER, "monthly")
    uncompressed_bytes = daily_info.file_size + monthly_info.file_size

    parent_dir = workspace or daily_path.parent
    if resources is not None:
        pre_phase = CompilationPhase.EXTRACTION if phase is CompilationPhase.COMPILE else CompilationPhase.REPLAY
        resources.check(CompilationSpaceEstimate(pre_phase, uncompressed_bytes))

    spill_dir = tempfile.TemporaryDirectory(prefix=".cl-dga-spill-", dir=parent_dir)
    spill_root = Path(spill_dir.name)
    pool = _SpillHandlePool()
    try:
        daily_years = _spill_product_archive(
            daily_path,
            member=CL_DGA_DAILY_MEMBER,
            product_id="discharge_daily",
            expected_header=DAILY_HEADER,
            spill_dir=spill_root,
            pool=pool,
        )
        monthly_years = _spill_product_archive(
            monthly_path,
            member=CL_DGA_MONTHLY_MEMBER,
            product_id="discharge_monthly_mean",
            expected_header=MONTHLY_HEADER,
            spill_dir=spill_root,
            pool=pool,
        )
    except BaseException:
        pool.close_all()
        spill_dir.cleanup()
        raise
    else:
        pool.close_all()

    try:
        all_states = [*daily_years.values(), *monthly_years.values()]
        total_rows = sum(state.row_count for state in all_states)
        sorted_units = sorted((state.unit_name, state.row_count, state.row_count) for state in all_states)
        inventory_sha256 = source_unit_inventory_fingerprint(sorted_units)

        if resources is not None:
            max_unsorted_bytes = max(
                (state.bytes_written for state in all_states if not state.sorted_by_station),
                default=0,
            )
            sort_workspace = (3 * max_unsorted_bytes + 1) // 2
            output_bytes = max(24 * total_rows, uncompressed_bytes // 2)
            growth = compiled_store_growth(phase, len(sorted_units), output_bytes)
            if sort_workspace > 0:
                sort_resources = CompilationResources(
                    resources.provider_id,
                    resources.workspace,
                    resources.free_space_probe,
                    sqlite_temp=resolve_sqlite_temp_directory(),
                )
                sort_resources.check(
                    CompilationSpaceEstimate(phase, growth + sort_workspace, sqlite_temp_bytes=sort_workspace)
                )
            else:
                resources.check(CompilationSpaceEstimate(phase, growth))
    except BaseException:
        spill_dir.cleanup()
        raise

    def batches() -> Iterator[NativeObservationBatch]:
        daily_date_cache: dict[str, tuple[int, datetime]] = {}
        monthly_ym_cache: dict[tuple[str, str], tuple[int, datetime]] = {}
        try:
            for product_id, year_map in (
                ("discharge_daily", daily_years),
                ("discharge_monthly_mean", monthly_years),
            ):
                source_unit_value = SERIES_MAPPINGS[product_id].source_unit
                series_cache: dict[str, SourceSeries] = {}
                retained_pairs = (
                    tuple(zip(_DAILY_RETAINED_COLUMNS, _DAILY_RETAINED_INDICES, strict=True))
                    if product_id == "discharge_daily"
                    else tuple(zip(_MONTHLY_RETAINED_COLUMNS, _MONTHLY_RETAINED_INDICES, strict=True))
                )
                null_columns = _MONTHLY_RETAINED_COLUMNS if product_id == "discharge_daily" else _DAILY_RETAINED_COLUMNS

                for year in sorted(year_map):
                    state = year_map[year]
                    columns = _new_empty_batch_columns()
                    new_series: list[SourceSeries] = []
                    batch_len = 0
                    unit_registered = False

                    def _flush(count: int, *, _unit: _YearSpillState = state) -> NativeObservationBatch:
                        nonlocal columns, new_series, unit_registered
                        units_tuple = (
                            (SourceUnitCount(_unit.unit_name, _unit.row_count, _unit.row_count),)
                            if not unit_registered
                            else ()
                        )
                        unit_registered = True
                        result = NativeObservationBatch(
                            rows=_build_batch_frame(columns),
                            source_units=units_tuple,
                            source_contributions=(SourceUnitContribution(_unit.unit_name, count),),
                            series=tuple(new_series),
                        )
                        columns = _new_empty_batch_columns()
                        new_series = []
                        return result

                    try:
                        for line in _iter_partition_lines(state, spill_root):
                            fields = _parse_csv_row(line)
                            station_id = fields[0]
                            entry = series_cache.get(station_id)
                            if entry is None:
                                entry = source_series(station_id, product_id)
                                series_cache[station_id] = entry
                                new_series.append(entry)

                            if product_id == "discharge_daily":
                                _, timestamp = _parse_daily_fecha(fields[10], daily_date_cache)
                                numeric_value, value_state = _parse_value(fields[11])
                            else:
                                _, timestamp = _parse_monthly_ym(fields[10], fields[11], monthly_ym_cache)
                                numeric_value, value_state = _parse_value(fields[12])

                            columns["product"].append(product_id)
                            columns["station_id"].append(station_id)
                            columns["time"].append(timestamp)
                            columns["time_zone"].append("unknown")
                            columns["value"].append(numeric_value)
                            columns["value_state"].append(value_state)
                            columns["series_id"].append(entry.series_id)
                            columns["facts_id"].append(entry.facts[0].facts_id)
                            columns["source_unit"].append(source_unit_value)
                            for col_name, idx in retained_pairs:
                                columns[col_name].append(fields[idx])
                            for col_name in null_columns:
                                columns[col_name].append(None)

                            batch_len += 1
                            if batch_len >= CL_DGA_ROWS_PER_BATCH:
                                count = batch_len
                                batch_len = 0
                                yield _flush(count)
                        if batch_len > 0:
                            count = batch_len
                            batch_len = 0
                            yield _flush(count)
                    finally:
                        state.path.unlink(missing_ok=True)
        finally:
            spill_dir.cleanup()

    batch_iter = batches()
    weakref.finalize(batch_iter, spill_dir.cleanup)
    return ObservationBatchStream(
        observed_source_columns=CL_DGA_SOURCE_COLUMNS,
        batches=batch_iter,
        expected_publisher_records=total_rows,
        expected_emitted_rows=total_rows,
        expected_inventory_sha256=inventory_sha256,
    )
