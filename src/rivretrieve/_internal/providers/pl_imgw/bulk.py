"""compile_imgw : ImgwCompileRequest × IMGWArchive+ → ValidatedStore.
decode_imgw_batches : IMGWArchive+ → ObservationBatchStream.

The compiler expands every strict, headerless publisher CSV record into the three
native daily products. It retains the ten source cells byte-for-byte as decoded
text; the shared store reader is the only observation query path after publication.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Final, cast

import polars as pl

from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.pl_imgw.series import source_series
from rivretrieve._internal.providers.registration import DownloadedBulkArtifact
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

PROVIDER_ID: Final = ProviderId("pl_imgw")
BASE_URL: Final = "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe"
ANNUAL_URL_TEMPLATE: Final = BASE_URL + "/{year}/codz_{year}.zip"
MONTHLY_URL_TEMPLATE: Final = BASE_URL + "/{year}/codz_{year}_{month:02d}.zip"
FIRST_PUBLISHED_YEAR: Final = 1951


@dataclass(frozen=True, slots=True)
class ImgwArtifactPlan:
    """One exact official archive discovered in the publisher's index."""

    url: str
    filename: str


class _ImgwDirectoryIndex(HTMLParser):
    """Read the publisher's Apache index without accepting an arbitrary HTML page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.titles: list[str] = []
        self.headings: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.closed: set[str] = set()
        self.text = ""
        self.href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"img", "hr", "br", "meta", "link", "input"}:
            return
        if tag in {"title", "h1", "a"}:
            self.text = ""
        if tag == "a":
            hrefs = [value for name, value in attrs if name == "href"]
            if len(hrefs) != 1 or not hrefs[0] or self.href is not None:
                raise ValueError("IMGW directory index has a malformed link")
            self.href = hrefs[0]
        self.stack.append(tag)

    def handle_data(self, data: str) -> None:
        if self.stack and self.stack[-1] in {"title", "h1", "a"}:
            self.text += data

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack.pop() != tag:
            raise ValueError("IMGW directory index has malformed HTML structure")
        self.closed.add(tag)
        if tag == "title":
            self.titles.append(self.text.strip())
        elif tag == "h1":
            self.headings.append(self.text.strip())
        elif tag == "a":
            if self.href is None:
                raise ValueError("IMGW directory index has a malformed link")
            self.links.append((self.href, self.text.strip()))
            self.href = None


def _imgw_directory_entries(content: bytes, url: str) -> tuple[str, ...]:
    """Validate an exact source index and return its unambiguous relative entries."""
    index = _ImgwDirectoryIndex()
    try:
        index.feed(content.decode("utf-8", errors="strict"))
        index.close()
    except UnicodeError as error:
        raise ValueError("IMGW directory index is not UTF-8 HTML") from error
    path = "/" + url.split("/", 3)[3].rstrip("/")
    identity = f"Index of {path}"
    if (
        index.stack
        or index.titles != [identity]
        or index.headings != [identity]
        or not {"html", "body", "table"}.issubset(index.closed)
    ):
        raise ValueError(f"IMGW directory index identity or structure is invalid: {url}")
    entries: list[str] = []
    seen: set[str] = set()
    parent = path.rsplit("/", 1)[0] + "/"
    for href, label in index.links:
        if href in seen:
            raise ValueError(f"IMGW directory index has a duplicate link: {href}")
        seen.add(href)
        if re.fullmatch(r"\?C=[NMSD];O=[AD]", href):
            continue
        if href == parent and label == "Parent Directory":
            continue
        if href != label or re.fullmatch(r"[A-Za-z0-9_.-]+/?", href) is None:
            raise ValueError(f"IMGW directory index has an unsupported link: {href}")
        entries.append(href)
    return tuple(entries)


def discover_imgw_artifacts(
    *, today: date, read_index: Callable[[str], bytes], first_year: int
) -> tuple[ImgwArtifactPlan, ...]:
    """Discover continuous daily publication, not calendar-implied availability.

    The notice promises regeneration in monthly form but gives no precedence for
    coexisting editions. An exclusive annual or monthly listing is supported;
    overlapping editions are refused rather than selected or deduplicated.
    """
    if not 1 < first_year <= today.year + (today.month >= 11):
        raise ValueError("IMGW publication starting year is invalid")
    root_url = BASE_URL + "/"
    entries = _imgw_directory_entries(read_index(root_url), root_url)
    years: list[int] = []
    for entry in entries:
        if entry in {"UWAGA.txt", "CODZ_publiczne_format.txt", "ZJAW_publiczne_format.txt"}:
            continue
        if re.fullmatch(r"[0-9]{4}/", entry) is None:
            raise ValueError(f"IMGW publication index contains an unsupported entry: {entry}")
        year = int(entry[:-1])
        if year < 2 or year > today.year + (today.month >= 11):
            raise ValueError(f"IMGW publication index contains an implausible year: {entry}")
        if year >= first_year:
            years.append(year)
    planned: list[ImgwArtifactPlan] = []
    previous = first_year * 12
    for year in sorted(years):
        url = f"{BASE_URL}/{year}/"
        names = _imgw_directory_entries(read_index(url), url)
        periods: list[tuple[tuple[int, ...], str]] = []
        for name in names:
            # ZJAW describes a separate phenomena product, not daily CODZ values.
            if name == "UWAGA.txt" or re.fullmatch(r"zjaw_[0-9]{4}(?:_[0-9]{2})?\.zip", name):
                continue
            if _ARTIFACT_NAME.fullmatch(name) is None:
                raise ValueError(f"IMGW publication index contains an unsupported daily archive: {name}")
            artifact_year, months = _imgw_artifact_period(Path(name))
            if artifact_year != year:
                raise ValueError(f"IMGW archive disagrees with its publication directory: {name}")
            if _imgw_period_source_vintage((year, months)) > today:
                raise ValueError(f"IMGW archive declares an unfinished publication period: {name}")
            periods.append((months, name))
        for months, name in sorted(periods):
            start = year * 12 + months[0]
            if start <= previous:
                raise ValueError(f"IMGW publication periods overlap ambiguously: {name}")
            if start != previous + 1:
                raise ValueError(f"IMGW published history has a gap before {name}")
            planned.append(ImgwArtifactPlan(url + name, name))
            previous = year * 12 + months[-1]
    if not planned:
        raise ValueError("IMGW publication index contains no supported daily history")
    return tuple(planned)


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
    (ProductId("stage_daily"), 6, frozenset({9999.0})),
    (ProductId("discharge_daily"), 7, frozenset({99999.999})),
    (ProductId("water_temperature_daily"), 8, frozenset({99.9})),
)


@dataclass(frozen=True, slots=True)
class DownloadedImgw:
    """Identity of one explicitly downloaded publisher archive."""

    path: Path
    url: str

    @property
    def source_vintage(self) -> date:
        basename = Path(self.url.rsplit("/", 1)[-1]).name
        return _imgw_period_source_vintage(_imgw_artifact_period(Path(basename)))


ArtifactTransfer = Callable[[str, Path], None]


def _imgw_period_source_vintage(period: tuple[int, tuple[int, ...]]) -> date:
    """Return the last date covered by the publisher-labelled hydrological period."""
    import calendar

    year, months = period
    last_month = months[-1]
    calendar_year = year - 1 if last_month <= 2 else year
    calendar_month = last_month + 10 if last_month <= 2 else last_month - 2
    return date(calendar_year, calendar_month, calendar.monthrange(calendar_year, calendar_month)[1])


def download_imgw_history(
    destination: Path,
    *,
    today: date,
    transfer: ArtifactTransfer,
    first_year: int | None = None,
    previous_source_vintage: date | None = None,
) -> tuple[DownloadedImgw, ...]:
    """Download the complete source-backed history into unique artifact paths."""
    import tempfile

    base = Path(destination)

    def read_index(url: str) -> bytes:
        # Own only a unique scratch directory; never overwrite recovery inputs.
        with tempfile.TemporaryDirectory(prefix=".imgw-publication-", dir=base.parent) as directory:
            target = Path(directory) / "index.html"
            transfer(url, target)
            return target.read_bytes()

    planned = discover_imgw_artifacts(
        today=today,
        read_index=read_index,
        first_year=FIRST_PUBLISHED_YEAR if first_year is None else first_year,
    )
    latest_vintage = _imgw_period_source_vintage(_imgw_artifact_period(Path(planned[-1].filename)))
    if previous_source_vintage is not None and latest_vintage < previous_source_vintage:
        raise ValueError(
            f"IMGW published history would regress from certified coverage {previous_source_vintage} "
            f"to {latest_vintage}; previously published trailing archives are missing"
        )
    downloaded: list[DownloadedImgw] = []
    try:
        for item in planned:
            target = base.with_name(f"{base.name}-{item.filename}")
            if target.exists() or target.is_symlink():
                raise FileExistsError(f'publisher artifact destination already exists: "{target}"')
            try:
                transfer(item.url, target)
                if not target.is_file():
                    raise OSError(f"IMGW transfer returned without creating {target.name}")
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            downloaded.append(DownloadedImgw(target, item.url))
    except BaseException:
        for item in downloaded:
            item.path.unlink(missing_ok=True)
        raise
    return tuple(downloaded)


@dataclass(frozen=True, slots=True)
class ImgwCompileRequest:
    """First-artifact identity, aggregate vintage, and resolved compilation inputs."""

    publisher_artifact: Path
    destination: StoreRoot
    publisher_url: str
    source_vintage: date
    built_at: datetime
    compiler_version: str
    publisher_artifacts: tuple[DownloadedBulkArtifact | DownloadedImgw, ...] = ()

    def __post_init__(self) -> None:
        artifacts = self.publisher_artifacts or (DownloadedImgw(self.publisher_artifact, self.publisher_url),)
        first = artifacts[0]
        if (first.path, first.url) != (self.publisher_artifact, self.publisher_url):
            raise ValueError("singular IMGW artifact must equal the first plural artifact")
        paths = [item.path.resolve() for item in artifacts]
        urls = [item.url for item in artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate publisher artifact path")
        if len(urls) != len(set(urls)):
            raise ValueError("duplicate publisher artifact URL")
        covered: set[tuple[int, int]] = set()
        previous: tuple[int, int] | None = None
        for item in artifacts:
            basename = Path(item.url.rsplit("/", 1)[-1]).name
            if not basename or not item.path.name.endswith(basename):
                raise ValueError("IMGW artifact path and URL basename disagree")
            year, months = _imgw_artifact_period(Path(basename))
            expected_url = (
                MONTHLY_URL_TEMPLATE.format(year=year, month=months[0])
                if len(months) == 1
                else ANNUAL_URL_TEMPLATE.format(year=year)
            )
            if item.url != expected_url:
                raise ValueError("IMGW artifact URL is not the exact official period template")
            if item.source_vintage != _imgw_period_source_vintage((year, months)):
                raise ValueError("IMGW source vintage must equal the publisher-labelled coverage end")
            interval = tuple((year, month) for month in months)
            if previous is not None and interval[0] <= previous:
                raise ValueError("IMGW publisher artifacts are out of period order or overlap")
            if previous is not None:
                previous_ordinal = previous[0] * 12 + previous[1]
                next_ordinal = interval[0][0] * 12 + interval[0][1]
                if next_ordinal != previous_ordinal + 1:
                    raise ValueError("IMGW publisher artifact periods must be contiguous")
            if covered.intersection(interval):
                raise ValueError("IMGW publisher artifact coverage overlaps")
            covered.update(interval)
            previous = interval[-1]
        if self.source_vintage != max(item.source_vintage for item in artifacts):
            raise ValueError("IMGW aggregate source vintage must equal the latest artifact coverage end")


def compile_imgw(request: ImgwCompileRequest) -> ValidatedStore:
    """Certify and publish the ordered IMGW archives as one store."""
    downloaded = request.publisher_artifacts or (
        DownloadedImgw(Path(request.publisher_artifact), request.publisher_url),
    )
    artifacts = tuple(Path(item.path) for item in downloaded)
    provenance = tuple(PublisherArtifact(item.url, _sha256(item.path)) for item in downloaded)
    compile_request = StoreCompileRequest(
        destination=request.destination,
        provider_id=PROVIDER_ID,
        compiler_version=request.compiler_version,
        built_at=request.built_at,
        source_vintage=max(item.source_vintage for item in downloaded),
        publisher_artifact=provenance[0],
        publisher_artifacts=provenance,
        source_columns=IMGW_SOURCE_COLUMNS,
        source_column_dispositions=IMGW_SOURCE_DISPOSITIONS,
    )
    return certify_store_batches(compile_request, artifacts, decode_imgw_batches)


IMGW_ROWS_PER_BATCH: Final = 65_536
_ARTIFACT_NAME = re.compile(r"codz_(?P<year>[0-9]{4})(?:_(?P<month>[0-9]{2}))?\.zip$")


def decode_imgw_batches(paths: Path | tuple[Path, ...]) -> ObservationBatchStream:
    """decode_imgw_batches : IMGWArchive+ → ObservationBatchStream."""
    from collections import Counter

    ordered = paths if isinstance(paths, tuple) else (paths,)
    periods = tuple(_imgw_artifact_period(path) for path in ordered)
    expected_records, expected_rows, inventory_sha256 = _expected_imgw_inventory(ordered)
    years = sorted({year for period in periods for year in _calendar_years(period)})

    def batches():
        for product, _index, _sentinels in sorted(_PRODUCT_COLUMNS, key=lambda item: str(item[0])):
            for year in years:
                iterators = [
                    _external_station_sort(_iter_imgw_product_year(path, product, year, artifact_index))
                    for artifact_index, (path, period) in enumerate(zip(ordered, periods, strict=True))
                    if year in _calendar_years(period)
                ]
                rows: list[dict[str, object]] = []
                units: list[SourceUnitCount] = []
                contributions: Counter[str] = Counter()
                for unit, row in _merge_station_order(iterators):
                    rows.append(row)
                    if product == ProductId("discharge_daily"):
                        units.append(unit)
                    contributions[unit.source_unit] += 1
                    if len(rows) == IMGW_ROWS_PER_BATCH:
                        yield NativeObservationBatch(
                            _imgw_frame(rows),
                            tuple(units),
                            tuple(SourceUnitContribution(name, count) for name, count in sorted(contributions.items())),
                            _batch_series(rows),
                        )
                        rows = []
                        units = []
                        contributions = Counter()
                if rows:
                    yield NativeObservationBatch(
                        _imgw_frame(rows),
                        tuple(units),
                        tuple(SourceUnitContribution(name, count) for name, count in sorted(contributions.items())),
                        _batch_series(rows),
                    )

    return ObservationBatchStream(IMGW_SOURCE_COLUMNS, batches(), expected_records, expected_rows, inventory_sha256)


def _imgw_source_unit(path: Path, artifact_index: int, ordinal: int, source: tuple[str, ...]) -> SourceUnitCount:
    encoded = json.dumps(source, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    record_sha = hashlib.sha256(encoded).hexdigest()
    artifact_match = _ARTIFACT_NAME.search(path.name)
    assert artifact_match is not None
    member = Path(artifact_match.group(0)).with_suffix(".csv").name
    identity = f"artifact={artifact_index:06d}:{path.name}:{member}:logical_ordinal={ordinal:012d}:sha256={record_sha}"
    return SourceUnitCount(identity, 1, len(_PRODUCT_COLUMNS))


def _expected_imgw_inventory(paths: tuple[Path, ...]) -> tuple[int, int, str]:
    """Inventory exact logical record identities independently from emission."""
    total_records = 0

    def units():
        nonlocal total_records
        for artifact_index, path in enumerate(paths):
            period = _imgw_artifact_period(path)
            artifact_records = 0
            for ordinal, source in enumerate(_iter_imgw_raw_records(path), start=1):
                emitted: list[dict[str, object]] = []
                _emit_source_row(source, path.name, ordinal, emitted, expected_period=period)
                if {row["product"] for row in emitted} != {str(item[0]) for item in _PRODUCT_COLUMNS}:
                    raise ValueError("IMGW publisher record did not expand to every declared product cell")
                artifact_records += 1
                total_records += 1
                unit = _imgw_source_unit(path, artifact_index, ordinal, source)
                yield unit.source_unit, unit.publisher_records, unit.expected_emitted_rows
            if artifact_records == 0:
                raise ValueError("IMGW publisher artifact contains no logical CSV records")

    inventory_sha256 = source_unit_inventory_fingerprint(units())
    return total_records, total_records * len(_PRODUCT_COLUMNS), inventory_sha256


def _imgw_artifact_period(path: Path) -> tuple[int, tuple[int, ...]]:
    match = _ARTIFACT_NAME.search(path.name)
    if match is None:
        raise ValueError(f"IMGW artifact name does not declare its publication period: {path.name}")
    year = int(match.group("year"))
    if year < 2:
        raise ValueError(f"IMGW artifact has invalid hydrological year: {path.name}")
    month_text = match.group("month")
    if month_text is None:
        return year, tuple(range(1, 13))
    month = int(month_text)
    if month < 1 or month > 12:
        raise ValueError(f"IMGW artifact has invalid hydrological month: {path.name}")
    return year, (month,)


def _calendar_years(period: tuple[int, tuple[int, ...]]) -> tuple[int, ...]:
    year, months = period
    return tuple(sorted({year - 1 if month <= 2 else year for month in months}))


def _iter_imgw_product_year(
    path: Path, product: ProductId, calendar_year: int, artifact_index: int
) -> Iterator[tuple[SourceUnitCount, dict[str, object]]]:
    period = _imgw_artifact_period(path)
    for ordinal, source in enumerate(_iter_imgw_records(path), start=1):
        output: list[dict[str, object]] = []
        _emit_source_row(source, path.name, ordinal, output, expected_period=period)
        for row in output:
            if row["product"] == str(product) and cast(datetime, row["time"]).year == calendar_year:
                yield _imgw_source_unit(path, artifact_index, ordinal, source), row


def _external_station_sort(rows):
    """Bounded external sort by station identifier and source ordinal."""
    import pickle
    import sqlite3
    import tempfile

    with tempfile.TemporaryDirectory(prefix="rivretrieve-imgw-sort-") as directory:
        database = Path(directory) / "rows.sqlite3"
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "CREATE TABLE rows (station BLOB NOT NULL, ordinal INTEGER NOT NULL, payload BLOB NOT NULL)"
            )
            pending: list[tuple[bytes, int, bytes]] = []
            for ordinal, item in enumerate(rows):
                pending.append((str(item[1]["station_id"]).encode("utf-8"), ordinal, pickle.dumps(item, protocol=5)))
                if len(pending) == IMGW_ROWS_PER_BATCH:
                    connection.executemany("INSERT INTO rows VALUES (?, ?, ?)", pending)
                    pending = []
            if pending:
                connection.executemany("INSERT INTO rows VALUES (?, ?, ?)", pending)
            connection.commit()
            cursor = connection.execute("SELECT payload FROM rows ORDER BY station, ordinal")
            while chunk := cursor.fetchmany(IMGW_ROWS_PER_BATCH):
                for (payload,) in chunk:
                    yield pickle.loads(payload)
        finally:
            connection.close()


def _merge_station_order(
    iterators: list[Iterator[tuple[SourceUnitCount, dict[str, object]]]],
) -> Iterator[tuple[SourceUnitCount, dict[str, object]]]:
    import heapq

    heap: list[
        tuple[bytes, int, int, SourceUnitCount, dict[str, object], Iterator[tuple[SourceUnitCount, dict[str, object]]]]
    ] = []
    for source_index, iterator in enumerate(iterators):
        try:
            source_unit, row = next(iterator)
        except StopIteration:
            continue
        station = str(row["station_id"]).encode("utf-8")
        heapq.heappush(heap, (station, source_index, 0, source_unit, row, iterator))
    while heap:
        _station, source_index, ordinal, source_unit, row, iterator = heapq.heappop(heap)
        yield source_unit, row
        try:
            next_unit, following = next(iterator)
        except StopIteration:
            continue
        next_station = str(following["station_id"]).encode("utf-8")
        heapq.heappush(heap, (next_station, source_index, ordinal + 1, next_unit, following, iterator))


def _iter_imgw_records(path: Path):
    yield from _iter_imgw_raw_records(path)


def _iter_imgw_raw_records(path: Path):
    import itertools

    artifact = Path(path)
    if not artifact.is_file():
        raise FileNotFoundError(f'IMGW publisher artifact does not exist: "{artifact}"')
    try:
        with zipfile.ZipFile(artifact) as archive:
            members = sorted(
                (info for info in archive.infolist() if not info.is_dir()),
                key=lambda info: info.filename.encode("utf-8"),
            )
            if len(members) != 1 or Path(members[0].filename).suffix.lower() != ".csv":
                raise ValueError("IMGW ZIP archive must contain exactly one CSV member")
            info = members[0]
            period_match = _ARTIFACT_NAME.search(artifact.name)
            assert period_match is not None
            declared_archive = period_match.group(0)
            expected_member = Path(declared_archive).with_suffix(".csv").name
            if Path(info.filename).name != expected_member:
                raise ValueError("IMGW ZIP member name does not match the publisher artifact period")
            with archive.open(info) as probe:
                encoding = "utf-8-sig" if probe.read(3).startswith(b"\xef\xbb\xbf") else "cp1250"
            with archive.open(info) as raw:
                text = io.TextIOWrapper(cast(Any, raw), encoding=encoding, errors="strict", newline="")
                first = text.readline()
                if not first:
                    return
                delimiter = ";" if ";" in first else ","
                lines = itertools.chain((first,), text)
                reader = csv.reader(lines, delimiter=delimiter, strict=True)
                for line_number, record in enumerate(reader, start=1):
                    if not record or (len(record) == 1 and record[0] == ""):
                        continue
                    # Annual source files can encode an entire CSV record as one
                    # quoted field. Decode that publisher layer without materializing
                    # the archive or changing the ten native cell strings.
                    if delimiter == "," and len(record) == 1:
                        record = next(csv.reader((record[0],), delimiter=",", strict=True))
                    if len(record) != len(_SOURCE_FIELDS):
                        raise ValueError(
                            f"IMGW member {info.filename!r} row {line_number} has {len(record)} source columns; expected {len(_SOURCE_FIELDS)}"
                        )
                    yield tuple(record)
    except zipfile.BadZipFile as error:
        raise ValueError("IMGW publisher artifact is not a valid ZIP") from error


def _imgw_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
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
            *_RETAINED_NAMES,
        )
        .with_columns(
            pl.col(
                "product",
                "station_id",
                "time_zone",
                "value_state",
                "series_id",
                "facts_id",
                "source_unit",
                *_RETAINED_NAMES,
            ).cast(pl.String),
            pl.col("time").cast(pl.Datetime("us")),
            pl.col("value").cast(pl.Float64),
        )
    )


def _emit_source_row(
    source: tuple[str, ...],
    member: str,
    ordinal: int,
    output: list[dict[str, object]],
    *,
    expected_period: tuple[int, tuple[int, ...]] | None = None,
) -> None:
    station = source[0].strip()
    if not station:
        raise ValueError(f"IMGW member {member!r} row {ordinal} has a blank station code")
    hydrological_year = _integer(source[3], member, ordinal, "hydrological_year")
    hydrological_month = _integer(source[4], member, ordinal, "month_indicator")
    if expected_period is not None:
        expected_year, expected_months = expected_period
        if hydrological_year != expected_year or hydrological_month not in expected_months:
            raise ValueError(
                f"IMGW filename publication period disagrees with hydrological year/month in {member!r} row {ordinal}"
            )
    if not 1 <= hydrological_month <= 12:
        raise ValueError(f"IMGW member {member!r} row {ordinal} has invalid month_indicator")
    day = _integer(source[5], member, ordinal, "day")
    # IMGW defines hydrological months 01..12 as November..October. The
    # additional calendar-month cell can be blank; retain it without filling it.
    calendar_month = (hydrological_month + 9) % 12 + 1
    if source[9].strip() and _integer(source[9], member, ordinal, "calendar_month") != calendar_month:
        raise ValueError(f"IMGW member {member!r} row {ordinal} has inconsistent month indicators")
    calendar_year = hydrological_year - 1 if hydrological_month <= 2 else hydrological_year
    try:
        timestamp = datetime(calendar_year, calendar_month, day)
    except ValueError as error:
        raise ValueError(f"IMGW member {member!r} row {ordinal} has an invalid calendar date") from error
    retained = dict(zip(_RETAINED_NAMES, source, strict=True))
    for product, value_index, null_sentinels in _PRODUCT_COLUMNS:
        definition = source_series(station, str(product))
        facts = definition.facts[0]
        value, state = _native_value(source[value_index], member, ordinal, _SOURCE_FIELDS[value_index], null_sentinels)
        output.append(
            {
                "product": str(product),
                "station_id": station,
                "time": timestamp,
                "time_zone": "unknown",
                "value": value,
                "value_state": state,
                "series_id": definition.series_id,
                "facts_id": facts.facts_id,
                "source_unit": facts.source_unit.value,
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
    if not math.isfinite(value):
        raise ValueError(f"IMGW member {member!r} row {ordinal} has non-finite {field}")
    if value in null_sentinels:
        return None, "published_null"
    return value, "published_value"


def _sha256(path: Path) -> ArtifactChecksum:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return ArtifactChecksum(f"sha256:{digest.hexdigest()}")


def _batch_series(rows: list[dict[str, object]]) -> tuple[SourceSeries, ...]:
    pairs = {(str(row["station_id"]), str(row["product"])) for row in rows}
    return tuple(source_series(station, product) for station, product in sorted(pairs))
