"""no_nve parse : Payload × ProviderConfig → WithIssues[Rows].

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import cast

import polars as pl

from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.engine import Payload, ProviderConfig, Rows, RowsSchema, WithIssues
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import IssueSeverity, ProductId, ProviderId
from rivretrieve._internal.providers.no_nve.config import NoNveSourceCoordinates
from rivretrieve._internal.providers.no_nve.issue_codes import NoNveObservationIssueCodes

PROVIDER_ID = ProviderId("no_nve")
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_SOURCE_ZONE = "+00:00"


def parse(payload: Payload, provider_config: ProviderConfig) -> WithIssues[Rows]:
    if len(payload.station_products) != 1:
        raise FatalContractError("no_nve payload must contain exactly one station-product pair")
    station_id, product_id = payload.station_products[0]
    coordinates = _coordinates(product_id, provider_config)
    if payload.source_coordinates.value != coordinates:
        raise FatalContractError("no_nve payload coordinates differ from its product tag")

    series = _series(payload.content, station_id, coordinates)
    observations = _observations(series)
    count = series.get("observationCount")
    if type(count) is not int or count != len(observations):
        raise FatalContractError("no_nve series observationCount differs from its observations")

    rows: list[dict[str, object]] = []
    quality_codes: dict[int, list[str]] = {}
    correction_codes: dict[int, list[str]] = {}
    for index, raw in enumerate(observations):
        if not isinstance(raw, dict):
            raise FatalContractError(f"no_nve observation {index} must be a JSON object")
        observation = cast("dict[str, object]", raw)
        label = _time(observation, index)
        quality = _code(observation, "quality", index)
        correction = _code(observation, "correction", index)
        quality_codes.setdefault(quality, []).append(label.isoformat())
        correction_codes.setdefault(correction, []).append(label.isoformat())
        rows.append(
            {
                "station_id": station_id,
                "product_id": product_id,
                "time": label,
                "value": _value(observation, index),
                "time_zone": _SOURCE_ZONE,
            }
        )

    frame = pl.DataFrame(rows, schema=RowsSchema.polars_schema)
    validate_catalogue(frame, RowsSchema, on_issue="raise")
    issues: list[Issue] = []
    if not rows:
        issues.append(
            _issue(
                NoNveObservationIssueCodes.MISSING_DATA,
                "warning",
                "no_nve series carries no observation in the requested reference time",
                {"station_id": station_id, "product_id": product_id},
            )
        )
    issues.extend(_code_issues(NoNveObservationIssueCodes.SOURCE_QUALITY_CODE, "quality", quality_codes, station_id))
    issues.extend(
        _code_issues(NoNveObservationIssueCodes.SOURCE_CORRECTION_CODE, "correction", correction_codes, station_id)
    )
    return WithIssues(value=frame, issues=tuple(issues))


def _coordinates(product_id: ProductId, provider_config: ProviderConfig) -> NoNveSourceCoordinates:
    try:
        value = provider_config.products[product_id].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"no_nve product is absent from provider config: {product_id}") from error
    if not isinstance(value, NoNveSourceCoordinates):
        raise FatalContractError(f"no_nve product has invalid source coordinates: {product_id}")
    return value


def _series(content: bytes, station_id: str, coordinates: NoNveSourceCoordinates) -> dict[str, object]:
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FatalContractError("no_nve payload content is not valid JSON") from error
    if not isinstance(document, dict):
        raise FatalContractError("no_nve payload content must be a JSON object")
    data = cast("dict[str, object]", document).get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise FatalContractError("no_nve payload must contain exactly one series object")
    series = cast("dict[str, object]", data[0])
    if series.get("stationId") != station_id:
        raise FatalContractError("no_nve series station differs from its requested station")
    if series.get("parameter") != int(coordinates.parameter):
        raise FatalContractError("no_nve series parameter differs from its requested parameter")
    if series.get("method") != coordinates.method:
        raise FatalContractError("no_nve series method differs from the declared product statistic")
    if series.get("unit") != coordinates.source_unit:
        raise FatalContractError("no_nve series unit differs from the declared source unit")
    return series


def _observations(series: dict[str, object]) -> list[object]:
    observations = series.get("observations")
    if not isinstance(observations, list):
        raise FatalContractError("no_nve series observations must be a list")
    return cast("list[object]", observations)


def _time(observation: dict[str, object], index: int) -> datetime:
    value = observation.get("time")
    if not isinstance(value, str):
        raise FatalContractError(f"no_nve observation {index} time must be a string")
    try:
        return datetime.strptime(value, _TIME_FORMAT)
    except ValueError as error:
        raise FatalContractError(f"no_nve observation {index} time must be a strict UTC instant label") from error


def _value(observation: dict[str, object], index: int) -> float | None:
    if "value" not in observation:
        raise FatalContractError(f"no_nve observation {index} is missing its value")
    value = observation["value"]
    if value is None:
        return None
    if type(value) not in (int, float):
        raise FatalContractError(f"no_nve observation {index} value must be numeric or null")
    return float(cast("int | float", value))


def _code(observation: dict[str, object], name: str, index: int) -> int:
    value = observation.get(name)
    if type(value) is not int:
        raise FatalContractError(f"no_nve observation {index} {name} must be an integer source code")
    return value


def _code_issues(
    code: NoNveObservationIssueCodes,
    name: str,
    labels_by_code: dict[int, list[str]],
    station_id: str,
) -> list[Issue]:
    return [
        _issue(
            code,
            "info",
            f"no_nve published source {name} code {source_code} without RivRetrieve interpretation",
            {
                "station_id": station_id,
                f"source_{name}_code": source_code,
                "count": len(labels),
                "first_source_time": labels[0],
                "last_source_time": labels[-1],
            },
        )
        for source_code, labels in sorted(labels_by_code.items())
    ]


def _issue(
    code: NoNveObservationIssueCodes,
    severity: IssueSeverity,
    message: str,
    details: dict[str, object],
) -> Issue:
    return Issue(
        severity=severity,
        code=code,
        message=message,
        details=details,
        provider_id=PROVIDER_ID,
    )
