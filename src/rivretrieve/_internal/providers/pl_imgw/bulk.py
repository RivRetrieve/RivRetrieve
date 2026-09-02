"""compile_imgw : ImgwCompileRequest × IMGWYearlyZIP → ValidatedStore.

The compiler expands every strict, headerless publisher CSV record into the three
native daily products. It retains the ten source cells byte-for-byte as decoded
text; the shared store reader is the only observation query path after publication.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
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

PROVIDER_ID: Final = ProviderId("pl_imgw")
FORMAT_VERSION: Final = 1
BASE_URL: Final = "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe"
ANNUAL_URL_TEMPLATE: Final = BASE_URL + "/{year}/codz_{year}.zip"

# The publisher files are headerless. These stable names describe their positional
# schema without translating or coalescing any cell.
_SOURCE_FIELDS: Final = (
    "station_code",
    "station_name",
    "river_name",
    "hydrological_year",
    "month_indicator",
    "day",
    "level_cm",
    "flow_m3s",
    "temperature_c",
    "calendar_month",
)
IMGW_SOURCE_COLUMNS: Final = tuple(SourceColumn(f"IMGW_DAILY.{name}", "TEXT") for name in _SOURCE_FIELDS)
IMGW_SOURCE_SCHEMA: Final = tuple((column.name, column.type) for column in IMGW_SOURCE_COLUMNS)
IMGW_SOURCE_DISPOSITIONS: Final = tuple(
    SourceColumnDisposition(column.name, Disposition.RETAINED, None, None) for column in IMGW_SOURCE_COLUMNS
)
_RETAINED_NAMES: Final = tuple(column.name for column in IMGW_SOURCE_COLUMNS)

_PRODUCT_COLUMNS: Final = (
    (ProductId("stage_daily_mean"), 6, frozenset({9999.0})),
    (ProductId("discharge_daily_mean"), 7, frozenset({99999.999, 999.0})),
    (ProductId("water_temperature_daily_mean"), 8, frozenset({99.9})),
)


@dataclass(frozen=True, slots=True)
class DownloadedImgw:
    """Identity of one explicitly downloaded publisher yearly archive."""

    path: Path
    url: str
    source_vintage: date


ArtifactTransfer = Callable[[str, Path], None]


def download_imgw(
    destination: Path,
    *,
    year: int,
    source_vintage: date,
    transfer: ArtifactTransfer,
) -> DownloadedImgw:
    """Transfer one named yearly archive to an already-authorised destination.

    Consent, free-space checks and orchestration across multiple years belong to
    the shared bulk verbs (RR5); this source operation performs no implicit work.
    """
    if type(year) is not int or year < 1 or year > 9999:
        raise ValueError("IMGW archive year must be an integer in 1..9999")
    target = Path(destination)
    if target.exists():
        raise FileExistsError(f'publisher artifact destination already exists: "{target}"')
    if not target.parent.is_dir():
        raise FileNotFoundError(f'publisher artifact parent does not exist: "{target.parent}"')
    url = ANNUAL_URL_TEMPLATE.format(year=year)
    try:
        transfer(url, target)
        if not target.is_file():
            raise OSError("IMGW transfer returned without creating the artifact")
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return DownloadedImgw(target, url, source_vintage)


download = download_imgw


@dataclass(frozen=True, slots=True)
class ImgwCompileRequest:
    """Publisher facts and resolved paths supplied by the composition root."""

    publisher_artifact: Path
    destination: StoreRoot
    publisher_url: str
    source_vintage: date
    built_at: datetime
    compiler_version: str


def compile_imgw(request: ImgwCompileRequest) -> ValidatedStore:
    """Certify and publish one complete IMGW yearly ZIP artifact."""
    artifact = Path(request.publisher_artifact)
    compile_request = StoreCompileRequest(
        destination=request.destination,
        provider_id=PROVIDER_ID,
        compiler_version=request.compiler_version,
        built_at=request.built_at,
        source_vintage=request.source_vintage,
        publisher_artifact=PublisherArtifact(request.publisher_url, _sha256(artifact)),
        source_columns=IMGW_SOURCE_COLUMNS,
        source_column_dispositions=IMGW_SOURCE_DISPOSITIONS,
    )
    return certify_store(compile_request, artifact, decode_imgw)


compile = compile_imgw


def decode_imgw(path: Path) -> NativeStoreMaterialization:
    """Decode all CSV members strictly, retaining native cells and values."""
    artifact = Path(path)
    if not artifact.is_file():
        raise FileNotFoundError(f'IMGW publisher artifact does not exist: "{artifact}"')
    rows: list[dict[str, object]] = []
    units: list[SourceUnitCount] = []
    try:
        with zipfile.ZipFile(artifact) as archive:
            members = sorted(
                (info for info in archive.infolist() if not info.is_dir()),
                key=lambda info: info.filename.encode("utf-8"),
            )
            if not members:
                raise ValueError("IMGW ZIP archive contains no files")
            non_csv = [info.filename for info in members if Path(info.filename).suffix.lower() != ".csv"]
            if non_csv:
                raise ValueError(f"IMGW ZIP archive contains undeclared non-CSV members: {non_csv!r}")
            if len(members) != 1:
                raise ValueError(f"IMGW ZIP archive must contain exactly one CSV member; found {len(members)}")
            for info in members:
                member_rows = _decode_csv_member(archive.read(info), info.filename)
                before = len(rows)
                for source_ordinal, source in enumerate(member_rows, start=1):
                    _emit_source_row(source, info.filename, source_ordinal, rows)
                emitted = len(rows) - before
                units.append(SourceUnitCount(info.filename, emitted, emitted))
    except zipfile.BadZipFile as error:
        raise ValueError("IMGW publisher artifact is not a valid ZIP") from error
    if not rows:
        raise ValueError("IMGW publisher artifact contains no daily records")
    frame = (
        pl.DataFrame(rows, infer_schema_length=None)
        .select("product", "station_id", "time", "time_zone", "value", "value_state", *_RETAINED_NAMES)
        .with_columns(
            pl.col("product", "station_id", "time_zone", "value_state", *_RETAINED_NAMES).cast(pl.String),
            pl.col("time").cast(pl.Datetime("us")),
            pl.col("value").cast(pl.Float64),
        )
    )
    return NativeStoreMaterialization(frame, IMGW_SOURCE_COLUMNS, tuple(units))


def _decode_csv_member(raw: bytes, member: str) -> list[tuple[str, ...]]:
    text = _decode_text(raw, member)
    first_line = next((line for line in text.splitlines() if line), "")
    if not first_line:
        return []
    delimiter = ";" if ";" in first_line else ","
    if delimiter == ",":
        probe = next(csv.reader(io.StringIO(first_line), delimiter=","), [])
        if len(probe) == 1 and first_line.startswith('"'):
            text = _unwrap_fully_quoted(text)
    records: list[tuple[str, ...]] = []
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        for line_number, record in enumerate(reader, start=1):
            if not record or (len(record) == 1 and record[0] == ""):
                continue
            if len(record) != len(_SOURCE_FIELDS):
                raise ValueError(
                    f"IMGW member {member!r} row {line_number} has {len(record)} source columns; "
                    f"expected {len(_SOURCE_FIELDS)}"
                )
            records.append(tuple(record))
    except csv.Error as error:
        raise ValueError(f"IMGW member {member!r} is truncated or malformed: {error}") from error
    return records


def _decode_text(raw: bytes, member: str) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="strict")
    try:
        return raw.decode("cp1250", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError(f"IMGW member {member!r} is neither BOM UTF-8 nor CP1250") from error


def _unwrap_fully_quoted(text: str) -> str:
    fixed: list[str] = []
    for line in text.splitlines():
        if not line:
            fixed.append(line)
            continue
        if not (line.startswith('"') and line.endswith('"')):
            raise ValueError("IMGW fully quoted CSV contains a truncated outer record")
        fixed.append(line[1:-1].replace('""', '"'))
    return "\n".join(fixed)


def _emit_source_row(
    source: tuple[str, ...],
    member: str,
    ordinal: int,
    output: list[dict[str, object]],
) -> None:
    station = source[0].strip()
    if not station:
        raise ValueError(f"IMGW member {member!r} row {ordinal} has a blank station code")
    hydrological_year = _integer(source[3], member, ordinal, "hydrological_year")
    hydrological_month = _integer(source[4], member, ordinal, "month_indicator")
    day = _integer(source[5], member, ordinal, "day")
    calendar_month = _integer(source[9], member, ordinal, "calendar_month")
    expected_hydrological_month = (calendar_month + 1) % 12 + 1
    if hydrological_month != expected_hydrological_month:
        raise ValueError(f"IMGW member {member!r} row {ordinal} has inconsistent month indicators")
    calendar_year = hydrological_year - 1 if calendar_month >= 11 else hydrological_year
    try:
        timestamp = datetime(calendar_year, calendar_month, day)
    except ValueError as error:
        raise ValueError(f"IMGW member {member!r} row {ordinal} has an invalid calendar date") from error
    retained = dict(zip(_RETAINED_NAMES, source, strict=True))
    for product, value_index, null_sentinels in _PRODUCT_COLUMNS:
        value, state = _native_value(source[value_index], member, ordinal, _SOURCE_FIELDS[value_index], null_sentinels)
        output.append(
            {
                "product": str(product),
                "station_id": station,
                "time": timestamp,
                "time_zone": "unknown",
                "value": value,
                "value_state": state,
                **retained,
            }
        )


def _integer(raw: str, member: str, ordinal: int, field: str) -> int:
    try:
        return int(raw.strip())
    except ValueError as error:
        raise ValueError(f"IMGW member {member!r} row {ordinal} has invalid {field}") from error


def _native_value(
    raw: str,
    member: str,
    ordinal: int,
    field: str,
    null_sentinels: frozenset[float],
) -> tuple[float | None, str]:
    stripped = raw.strip()
    if stripped == "":
        return None, "published_blank"
    try:
        value = float(stripped)
    except ValueError as error:
        raise ValueError(f"IMGW member {member!r} row {ordinal} has non-numeric {field}") from error
    if round(value, 3) in null_sentinels:
        return None, "published_null"
    return value, "published_value"


def _sha256(path: Path) -> ArtifactChecksum:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return ArtifactChecksum(f"sha256:{digest.hexdigest()}")
