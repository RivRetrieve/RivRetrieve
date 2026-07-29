"""parse : Payload × ProviderConfig → WithIssues[Rows]"""

from __future__ import annotations

from datetime import datetime
from typing import cast

import polars as pl

from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.engine import Daily, Payload, ProviderConfig, Rows, RowsSchema, WithIssues
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.ca_eccc.config import HydatSourceCoordinates
from rivretrieve._internal.providers.ca_eccc.issue_codes import CaEcccObservationIssueCodes

PROVIDER_ID = ProviderId("ca_eccc")


def parse(payload: Payload, provider_config: ProviderConfig) -> WithIssues[Rows]:
    if len(payload.station_products) != 1:
        raise FatalContractError("ca_eccc payload must contain exactly one station-product pair")
    station_id, product_id = payload.station_products[0]

    if product_id not in provider_config.products:
        return _result(
            _empty_rows(),
            [
                _parse_error(
                    "HYDAT payload names an undeclared product",
                    {"station_id": station_id, "product_id": product_id},
                ),
                _missing_data_issue(station_id, product_id),
            ],
        )

    product = provider_config.products[product_id]
    if not isinstance(product.semantics, Daily):
        raise FatalContractError("ca_eccc HYDAT products must declare Daily semantics")

    coordinates = payload.source_coordinates.value
    if not isinstance(coordinates, HydatSourceCoordinates):
        raise FatalContractError("ca_eccc payload source coordinates must be HydatSourceCoordinates")
    if payload.source_coordinates != product.coordinates:
        raise FatalContractError("ca_eccc payload source coordinates do not match the declared product")

    content = payload.content
    if not isinstance(content, list):
        return _result(
            _empty_rows(),
            [
                _parse_error(
                    "HYDAT payload content is not a list of monthly rows",
                    {"content_type": type(content).__name__},
                ),
                _missing_data_issue(station_id, product_id),
            ],
        )
    if not content:
        return _result(_empty_rows(), [_missing_data_issue(station_id, product_id)])

    row_data: list[dict[str, object]] = []
    issues: list[Issue] = []
    for row_index, raw_row in enumerate(content):
        if not isinstance(raw_row, dict):
            issues.append(
                _parse_error(
                    "Dropped malformed HYDAT monthly row",
                    {"row_index": row_index, "reason": "row is not a mapping"},
                )
            )
            continue
        row = cast("dict[str, object]", raw_row)
        calendar_fields = _calendar_fields(row)
        if calendar_fields is None:
            issues.append(
                _parse_error(
                    "Dropped malformed HYDAT monthly row",
                    {"row_index": row_index, "reason": "YEAR, MONTH, and NO_DAYS must be integers in range"},
                )
            )
            continue
        year, month, no_days = calendar_fields

        for day in range(1, no_days + 1):
            try:
                day_label = datetime(year, month, day)
            except ValueError:
                issues.append(
                    _parse_error(
                        "Dropped impossible HYDAT day index",
                        {"row_index": row_index, "year": year, "month": month, "day": day},
                    )
                )
                continue

            value_column = f"{coordinates.value_prefix}{day}"
            symbol_column = f"{coordinates.symbol_prefix}{day}"
            if value_column not in row:
                issues.append(
                    _parse_error(
                        "Dropped HYDAT day with a missing value column",
                        {"row_index": row_index, "day": day, "column": value_column},
                    )
                )
                continue
            if symbol_column not in row:
                issues.append(
                    _parse_error(
                        "HYDAT day has no quality-symbol column",
                        {"row_index": row_index, "day": day, "column": symbol_column},
                    )
                )

            raw_value = row[value_column]
            if raw_value is None:
                value = None
            elif isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
                issues.append(
                    _parse_error(
                        "Dropped HYDAT day with a non-numeric value",
                        {"row_index": row_index, "day": day, "column": value_column},
                    )
                )
                continue
            else:
                value = float(raw_value)

            row_data.append(
                {
                    "station_id": station_id,
                    "product_id": product_id,
                    "time": day_label,
                    "value": value,
                    "time_zone": provider_config.zone.value,
                }
            )

    rows = pl.DataFrame(row_data, schema=RowsSchema.polars_schema)
    if rows.is_empty():
        issues.append(_missing_data_issue(station_id, product_id))
    return _result(rows, issues)


def _calendar_fields(row: dict[str, object]) -> tuple[int, int, int] | None:
    for field in ("YEAR", "MONTH", "NO_DAYS"):
        if field not in row or isinstance(row[field], bool) or not isinstance(row[field], int):
            return None
    year = cast("int", row["YEAR"])
    month = cast("int", row["MONTH"])
    no_days = cast("int", row["NO_DAYS"])
    if not 1 <= year <= 9999 or not 1 <= month <= 12 or not 1 <= no_days <= 31:
        return None
    return year, month, no_days


def _empty_rows() -> Rows:
    return pl.DataFrame(schema=RowsSchema.polars_schema)


def _missing_data_issue(station_id: str, product_id: ProductId) -> Issue:
    return Issue(
        severity="warning",
        code=CaEcccObservationIssueCodes.MISSING_DATA,
        message="No HYDAT observation rows found",
        details={"station_id": station_id, "product_id": product_id},
        provider_id=PROVIDER_ID,
    )


def _parse_error(message: str, details: dict[str, object]) -> Issue:
    return Issue(
        severity="warning",
        code=CaEcccObservationIssueCodes.PARSE_ERROR,
        message=message,
        details=details,
        provider_id=PROVIDER_ID,
    )


def _result(rows: Rows, issues: list[Issue]) -> WithIssues[Rows]:
    validate_catalogue(rows, RowsSchema, on_issue="raise")
    return WithIssues(value=rows, issues=tuple(issues))
