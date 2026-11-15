"""jp_mlit native observations and source-series evidence.

Contributed by: Thiago von Däniken
"""

import csv
import re
from calendar import monthrange
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import isfinite

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, Rows, RowsSchema, WithIssues
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.provider_series import NATIVE_SCHEMA, UnsupportedSourceStructureError, parse_mapped_series
from rivretrieve._internal.providers.jp_mlit.annotations import JP_MLIT_OBSERVATIONS_SCHEMA
from rivretrieve._internal.providers.jp_mlit.config import SERIES_MAPPINGS, JpMlitSourceCoordinates
from rivretrieve._internal.providers.jp_mlit.fetch import JpMlitPayloadCoordinates, _page
from rivretrieve._internal.source_annotations import (
    OBSERVATION_STRUCTURAL_SCHEMA,
    AnnotationBundle,
    ObservationAnnotationTable,
)
from rivretrieve._internal.source_series import OutcomeStatus, ParsedSeries

_TITLES = {2: "時刻水位月表検索結果", 3: "日水位年表検索結果", 6: "時刻流量月表検索結果", 7: "日流量年表検索結果"}
_LEGENDS = {
    2: "#  フラグの意味： *:暫定値, $:欠測, #:閉局, -:未登録",
    3: "#  フラグの意味： $:欠測, -:未登録",
    6: "#  フラグの意味： *:暫定値, $:欠測, #:閉局, -:未登録",
    7: "#  フラグの意味： $:欠測, -:未登録",
}


@dataclass(frozen=True, slots=True)
class _SlotAnnotation:
    time: datetime
    flag: str | None
    measured: bool


def _empty() -> Rows:
    return pl.DataFrame(schema=NATIVE_SCHEMA)


def _payload_identity(
    payload: Payload, provider_config: ProviderConfig
) -> tuple[JpMlitPayloadCoordinates, str, ProductId]:
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
    return coordinates, station_id, product_id


def _parse_native(
    payload: Payload,
    provider_config: ProviderConfig,
    *,
    annotations_out: list[_SlotAnnotation] | None = None,
) -> WithIssues[Rows]:
    coordinates, station_id, product_id = _payload_identity(payload, provider_config)
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
        return _hourly(lines[header_index + 1 :], station_id, product_id, count, annotations_out=annotations_out)
    return _daily(lines[header_index + 1 :], station_id, product_id, count, annotations_out=annotations_out)


def _cell(
    value: str,
    flag_value: str,
    station: str,
    product: str,
    label: str,
    rows: list[dict[str, object]],
    slots: list[_SlotAnnotation],
    time: datetime,
) -> None:
    raw = value.strip()
    flag = flag_value.strip()
    if flag not in ("", "*", "$", "#", "-"):
        raise UnsupportedSourceStructureError(f"jp_mlit unknown native flag {flag!r} at {label}")
    if flag in ("$", "#", "-"):
        slots.append(_SlotAnnotation(time=time, flag=flag, measured=False))
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
    slots.append(_SlotAnnotation(time=time, flag="*" if flag == "*" else None, measured=True))
    rows.append({"station_id": station, "product_id": product, "time": time, "value": number, "time_zone": "unknown"})


def _hourly(
    lines: list[str],
    station: str,
    product: str,
    count: int,
    *,
    annotations_out: list[_SlotAnnotation] | None = None,
) -> WithIssues[Rows]:
    rows: list[dict[str, object]] = []
    slots: list[_SlotAnnotation] = []
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
                slots,
                time,
            )
    frame = pl.DataFrame(rows, schema=NATIVE_SCHEMA)
    if annotations_out is not None:
        annotations_out.extend(slots)
    return WithIssues(frame, ())


def _daily(
    lines: list[str],
    station: str,
    product: str,
    count: int,
    *,
    annotations_out: list[_SlotAnnotation] | None = None,
) -> WithIssues[Rows]:
    rows: list[dict[str, object]] = []
    slots: list[_SlotAnnotation] = []
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
            _cell(raw, flag, station, product, f"{year}年{month}月{day}日", rows, slots, time)
    if year is None:
        raise UnsupportedSourceStructureError("jp_mlit daily DAT has no year marker")
    frame = pl.DataFrame(rows, schema=NATIVE_SCHEMA)
    if annotations_out is not None:
        annotations_out.extend(slots)
    return WithIssues(frame, ())


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    coordinates, station_id, _ = _payload_identity(payload, provider_config)
    if coordinates.role == "html":
        try:
            links = _page(payload.content, coordinates.kind, station_id)
        except UnsupportedSourceStructureError:
            pass  # The mapped parser identifies this failed HTML boundary below.
        else:
            if links:
                # A valid HTML prerequisite is not a successful empty observation series.
                return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), ())
    captured_slots: list[_SlotAnnotation] = []
    parsed = parse_mapped_series(
        payload,
        provider_config,
        provider="jp_mlit",
        mappings=SERIES_MAPPINGS,
        native_parse=lambda tagged, cfg: _parse_native(tagged, cfg, annotations_out=captured_slots),
    )
    if (
        not parsed.series
        or not parsed.outcomes
        or parsed.outcomes[0].status not in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY)
        or not captured_slots
    ):
        return parsed
    series = parsed.series[0]
    facts_id = series.facts[0].facts_id
    measurement_indices: list[int | None] = []
    next_idx = 0
    for slot in captured_slots:
        if slot.measured:
            measurement_indices.append(next_idx)
            next_idx += 1
        else:
            measurement_indices.append(None)
    if next_idx != parsed.rows.height:
        raise FatalContractError("jp_mlit parsed rows and measured slot count mismatch")
    count = len(captured_slots)
    ann_frame = pl.DataFrame(
        {
            "series_id": [series.series_id] * count,
            "facts_id": [facts_id] * count,
            "station_id": [series.station_id] * count,
            "product_id": [series.product_id] * count,
            "time": [slot.time for slot in captured_slots],
            "time_zone": ["unknown"] * count,
            "measured": [slot.measured for slot in captured_slots],
            "flag": [slot.flag for slot in captured_slots],
        },
        schema={**OBSERVATION_STRUCTURAL_SCHEMA, **JP_MLIT_OBSERVATIONS_SCHEMA.polars_schema()},
    )
    table = ObservationAnnotationTable.from_rows(
        schema=JP_MLIT_OBSERVATIONS_SCHEMA,
        rows=ann_frame,
        measurement_indices=measurement_indices,
    )
    return replace(
        parsed,
        annotations=AnnotationBundle(observation_tables={JP_MLIT_OBSERVATIONS_SCHEMA.schema_id: table}),
    )
