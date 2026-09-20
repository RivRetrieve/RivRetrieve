"""jp_mlit native observations and source-series evidence.

Contributed by: Thiago von Däniken
"""

import csv
import re
from calendar import monthrange
from datetime import datetime, timedelta
from math import isfinite

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, Rows, RowsSchema, WithIssues
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.provider_series import NATIVE_SCHEMA, UnsupportedSourceStructureError, parse_mapped_series
from rivretrieve._internal.providers.jp_mlit.config import SERIES_MAPPINGS, JpMlitSourceCoordinates
from rivretrieve._internal.providers.jp_mlit.fetch import JpMlitPayloadCoordinates, _page
from rivretrieve._internal.source_series import ParsedSeries

_TITLES = {2: "時刻水位月表検索結果", 3: "日水位年表検索結果", 6: "時刻流量月表検索結果", 7: "日流量年表検索結果"}
_LEGENDS = {
    2: "#  フラグの意味： *:暫定値, $:欠測, #:閉局, -:未登録",
    3: "#  フラグの意味： $:欠測, -:未登録",
    6: "#  フラグの意味： *:暫定値, $:欠測, #:閉局, -:未登録",
    7: "#  フラグの意味： $:欠測, -:未登録",
}
_FLAG_CODES = {"*": "source_tentative", "$": "source_missing", "#": "source_closed_station", "-": "source_unregistered"}


def _empty() -> Rows:
    return pl.DataFrame(schema=NATIVE_SCHEMA)


def _issue(code: str, station: str, product: str, label: str) -> Issue:
    return Issue(
        severity="info",
        code=code,
        provider_id=ProviderId("jp_mlit"),
        message=f"jp_mlit {code}: {station} {product} {label}",
        details={"station_id": station, "product_id": product, "source_label": label},
    )


def _source_label(issue: Issue) -> object:
    if issue.details is None:
        raise AssertionError("jp_mlit internal issue lacks details")
    return issue.details["source_label"]


def _aggregate(issues: list[Issue]) -> tuple[Issue, ...]:
    grouped: dict[str, list[Issue]] = {}
    for issue in issues:
        grouped.setdefault(issue.code, []).append(issue)
    return tuple(
        Issue(
            severity="info",
            code=code,
            provider_id=ProviderId("jp_mlit"),
            message=f"jp_mlit {code}: {len(members)} source slots",
            details={
                "count": len(members),
                "first_source_label": _source_label(members[0]),
                "last_source_label": _source_label(members[-1]),
            },
        )
        for code, members in grouped.items()
    )


def _parse_native(payload: Payload, provider_config: ProviderConfig) -> WithIssues[Rows]:
    coordinates = payload.source_coordinates.value
    if not isinstance(coordinates, JpMlitPayloadCoordinates):
        raise FatalContractError("jp_mlit payload has invalid request coordinates")
    if len(payload.station_products) != 1:
        raise FatalContractError("jp_mlit payload must tag exactly one station-product pair")
    station_id, product_id = payload.station_products[0]
    try:
        product = provider_config.products[product_id]
    except KeyError as error:
        raise FatalContractError(f"jp_mlit product is absent from provider config: {product_id}") from error
    source = product.coordinates.value
    if not isinstance(source, JpMlitSourceCoordinates) or source.kind != coordinates.kind:
        raise FatalContractError("jp_mlit payload KIND differs from its product tag")
    if coordinates.role == "html":
        _page(payload.content, coordinates.kind, station_id)
        return WithIssues(_empty(), ())
    try:
        text = payload.content.decode("shift_jis", errors="strict")
    except UnicodeDecodeError as error:
        raise UnsupportedSourceStructureError("jp_mlit DAT is not strict Shift-JIS") from error
    lines = text.splitlines()
    if len(lines) < 10 or lines[0].strip() != _TITLES[coordinates.kind]:
        raise UnsupportedSourceStructureError("jp_mlit DAT title differs from requested KIND")
    expected_labels = ("水系名", "河川名", "観測所名", "観測所記号")
    for line, label in zip(lines[1:5], expected_labels, strict=True):
        cells = next(csv.reader([line]))
        if len(cells) != 2 or cells[0] != label or not cells[1].strip():
            raise UnsupportedSourceStructureError("jp_mlit DAT station or source identity header is malformed")
        if label == "観測所記号" and cells[1] != station_id:
            raise UnsupportedSourceStructureError("jp_mlit DAT station identity differs from request")
    if _LEGENDS[coordinates.kind] not in lines:
        raise UnsupportedSourceStructureError("jp_mlit DAT flag legend differs from KIND contract")
    header_index = next(
        (index for index, line in enumerate(lines) if line.startswith(",1時,") or line.startswith(",1日,")), None
    )
    if header_index is None:
        raise UnsupportedSourceStructureError("jp_mlit DAT has no exact value/flag header")
    header = next(csv.reader([lines[header_index]]))
    count = 24 if coordinates.kind in (2, 6) else 31
    expected_header = [""] + [
        cell for index in range(1, count + 1) for cell in (f"{index}{'時' if count == 24 else '日'}", "")
    ]
    if header != expected_header:
        raise UnsupportedSourceStructureError("jp_mlit DAT value/flag header is malformed")
    if coordinates.kind in (2, 6):
        return _hourly(lines[header_index + 1 :], station_id, product_id, count)
    return _daily(lines[header_index + 1 :], station_id, product_id, count)


def _cell(
    value: str,
    flag_value: str,
    station: str,
    product: str,
    label: str,
    rows: list[dict[str, object]],
    issues: list[Issue],
    time: datetime,
) -> None:
    raw = value.strip()
    flag = flag_value.strip()
    if flag not in ("", "*", "$", "#", "-"):
        raise UnsupportedSourceStructureError(f"jp_mlit unknown native flag {flag!r} at {label}")
    if flag in ("$", "#", "-"):
        issues.append(_issue(_FLAG_CODES[flag], station, product, label))
        return
    if not raw:
        raise UnsupportedSourceStructureError(f"jp_mlit usable cell is blank at {label}")
    try:
        number = float(raw)
    except (ValueError, OverflowError) as error:
        raise UnsupportedSourceStructureError(
            f"jp_mlit usable cell is nonnumeric or unrepresentable at {label}"
        ) from error
    if not isfinite(number):
        raise UnsupportedSourceStructureError(f"jp_mlit usable cell must be finite at {label}")
    if flag == "*":
        issues.append(_issue(_FLAG_CODES[flag], station, product, label))
    rows.append({"station_id": station, "product_id": product, "time": time, "value": number, "time_zone": "unknown"})


def _hourly(lines: list[str], station: str, product: str, count: int) -> WithIssues[Rows]:
    rows: list[dict[str, object]] = []
    issues: list[Issue] = []
    for line in lines:
        if not line.strip():
            continue
        cells = next(csv.reader([line]))
        if len(cells) != 1 + 2 * count:
            raise UnsupportedSourceStructureError("jp_mlit hourly row does not contain exact value/flag pairs")
        try:
            day = datetime.strptime(cells[0].strip(), "%Y/%m/%d")
        except ValueError as error:
            raise UnsupportedSourceStructureError("jp_mlit hourly row has invalid source date") from error
        for hour in range(1, 25):
            time = day + timedelta(days=1) if hour == 24 else day.replace(hour=hour)
            _cell(
                cells[2 * hour - 1],
                cells[2 * hour],
                station,
                product,
                f"{cells[0].strip()} {hour}時",
                rows,
                issues,
                time,
            )
    frame = pl.DataFrame(rows, schema=NATIVE_SCHEMA)
    return WithIssues(frame, _aggregate(issues))


def _daily(lines: list[str], station: str, product: str, count: int) -> WithIssues[Rows]:
    rows: list[dict[str, object]] = []
    issues: list[Issue] = []
    year: int | None = None
    for line in lines:
        if not line.strip():
            continue
        if match := re.fullmatch(r"(\d{4})年", line.strip()):
            if year is not None:
                raise UnsupportedSourceStructureError("jp_mlit daily DAT contains multiple year markers")
            year = int(match.group(1))
            continue
        if year is None:
            raise UnsupportedSourceStructureError("jp_mlit daily DAT has data before its year marker")
        cells = next(csv.reader([line]))
        if len(cells) > 1 + 2 * count or (len(cells) - 1) % 2:
            raise UnsupportedSourceStructureError("jp_mlit daily row does not contain exact value/flag pairs")
        match = re.fullmatch(r"(\d{1,2})月", cells[0].strip())
        if match is None:
            raise UnsupportedSourceStructureError("jp_mlit daily row has invalid month label")
        month = int(match.group(1))
        try:
            expected_days = monthrange(year, month)[1]
        except ValueError as error:
            raise UnsupportedSourceStructureError("jp_mlit daily row has invalid month label") from error
        if len(cells) != 1 + 2 * expected_days:
            raise UnsupportedSourceStructureError("jp_mlit daily row does not contain the exact calendar-day pairs")
        for day in range(1, expected_days + 1):
            raw, flag = cells[2 * day - 1], cells[2 * day]
            try:
                time = datetime(year, month, day)
            except ValueError as error:
                if raw.strip() or flag.strip():
                    raise UnsupportedSourceStructureError(
                        "jp_mlit invalid calendar day contains an observation"
                    ) from error
                continue
            _cell(raw, flag, station, product, f"{year}年{month}月{day}日", rows, issues, time)
    if year is None:
        raise UnsupportedSourceStructureError("jp_mlit daily DAT has no year marker")
    frame = pl.DataFrame(rows, schema=NATIVE_SCHEMA)
    return WithIssues(frame, _aggregate(issues))


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    if (
        isinstance(payload.source_coordinates.value, JpMlitPayloadCoordinates)
        and payload.source_coordinates.value.role == "html"
    ):
        _parse_native(payload, provider_config)
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), ())
    return parse_mapped_series(
        payload, provider_config, provider="jp_mlit", mappings=SERIES_MAPPINGS, native_parse=_parse_native
    )
