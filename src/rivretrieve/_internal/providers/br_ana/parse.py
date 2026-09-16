"""ANA parse : Payload × ProviderConfig → WithIssues[Rows] (native source variants, no quality policy).

Contributed by: Thiago von Däniken
"""

import json
import re
from calendar import monthrange
from collections import Counter
from datetime import datetime
from math import isfinite
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, Rows, RowsSchema, WithIssues
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.br_ana.config import BrAnaDailySourceCoordinates, BrAnaSourceCoordinates
from rivretrieve._internal.providers.br_ana.issue_codes import BrAnaObservationIssueCodes

_PROVIDER = ProviderId("br_ana")
_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?")
_NUMBER = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?")


def parse(payload: Payload, config: ProviderConfig) -> WithIssues[Rows]:
    if len(payload.station_products) != 1:
        raise FatalContractError("ANA payload requires exactly one station-product pair")
    station, product = payload.station_products[0]
    coordinates = config.products[product].coordinates.value
    if (
        not isinstance(coordinates, (BrAnaSourceCoordinates, BrAnaDailySourceCoordinates))
        or payload.source_coordinates.value != coordinates
    ):
        raise FatalContractError("ANA payload coordinates differ from the requested source product")
    observations = _observations(payload.content)
    if isinstance(coordinates, BrAnaDailySourceCoordinates):
        return _daily_rows(observations, station, product, coordinates)
    rows: list[dict[str, object]] = []
    statuses: Counter[str | None] = Counter()
    for index, observation in enumerate(observations):
        if observation.get("codigoestacao") != station:
            raise FatalContractError(f"ANA observation {index} station differs from the requested station")
        label = _time(observation.get("Data_Hora_Medicao"), index)
        if coordinates.field not in observation or f"{coordinates.field}_Status" not in observation:
            raise FatalContractError(f"ANA observation {index} is missing an adopted value or status field")
        status = observation[f"{coordinates.field}_Status"]
        if status is not None and not isinstance(status, str):
            raise FatalContractError(f"ANA observation {index} adopted status must be a source string or null")
        statuses[status] += 1
        rows.append(
            {
                "station_id": station,
                "product_id": product,
                "time": label,
                "value": _value(observation[coordinates.field], index),
                "time_zone": "unknown",
            }
        )
    # Unordered source arrays are not chronology. Retain duplicate multiplicity and
    # differing values: neither the status nor the update label authorizes selection.
    frame = pl.DataFrame(rows, schema=RowsSchema.polars_schema).sort("time", maintain_order=True)
    issues = tuple(
        Issue(
            severity="info",
            code=BrAnaObservationIssueCodes.SOURCE_STATUS,
            message="ANA published adopted telemetry status without RivRetrieve interpretation",
            details={
                "station_id": station,
                "product_id": product,
                "source_field": f"{coordinates.field}_Status",
                "source_status": status,
                "count": count,
            },
            provider_id=_PROVIDER,
        )
        for status, count in sorted(statuses.items(), key=lambda item: (item[0] is not None, item[0] or ""))
    )
    if not observations:
        issues += (
            Issue(
                severity="warning",
                code=BrAnaObservationIssueCodes.MISSING_DATA,
                message="ANA response contains no adopted telemetry observations",
                details={"station_id": station, "product_id": product},
                provider_id=_PROVIDER,
            ),
        )
    return WithIssues(frame, issues)


def _daily_rows(
    observations: list[dict[str, object]],
    station: str,
    product: ProductId,
    coordinates: BrAnaDailySourceCoordinates,
) -> WithIssues[Rows]:
    """Decode monthly source day slots for one exact mean/consistency variant."""
    rows: list[dict[str, object]] = []
    statuses: Counter[tuple[str, str | None]] = Counter()
    consistency_field = "nivelconsistencia" if coordinates.field_prefix == "Cota" else "Nivel_Consistencia"
    for index, observation in enumerate(observations):
        if observation.get("codigoestacao") != station:
            raise FatalContractError(f"ANA observation {index} station differs from the requested station")
        mean = observation.get("Mediadiaria")
        consistency = observation.get(consistency_field)
        if mean not in ("0", "1") or consistency not in ("1", "2"):
            raise FatalContractError(f"ANA observation {index} has an invalid mean or consistency code")
        # Flag0 headers legitimately carry07:00/17:00. They are outside this
        # mean product, not malformed daily means and never averaging inputs.
        if mean != "1" or consistency != coordinates.consistency:
            continue
        header = _time(observation.get("Data_Hora_Dado"), index)
        if header.day != 1 or header != datetime(header.year, header.month, 1):
            raise FatalContractError(f"ANA observation {index} daily mean requires a midnight first-of-month header")
        last_day = monthrange(header.year, header.month)[1]
        for day in range(1, 32):
            field = f"{coordinates.field_prefix}_{day:02d}"
            status_field = f"{field}_Status"
            if field not in observation or status_field not in observation:
                raise FatalContractError(f"ANA observation {index} is missing a daily value or status field")
            raw = observation[field]
            status = observation[status_field]
            if status is not None and not isinstance(status, str):
                raise FatalContractError(f"ANA observation {index} daily status must be a source string or null")
            if day > last_day:
                # Hidro1.4 explicitly names status0 BRANCO. It is not a
                # numeric-value sentinel: a finite value outside the month fails.
                if raw not in (None, "") or status not in (None, "", "0"):
                    raise FatalContractError(f"ANA observation {index} has a nonempty invalid calendar slot {field}")
                continue
            statuses[(status_field, status)] += 1
            rows.append(
                {
                    "station_id": station,
                    "product_id": product,
                    "time": datetime(header.year, header.month, day),
                    "value": None if raw == "" else _value(raw, index),
                    "time_zone": "unknown",
                }
            )
    # Source duplicates are observations, not authorization to choose a winner.
    frame = pl.DataFrame(rows, schema=RowsSchema.polars_schema).sort("time", maintain_order=True)
    issues = tuple(
        Issue(
            severity="info",
            code=BrAnaObservationIssueCodes.SOURCE_STATUS,
            message="ANA published daily status without RivRetrieve interpretation",
            details={
                "station_id": station,
                "product_id": product,
                "source_field": field,
                "source_status": status,
                "count": count,
            },
            provider_id=_PROVIDER,
        )
        for (field, status), count in sorted(
            statuses.items(), key=lambda item: (item[0][0], item[0][1] is not None, item[0][1] or "")
        )
    )
    if not rows:
        issues += (
            Issue(
                severity="warning",
                code=BrAnaObservationIssueCodes.MISSING_DATA,
                message="ANA response contains no daily observations for the requested source variant",
                details={"station_id": station, "product_id": product},
                provider_id=_PROVIDER,
            ),
        )
    return WithIssues(frame, issues)


def _observations(content: bytes) -> list[dict[str, object]]:
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FatalContractError("ANA response must be valid JSON") from error
    if (
        not isinstance(document, dict)
        or document.get("status") != "OK"
        or type(document.get("code")) is not int
        or document["code"] != 200
    ):
        raise FatalContractError("ANA response must be a successful source envelope")
    items = document.get("items")
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise FatalContractError("ANA successful response items must be a list of observation objects")
    return cast("list[dict[str, object]]", items)


def _time(value: object, index: int) -> datetime:
    if not isinstance(value, str) or _TIME.fullmatch(value) is None:
        raise FatalContractError(f"ANA observation {index} requires a native naive measurement timestamp")
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise FatalContractError(f"ANA observation {index} has an invalid measurement timestamp") from error


def _value(value: object, index: int) -> float | None:
    if value is None:
        return None
    if not isinstance(value, str) or _NUMBER.fullmatch(value) is None:
        raise FatalContractError(f"ANA observation {index} value must be a decimal string or null")
    result = float(value)
    if not isfinite(result):
        raise FatalContractError(f"ANA observation {index} value must be finite")
    # No documented sentinel rule: finite source numbers remain numbers, including negative values.
    return result
