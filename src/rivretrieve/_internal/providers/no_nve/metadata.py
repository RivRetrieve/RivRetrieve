"""Acquire the currently published HydAPI version inventory for one access coordinate."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rivretrieve._internal.authentication import CredentialExchangeError
from rivretrieve._internal.engine import SourceAcquisition, SourceCallOrigin, UnknownOriginFact
from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.no_nve.config import NoNveSourceCoordinates
from rivretrieve._internal.providers.no_nve.series import describe_series
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
    stable_id,
)
from rivretrieve._internal.transport import HttpMethod, Transport, TransportFailure, TransportRequest

_URL = "https://hydapi.nve.no/api/v1/Series"
_EVIDENCE = "https://hydapi.nve.no/UserDocumentation/#series; scoped HydAPI Series response"


class _Resolution(BaseModel):
    model_config = ConfigDict(strict=True)
    resolution: int = Field(alias="resTime")
    method: str | None


class _SeriesMetadata(BaseModel):
    model_config = ConfigDict(strict=True)
    station: str = Field(alias="stationId")
    parameter: int
    version: int = Field(alias="versionNo")
    unit: str | None
    resolutions: list[_Resolution] = Field(alias="resolutionList")


def acquire_inventory(
    station: str,
    product: str,
    coordinates: NoNveSourceCoordinates,
    transport: Transport,
    window: SeriesWindow,
) -> SourceAcquisition:
    """Read current published metadata, without claiming timeless historical completeness."""
    request = TransportRequest(
        HttpMethod.GET,
        _URL,
        {"StationId": station, "Parameter": int(coordinates.parameter)},
        {"Accept": "application/json"},
    )
    scope = SeriesScope(provider_ids=("no_nve",), station_ids=(station,), product_ids=(product,))
    reasons: list[str] = []
    definitions: dict[str, SourceSeries] = {}
    unknown = UnknownOriginFact()
    acquired: datetime | None = None
    try:
        response = transport.send(request)
    except (TransportFailure, CredentialExchangeError) as error:
        status = error.status_code
        origin = SourceCallOrigin(
            _URL, request.params or {}, status if status is not None else unknown, unknown, unknown, unknown, unknown
        )
        capture = uuid4().hex
        reasons.append(
            f"HydAPI current version inventory request failed: {error.reason.value}"
            + (f" after {error.attempts} attempts" if isinstance(error, TransportFailure) else "")
            + (f" (HTTP {status})" if status is not None else "")
        )
    else:
        acquired = response.retrieved_at
        origin = SourceCallOrigin(
            response.url,
            response.request_parameters,
            response.status_code,
            response.retrieved_at,
            response.content_type or unknown,
            unknown,
            unknown,
        )
        capture = stable_id(hashlib.sha256(response.content).hexdigest(), acquired.isoformat())
        try:
            if response.status_code != 200:
                raise ValueError(f"HydAPI current version inventory returned HTTP {response.status_code}")
            document = json.loads(response.content)
            if not isinstance(document, dict) or not isinstance(document.get("data"), list):
                raise ValueError("HydAPI current version inventory lacks a data array")
            entries = document["data"]
            if type(document.get("itemCount")) is not int or document["itemCount"] != len(entries):
                raise ValueError("HydAPI current version inventory itemCount contradicts its data array")
        except (ValueError, UnicodeDecodeError) as error:
            reasons.append(str(error))
        else:
            seen: set[int] = set()
            for index, entry in enumerate(entries):
                try:
                    item = _SeriesMetadata.model_validate(entry)
                    if item.station != station or item.parameter != int(coordinates.parameter):
                        raise ValueError("returned station or parameter contradicts requested coordinates")
                    if item.version in seen:
                        raise ValueError("duplicate published version identity")
                    seen.add(item.version)
                    resolutions = [r for r in item.resolutions if r.resolution == int(coordinates.resolution_time)]
                    if len(resolutions) > 1:
                        raise ValueError("duplicate resolution for published version")
                    if not resolutions:
                        continue
                    if item.unit == "":
                        raise ValueError('published source unit is the empty string ""')
                    definition = describe_series(
                        station,
                        item.parameter,
                        item.version,
                        int(coordinates.resolution_time),
                        resolutions[0].method,
                        item.unit,
                    )
                    definitions[definition.series_id] = definition
                except (ValidationError, ValueError) as error:
                    # External metadata errors are scoped source limitations, not internal-contract failures.
                    detail = "malformed required metadata fields" if isinstance(error, ValidationError) else str(error)
                    reasons.append(f"HydAPI current version inventory member {index}: {detail}")
    reason = "; ".join(reasons) if reasons else None
    inventory = InventorySnapshot(
        snapshot_id=stable_id("no_nve", "current-version-inventory", capture, scope.model_dump_json()),
        scope=scope,
        members=tuple(definitions),
        member_facts=tuple((key, tuple(f.facts_id for f in item.facts)) for key, item in definitions.items()),
        completeness=InventoryCompleteness.INCOMPLETE if reasons else InventoryCompleteness.COMPLETE,
        access="HydAPI Series currently published versions for station, parameter and resolution",
        origin="response",
        acquired_at=acquired,
        window=window,
        evidence=(_EVIDENCE,),
        reason=reason,
    )
    outcomes = ()
    issues = ()
    if reason or not definitions:
        message = reason or "HydAPI current metadata publishes no version for the requested access coordinate"
        outcomes = (
            RetrievalOutcome(
                outcome_id=stable_id(capture, message),
                series_id=None,
                station_id=station,
                product_id=product,
                window=window,
                status=OutcomeStatus.UNRESOLVED if reason else OutcomeStatus.NO_MATCH,
                reason=message,
                retrieved_at=acquired,
            ),
        )
        if reason:
            issues = (
                Issue(
                    severity="warning",
                    code="source.inventory_unresolved",
                    message=message,
                    provider_id=ProviderId("no_nve"),
                    details={"station_id": station, "product_id": product, "url": _URL},
                ),
            )
    return SourceAcquisition(
        value=(),
        issues=issues,
        series=tuple(definitions.values()),
        inventories=(inventory,),
        outcomes=outcomes,
        calls=(origin,),
    )
