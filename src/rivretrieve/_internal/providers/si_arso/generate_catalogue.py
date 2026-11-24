"""Offline catalogue builder for official Slovenia ARSO hydrological data.

Reconstructs the canonical 619-station flowing river and canal universe,
rescues documented Q-statistics metadata/coordinates where omitted from
``Spisek vodomernih postaj_okt2019.xlsx``, witnesses parameter availability and
published date bounds across exhaustive ``b_oddo_CSV`` / ``b_eks_CSV`` / ``amp``
captures, and packages provenance-bound runtime catalogue tables.
"""

from __future__ import annotations

import calendar
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import cast

import openpyxl
import polars as pl

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    CatalogueBuildInputs,
    RecordingReference,
    RetainedInputReceipt,
)
from rivretrieve._internal.catalogue_origins import OriginDeclarations
from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, stamp_native_table
from rivretrieve._internal.catalogues.source_series import SourceDescriptions
from rivretrieve._internal.catalogues.station_metadata import MetadataField
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.si_arso.series import (
    DEFERRED_AMP_COLUMNS,
    DEFERRED_EKS_PREFIXES,
    DEFERRED_ODDO_COLUMNS,
    PRODUCT_SPECS,
    SPECS_BY_AMP_ROUTE,
    SPECS_BY_ARCHIVE_COLUMN,
    SPECS_BY_EKS_PREFIX,
    SPECS_BY_PRODUCT_ID,
    build_source_descriptions,
    product_native_coordinate,
    product_physical_facts,
    route_product_facts,
    station_amp_t1_frequency,
)

__all__ = [
    "ASSOCIATION_SCHEMA",
    "EXCLUDED_COASTAL_STATIONS",
    "EXCLUDED_LAKE_STATIONS",
    "EXCLUDED_SPRING_STATIONS",
    "EXCLUDED_STATIONS",
    "STAMPED_STATION_SCHEMA",
    "STATION_SOURCE_SCHEMA",
    "GeneratedSiArsoCatalogue",
    "SiArsoCatalogueSources",
    "build_catalogue",
    "catalogue_tables",
    "describe_associations",
    "main",
    "read_catalogue_sources",
    "read_native_sources",
    "read_original",
    "selected_supporting_inputs",
    "station_native_table",
    "write_catalogue",
]

EXCLUDED_LAKE_STATIONS: frozenset[str] = frozenset({"2860", "3280", "3340", "3350", "3360", "5670", "5680", "8451"})
EXCLUDED_SPRING_STATIONS: frozenset[str] = frozenset(
    {
        "4360",
        "4965",
        "4985",
        "4986",
        "5290",
        "5300",
        "5310",
        "5580",
        "6253",
        "7230",
        "7245",
        "7250",
        "7260",
        "7350",
        "7518",
        "8452",
        "8453",
        "8549",
    }
)
EXCLUDED_COASTAL_STATIONS: frozenset[str] = frozenset({"9350", "9400"})
EXCLUDED_STATIONS: frozenset[str] = EXCLUDED_LAKE_STATIONS | EXCLUDED_SPRING_STATIONS | EXCLUDED_COASTAL_STATIONS

STATION_SOURCE_SCHEMA = pl.Schema(
    {
        "sifra": pl.String,
        "VODOMERNA POSTAJA": pl.String,
        "VODOTOK": pl.String,
        "gky": pl.Float64,
        "gkx": pl.Float64,
        "ZALEDJE - F (km2)": pl.Float64,
        "Postaja": pl.String,
        "Vodotok": pl.String,
        "F (km2)": pl.Float64,
        "dropdown_postaja": pl.String,
        "dropdown_vodotok": pl.String,
        "in_spisek": pl.Boolean,
        "in_q_stats": pl.Boolean,
        "in_amp": pl.Boolean,
    }
)
STAMPED_STATION_SCHEMA = pl.Schema({**STATION_SOURCE_SCHEMA, "retrieved_at": pl.Datetime("us", "UTC")})

ASSOCIATION_SCHEMA = pl.Schema(
    {
        "station_id": pl.String,
        "product_id": pl.String,
        "published_record_start_date": pl.Date,
        "published_record_end_date": pl.Date,
        "stream": pl.String,
    }
)

_AMP_HREF_RE = re.compile(r"H(\d{4})_[gt]_(?:1|7|30)\.html")
_COORD_X_RE = re.compile(r"X koordinata:\s*([0-9]+(?:[.,][0-9]+)?)")
_COORD_Y_RE = re.compile(r"Y koordinata:\s*([0-9]+(?:[.,][0-9]+)?)")
_SPISEK_EXPECTED_PREFIX = (
    "ŠIFRA",
    "VODOMERNA POSTAJA",
    "VODOTOK",
    "GKY",
    "GKX",
    "LON",
    "LAT",
    "ZALEDJE - F (km2)",
)


class _DropdownHtmlParser(HTMLParser):
    """Extract selected river and gauge options from ``pov_arhiv_tab.php`` HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._select_name: str | None = None
        self._opt_val: str | None = None
        self._opt_selected = False
        self._buf: list[str] = []
        self.selected_rivers: list[str] = []
        self.all_rivers: list[str] = []
        self.stations: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "select":
            self._select_name = attr_map.get("name")
        elif tag == "option" and self._select_name in {"p_vodotok", "p_postaja"}:
            self._opt_val = (attr_map.get("value") or "").strip()
            self._opt_selected = "selected" in attr_map
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "select":
            self._select_name = None
        elif tag == "option" and self._opt_val is not None:
            text = " ".join("".join(self._buf).split())
            if self._select_name == "p_vodotok" and self._opt_val:
                self.all_rivers.append(" ".join(self._opt_val.split()))
                if self._opt_selected:
                    self.selected_rivers.append(" ".join(self._opt_val.split()))
            elif self._select_name == "p_postaja" and self._opt_val:
                self.stations.append((self._opt_val, text))
            self._opt_val = None

    def handle_data(self, data: str) -> None:
        if self._opt_val is not None:
            self._buf.append(data)


class _PodatkiTableParser(HTMLParser):
    """Extract headers and first-column timestamps from ``<table class="podatki">``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_table = False
        self._in_tbody = False
        self._in_th = False
        self._in_tr = False
        self._col_index = 0
        self._in_first_td = False
        self._buf: list[str] = []
        self.headers: list[str] = []
        self.timestamps: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "table" and "podatki" in (attr_map.get("class") or "").split():
            self._in_table = True
        elif not self._in_table:
            return
        elif tag == "th":
            self._in_th = True
            self._buf = []
        elif tag == "tbody":
            self._in_tbody = True
        elif self._in_tbody and tag == "tr":
            self._in_tr = True
            self._col_index = 0
        elif self._in_tr and tag == "td" and self._col_index == 0:
            self._in_first_td = True
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_table:
            self._in_table = False
            self._in_tbody = False
            self._in_tr = False
        elif tag == "th" and self._in_th:
            self._in_th = False
            self.headers.append(" ".join("".join(self._buf).split()))
        elif tag == "tbody":
            self._in_tbody = False
            self._in_tr = False
        elif tag == "tr":
            self._in_tr = False
        elif tag == "td" and self._in_tr:
            if self._in_first_td:
                text = " ".join("".join(self._buf).split())
                if text:
                    self.timestamps.append(text)
                self._in_first_td = False
            self._col_index += 1

    def handle_data(self, data: str) -> None:
        if self._in_th or self._in_first_td:
            self._buf.append(data)


@dataclass(frozen=True, slots=True)
class _SpisekEntry:
    station_name: str | None
    water_body_name: str | None
    gky: float | None
    gkx: float | None
    drainage_area: float | None


@dataclass(frozen=True, slots=True)
class _QStatsEntry:
    station_name: str | None
    water_body_name: str | None
    gky: float | None
    gkx: float | None
    drainage_area: float | None


@dataclass(frozen=True)
class GeneratedSiArsoCatalogue:
    """Generated canonical Slovenia ARSO catalogue tables and provenance."""

    provider_info: dict[str, object]
    products: pl.DataFrame
    stations: pl.DataFrame
    station_products: pl.DataFrame
    station_metadata: pl.DataFrame
    acquisition_provenance: AcquisitionProvenance
    source_descriptions: SourceDescriptions


@dataclass(frozen=True)
class SiArsoCatalogueSources:
    """Verified retained Slovenia ARSO catalogue inputs."""

    native_table: NativeTable
    associations: pl.DataFrame
    provenance: AcquisitionProvenance
    checked_on: date


def _as_clean_str(value: object) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text if text else None


def _as_float(value: object, *, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise FatalContractError(f"Unexpected boolean scalar for {label}")
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        number = float(text.replace(",", "."))
    else:
        raise FatalContractError(f"Unsupported scalar type for {label}: {type(value).__name__}")
    if not math.isfinite(number):
        raise FatalContractError(f"Non-finite scalar for {label}: {value!r}")
    return number


def _parse_pov_arhiv_tab(raw: bytes) -> tuple[set[str], dict[str, str]]:
    parser = _DropdownHtmlParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    if not parser.all_rivers or not parser.stations:
        raise FatalContractError("ARSO pov_arhiv_tab.php capture contains no p_vodotok or p_postaja options")
    stations: dict[str, str] = {}
    for code, name in parser.stations:
        if not re.fullmatch(r"\d{4}", code):
            raise FatalContractError(f"Unexpected ARSO p_postaja option code: {code!r}")
        if not name:
            raise FatalContractError(f"Empty ARSO station label in pov_arhiv_tab for {code}")
        stations[code] = name
    return set(parser.all_rivers), stations


def _parse_dropdown_page(raw: bytes) -> tuple[str, dict[str, set[str]]]:
    parser = _DropdownHtmlParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    if len(parser.selected_rivers) != 1:
        raise FatalContractError(f"ARSO dropdown capture must select exactly one river, got {parser.selected_rivers!r}")
    river = " ".join(parser.selected_rivers[0].split())
    stations: dict[str, set[str]] = defaultdict(set)
    for code, name in parser.stations:
        if not re.fullmatch(r"\d{4}", code):
            raise FatalContractError(f"Unexpected ARSO p_postaja code {code!r} on river {river!r}")
        if not name:
            raise FatalContractError(f"Empty ARSO station name for {code!r} on river {river!r}")
        stations[code].add(name)
    return river, stations


def _parse_spisek_workbook(raw: bytes) -> dict[str, _SpisekEntry]:
    workbook = openpyxl.load_workbook(BytesIO(raw), data_only=True, read_only=True)
    if "VSE_VP" not in workbook.sheetnames or "LEGENDA" not in workbook.sheetnames:
        raise FatalContractError("Spisek workbook lacks expected VSE_VP or LEGENDA worksheet")
    sheet = workbook["VSE_VP"]
    rows = iter(sheet.iter_rows(values_only=True))
    try:
        header = next(rows)
    except StopIteration as exc:
        raise FatalContractError("Spisek VSE_VP worksheet is empty") from exc
    if header[: len(_SPISEK_EXPECTED_PREFIX)] != _SPISEK_EXPECTED_PREFIX:
        raise FatalContractError(f"Unexpected Spisek VSE_VP header columns: {header[:10]!r}")

    entries: dict[str, _SpisekEntry] = {}
    for row in rows:
        if not row or row[0] is None:
            continue
        code = str(row[0]).strip()
        if not re.fullmatch(r"\d{4}", code):
            raise FatalContractError(f"Unexpected Spisek ŠIFRA value: {code!r}")
        if code in entries:
            raise FatalContractError(f"Duplicate ŠIFRA {code!r} in Spisek VSE_VP")
        gky = _as_float(row[3], label=f"Spisek {code} GKY")
        gkx = _as_float(row[4], label=f"Spisek {code} GKX")
        if (gky is None) != (gkx is None):
            raise FatalContractError(f"Partial D48/GK coordinates in Spisek for {code}")
        entries[code] = _SpisekEntry(
            station_name=_as_clean_str(row[1]),
            water_body_name=_as_clean_str(row[2]),
            gky=gky,
            gkx=gkx,
            drainage_area=_as_float(row[7], label=f"Spisek {code} ZALEDJE - F (km2)"),
        )
    if not entries:
        raise FatalContractError("Spisek VSE_VP yielded zero stations")
    return entries


def _parse_q_stats_workbook(raw: bytes) -> dict[str, _QStatsEntry]:
    workbook = openpyxl.load_workbook(BytesIO(raw), data_only=True, read_only=True)
    entries: dict[str, _QStatsEntry] = {}
    for sheetname in workbook.sheetnames:
        sid = sheetname.strip()
        if not re.fullmatch(r"\d{4}", sid):
            continue
        if sid in entries:
            raise FatalContractError(f"Duplicate Q_stats worksheet for station {sid}")
        sheet = workbook[sheetname]
        lines: list[str] = []
        for row in sheet.iter_rows(min_row=1, max_row=10, values_only=True):
            for cell in row:
                if cell is not None:
                    text = str(cell).strip()
                    if text:
                        lines.append(text)
        station_name: str | None = None
        water_body_name: str | None = None
        drainage_area: float | None = None
        gky: float | None = None
        gkx: float | None = None
        for line in lines:
            if line.startswith("Vodotok:"):
                water_body_name = _as_clean_str(line.split(":", 1)[1])
            elif line.startswith("Postaja:"):
                station_name = _as_clean_str(line.split(":", 1)[1])
            elif line.startswith("Šifra postaje:"):
                declared = line.split(":", 1)[1].strip()
                if declared and declared != sid:
                    raise FatalContractError(f"Q_stats sheet {sid} declares mismatched Šifra postaje {declared!r}")
            elif line.startswith("F (km2):"):
                drainage_area = _as_float(line.split(":", 1)[1], label=f"Q_stats {sid} F (km2)")
            elif "X koordinata:" in line:
                match_x = _COORD_X_RE.search(line)
                match_y = _COORD_Y_RE.search(line)
                if match_x:
                    gkx = _as_float(match_x.group(1), label=f"Q_stats {sid} GKX")
                if match_y:
                    gky = _as_float(match_y.group(1), label=f"Q_stats {sid} GKY")
        if (gky is None) != (gkx is None):
            raise FatalContractError(f"Partial D48/GK coordinates in Q_stats for {sid}")
        entries[sid] = _QStatsEntry(
            station_name=station_name,
            water_body_name=water_body_name,
            gky=gky,
            gkx=gkx,
            drainage_area=drainage_area,
        )
    return entries


def _parse_amp_index(raw: bytes) -> set[str]:
    text = raw.decode("utf-8", errors="replace")
    return set(_AMP_HREF_RE.findall(text))


def _parse_archive_date(token: str, *, station: str) -> date:
    if len(token) != 10 or token[2] != "." or token[5] != ".":
        raise FatalContractError(f"Unexpected ARSO archive date token {token!r} on station {station}")
    try:
        return date(int(token[6:10]), int(token[3:5]), int(token[0:2]))
    except ValueError as exc:
        raise FatalContractError(f"Invalid ARSO archive calendar date {token!r} on station {station}") from exc


def _parse_strict_float(cell: str, *, context: str) -> float:
    if "_" in cell:
        raise FatalContractError(f"Unsupported underscore in numeric cell {cell!r} ({context})")
    try:
        value = float(cell)
    except ValueError as exc:
        raise FatalContractError(f"Non-numeric ARSO archive value {cell!r} ({context})") from exc
    if not math.isfinite(value):
        raise FatalContractError(f"Non-finite ARSO archive value {cell!r} ({context})")
    return value


def _inspect_oddo_associations(station: str, raw: bytes) -> list[tuple[str, str, date, date, str]]:
    text = raw.decode("utf-8")
    lines = text.splitlines()
    if not lines:
        raise FatalContractError(f"Empty ARSO b_oddo_CSV response for station {station}")
    headers = lines[0].split(";")
    if not headers or headers[0] != "Datum":
        raise FatalContractError(f"ARSO b_oddo_CSV header must begin with 'Datum', got {headers[:2]!r} ({station})")

    active_columns: list[tuple[int, str]] = []
    allowed_deferred = DEFERRED_ODDO_COLUMNS
    for idx, col in enumerate(headers[1:], start=1):
        spec = SPECS_BY_ARCHIVE_COLUMN.get(col)
        if spec is not None:
            active_columns.append((idx, spec.product_id))
        elif col not in allowed_deferred:
            raise FatalContractError(f"Unclassified ARSO b_oddo_CSV column {col!r} on station {station}")
    if not active_columns:
        return []

    starts: dict[str, date | None] = {product_id: None for _, product_id in active_columns}
    ends: dict[str, date | None] = {product_id: None for _, product_id in active_columns}

    for line in lines[1:]:
        # Skip rows where every column after Datum is empty (~90% of rows since 1895).
        if ";" not in line.rstrip(";"):
            continue
        cells = line.split(";")
        n_cells = len(cells)
        row_date: date | None = None
        for idx, product_id in active_columns:
            if idx >= n_cells:
                continue
            raw_val = cells[idx].strip()
            if not raw_val:
                continue
            _parse_strict_float(raw_val, context=f"oddo {station} {product_id}")
            if row_date is None:
                row_date = _parse_archive_date(cells[0].strip(), station=station)
            prev_start = starts[product_id]
            prev_end = ends[product_id]
            if prev_start is None or row_date < prev_start:
                starts[product_id] = row_date
            if prev_end is None or row_date > prev_end:
                ends[product_id] = row_date

    results: list[tuple[str, str, date, date, str]] = []
    for _, product_id in active_columns:
        start_d = starts[product_id]
        end_d = ends[product_id]
        if start_d is not None and end_d is not None:
            results.append((station, product_id, start_d, end_d, "archive_daily"))
    return results


def _inspect_eks_associations(station: str, raw: bytes) -> list[tuple[str, str, date, date, str]]:
    text = raw.decode("utf-8")
    lines = text.splitlines()
    if not lines:
        raise FatalContractError(f"Empty ARSO b_eks_CSV response for station {station}")
    headers = lines[0].split(";")
    if len(headers) < 2 or headers[:2] != ["Leto", "Mesec"]:
        raise FatalContractError(f"ARSO b_eks_CSV header must start with Leto;Mesec, got {headers[:3]!r} ({station})")

    col_lookup: dict[str, tuple[int, str]] = {}
    prefix_seen_cols: dict[str, set[str]] = defaultdict(set)
    for idx, col in enumerate(headers[2:], start=2):
        matched = False
        for suffix, col_role in (("_datum", "datum"), ("_vrednost", "vrednost")):
            for extremum in ("_MIN", "_MAX"):
                full_suffix = f"{extremum}{suffix}"
                if col.endswith(full_suffix):
                    eks_key = col.removesuffix(suffix)
                    prefix = col.removesuffix(full_suffix)
                    spec = SPECS_BY_EKS_PREFIX.get(eks_key)
                    if spec is not None:
                        prefix_seen_cols[eks_key].add(col_role)
                        if col_role == "vrednost":
                            col_lookup[eks_key] = (idx, spec.product_id)
                    elif prefix not in DEFERRED_EKS_PREFIXES:
                        raise FatalContractError(f"Unclassified ARSO b_eks_CSV prefix {prefix!r} on station {station}")
                    matched = True
                    break
            if matched:
                break
        if not matched:
            raise FatalContractError(f"Malformed ARSO b_eks_CSV column name {col!r} on station {station}")

    expected_pair = {"datum", "vrednost"}
    for eks_key, cols in prefix_seen_cols.items():
        if cols != expected_pair:
            raise FatalContractError(f"Incomplete ARSO b_eks_CSV columns for {eks_key!r} on {station}: {sorted(cols)}")

    if not col_lookup:
        return []

    starts: dict[str, date | None] = {pid: None for _, pid in col_lookup.values()}
    ends: dict[str, date | None] = {pid: None for _, pid in col_lookup.values()}

    for line in lines[1:]:
        if line.count(";") < 2 or not line.split(";", 2)[2].strip(";"):
            continue
        cells = line.split(";")
        n_cells = len(cells)
        year = int(cells[0])
        month = int(cells[1])
        month_start = date(year, month, 1)
        month_end = date(year, month, calendar.monthrange(year, month)[1])
        for idx, product_id in col_lookup.values():
            if idx >= n_cells:
                continue
            raw_val = cells[idx].strip()
            if not raw_val:
                continue
            _parse_strict_float(raw_val, context=f"eks {station} {product_id}")
            prev_start = starts[product_id]
            prev_end = ends[product_id]
            if prev_start is None or month_start < prev_start:
                starts[product_id] = month_start
            if prev_end is None or month_end > prev_end:
                ends[product_id] = month_end

    results: list[tuple[str, str, date, date, str]] = []
    for _, product_id in col_lookup.values():
        start_d = starts[product_id]
        end_d = ends[product_id]
        if start_d is not None and end_d is not None:
            results.append((station, product_id, start_d, end_d, "archive_monthly_extremes"))
    return results


def _amp_uniform_frequency(station: str, cadence: str, raw_timestamps: list[str]) -> str:
    """Verify uniform AMP row cadence and match against declared ``si_arso`` ISO 8601 frequency."""
    if len(raw_timestamps) < 2:
        raise FatalContractError(f"ARSO AMP page {station} {cadence} has fewer than 2 rows ({len(raw_timestamps)})")
    try:
        parsed = [datetime.strptime(item, "%d.%m.%Y %H:%M") for item in raw_timestamps]
    except ValueError as exc:
        raise FatalContractError(f"ARSO AMP page {station} {cadence} has invalid Datum timestamp: {exc}") from exc
    diffs = {int((parsed[i] - parsed[i + 1]).total_seconds()) for i in range(len(parsed) - 1)}
    if len(diffs) != 1:
        raise FatalContractError(f"ARSO AMP page {station} {cadence} has non-uniform spacing seconds: {sorted(diffs)}")
    step_seconds = next(iter(diffs))
    if step_seconds <= 0 or step_seconds % 60 != 0:
        raise FatalContractError(
            f"ARSO AMP page {station} {cadence} has unexpected descending step_seconds={step_seconds}"
        )
    step_minutes = step_seconds // 60
    observed = "PT1H" if step_minutes == 60 else f"PT{step_minutes}M"
    if cadence == "t_1":
        expected = station_amp_t1_frequency(station)
    elif cadence == "t_7":
        expected = "PT30M"
    elif cadence == "t_30":
        expected = "PT1H"
    else:
        raise FatalContractError(f"Unsupported ARSO AMP cadence {cadence!r} for station {station!r}")
    if observed != expected:
        raise FatalContractError(
            f"ARSO AMP page {station} {cadence} cadence mismatch: expected {expected!r}, observed {observed!r}"
        )
    return observed


def _inspect_amp_associations(
    station: str,
    cadence: str,
    raw: bytes,
) -> list[tuple[str, str, None, None, str]]:
    text = raw.decode("utf-8", errors="replace")
    table_start = text.find('<table class="podatki">')
    if table_start >= 0:
        table_end = text.find("</table>", table_start)
        snippet = text[table_start : table_end + 8] if table_end >= 0 else text[table_start:]
    else:
        snippet = text
    parser = _PodatkiTableParser()
    parser.feed(snippet)
    if not parser.headers:
        raise FatalContractError(f"ARSO AMP page {station} {cadence} contains no <table class='podatki'> headers")
    if parser.headers[0] != "Datum":
        raise FatalContractError(
            f"ARSO AMP table must start with 'Datum', got {parser.headers!r} ({station} {cadence})"
        )
    _amp_uniform_frequency(station, cadence, parser.timestamps)

    results: list[tuple[str, str, None, None, str]] = []
    for col in parser.headers[1:]:
        spec = SPECS_BY_AMP_ROUTE.get((cadence, col))
        if spec is not None:
            results.append((station, spec.product_id, None, None, f"amp_{cadence}"))
        elif col not in DEFERRED_AMP_COLUMNS:
            raise FatalContractError(f"Unclassified ARSO AMP column {col!r} on {station} {cadence}")
    return results


def station_native_table(
    *,
    dropdown_station_names: dict[str, set[str]],
    dropdown_river_names: dict[str, set[str]],
    spisek: dict[str, _SpisekEntry],
    q_stats: dict[str, _QStatsEntry],
    in_scope_ids: set[str],
    amp_station_ids: set[str],
    retrieved_at: RetrievedAt,
) -> NativeTable:
    """Build the verified native station metadata table for the 619 ARSO gauges."""
    rows: list[dict[str, object]] = []
    for sid in sorted(in_scope_ids):
        sp = spisek.get(sid)
        qs = q_stats.get(sid)
        dd_names = sorted(dropdown_station_names.get(sid, set()))
        dd_rivers = sorted(dropdown_river_names.get(sid, set()))
        if not dd_names or not dd_rivers:
            raise FatalContractError(f"ARSO dropdown station {sid} lacks river or station label")

        gky = sp.gky if sp is not None and sp.gky is not None else (qs.gky if qs is not None else None)
        gkx = sp.gkx if sp is not None and sp.gkx is not None else (qs.gkx if qs is not None else None)
        if (gky is None) != (gkx is None):
            raise FatalContractError(f"Incomplete D48/GK coordinates assembled for ARSO station {sid}")

        rows.append(
            {
                "sifra": sid,
                "VODOMERNA POSTAJA": sp.station_name if sp is not None else None,
                "VODOTOK": sp.water_body_name if sp is not None else None,
                "gky": gky,
                "gkx": gkx,
                "ZALEDJE - F (km2)": sp.drainage_area if sp is not None else None,
                "Postaja": qs.station_name if qs is not None else None,
                "Vodotok": qs.water_body_name if qs is not None else None,
                "F (km2)": qs.drainage_area if qs is not None else None,
                "dropdown_postaja": " / ".join(dd_names),
                "dropdown_vodotok": " / ".join(dd_rivers),
                "in_spisek": sp is not None,
                "in_q_stats": qs is not None,
                "in_amp": sid in amp_station_ids,
            }
        )
    frame = pl.DataFrame(rows, schema=STATION_SOURCE_SCHEMA).sort("sifra")
    return stamp_native_table(frame, retrieved_at)


def _project_to_wgs84(gky: pl.Series, gkx: pl.Series) -> tuple[pl.Series, pl.Series]:
    """Re-project D48/GK (EPSG:3912) coordinates to WGS 84 (EPSG:4326).

    Independent of ``origins.D48GkToWgs84Conversion``, which re-verifies this
    projection inside the shared origin gate.
    """
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:3912", "EPSG:4326", always_xy=True)
    lon: list[float | None] = []
    lat: list[float | None] = []
    for easting, northing in zip(gky.to_list(), gkx.to_list(), strict=True):
        if easting is None or northing is None:
            lon.append(None)
            lat.append(None)
            continue
        projected_lon, projected_lat = transformer.transform(easting, northing)
        lon.append(projected_lon)
        lat.append(projected_lat)
    return pl.Series("longitude", lon, dtype=pl.Float64), pl.Series("latitude", lat, dtype=pl.Float64)


def catalogue_tables(
    native: NativeTable,
    associations: pl.DataFrame,
    *,
    checked_on: date,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Assemble validated ``products``, ``stations``, and ``station_products`` tables."""
    from rivretrieve._internal.catalogues.products import product_row
    from rivretrieve._internal.catalogues.schemas import (
        PRODUCT_CATALOG_SCHEMA,
        STATION_CATALOG_SCHEMA,
        STATION_PRODUCT_CATALOG_SCHEMA,
        validate_catalogue,
    )

    lon_s, lat_s = _project_to_wgs84(native.data["gky"], native.data["gkx"])
    crs_s = pl.Series(
        "crs",
        ["EPSG:4326" if val is not None else "unknown" for val in native.data["gky"].to_list()],
        dtype=pl.String,
    )
    stations = (
        native.data.select(pl.lit("si_arso").alias("provider_id"), pl.col("sifra").alias("station_id"))
        .with_columns(latitude=lat_s, longitude=lon_s, crs=crs_s)
        .sort("station_id")
    )

    station_set = set(stations["station_id"].to_list())
    if not set(associations["station_id"].to_list()) <= station_set:
        raise FatalContractError("ARSO association references station outside canonical station catalogue")

    product_rows = [
        product_row(
            "si_arso",
            spec.product_id,
            product_native_coordinate(spec),
            route_product_facts(spec.product_id),
        )
        for spec in PRODUCT_SPECS
    ]
    products = pl.DataFrame(product_rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")

    observed: dict[tuple[str, str], tuple[date | None, date | None]] = {}
    for row in associations.iter_rows(named=True):
        pair = (str(row["station_id"]), str(row["product_id"]))
        if pair in observed:
            raise FatalContractError(f"Duplicate ARSO association for {pair!r}")
        observed[pair] = (row["published_record_start_date"], row["published_record_end_date"])

    in_amp = {str(row["sifra"]) for row in native.data.select("sifra", "in_amp").iter_rows(named=True) if row["in_amp"]}

    pair_rows: list[dict[str, object]] = []
    for station in stations["station_id"].to_list():
        for spec in PRODUCT_SPECS:
            bounds = observed.get((station, spec.product_id))
            if bounds is not None:
                start_d, end_d = bounds
                if spec.stream == "amp":
                    reason = "Witnessed in ARSO AMP operational table header; rolling 1-, 7-, or 30-day window"
                else:
                    reason = (
                        "Witnessed in exhaustive ARSO hydrological archive CSV snapshot with empirical record bounds"
                    )
                availability = "available"
            else:
                start_d, end_d = None, None
                availability = "unavailable"
                if spec.stream != "amp":
                    reason = "No populated observations for this parameter in exhaustive ARSO hydrological archive CSV snapshot"
                elif station not in in_amp:
                    reason = "Station not listed in ARSO AMP operational surface-water index"
                else:
                    reason = "Parameter column absent from ARSO AMP operational table header"
            pair_rows.append(
                {
                    "provider_id": "si_arso",
                    "station_id": station,
                    "product_id": spec.product_id,
                    "availability": availability,
                    "availability_reason": reason,
                    "published_record_start_date": start_d,
                    "published_record_end_date": end_d,
                    "last_catalogue_check": checked_on,
                }
            )
    pairs = pl.DataFrame(pair_rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).sort(
        "station_id", "product_id"
    )

    for frame, schema in (
        (products, PRODUCT_CATALOG_SCHEMA),
        (stations, STATION_CATALOG_SCHEMA),
        (pairs, STATION_PRODUCT_CATALOG_SCHEMA),
    ):
        validate_catalogue(frame, schema, on_issue="raise")
    return products, stations, pairs


def describe_associations(associations: pl.DataFrame) -> SourceDescriptions:
    """Group available ``si_arso`` associations into compact ``SourceDescriptions``."""
    from rivretrieve._internal.catalogues.source_descriptions import content_identified_descriptions
    from rivretrieve._internal.catalogues.source_series import SourceDescriptions

    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in associations.sort("product_id", "station_id").iter_rows(named=True):
        product_id = str(row["product_id"])
        if product_id not in SPECS_BY_PRODUCT_ID:
            raise FatalContractError(f"Unsupported si_arso product_id in associations: {product_id!r}")
        station_id = str(row["station_id"])
        facts = product_physical_facts(product_id, station=station_id)
        grouped[(product_id, facts.facts_id)].append(station_id)

    ordered = [
        (product_id, station_ids)
        for (product_id, _), station_ids in sorted(grouped.items(), key=lambda item: (item[0][0], item[1][0]))
    ]
    return content_identified_descriptions(
        SourceDescriptions(provider_id="si_arso", descriptions=build_source_descriptions(ordered))
    )


def build_catalogue(
    native_table: NativeTable,
    origins: OriginDeclarations,
    *,
    associations: pl.DataFrame,
    checked_on: date,
    provenance: AcquisitionProvenance,
) -> GeneratedSiArsoCatalogue:
    """Assemble and origin-certify the Slovenia ARSO offline catalogue."""
    from rivretrieve._internal.catalogue_origins import enforce_catalogue_origins
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.si_arso.station_metadata import project_station_metadata

    if native_table.data.schema != STAMPED_STATION_SCHEMA:
        raise FatalContractError("ARSO native table does not match STAMPED_STATION_SCHEMA")
    if native_table.data.is_empty():
        raise FatalContractError("ARSO native table must not be empty")

    products, stations, pairs = catalogue_tables(native_table, associations, checked_on=checked_on)
    enforce_catalogue_origins(ProviderId("si_arso"), origins, native_table, stations)
    if provenance is None or provenance.provider_id != "si_arso":
        raise FatalContractError("Official ARSO catalogue requires its selected acquisition provenance")

    station_metadata = project_station_metadata(native_table, stations)
    statements = {
        statement.kind: statement.exact_text for source in provenance.source_records for statement in source.statements
    }
    provider_info: dict[str, object] = {
        "provider_id": "si_arso",
        "name": "Agencija Republike Slovenije za okolje (ARSO)",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": checked_on.isoformat(),
        "license": statements.get("license"),
        "citation": statements.get("citation"),
    }
    return GeneratedSiArsoCatalogue(
        provider_info=provider_info,
        products=products,
        stations=stations,
        station_products=pairs,
        station_metadata=station_metadata,
        acquisition_provenance=provenance,
        source_descriptions=describe_associations(associations),
    )


def write_catalogue(
    catalogue: GeneratedSiArsoCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs,
    native_table: NativeTable,
    metadata_fields: tuple[MetadataField, ...] = (),
) -> None:
    """Publish candidate runtime tables through the shared evidence-aware publication path."""
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.si_arso.origins import (
        STATION_CATALOGUE_ORIGINS,
        STATION_METADATA_NOTICE,
    )

    files = {
        "provider.json": (json.dumps(catalogue.provider_info, sort_keys=True, separators=(",", ":")) + "\n").encode()
    }
    for name, frame in (
        ("products", catalogue.products),
        ("stations", catalogue.stations),
        ("station_products", catalogue.station_products),
    ):
        buffer = BytesIO()
        frame.write_parquet(buffer)
        files[f"{name}.parquet"] = buffer.getvalue()

    metadata = build_catalogue_metadata(
        catalogue.acquisition_provenance,
        (STATION_CATALOGUE_ORIGINS,),
        files,
        build_inputs=build_inputs,
        native_table=native_table,
        metadata_fields=metadata_fields,
        station_metadata=catalogue.station_metadata,
        metadata_implementation=(
            "src/rivretrieve/_internal/providers/si_arso/station_metadata.py",
            "project_station_metadata",
        ),
        station_metadata_notice=STATION_METADATA_NOTICE,
        source_descriptions=catalogue.source_descriptions,
    )
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    for name, content in {**files, **metadata}.items():
        (output / name).write_bytes(content)


def read_original(
    evidence_root: Path,
    reference: RecordingReference,
    *,
    input_receipt: RetainedInputReceipt,
) -> bytes:
    """Verify one explicitly selected publisher body before parsing it."""
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    selected = {item.consumer_path: item for item in input_receipt.inputs}
    member = selected.get(reference.repository_path)
    if member is None:
        raise FatalContractError(f"ARSO original {reference.repository_path!r} is absent from selected retained inputs")
    if member.sha256 != reference.sha256:
        raise FatalContractError(f"ARSO original {reference.repository_path!r} differs from selected recording sha256")
    verify_retained_input_files(
        input_receipt.model_copy(update={"inputs": (member,), "declaration_inputs": (), "support_inputs": ()}),
        evidence_root,
    )
    return (evidence_root / reference.repository_path).read_bytes()


def _validate_doc_or_probe(kind: str, raw: bytes, path: str) -> None:
    if kind == "opsi_metadata":
        payload = json.loads(raw)
        licence = payload.get("result", {}).get("pogoji_licence", "") if isinstance(payload, dict) else ""
        if "CC BY 4.0" not in str(licence):
            raise FatalContractError(f"OPSI metadata {path!r} lacks CC BY 4.0 license statement")
    elif kind == "legal":
        text = raw.decode("utf-8", errors="replace")
        if "Agencij" not in text and "ARSO" not in text:
            raise FatalContractError(f"ARSO legal page {path!r} lacks expected agency text")
    elif kind == "hidro_zadnji_xml":
        text = raw.decode("utf-8", errors="replace")
        if "<arsopodatki" not in text or "<datum_cet>" not in text:
            raise FatalContractError(f"ARSO hidro_zadnji.xml {path!r} lacks expected XML tags")
    elif kind == "portal_doc":
        if not raw:
            raise FatalContractError(f"Empty ARSO portal document {path!r}")


def _read_selection_and_originals(
    evidence_root: Path,
    *,
    selection_path: str,
    input_receipt: RetainedInputReceipt,
    include_associations: bool,
) -> tuple[dict[str, object], tuple[RecordingReference, ...], NativeTable, pl.DataFrame]:
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    if selection_path not in {item.consumer_path for item in input_receipt.declaration_inputs}:
        raise FatalContractError("ARSO selection requires a selected authored declaration")
    verify_retained_input_files(input_receipt, evidence_root)
    selection = json.loads((evidence_root / selection_path).read_bytes())
    if not isinstance(selection, dict) or not isinstance(selection.get("captures"), list):
        raise FatalContractError("ARSO selection requires explicit captures")

    selected_inputs = {item.consumer_path: item for item in input_receipt.inputs}
    recordings: list[RecordingReference] = []
    native_instants: list[datetime] = []

    pov_tab_rivers: set[str] | None = None
    pov_tab_stations: dict[str, str] | None = None
    parsed_dropdown_rivers: set[str] = set()
    dropdown_station_names: dict[str, set[str]] = defaultdict(set)
    dropdown_river_names: dict[str, set[str]] = defaultdict(set)
    spisek_entries: dict[str, _SpisekEntry] | None = None
    q_stats_entries: dict[str, _QStatsEntry] = {}
    amp_index_ids: set[str] | None = None
    association_rows: list[tuple[str, str, date | None, date | None, str]] = []
    seen_oddo: set[str] = set()
    seen_eks: set[str] = set()
    seen_amp: dict[str, set[str]] = defaultdict(set)

    for capture in selection["captures"]:
        reference = RecordingReference.model_validate(capture["recording"])
        if reference.repository_path != capture["body"]:
            raise FatalContractError(f"ARSO selected body {capture['body']!r} disagrees with recording identity")
        member = selected_inputs.get(reference.repository_path)
        if member is None or member.sha256 != reference.sha256:
            raise FatalContractError(f"ARSO selected member {reference.repository_path!r} mismatches receipt")
        recordings.append(reference)
        kind = str(capture["kind"])

        if not include_associations and kind in {"oddo_csv", "eks_csv", "amp_page"}:
            continue

        raw = (evidence_root / reference.repository_path).read_bytes()
        if kind == "pov_arhiv_tab":
            if pov_tab_rivers is not None:
                raise FatalContractError("Duplicate pov_arhiv_tab capture in ARSO selection")
            pov_tab_rivers, pov_tab_stations = _parse_pov_arhiv_tab(raw)
            native_instants.append(reference.retrieved_at)
        elif kind == "dropdown":
            river, dd_map = _parse_dropdown_page(raw)
            parsed_dropdown_rivers.add(river)
            for sid, names in dd_map.items():
                dropdown_station_names[sid].update(names)
                dropdown_river_names[sid].add(river)
            native_instants.append(reference.retrieved_at)
        elif kind == "spisek":
            if spisek_entries is not None:
                raise FatalContractError("Duplicate Spisek workbook capture in ARSO selection")
            spisek_entries = _parse_spisek_workbook(raw)
            native_instants.append(reference.retrieved_at)
        elif kind == "q_stats":
            parsed_q = _parse_q_stats_workbook(raw)
            for sid, entry in parsed_q.items():
                if sid in q_stats_entries:
                    raise FatalContractError(f"Duplicate Q_stats worksheet for station {sid}")
                q_stats_entries[sid] = entry
            native_instants.append(reference.retrieved_at)
        elif kind == "amp_index":
            if amp_index_ids is not None:
                raise FatalContractError("Duplicate amp_index capture in ARSO selection")
            amp_index_ids = _parse_amp_index(raw)
            native_instants.append(reference.retrieved_at)
        elif kind == "oddo_csv":
            sid = str(capture["station"])
            if sid in seen_oddo:
                raise FatalContractError(f"Duplicate oddo_csv capture for station {sid}")
            seen_oddo.add(sid)
            association_rows.extend(_inspect_oddo_associations(sid, raw))
        elif kind == "eks_csv":
            sid = str(capture["station"])
            if sid in seen_eks:
                raise FatalContractError(f"Duplicate eks_csv capture for station {sid}")
            seen_eks.add(sid)
            association_rows.extend(_inspect_eks_associations(sid, raw))
        elif kind == "amp_page":
            sid = str(capture["station"])
            cadence = str(capture["cadence"])
            if sid in seen_amp[cadence]:
                raise FatalContractError(f"Duplicate amp_page capture for {sid} {cadence}")
            seen_amp[cadence].add(sid)
            association_rows.extend(_inspect_amp_associations(sid, cadence, raw))
        elif kind in {
            "opsi_metadata",
            "legal",
            "hidro_zadnji_xml",
            "portal_doc",
            "tvode_stats",
            "jezera_stats",
            "access_probe",
        }:
            _validate_doc_or_probe(kind, raw, reference.repository_path)
        else:
            raise FatalContractError(f"Unsupported ARSO capture kind: {kind!r}")

    if pov_tab_rivers is None or pov_tab_stations is None or spisek_entries is None or amp_index_ids is None:
        raise FatalContractError("ARSO selection requires pov_arhiv_tab, spisek, and amp_index captures")
    if parsed_dropdown_rivers != pov_tab_rivers:
        raise FatalContractError(
            f"ARSO dropdown rivers ({len(parsed_dropdown_rivers)}) differ from pov_arhiv_tab ({len(pov_tab_rivers)})"
        )
    if not dropdown_station_names:
        raise FatalContractError("ARSO selection lacks dropdown river captures")
    if not q_stats_entries:
        raise FatalContractError("ARSO selection lacks Q_stats workbooks")

    dd_union = set(dropdown_station_names)
    if not set(pov_tab_stations) <= dd_union:
        raise FatalContractError("ARSO pov_arhiv_tab default stations absent from dropdown river union")
    for sid, label in pov_tab_stations.items():
        dropdown_station_names[sid].add(label)

    in_scope_ids = dd_union - EXCLUDED_STATIONS
    amp_in_scope = amp_index_ids - EXCLUDED_STATIONS
    if not amp_in_scope <= in_scope_ids:
        raise FatalContractError(
            f"ARSO AMP index contains non-dropdown river stations: {sorted(amp_in_scope - in_scope_ids)}"
        )

    if include_associations:
        if seen_oddo != in_scope_ids:
            raise FatalContractError(
                f"ARSO oddo captures ({len(seen_oddo)}) do not match in-scope stations ({len(in_scope_ids)})"
            )
        if seen_eks != in_scope_ids:
            raise FatalContractError(
                f"ARSO eks captures ({len(seen_eks)}) do not match in-scope stations ({len(in_scope_ids)})"
            )
        for cadence in ("t_1", "t_7", "t_30"):
            if seen_amp[cadence] != amp_in_scope:
                raise FatalContractError(
                    f"ARSO AMP {cadence} captures ({len(seen_amp[cadence])}) mismatch amp_in_scope ({len(amp_in_scope)})"
                )

    max_instant = max(native_instants).astimezone(UTC)
    recomputed_native = station_native_table(
        dropdown_station_names=dropdown_station_names,
        dropdown_river_names=dropdown_river_names,
        spisek=spisek_entries,
        q_stats=q_stats_entries,
        in_scope_ids=in_scope_ids,
        amp_station_ids=amp_in_scope,
        retrieved_at=RetrievedAt(max_instant),
    )
    associations = (
        pl.DataFrame(association_rows, schema=ASSOCIATION_SCHEMA, orient="row").sort("station_id", "product_id")
        if association_rows
        else pl.DataFrame(schema=ASSOCIATION_SCHEMA)
    )
    return cast("dict[str, object]", selection), tuple(recordings), recomputed_native, associations


def read_native_sources(
    evidence_root: Path,
    *,
    selection_path: str = "maintenance/catalogue/si_arso/official/selection.json",
    input_receipt: RetainedInputReceipt,
) -> NativeTable:
    """Recompute the ARSO native station table from verified selected originals."""
    _, _, recomputed_native, _ = _read_selection_and_originals(
        evidence_root,
        selection_path=selection_path,
        input_receipt=input_receipt,
        include_associations=False,
    )
    return recomputed_native


def read_catalogue_sources(
    evidence_root: Path,
    *,
    selection_path: str = "maintenance/catalogue/si_arso/official/selection.json",
    input_receipt: RetainedInputReceipt,
) -> SiArsoCatalogueSources:
    """Read an explicitly selected offline ARSO build after exact member verification."""
    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        FactBinding,
        NativeTableIdentity,
        SourceStatement,
    )
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.si_arso import origins

    selection, recordings, recomputed_native, associations = _read_selection_and_originals(
        evidence_root,
        selection_path=selection_path,
        input_receipt=input_receipt,
        include_associations=True,
    )
    selected = {item.consumer_path: item for item in input_receipt.inputs}
    native_path = selection.get("native_table")
    if not isinstance(native_path, str) or native_path not in selected:
        raise FatalContractError("ARSO native table is absent from selected inputs")
    native_member = selected[native_path]
    retained_native = read_native_table(
        evidence_root / native_path,
        expected_sha256=native_member.sha256,
        expected_byte_size=native_member.byte_size,
    )
    if not retained_native.data.equals(recomputed_native.data):
        raise FatalContractError("ARSO retained native table differs from recomputed station snapshot")

    native_revision = selection.get("native_revision")
    checked_on_raw = selection.get("checked_on")
    if not isinstance(native_revision, str) or not isinstance(checked_on_raw, str):
        raise FatalContractError("ARSO selection requires native_revision and checked_on strings")

    provenance = origins.build_acquisition_provenance(
        NativeTableIdentity(
            location_kind="retained",
            repository_path=native_path,
            revision=native_revision,
            sha256=native_member.sha256,
            byte_size=native_member.byte_size,
        ),
        recordings,
        acquisitions=tuple(
            AcquisitionRecord.model_validate(item)
            for item in cast("list[object]", selection["publication_acquisitions"])
        ),
        source_bindings=tuple(
            FactBinding.model_validate(item) for item in cast("list[object]", selection["source_bindings"])
        ),
        statements=tuple(
            SourceStatement.model_validate(item) for item in cast("list[object]", selection["statements"])
        ),
    )
    return SiArsoCatalogueSources(
        native_table=retained_native,
        associations=associations,
        provenance=provenance,
        checked_on=date.fromisoformat(checked_on_raw),
    )


def selected_supporting_inputs(provenance: AcquisitionProvenance, selection: dict) -> dict[str, tuple[str, ...]]:
    """Associate selected ARSO acquisition receipts with the facts of their original bodies."""
    receipt_by_body = {capture["body"]: capture["receipt"] for capture in selection["captures"] if "receipt" in capture}
    facts_by_acquisition = {
        (source.source_id, acquisition.acquisition_id): tuple(
            fact
            for binding in provenance.fact_bindings
            if binding.source_id == source.source_id and binding.acquisition_id == acquisition.acquisition_id
            for fact in binding.facts
        )
        for source in provenance.source_records
        for acquisition in source.acquisitions
    }
    result: dict[str, tuple[str, ...]] = {}
    for source in provenance.source_records:
        paths = {item.recording.recording_id: item.recording.repository_path for item in source.evidence}
        for acquisition in source.acquisitions:
            facts = facts_by_acquisition[(source.source_id, acquisition.acquisition_id)]
            for recording_id in acquisition.recording_ids:
                path = paths[recording_id]
                if path in receipt_by_body and facts:
                    result[receipt_by_body[path]] = facts
    return result


def main(argv: list[str] | None = None) -> int:
    """Compose a derived native candidate or runtime ARSO catalogue outside source checkouts."""
    import argparse

    from rivretrieve._internal.catalogues.native import write_native_table

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--selection", default="maintenance/catalogue/si_arso/official/selection.json")
    parser.add_argument("--input-receipt", type=Path, required=True)
    parser.add_argument("--native-only", action="store_true")
    parser.add_argument("--build-inputs", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    output = args.out.resolve()
    evidence_root = args.evidence_root.resolve(strict=True)
    if output.exists() or output.is_relative_to(evidence_root) or evidence_root.is_relative_to(output):
        raise FatalContractError("ARSO catalogue output must be a new path separate from retained inputs")
    if any((parent / ".git").exists() for parent in (output, *output.parents)):
        raise FatalContractError("ARSO catalogue output must stay outside source checkouts")

    receipt = RetainedInputReceipt.model_validate_json(args.input_receipt.read_bytes())
    if args.native_only:
        native = read_native_sources(evidence_root, selection_path=args.selection, input_receipt=receipt)
        write_native_table(native, output / "native.parquet")
        return 0

    if args.build_inputs is None:
        raise FatalContractError("ARSO catalogue publication requires explicit --build-inputs")
    from rivretrieve._internal.providers.si_arso.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_FIELDS

    sources = read_catalogue_sources(evidence_root, selection_path=args.selection, input_receipt=receipt)
    catalogue = build_catalogue(
        sources.native_table,
        STATION_CATALOGUE_ORIGINS,
        associations=sources.associations,
        checked_on=sources.checked_on,
        provenance=sources.provenance,
    )
    write_catalogue(
        catalogue,
        output,
        build_inputs=CatalogueBuildInputs.model_validate_json(args.build_inputs.read_bytes()),
        native_table=sources.native_table,
        metadata_fields=STATION_METADATA_FIELDS,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
