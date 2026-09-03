"""za_dws parse : Payload × ProviderConfig → WithIssues[Rows].

Decodes one HyData.aspx page: the ``<pre>`` block's format legend, station line, header row,
whitespace-delimited fixed-format rows and, for Daily, the ``ZZZZZZZZZZZZ`` terminator. Quality
codes and the ``99999.999`` token are surfaced as issues and never interpreted.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import polars as pl

from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.engine import Payload, ProviderConfig, Rows, RowsSchema, WithIssues
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.za_dws.config import ZaDwsColumn, ZaDwsDataType, ZaDwsSourceCoordinates
from rivretrieve._internal.providers.za_dws.fetch import ZaDwsSourceRoute
from rivretrieve._internal.providers.za_dws.issue_codes import ZaDwsObservationIssueCodes

PROVIDER_ID = ProviderId("za_dws")

_PRE_BLOCK = re.compile(r"<pre[^>]*>(.*?)</pre>", re.DOTALL | re.IGNORECASE)
_LEGEND_LINE = re.compile(r"^POS\.\s+\d+-\d+\s+=\s+")
_VARIABLE_LINE = "Variable 100.00 Surface Water Level"
_HEADER_PREFIX = "DATE"
_TERMINATOR = "ZZZZZZZZZZZZ"
# The real 2020 Daily response closes its rows with the terminator; the only real Point bytes
# (a legacy file that may be truncated) end at a data row, so whether Point responses carry
# the terminator is unknown until a recording settles it.
_TERMINATOR_REQUIRED: dict[ZaDwsDataType, bool] = {"Daily": True, "Point": False}
# The Daily legend line reads "Daily avg flow rate in cubic metres/sec 99999.999". The retired
# port read that token as a missing-value marker; that meaning is unverified (the line may be a
# column mask, and the Point legend has no such token), so a value equal to it is returned as
# published and reported.
_MARKER_TOKEN = "99999.999"
# Plain-text body the retired port expected without a <pre> block when the portal holds nothing
# for a window. It has not been observed through this adapter.
_NO_DATA_STATEMENTS = ("No data for requested period.",)


@dataclass(frozen=True, slots=True)
class _RowLayout:
    """Whitespace-token positions of one DataType's rows, as the header row orders them."""

    token_count: int
    time_token: int | None
    value_tokens: dict[ZaDwsColumn, int]
    quality_tokens: dict[ZaDwsColumn, int]


_LAYOUTS: dict[ZaDwsDataType, _RowLayout] = {
    "Daily": _RowLayout(3, None, {"D AVG F/R": 1}, {"D AVG F/R": 2}),
    "Point": _RowLayout(6, 1, {"COR.LEVEL": 2, "COR.FLOW": 4}, {"COR.LEVEL": 3, "COR.FLOW": 5}),
}


@dataclass(slots=True)
class _Tally:
    count: int = 0
    first: datetime | None = None
    last: datetime | None = None

    def add(self, time: datetime) -> None:
        self.count += 1
        self.first = time if self.first is None else self.first
        self.last = time


def parse(payload: Payload, provider_config: ProviderConfig) -> WithIssues[Rows]:
    route = payload.source_coordinates.value
    if not isinstance(route, ZaDwsSourceRoute):
        raise FatalContractError("za_dws payload has invalid source route coordinates")
    if not payload.station_products:
        raise FatalContractError("za_dws payload must contain at least one station-product pair")
    stations = {station for station, _ in payload.station_products}
    if len(stations) != 1:
        raise FatalContractError("za_dws payload must contain exactly one station")
    station = next(iter(stations))
    columns = {product: _column(product, provider_config, route.data_type) for _, product in payload.station_products}
    layout = _LAYOUTS[route.data_type]

    text = _text(payload.content)
    block = _PRE_BLOCK.search(text)
    if block is None:
        if any(statement in text for statement in _NO_DATA_STATEMENTS):
            return WithIssues(_empty(), (_no_data(station, tuple(columns), route.data_type),))
        raise FatalContractError("za_dws response has neither a <pre> data block nor a recognised no-data statement")
    data_lines = _data_lines(
        block.group(1).splitlines(), station, tuple(columns.values()), _TERMINATOR_REQUIRED[route.data_type]
    )

    rows: list[dict[str, object]] = []
    markers: dict[ProductId, _Tally] = {}
    qualities: dict[tuple[ProductId, str], _Tally] = {}
    for line in data_lines:
        tokens = line.split()
        if len(tokens) != layout.token_count:
            raise FatalContractError(
                f"za_dws {route.data_type} row does not have exactly {layout.token_count} fields: {line!r}"
            )
        time = _time(tokens[0], None if layout.time_token is None else tokens[layout.time_token], line)
        for _, product in payload.station_products:
            column = columns[product]
            raw = tokens[layout.value_tokens[column]]
            try:
                value = float(raw)
            except ValueError as error:
                raise FatalContractError(f"za_dws {column} field is not numeric: {line!r}") from error
            if raw == _MARKER_TOKEN:
                markers.setdefault(product, _Tally()).add(time)
            qualities.setdefault((product, tokens[layout.quality_tokens[column]]), _Tally()).add(time)
            rows.append(
                {"station_id": station, "product_id": product, "time": time, "value": value, "time_zone": "unknown"}
            )

    frame = pl.DataFrame(rows, schema=RowsSchema.polars_schema)
    validate_catalogue(frame, RowsSchema, on_issue="raise")
    issues = (
        *(_marker_issue(station, product, tally) for product, tally in markers.items()),
        *(_quality_issue(station, product, code, tally) for (product, code), tally in qualities.items()),
    )
    return WithIssues(value=frame, issues=issues)


def _column(product: ProductId, config: ProviderConfig, data_type: ZaDwsDataType) -> ZaDwsColumn:
    try:
        value = config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"za_dws product is absent from provider config: {product}") from error
    if not isinstance(value, ZaDwsSourceCoordinates):
        raise FatalContractError(f"za_dws product has invalid source coordinates: {product}")
    if value.data_type != data_type:
        raise FatalContractError(f"za_dws payload DataType {data_type} does not publish product {product}")
    return value.column


def _text(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FatalContractError("za_dws response is not UTF-8 text") from error


def _data_lines(
    lines: list[str], station: str, columns: tuple[ZaDwsColumn, ...], terminator_required: bool
) -> list[str]:
    stripped = [line.strip() for line in lines]
    if not any(_LEGEND_LINE.match(line) for line in stripped):
        raise FatalContractError("za_dws <pre> block has no format legend")
    header_index = next((index for index, line in enumerate(stripped) if line.startswith(_HEADER_PREFIX)), None)
    if header_index is None:
        raise FatalContractError("za_dws <pre> block has no DATE header row")
    preamble = stripped[:header_index]
    if station not in preamble:
        raise FatalContractError(f"za_dws <pre> block does not name requested station {station}")
    if _VARIABLE_LINE not in preamble:
        raise FatalContractError(f"za_dws <pre> block does not name {_VARIABLE_LINE!r}")
    header = stripped[header_index]
    for column in columns:
        if column not in header:
            raise FatalContractError(f"za_dws header row {header!r} lacks column {column!r}")
    try:
        terminator_index = stripped.index(_TERMINATOR, header_index + 1)
    except ValueError as error:
        if terminator_required:
            raise FatalContractError(f"za_dws <pre> block is not closed by the {_TERMINATOR} terminator") from error
        terminator_index = len(stripped)
    return [line for line in stripped[header_index + 1 : terminator_index] if line]


def _time(date_token: str, time_token: str | None, line: str) -> datetime:
    label = date_token if time_token is None else f"{date_token} {time_token}"
    pattern = "%Y%m%d" if time_token is None else "%Y%m%d %H%M%S"
    if re.fullmatch(r"[0-9]{8}( [0-9]{6})?", label) is None:
        raise FatalContractError(f"za_dws row has a malformed date or time: {line!r}")
    try:
        return datetime.strptime(label, pattern)
    except ValueError as error:
        raise FatalContractError(f"za_dws row has an invalid calendar date or time: {line!r}") from error


def _empty() -> Rows:
    return pl.DataFrame(schema=RowsSchema.polars_schema)


def _no_data(station: str, products: tuple[ProductId, ...], data_type: ZaDwsDataType) -> Issue:
    return Issue(
        severity="warning",
        code=ZaDwsObservationIssueCodes.NO_DATA_FOR_PERIOD,
        message="DWS states it holds no data for the requested station and period",
        details={"station_id": station, "product_ids": list(products), "data_type": data_type},
        provider_id=PROVIDER_ID,
    )


def _tally_details(station: str, product: ProductId, tally: _Tally) -> dict[str, object]:
    return {
        "station_id": station,
        "product_id": product,
        "count": tally.count,
        "first_time": None if tally.first is None else tally.first.isoformat(),
        "last_time": None if tally.last is None else tally.last.isoformat(),
    }


def _marker_issue(station: str, product: ProductId, tally: _Tally) -> Issue:
    return Issue(
        severity="warning",
        code=ZaDwsObservationIssueCodes.UNVERIFIED_MARKER_VALUE,
        message=(
            f"DWS published the token {_MARKER_TOKEN}, which the Daily legend names and the retired port read "
            "as a missing-value marker; the meaning is unverified, so the value is returned exactly as published"
        ),
        details={**_tally_details(station, product, tally), "token": _MARKER_TOKEN},
        provider_id=PROVIDER_ID,
    )


def _quality_issue(station: str, product: ProductId, code: str, tally: _Tally) -> Issue:
    return Issue(
        severity="info",
        code=ZaDwsObservationIssueCodes.SOURCE_QUALITY_CODE,
        message=f"DWS quality code {code} accompanies {tally.count} value(s); the code is source judgement",
        details={**_tally_details(station, product, tally), "quality_code": code},
        provider_id=PROVIDER_ID,
    )
