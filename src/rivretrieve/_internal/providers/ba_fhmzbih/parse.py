"""ba_fhmzbih native observations and source-series evidence.

Contributed by: Thiago von Däniken
"""

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from io import BytesIO
from math import isfinite

import openpyxl
import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, Rows, RowsSchema, WithIssues
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import NATIVE_SCHEMA, UnsupportedSourceStructureError, parse_mapped_series
from rivretrieve._internal.providers.ba_fhmzbih.config import (
    SERIES_MAPPINGS,
    BaFhmzbihMetadataCoordinates,
    BaFhmzbihSourceCoordinates,
)
from rivretrieve._internal.source_series import OutcomeStatus, ParsedSeries, RetrievalOutcome, SeriesWindow, stable_id


def resolve_metadata_groups(content: bytes, stations: tuple[str, ...]) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve publisher station routes per station without aborting valid siblings."""
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedSourceStructureError("ba_fhmzbih metadata index is not valid JSON") from error
    if not isinstance(document, list):
        raise UnsupportedSourceStructureError("ba_fhmzbih metadata index must be a JSON array")
    groups: dict[str, str] = {}
    errors: dict[str, str] = {}
    for station in dict.fromkeys(stations):
        matches = [row for row in document if isinstance(row, dict) and row.get("metadata_station_no") == station]
        if (
            len(matches) != 1
            or not isinstance(matches[0].get("metadata_site_no"), str)
            or not matches[0]["metadata_site_no"]
        ):
            errors[station] = f"ba_fhmzbih metadata index does not resolve exactly one group for station {station}"
        else:
            groups[station] = matches[0]["metadata_site_no"]
    return groups, errors


def metadata_groups(content: bytes, stations: tuple[str, ...]) -> dict[str, str]:
    """Resolve publisher station routes without inventing missing group identifiers."""
    groups, errors = resolve_metadata_groups(content, stations)
    if errors:
        raise UnsupportedSourceStructureError(next(iter(errors.values())))
    return groups


def _metadata_failure(
    payload: Payload, station: str, product: ProductId, reason: str
) -> tuple[RetrievalOutcome, Issue]:
    outcome = RetrievalOutcome(
        outcome_id=stable_id(station, product, reason, str(payload.origin.retrieved_at)),
        series_id=None,
        station_id=station,
        product_id=product,
        window=SeriesWindow(
            start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
            end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
        ),
        status=OutcomeStatus.UNSUPPORTED,
        reason=reason,
        retrieved_at=payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None,
    )
    issue = Issue(
        severity="error",
        code="unsupported_source_structure",
        message=reason,
        provider_id=ProviderId("ba_fhmzbih"),
        details={"station_id": station, "product_id": product},
    )
    return outcome, issue


def interpret_metadata_payload(
    payload: Payload,
    provider_config: ProviderConfig,
    *,
    error: UnsupportedSourceStructureError | None = None,
) -> ParsedSeries:
    """Build the metadata payload interpretation without re-decoding source JSON."""
    outcomes: list[RetrievalOutcome] = []
    issues: list[Issue] = []
    for station, product in payload.station_products:
        if product not in provider_config.products:
            raise FatalContractError("ba_fhmzbih metadata payload has an undeclared product")
        if error is not None:
            outcome, issue = _metadata_failure(payload, station, product, str(error))
            outcomes.append(outcome)
            issues.append(issue)
    return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), tuple(outcomes), tuple(issues))


def interpret_metadata_group(
    payload: Payload,
    pair_payloads: Mapping[tuple[str, ProductId], Payload],
    provider_config: ProviderConfig,
) -> tuple[tuple[dict[str, str], dict[str, str]], dict[tuple[str, ProductId], ParsedSeries]]:
    """Decode metadata index JSON once and build per-pair metadata interpretations."""
    empty_rows = pl.DataFrame(schema=RowsSchema.polars_schema)
    for _station, product in pair_payloads:
        if product not in provider_config.products:
            raise FatalContractError("ba_fhmzbih metadata payload has an undeclared product")
    stations = tuple(dict.fromkeys(station for station, _ in pair_payloads))
    try:
        groups, station_errors = resolve_metadata_groups(payload.content, stations)
    except UnsupportedSourceStructureError as error:
        failed_all: dict[tuple[str, ProductId], ParsedSeries] = {}
        for (station, product), pair_payload in pair_payloads.items():
            outcome, issue = _metadata_failure(pair_payload, station, product, str(error))
            failed_all[(station, product)] = ParsedSeries(empty_rows, (), (), (outcome,), (issue,))
        return ({}, {}), failed_all

    result: dict[tuple[str, ProductId], ParsedSeries] = {}
    for (station, product), pair_payload in pair_payloads.items():
        station_error = station_errors.get(station)
        if station_error is not None:
            outcome, issue = _metadata_failure(pair_payload, station, product, station_error)
            result[(station, product)] = ParsedSeries(empty_rows, (), (), (outcome,), (issue,))
        else:
            result[(station, product)] = ParsedSeries(empty_rows, (), (), (), ())
    return (groups, station_errors), result


def _parse_native(payload: Payload, provider_config: ProviderConfig) -> WithIssues[Rows]:
    if len(payload.station_products) != 1:
        raise FatalContractError("ba_fhmzbih workbook payload must contain one station-product pair")
    station, product = payload.station_products[0]
    coordinates = payload.source_coordinates.value
    if not isinstance(coordinates, BaFhmzbihSourceCoordinates):
        raise FatalContractError("ba_fhmzbih workbook has invalid source coordinates")
    try:
        workbook = openpyxl.load_workbook(BytesIO(payload.content), read_only=True, data_only=True)
        try:
            if len(workbook.worksheets) != 1:
                raise UnsupportedSourceStructureError(
                    "ba_fhmzbih workbook has multiple worksheets; their source-series relationship is not established"
                )
            (sheet,) = workbook.worksheets
            headers = tuple(
                tuple(cell for cell in row[:2]) for row in sheet.iter_rows(min_row=1, max_row=8, values_only=True)
            )
            expected = (
                ("#Station Name", headers[0][1]),
                ("#Station Number", station),
                ("#Station Parameter Name", coordinates.source_parameter),
                ("#Timeseries Name", "81 Web Kontinuirani"),
                ("#Unit Symbol", coordinates.source_unit),
                ("#Rows", headers[5][1]),
                ("#", None),
                ("#Timestamp", "Value"),
            )
            if headers != expected or (
                isinstance(headers[5][1], bool)
                or not isinstance(headers[5][1], int | float)
                or not float(headers[5][1]).is_integer()
            ):
                raise UnsupportedSourceStructureError("ba_fhmzbih workbook headers differ from the source contract")
            rows = []
            invalid_count = 0
            for timestamp, value, *_ in sheet.iter_rows(min_row=9, values_only=True):
                if not isinstance(timestamp, datetime):
                    invalid_count += 1
                    continue
                if isinstance(value, bool):
                    raise UnsupportedSourceStructureError("ba_fhmzbih workbook observation value cannot be boolean")
                try:
                    native_value = None if value is None else float(value)
                except OverflowError as error:
                    raise UnsupportedSourceStructureError(
                        "ba_fhmzbih workbook observation value is not representable as a finite number"
                    ) from error
                except (TypeError, ValueError):
                    invalid_count += 1
                    continue
                if native_value is not None and not isfinite(native_value):
                    raise UnsupportedSourceStructureError("ba_fhmzbih workbook observation value must be finite")
                rows.append(
                    {
                        "station_id": station,
                        "product_id": product,
                        "time": timestamp,
                        "value": native_value,
                        "time_zone": "unknown",
                    }
                )
        finally:
            workbook.close()
    except (FatalContractError, UnsupportedSourceStructureError):
        raise
    except Exception as error:
        raise UnsupportedSourceStructureError("ba_fhmzbih payload is not a readable workbook") from error
    if len(rows) + invalid_count != headers[5][1]:
        raise UnsupportedSourceStructureError("ba_fhmzbih workbook declared row count differs from its data rows")
    frame = pl.DataFrame(rows, schema=NATIVE_SCHEMA).sort("time")
    issues = []
    if invalid_count:
        raise UnsupportedSourceStructureError(
            f"ba_fhmzbih workbook has {invalid_count} rows with unrepresentable timestamps or values; complete interval coverage is not established"
        )
    if frame.is_empty():
        issues.append(_issue("missing_data", "Workbook contains no observation rows", station, 0))
    return WithIssues(frame, tuple(issues))


def _issue(code: str, message: str, station: str, count: int) -> Issue:
    return Issue(
        severity="warning",
        code=code,
        message=message,
        details={"station_id": station, "row_count": count},
        provider_id=ProviderId("ba_fhmzbih"),
    )


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    if isinstance(payload.source_coordinates.value, BaFhmzbihMetadataCoordinates):
        outcomes = []
        issues = []
        for station, product in payload.station_products:
            if product not in provider_config.products:
                raise FatalContractError("ba_fhmzbih metadata payload has an undeclared product")
            try:
                metadata_groups(payload.content, (station,))
            except UnsupportedSourceStructureError as error:
                outcome, issue = _metadata_failure(payload, station, product, str(error))
                outcomes.append(outcome)
                issues.append(issue)
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), tuple(outcomes), tuple(issues))
    parsed = parse_mapped_series(
        payload, provider_config, provider="ba_fhmzbih", mappings=SERIES_MAPPINGS, native_parse=_parse_native
    )
    # A rolling workbook establishes its published rows, not complete temporal coverage.
    return replace(
        parsed,
        outcomes=tuple(outcome.model_copy(update={"coverage": "observations"}) for outcome in parsed.outcomes),
    )
