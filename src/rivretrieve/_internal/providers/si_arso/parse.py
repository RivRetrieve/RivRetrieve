"""Normalize Slovenia ARSO archive CSVs and operational amp HTML tables."""

from __future__ import annotations

import calendar
import csv
import io
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from math import isfinite
from typing import Literal

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema, narrow_payload_for_pair
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.si_arso.annotations import SI_ARSO_SERIES_SCHEMA
from rivretrieve._internal.providers.si_arso.config import (
    SiArsoAmpCoordinates,
    SiArsoArchiveCoordinates,
)
from rivretrieve._internal.providers.si_arso.fetch import SiArsoRouteCoordinates
from rivretrieve._internal.providers.si_arso.series import (
    ARCHIVE_MISSING_DATUM_MARKERS,
    DEFERRED_AMP_COLUMNS,
    DEFERRED_EKS_PREFIXES,
    DEFERRED_ODDO_COLUMNS,
    SPECS_BY_AMP_ROUTE,
    SPECS_BY_ARCHIVE_COLUMN,
    SPECS_BY_EKS_PREFIX,
    SPECS_BY_PRODUCT_ID,
    SiArsoProductSpec,
    source_series,
    validate_station_id,
)
from rivretrieve._internal.source_annotations import (
    SERIES_STRUCTURAL_SCHEMA,
    AnnotationBundle,
    SeriesAnnotationTable,
)
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    PhysicalFacts,
    RestrictionKind,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
    stable_id,
    validate_series_rows,
)

_PROVIDER_ID = ProviderId("si_arso")
_ONE_US = timedelta(microseconds=1)
_AMP_ZONE = "+01:00"


def _fact_signature(fact: PhysicalFacts) -> tuple[object, ...]:
    return (
        fact.quantity.value,
        fact.source_unit.value,
        fact.normalized_unit,
        fact.frequency.value,
        fact.statistic.value,
        fact.temporal_support.value,
        fact.day_definition.value,
        fact.timestamp_anchor.value,
        fact.time_zone.value,
        fact.vertical_reference.value,
        fact.vertical_datum.value,
        fact.clipping_axis,
        fact.label_time,
    )


def reused_series(definition: SourceSeries, known_series: tuple[SourceSeries, ...]) -> SourceSeries:
    """Preserve prior established identity and matching fact IDs when available."""
    candidate = next((item for item in known_series if item.series_id == definition.series_id), None)
    if candidate is None:
        return definition
    retained = {_fact_signature(fact): fact for fact in candidate.facts}
    return definition.model_copy(
        update={
            "identity": candidate.identity,
            "facts": tuple(retained.get(_fact_signature(fact), fact) for fact in definition.facts),
        }
    )


def _parse_dmy_date(token: str, row_num: int) -> date:
    if len(token) != 10 or token[2] != "." or token[5] != ".":
        raise UnsupportedSourceStructureError(f"si_arso archive row {row_num} has invalid Datum {token!r}")
    day_s, month_s, year_s = token[0:2], token[3:5], token[6:10]
    if not (day_s.isdigit() and month_s.isdigit() and year_s.isdigit()):
        raise UnsupportedSourceStructureError(f"si_arso archive row {row_num} has non-numeric Datum {token!r}")
    try:
        return date(int(year_s), int(month_s), int(day_s))
    except ValueError as error:
        raise UnsupportedSourceStructureError(
            f"si_arso archive row {row_num} has invalid calendar Datum {token!r}"
        ) from error


def _parse_dmy_hm(token: str, row_num: int, context: str) -> datetime:
    if len(token) != 16 or token[2] != "." or token[5] != "." or token[10] != " " or token[13] != ":":
        raise UnsupportedSourceStructureError(f"si_arso {context} row {row_num} has invalid timestamp {token!r}")
    parts = (token[0:2], token[3:5], token[6:10], token[11:13], token[14:16])
    if any(not part.isdigit() for part in parts):
        raise UnsupportedSourceStructureError(f"si_arso {context} row {row_num} has non-numeric timestamp {token!r}")
    day, month, year, hour, minute = (int(part) for part in parts)
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError as error:
        raise UnsupportedSourceStructureError(
            f"si_arso {context} row {row_num} has invalid datetime {token!r}"
        ) from error


def _parse_finite_float(token: str, row_num: int, context: str) -> float:
    stripped = token.strip()
    if "_" in stripped:
        raise UnsupportedSourceStructureError(f"si_arso {context} row {row_num} has non-numeric value {token!r}")
    try:
        number = float(stripped)
    except ValueError as error:
        raise UnsupportedSourceStructureError(
            f"si_arso {context} row {row_num} has non-numeric value {token!r}"
        ) from error
    if not isfinite(number):
        raise UnsupportedSourceStructureError(f"si_arso {context} row {row_num} has non-finite value {token!r}")
    return number


class _PodatkiTableParser(HTMLParser):
    """Extract header and row cells from the single ``<table class="podatki">`` table."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_table = False
        self._table_depth = 0
        self._in_tr = False
        self._in_cell = False
        self._row: list[str] = []
        self._cell: list[str] = []
        self.found_table = False
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            classes = dict(attrs).get("class") or ""
            if not self._in_table and "podatki" in classes.split():
                if self.found_table:
                    raise UnsupportedSourceStructureError("si_arso amp page contains multiple table.podatki elements")
                self._in_table = True
                self._table_depth = 1
                self.found_table = True
            elif self._in_table:
                self._table_depth += 1
        elif self._in_table and self._table_depth == 1:
            if tag == "tr":
                self._in_tr = True
                self._row = []
            elif tag in ("th", "td") and self._in_tr:
                self._in_cell = True
                self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_table:
            self._table_depth -= 1
            if self._table_depth == 0:
                self._in_table = False
        elif self._in_table and self._table_depth == 1:
            if tag in ("th", "td") and self._in_cell:
                self._in_cell = False
                self._row.append("".join(self._cell).strip())
            elif tag == "tr" and self._in_tr:
                self._in_tr = False
                if self._row:
                    self.rows.append(self._row)

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)


@dataclass(frozen=True, slots=True)
class _ParsedColumnSeries:
    product: ProductId
    spec: SiArsoProductSpec
    times: list[datetime]
    values: list[float]
    time_zone: str
    covered_bounds: tuple[datetime, datetime] | None
    column_absent: bool = False
    error_reason: str | None = None
    observation_keys: tuple[tuple[str, datetime, str], ...] = ()
    coverage_mode: str = "interval"
    inventory_completeness: InventoryCompleteness = InventoryCompleteness.COMPLETE
    incomplete_reason: str | None = None


def _build_unresolved_outcome(
    *,
    acquisition_id: str,
    series_id: str | None,
    facts_ids: tuple[str, ...],
    station: str,
    product: ProductId,
    window: SeriesWindow,
    retrieved: datetime | None,
    reason: str,
    tag: str,
) -> RetrievalOutcome:
    return RetrievalOutcome(
        outcome_id=stable_id(acquisition_id, station, str(product), series_id, window.model_dump_json(), tag),
        series_id=series_id,
        station_id=station,
        product_id=str(product),
        window=window,
        status=OutcomeStatus.UNRESOLVED,
        facts_ids=facts_ids if series_id is not None else (),
        reason=reason,
        retrieved_at=retrieved,
    )


def _append_disjoint_unresolved_bounds(
    outcomes: list[RetrievalOutcome],
    *,
    acquisition_id: str,
    definition: SourceSeries,
    fact_id: str,
    station: str,
    product: ProductId,
    requested_window: SeriesWindow,
    covered_start: datetime,
    covered_end: datetime,
    retrieved: datetime | None,
    reason_prefix: str,
) -> None:
    if requested_window.start < covered_start:
        pre_end = min(requested_window.end, covered_start - _ONE_US)
        if requested_window.start <= pre_end:
            gap_window = SeriesWindow(
                start=requested_window.start,
                end=pre_end,
                axis=requested_window.axis,
            )
            outcomes.append(
                _build_unresolved_outcome(
                    acquisition_id=acquisition_id,
                    series_id=definition.series_id,
                    facts_ids=(fact_id,),
                    station=station,
                    product=product,
                    window=gap_window,
                    retrieved=retrieved,
                    reason=f"{reason_prefix} before {covered_start.isoformat()}",
                    tag="pre-gap",
                )
            )
    if requested_window.end > covered_end:
        post_start = max(requested_window.start, covered_end + _ONE_US)
        if post_start <= requested_window.end:
            gap_window = SeriesWindow(
                start=post_start,
                end=requested_window.end,
                axis=requested_window.axis,
            )
            outcomes.append(
                _build_unresolved_outcome(
                    acquisition_id=acquisition_id,
                    series_id=definition.series_id,
                    facts_ids=(fact_id,),
                    station=station,
                    product=product,
                    window=gap_window,
                    retrieved=retrieved,
                    reason=f"{reason_prefix} after {covered_end.isoformat()}",
                    tag="post-gap",
                )
            )


def _parse_archive_daily(
    payload: Payload,
    station: str,
    requested: list[tuple[ProductId, SiArsoProductSpec]],
) -> dict[ProductId, _ParsedColumnSeries]:
    try:
        text = payload.content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise UnsupportedSourceStructureError("si_arso archive_daily payload is not valid UTF-8") from error

    csv_stream = io.StringIO(text)
    del text
    reader = csv.reader(csv_stream, delimiter=";")
    header = next(reader, None)
    if not header or header[0] != "Datum":
        raise UnsupportedSourceStructureError("si_arso archive_daily CSV lacks leading Datum column")

    col_index: dict[str, int] = {}
    for idx, col in enumerate(header[1:], 1):
        if col in col_index:
            raise UnsupportedSourceStructureError(f"si_arso archive_daily CSV has duplicate column {col!r}")
        if col in DEFERRED_ODDO_COLUMNS or col in SPECS_BY_ARCHIVE_COLUMN:
            col_index[col] = idx
            continue
        raise UnsupportedSourceStructureError(f"si_arso archive_daily CSV has unsupported column {col!r}")

    req_cols = [
        (product, spec, col_index.get(spec.archive_column))
        for product, spec in requested
        if spec.archive_column is not None
    ]
    times_by_product: dict[ProductId, list[datetime]] = {product: [] for product, _, _ in req_cols}
    values_by_product: dict[ProductId, list[float]] = {product: [] for product, _, _ in req_cols}
    date_bounds: dict[ProductId, tuple[date, date]] = {}
    errors_by_product: dict[ProductId, str] = {}

    prev_date: date | None = None
    header_len = len(header)
    for row_num, raw_row in enumerate(reader, start=2):
        if not raw_row:
            continue
        if len(raw_row) > header_len:
            raise UnsupportedSourceStructureError(
                f"si_arso archive_daily row {row_num} has {len(raw_row)} cells, exceeding {header_len}"
            )
        cur_date = _parse_dmy_date(raw_row[0].strip(), row_num)
        if prev_date is not None and cur_date <= prev_date:
            raise UnsupportedSourceStructureError(
                f"si_arso archive_daily row {row_num} Datum {cur_date.isoformat()} is not strictly increasing"
            )
        prev_date = cur_date
        ts = datetime(cur_date.year, cur_date.month, cur_date.day)
        row_len = len(raw_row)
        for product, spec, idx in req_cols:
            if idx is None or idx >= row_len or product in errors_by_product:
                continue
            tok = raw_row[idx].strip()
            if tok in ARCHIVE_MISSING_DATUM_MARKERS:
                continue
            try:
                val = _parse_finite_float(tok, row_num, f"archive_daily({spec.archive_column})")
            except UnsupportedSourceStructureError as error:
                errors_by_product[product] = str(error)
                times_by_product[product].clear()
                values_by_product[product].clear()
                date_bounds.pop(product, None)
                continue
            first_d = date_bounds[product][0] if product in date_bounds else cur_date
            date_bounds[product] = (first_d, cur_date)
            times_by_product[product].append(ts)
            values_by_product[product].append(val)
    del csv_stream, reader

    parsed: dict[ProductId, _ParsedColumnSeries] = {}
    for product, spec, idx in req_cols:
        if product in errors_by_product:
            parsed[product] = _ParsedColumnSeries(
                product=product,
                spec=spec,
                times=[],
                values=[],
                time_zone="unknown",
                covered_bounds=None,
                error_reason=errors_by_product[product],
            )
            continue
        if idx is None or product not in date_bounds:
            parsed[product] = _ParsedColumnSeries(
                product=product,
                spec=spec,
                times=[],
                values=[],
                time_zone="unknown",
                covered_bounds=None,
                column_absent=True,
                inventory_completeness=InventoryCompleteness.INCOMPLETE,
                incomplete_reason=(
                    f"si_arso archive_daily CSV for {station} publishes no observations for {spec.archive_column!r}"
                ),
            )
            continue
        first_d, last_d = date_bounds[product]
        cov_start = datetime.combine(first_d, time.min)
        cov_end = datetime.combine(last_d, time.max)
        parsed[product] = _ParsedColumnSeries(
            product=product,
            spec=spec,
            times=times_by_product[product],
            values=values_by_product[product],
            time_zone="unknown",
            covered_bounds=(cov_start, cov_end),
            inventory_completeness=InventoryCompleteness.COMPLETE,
            incomplete_reason=None,
        )
    return parsed


def _parse_archive_monthly_extremes(
    payload: Payload,
    station: str,
    requested: list[tuple[ProductId, SiArsoProductSpec]],
) -> dict[ProductId, _ParsedColumnSeries]:
    try:
        text = payload.content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise UnsupportedSourceStructureError("si_arso archive_monthly_extremes payload is not valid UTF-8") from error

    csv_stream = io.StringIO(text)
    del text
    reader = csv.reader(csv_stream, delimiter=";")
    header = next(reader, None)
    if not header or len(header) < 2 or header[0] != "Leto" or header[1] != "Mesec" or (len(header) - 2) % 2 != 0:
        raise UnsupportedSourceStructureError("si_arso archive_monthly_extremes CSV lacks Leto;Mesec paired headers")

    prefix_indices: dict[str, tuple[int, int]] = {}
    for offset in range(2, len(header), 2):
        d_hdr, v_hdr = header[offset], header[offset + 1]
        if not d_hdr.endswith("_datum") or not v_hdr.endswith("_vrednost"):
            raise UnsupportedSourceStructureError(
                f"si_arso archive_monthly_extremes CSV has unpaired headers {d_hdr!r}, {v_hdr!r}"
            )
        prefix = d_hdr[:-6]
        if prefix != v_hdr[:-9]:
            raise UnsupportedSourceStructureError(
                f"si_arso archive_monthly_extremes CSV header pair mismatch: {d_hdr!r} vs {v_hdr!r}"
            )
        if prefix in prefix_indices:
            raise UnsupportedSourceStructureError(f"si_arso archive_monthly_extremes CSV duplicates {prefix!r}")
        base_prefix = prefix.rsplit("_", 1)[0]
        if prefix not in SPECS_BY_EKS_PREFIX and base_prefix not in DEFERRED_EKS_PREFIXES:
            raise UnsupportedSourceStructureError(f"si_arso archive_monthly_extremes CSV has unsupported {prefix!r}")
        prefix_indices[prefix] = (offset, offset + 1)

    req_cols = [
        (product, spec, prefix_indices.get(spec.eks_prefix))
        for product, spec in requested
        if spec.eks_prefix is not None
    ]
    times_by_product: dict[ProductId, list[datetime]] = {product: [] for product, _, _ in req_cols}
    values_by_product: dict[ProductId, list[float]] = {product: [] for product, _, _ in req_cols}
    month_bounds: dict[ProductId, tuple[tuple[int, int], tuple[int, int]]] = {}
    errors_by_product: dict[ProductId, str] = {}

    prev_ym: tuple[int, int] | None = None
    header_len = len(header)
    for row_num, raw_row in enumerate(reader, start=2):
        if not raw_row:
            continue
        if len(raw_row) < 2 or len(raw_row) > header_len:
            raise UnsupportedSourceStructureError(
                f"si_arso archive_monthly_extremes row {row_num} has invalid length {len(raw_row)}"
            )
        year_s, month_s = raw_row[0].strip(), raw_row[1].strip()
        if not (year_s.isdigit() and month_s.isdigit()):
            raise UnsupportedSourceStructureError(
                f"si_arso archive_monthly_extremes row {row_num} has non-numeric Leto/Mesec: {year_s!r}/{month_s!r}"
            )
        year, month = int(year_s), int(month_s)
        if not (1800 <= year <= 2100 and 1 <= month <= 12):
            raise UnsupportedSourceStructureError(
                f"si_arso archive_monthly_extremes row {row_num} out-of-range Leto/Mesec: {(year, month)!r}"
            )
        ym = (year, month)
        if prev_ym is not None and ym <= prev_ym:
            raise UnsupportedSourceStructureError(
                f"si_arso archive_monthly_extremes row {row_num} Leto/Mesec {ym!r} is not strictly increasing"
            )
        prev_ym = ym
        row_len = len(raw_row)
        for product, spec, idxs in req_cols:
            if idxs is None or product in errors_by_product:
                continue
            d_idx, v_idx = idxs
            d_tok = raw_row[d_idx].strip() if d_idx < row_len else ""
            v_tok = raw_row[v_idx].strip() if v_idx < row_len else ""
            try:
                if (d_tok in ARCHIVE_MISSING_DATUM_MARKERS) != (v_tok in ARCHIVE_MISSING_DATUM_MARKERS):
                    raise UnsupportedSourceStructureError(
                        f"si_arso archive_monthly_extremes row {row_num} {spec.eks_prefix} has unpaired datum/value: "
                        f"({d_tok!r}, {v_tok!r})"
                    )
                if d_tok in ARCHIVE_MISSING_DATUM_MARKERS:
                    continue
                ts = _parse_dmy_hm(d_tok, row_num, f"archive_monthly_extremes({spec.eks_prefix})")
                if (ts.year, ts.month) != ym:
                    raise UnsupportedSourceStructureError(
                        f"si_arso archive_monthly_extremes row {row_num} {spec.eks_prefix} timestamp {d_tok!r} "
                        f"lies outside month {ym!r}"
                    )
                val = _parse_finite_float(v_tok, row_num, f"archive_monthly_extremes({spec.eks_prefix})")
            except UnsupportedSourceStructureError as error:
                errors_by_product[product] = str(error)
                times_by_product[product].clear()
                values_by_product[product].clear()
                month_bounds.pop(product, None)
                continue
            first_ym = month_bounds[product][0] if product in month_bounds else ym
            month_bounds[product] = (first_ym, ym)
            times_by_product[product].append(ts)
            values_by_product[product].append(val)
    del csv_stream, reader

    parsed: dict[ProductId, _ParsedColumnSeries] = {}
    for product, spec, idxs in req_cols:
        if product in errors_by_product:
            parsed[product] = _ParsedColumnSeries(
                product=product,
                spec=spec,
                times=[],
                values=[],
                time_zone="unknown",
                covered_bounds=None,
                error_reason=errors_by_product[product],
            )
            continue
        if idxs is None or product not in month_bounds:
            parsed[product] = _ParsedColumnSeries(
                product=product,
                spec=spec,
                times=[],
                values=[],
                time_zone="unknown",
                covered_bounds=None,
                column_absent=True,
                inventory_completeness=InventoryCompleteness.INCOMPLETE,
                incomplete_reason=(
                    f"si_arso archive_monthly_extremes CSV for {station} publishes no observations for {spec.eks_prefix!r}"
                ),
            )
            continue
        (first_y, first_m), (last_y, last_m) = month_bounds[product]
        cov_start = datetime(first_y, first_m, 1, 0, 0, 0, 0)
        cov_end = datetime(last_y, last_m, calendar.monthrange(last_y, last_m)[1], 23, 59, 59, 999999)
        parsed[product] = _ParsedColumnSeries(
            product=product,
            spec=spec,
            times=times_by_product[product],
            values=values_by_product[product],
            time_zone="unknown",
            covered_bounds=(cov_start, cov_end),
            inventory_completeness=InventoryCompleteness.COMPLETE,
            incomplete_reason=None,
        )
    return parsed


def _parse_amp(
    payload: Payload,
    route: SiArsoRouteCoordinates,
    requested: list[tuple[ProductId, SiArsoProductSpec]],
    facts_by_product: dict[ProductId, str],
) -> dict[ProductId, _ParsedColumnSeries]:
    assert route.amp_cadence is not None
    try:
        html_text = payload.content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise UnsupportedSourceStructureError("si_arso amp HTML response is not valid UTF-8") from error

    parser = _PodatkiTableParser()
    parser.feed(html_text)
    del html_text
    if not parser.found_table or len(parser.rows) < 2:
        raise UnsupportedSourceStructureError("si_arso amp HTML response lacks populated table.podatki rows")

    header = parser.rows[0]
    if not header or header[0] != "Datum":
        raise UnsupportedSourceStructureError("si_arso amp table.podatki lacks leading Datum header")

    col_index: dict[str, int] = {}
    in_scope_cols: set[str] = set()
    for idx, col in enumerate(header[1:], 1):
        if col in col_index:
            raise UnsupportedSourceStructureError(f"si_arso amp table.podatki duplicates column {col!r}")
        if (route.amp_cadence, col) in SPECS_BY_AMP_ROUTE:
            col_index[col] = idx
            in_scope_cols.add(col)
            continue
        if col in DEFERRED_AMP_COLUMNS:
            col_index[col] = idx
            continue
        raise UnsupportedSourceStructureError(f"si_arso amp table.podatki has unsupported column {col!r}")

    expected_len = len(header)
    parser_rows = parser.rows[1:]
    del parser
    parsed_times: list[datetime] = []
    values_by_col: dict[str, dict[datetime, float]] = {col: {} for col in col_index if col in in_scope_cols}
    col_errors: dict[str, str] = {}
    for row_num, cells in enumerate(parser_rows, start=2):
        if len(cells) != expected_len:
            raise UnsupportedSourceStructureError(
                f"si_arso amp table row {row_num} has {len(cells)} cells; expected {expected_len}"
            )
        ts = _parse_dmy_hm(cells[0], row_num, f"amp({route.amp_cadence})")
        parsed_times.append(ts)
        for col, idx in col_index.items():
            if col not in values_by_col or col in col_errors:
                continue
            tok = cells[idx]
            if tok in ARCHIVE_MISSING_DATUM_MARKERS:
                continue
            try:
                val = _parse_finite_float(tok, row_num, f"amp({route.amp_cadence},{col})")
                existing = values_by_col[col].get(ts)
                if existing is not None and existing != val:
                    raise UnsupportedSourceStructureError(
                        f"si_arso amp table {col!r} has conflicting values at {ts.isoformat()}"
                    )
            except UnsupportedSourceStructureError as error:
                col_errors[col] = str(error)
                values_by_col[col].clear()
                continue
            values_by_col[col][ts] = val
    del parser_rows

    snap_min = min(parsed_times)
    snap_max = max(parsed_times)

    parsed: dict[ProductId, _ParsedColumnSeries] = {}
    for product, spec in requested:
        assert spec.amp_column is not None
        if spec.amp_column in col_errors:
            parsed[product] = _ParsedColumnSeries(
                product=product,
                spec=spec,
                times=[],
                values=[],
                time_zone=_AMP_ZONE,
                covered_bounds=None,
                error_reason=col_errors[spec.amp_column],
            )
            continue
        idx = col_index.get(spec.amp_column)
        if idx is None:
            parsed[product] = _ParsedColumnSeries(
                product=product,
                spec=spec,
                times=[],
                values=[],
                time_zone=_AMP_ZONE,
                covered_bounds=None,
                column_absent=True,
                inventory_completeness=InventoryCompleteness.COMPLETE,
            )
            continue
        series_map = values_by_col[spec.amp_column]
        all_points = sorted(series_map.items(), key=lambda item: item[0])
        if not all_points:
            parsed[product] = _ParsedColumnSeries(
                product=product,
                spec=spec,
                times=[],
                values=[],
                time_zone=_AMP_ZONE,
                covered_bounds=None,
                column_absent=False,
                coverage_mode="observations",
                inventory_completeness=InventoryCompleteness.INCOMPLETE,
                incomplete_reason=(
                    f"si_arso amp/{route.amp_cadence} HTML table has no numeric observations for {spec.amp_column!r}"
                ),
            )
            continue
        times = [ts for ts, _ in all_points]
        values = [val for _, val in all_points]
        fact_id = facts_by_product[product]
        obs_keys = tuple((fact_id, ts, _AMP_ZONE) for ts in times)
        parsed[product] = _ParsedColumnSeries(
            product=product,
            spec=spec,
            times=times,
            values=values,
            time_zone=_AMP_ZONE,
            covered_bounds=(snap_min, snap_max),
            observation_keys=obs_keys,
            coverage_mode="observations",
            inventory_completeness=InventoryCompleteness.INCOMPLETE,
            incomplete_reason=(
                f"si_arso amp/{route.amp_cadence} HTML table exposes only a rolling buffer "
                "and does not establish historical coverage or station-wide completeness"
            ),
        )
    return parsed


def _failed_payload_result(
    payload: Payload,
    station: str,
    requested: list[tuple[ProductId, SiArsoProductSpec]],
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
    reason: str,
    *,
    series_by_product: Mapping[ProductId, SourceSeries] | None = None,
) -> ParsedSeries:
    evidence = f"source-call:{payload.acquisition_id}"
    series_list: list[SourceSeries] = []
    inventories: list[InventorySnapshot] = []
    outcomes: list[RetrievalOutcome] = []
    issues: list[Issue] = []

    for product, spec in requested:
        definition = (
            series_by_product[product]
            if series_by_product is not None and product in series_by_product
            else reused_series(
                source_series(station, str(product), origin="response", identity_evidence=(evidence,)),
                payload.known_series,
            )
        )
        series_list.append(definition)
        outcome = RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, station, str(product), definition.series_id, "failed", reason),
            series_id=definition.series_id,
            station_id=station,
            product_id=str(product),
            window=window,
            status=OutcomeStatus.FAILED,
            reason=reason,
            retrieved_at=retrieved,
        )
        outcomes.append(outcome)
        inventories.append(
            InventorySnapshot(
                snapshot_id=stable_id(payload.acquisition_id, station, str(product), "failed-inventory"),
                scope=scope.model_copy(update={"station_ids": (station,), "product_ids": (str(product),)}),
                members=(definition.series_id,),
                completeness=InventoryCompleteness.INCOMPLETE,
                access=f"ARSO si_arso {spec.stream} response",
                origin="response",
                acquired_at=retrieved,
                window=window,
                evidence=(evidence,),
                reason=reason,
            )
        )
        issues.append(
            Issue(
                severity="error",
                code="source.unsupported_structure",
                message=reason,
                details={
                    "station_id": station,
                    "product_id": str(product),
                    "series_id": definition.series_id,
                    "outcome_id": outcome.outcome_id,
                },
                provider_id=_PROVIDER_ID,
            )
        )

    return ParsedSeries(
        pl.DataFrame(schema=RowsSchema.polars_schema),
        tuple(series_list),
        tuple(inventories),
        tuple(outcomes),
        tuple(issues),
    )


def _validated_product_route(
    product: ProductId,
    route: object,
    provider_config: ProviderConfig,
) -> SiArsoRouteCoordinates:
    if not isinstance(route, SiArsoRouteCoordinates):
        raise FatalContractError(f"si_arso payload has invalid route coordinates: {route!r}")
    try:
        configured = provider_config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"si_arso product is absent from provider config: {product}") from error
    if route.stream == "amp":
        if not isinstance(configured, SiArsoAmpCoordinates) or configured.amp_cadence != route.amp_cadence:
            raise FatalContractError(f"si_arso product {product!r} contradicts amp route {route!r}")
    else:
        if not isinstance(configured, SiArsoArchiveCoordinates) or configured.b_flag != route.b_flag:
            raise FatalContractError(f"si_arso product {product!r} contradicts archive route {route!r}")
    return route


def _build_pair_parsed_series(
    pair_payload: Payload,
    *,
    station: str,
    product: ProductId,
    route: SiArsoRouteCoordinates,
    res: _ParsedColumnSeries,
    definition: SourceSeries,
    window: SeriesWindow,
    retrieved: datetime | None,
    pair_scope: SeriesScope,
) -> ParsedSeries:
    spec = res.spec
    evidence = f"source-call:{pair_payload.acquisition_id}"
    if res.error_reason is not None:
        return _failed_payload_result(
            pair_payload,
            station,
            [(product, spec)],
            window,
            retrieved,
            pair_scope,
            res.error_reason,
            series_by_product={product: definition},
        )

    if res.column_absent:
        inventories: list[InventorySnapshot] = []
        outcomes: list[RetrievalOutcome] = []
        issues: list[Issue] = []
        if route.stream == "amp":
            inventories.append(
                InventorySnapshot(
                    snapshot_id=stable_id(pair_payload.acquisition_id, station, str(product), "amp-absent"),
                    scope=pair_scope,
                    members=(),
                    completeness=InventoryCompleteness.COMPLETE,
                    access=f"ARSO si_arso amp/{route.amp_cadence} table.podatki",
                    origin="response",
                    acquired_at=retrieved,
                    window=window,
                    evidence=(evidence,),
                )
            )
            if pair_scope.restriction is RestrictionKind.ALL:
                reason = f"ARSO amp/{route.amp_cadence} table for {station} publishes no {spec.amp_column!r} column"
                outcome = RetrievalOutcome(
                    outcome_id=stable_id(pair_payload.acquisition_id, station, str(product), "amp-no-match"),
                    series_id=None,
                    station_id=station,
                    product_id=str(product),
                    window=window,
                    status=OutcomeStatus.NO_MATCH,
                    reason=reason,
                    retrieved_at=retrieved,
                )
                outcomes.append(outcome)
                issues.append(
                    Issue(
                        severity="warning",
                        code="source.no_match",
                        message=reason,
                        details={
                            "station_id": station,
                            "product_id": str(product),
                            "outcome_id": outcome.outcome_id,
                        },
                        provider_id=_PROVIDER_ID,
                    )
                )
        else:
            reason = res.incomplete_reason or f"si_arso archive response lacks {product!r}"
            outcomes.append(
                _build_unresolved_outcome(
                    acquisition_id=pair_payload.acquisition_id,
                    series_id=None,
                    facts_ids=(),
                    station=station,
                    product=product,
                    window=window,
                    retrieved=retrieved,
                    reason=reason,
                    tag="archive-column-absent",
                )
            )
            inventories.append(
                InventorySnapshot(
                    snapshot_id=stable_id(pair_payload.acquisition_id, station, str(product), "archive-absent"),
                    scope=pair_scope,
                    members=(),
                    completeness=InventoryCompleteness.INCOMPLETE,
                    access=f"ARSO si_arso {spec.stream} CSV",
                    origin="response",
                    acquired_at=retrieved,
                    window=window,
                    evidence=(evidence,),
                    reason=reason,
                )
            )
        return ParsedSeries(
            pl.DataFrame(schema=RowsSchema.polars_schema),
            (),
            tuple(inventories),
            tuple(outcomes),
            tuple(issues),
        )

    fact = definition.facts[0]
    if res.covered_bounds is None:
        reason = res.incomplete_reason or f"si_arso {spec.stream} response publishes no numeric observations"
        out = _build_unresolved_outcome(
            acquisition_id=pair_payload.acquisition_id,
            series_id=definition.series_id,
            facts_ids=(fact.facts_id,),
            station=station,
            product=product,
            window=window,
            retrieved=retrieved,
            reason=reason,
            tag="no-numeric-observations",
        )
        inv = InventorySnapshot(
            snapshot_id=stable_id(pair_payload.acquisition_id, station, str(product), "empty-series-inventory"),
            scope=pair_scope,
            members=(definition.series_id,),
            member_facts=((definition.series_id, (fact.facts_id,)),),
            completeness=res.inventory_completeness,
            access=f"ARSO si_arso {spec.stream}",
            origin="response",
            acquired_at=retrieved,
            window=window,
            evidence=(evidence,),
            reason=reason,
        )
        return ParsedSeries(
            pl.DataFrame(schema=RowsSchema.polars_schema),
            (definition,),
            (inv,),
            (out,),
            (),
        )

    span_start, span_end = res.covered_bounds
    covered_window = SeriesWindow(start=span_start, end=span_end, axis=window.axis)
    coverage_value: Literal["interval", "observations"] = (
        "observations" if res.coverage_mode == "observations" else "interval"
    )
    pair_outcomes: list[RetrievalOutcome] = [
        RetrievalOutcome(
            outcome_id=stable_id(
                pair_payload.acquisition_id,
                definition.series_id,
                fact.facts_id,
                covered_window.model_dump_json(),
                OutcomeStatus.SUCCESS,
            ),
            series_id=definition.series_id,
            station_id=station,
            product_id=str(product),
            window=covered_window,
            status=OutcomeStatus.SUCCESS,
            facts_ids=(fact.facts_id,),
            retrieved_at=retrieved,
            coverage=coverage_value,
            observation_keys=res.observation_keys if coverage_value == "observations" else (),
        )
    ]
    _append_disjoint_unresolved_bounds(
        pair_outcomes,
        acquisition_id=pair_payload.acquisition_id,
        definition=definition,
        fact_id=fact.facts_id,
        station=station,
        product=product,
        requested_window=window,
        covered_start=span_start,
        covered_end=span_end,
        retrieved=retrieved,
        reason_prefix=f"si_arso {spec.stream} provides no verified/retained record",
    )
    inventory_window = window if route.stream == "amp" else covered_window
    inventory = InventorySnapshot(
        snapshot_id=stable_id(pair_payload.acquisition_id, station, str(product), definition.series_id, "inventory"),
        scope=pair_scope,
        members=(definition.series_id,),
        member_facts=((definition.series_id, (fact.facts_id,)),),
        completeness=res.inventory_completeness,
        access=f"ARSO si_arso {spec.stream}",
        origin="response",
        acquired_at=retrieved,
        window=inventory_window,
        evidence=(evidence,),
        reason=res.incomplete_reason,
    )

    count = len(res.times)
    frame = pl.DataFrame(
        {
            "station_id": pl.repeat(station, count, dtype=pl.String, eager=True),
            "product_id": pl.repeat(str(product), count, dtype=pl.String, eager=True),
            "time": pl.Series("time", res.times, dtype=pl.Datetime("us")),
            "value": pl.Series("value", res.values, dtype=pl.Float64),
            "time_zone": pl.repeat(res.time_zone, count, dtype=pl.String, eager=True),
            "series_id": pl.repeat(definition.series_id, count, dtype=pl.String, eager=True),
            "facts_id": pl.repeat(fact.facts_id, count, dtype=pl.String, eager=True),
            "source_unit": pl.repeat(fact.source_unit.value, count, dtype=pl.String, eager=True),
        },
        schema=RowsSchema.polars_schema,
    )
    validate_series_rows(frame, (definition,))

    ann_schema = {**SERIES_STRUCTURAL_SCHEMA, **SI_ARSO_SERIES_SCHEMA.polars_schema()}
    ann_table = SeriesAnnotationTable.from_rows(
        schema=SI_ARSO_SERIES_SCHEMA,
        rows=pl.DataFrame(
            {
                "series_id": pl.Series("series_id", [definition.series_id], dtype=pl.String),
                "data_status": pl.Series("data_status", [spec.data_status], dtype=pl.String),
            },
            schema=ann_schema,
        ),
    )
    annotations = AnnotationBundle(series_tables={SI_ARSO_SERIES_SCHEMA.schema_id: ann_table})
    return ParsedSeries(
        frame,
        (definition,),
        (inventory,),
        tuple(pair_outcomes),
        (),
        annotations=annotations,
    )


def parse_group(
    payload: Payload,
    pair_payloads: Mapping[tuple[str, ProductId], Payload],
    provider_config: ProviderConfig,
) -> dict[tuple[str, ProductId], ParsedSeries]:
    """Decode one shared ARSO payload once and project independent per-pair ``ParsedSeries`` results."""
    if not pair_payloads:
        raise FatalContractError("si_arso group parse requires at least one pair payload")
    stations = {validate_station_id(station) for station, _ in pair_payloads}
    if len(stations) != 1:
        raise FatalContractError("si_arso payload must contain exactly one station")
    station = next(iter(stations))

    if not payload.station_products:
        raise FatalContractError("si_arso payload must contain at least one station-product pair")
    payload_stations = {validate_station_id(item_station) for item_station, _ in payload.station_products}
    if payload_stations != {station}:
        raise FatalContractError("si_arso payload must match its requested group station")

    route = payload.source_coordinates.value
    if not isinstance(route, SiArsoRouteCoordinates):
        raise FatalContractError(f"si_arso payload has invalid route coordinates: {route!r}")

    requested: list[tuple[ProductId, SiArsoProductSpec]] = []
    base_series_cache: dict[tuple[str, ProductId], SourceSeries] = {}
    definitions_by_pair: dict[tuple[str, ProductId], SourceSeries] = {}
    meta_by_pair: dict[tuple[str, ProductId], tuple[Payload, SeriesWindow, datetime | None, SeriesScope]] = {}

    for key, pair_payload in pair_payloads.items():
        pair_station, product = key
        if pair_payload.station_products != ((pair_station, product),):
            raise FatalContractError("si_arso pair payload station_products does not match its group key")
        _validated_product_route(product, route, provider_config)
        pair_route = _validated_product_route(product, pair_payload.source_coordinates.value, provider_config)
        if pair_route != route:
            raise FatalContractError(f"si_arso pair payload route {pair_route!r} contradicts shared route {route!r}")

        spec = SPECS_BY_PRODUCT_ID[str(product)]
        requested.append((product, spec))
        evidence = f"source-call:{pair_payload.acquisition_id}"
        base_key = (pair_payload.acquisition_id, product)
        base_def = base_series_cache.get(base_key)
        if base_def is None:
            base_def = source_series(station, str(product), origin="response", identity_evidence=(evidence,))
            base_series_cache[base_key] = base_def
        definitions_by_pair[key] = reused_series(base_def, pair_payload.known_series)

        window = SeriesWindow(
            start=datetime.fromisoformat(pair_payload.fetch_window.start.isoformat()),
            end=datetime.fromisoformat(pair_payload.fetch_window.end.isoformat()),
            axis=pair_payload.acquisition_axis,
        )
        retrieved = pair_payload.origin.retrieved_at if isinstance(pair_payload.origin.retrieved_at, datetime) else None
        pair_scope = pair_payload.scope or SeriesScope(
            provider_ids=("si_arso",),
            station_ids=(station,),
            product_ids=(str(product),),
        )
        meta_by_pair[key] = (pair_payload, window, retrieved, pair_scope)

    facts_by_product = {key[1]: dfn.facts[0].facts_id for key, dfn in definitions_by_pair.items()}
    try:
        if route.stream == "archive_daily":
            col_results = _parse_archive_daily(payload, station, requested)
        elif route.stream == "archive_monthly_extremes":
            col_results = _parse_archive_monthly_extremes(payload, station, requested)
        else:
            col_results = _parse_amp(payload, route, requested, facts_by_product)
    except UnsupportedSourceStructureError as error:
        reason = str(error)
        return {
            key: _failed_payload_result(
                pair_payload,
                station,
                [(key[1], SPECS_BY_PRODUCT_ID[str(key[1])])],
                window,
                retrieved,
                pair_scope,
                reason,
                series_by_product={key[1]: definitions_by_pair[key]},
            )
            for key, (pair_payload, window, retrieved, pair_scope) in meta_by_pair.items()
        }

    return {
        key: _build_pair_parsed_series(
            pair_payload,
            station=station,
            product=key[1],
            route=route,
            res=col_results[key[1]],
            definition=definitions_by_pair[key],
            window=window,
            retrieved=retrieved,
            pair_scope=pair_scope,
        )
        for key, (pair_payload, window, retrieved, pair_scope) in meta_by_pair.items()
    }


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    """Parse one ARSO archive CSV or operational amp HTML payload with bounded failures."""
    if not payload.station_products:
        raise FatalContractError("si_arso payload must contain at least one station-product pair")
    stations = {validate_station_id(station) for station, _ in payload.station_products}
    if len(stations) != 1:
        raise FatalContractError("si_arso payload must contain exactly one station")

    seen_products: set[ProductId] = set()
    route = payload.source_coordinates.value
    for _, product in payload.station_products:
        if product in seen_products:
            raise FatalContractError(f"si_arso payload contains duplicate product {product!r}")
        seen_products.add(product)
        _validated_product_route(product, route, provider_config)

    if len(payload.station_products) == 1:
        pair = payload.station_products[0]
        return parse_group(payload, {pair: payload}, provider_config)[pair]

    pair_payloads = {
        (station, product): narrow_payload_for_pair(payload, station, product)
        for station, product in payload.station_products
    }
    grouped = parse_group(payload, pair_payloads, provider_config)

    frames: list[pl.DataFrame] = []
    definitions: dict[str, SourceSeries] = {}
    inventories: list[InventorySnapshot] = []
    outcomes: list[RetrievalOutcome] = []
    issues: list[Issue] = []
    annotation_bundles: list[AnnotationBundle] = []
    annotation_offsets: list[int] = []
    offset = 0
    for pair in payload.station_products:
        part = grouped[pair]
        if not part.annotations.is_empty:
            annotation_bundles.append(part.annotations)
            annotation_offsets.append(offset)
        if not part.rows.is_empty():
            frames.append(part.rows)
            offset += part.rows.height
        for item in part.series:
            definitions[item.series_id] = item
        inventories.extend(part.inventories)
        outcomes.extend(part.outcomes)
        issues.extend(part.issues)
    combined = pl.concat(frames) if frames else pl.DataFrame(schema=RowsSchema.polars_schema)
    annotations = (
        AnnotationBundle.merge_sorted(
            annotation_bundles,
            row_offsets=annotation_offsets,
            old_to_new={i: i for i in range(combined.height)},
        )
        if annotation_bundles
        else AnnotationBundle.empty()
    )
    return ParsedSeries(
        combined,
        tuple(definitions.values()),
        tuple(inventories),
        tuple(outcomes),
        tuple(issues),
        annotations=annotations,
    )
