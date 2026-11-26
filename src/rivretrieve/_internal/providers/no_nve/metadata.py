"""Acquire the currently published HydAPI version inventory for one access coordinate."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rivretrieve._internal.authentication import CredentialExchangeError
from rivretrieve._internal.engine import ProviderConfig, SourceAcquisition, SourceCallOrigin, UnknownOriginFact
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.no_nve.config import NoNveSourceCoordinates
from rivretrieve._internal.providers.no_nve.series import describe_series
from rivretrieve._internal.request_planning import (
    ConsumerNeed,
    LookupFailureOutcome,
    ResolvedLookup,
)
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    RestrictionKind,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
    admission,
    stable_id,
)
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportFailure,
    TransportRequest,
    TransportResponse,
)

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


def _evaluate_series_consumer(
    station: str,
    product: str,
    coordinates: NoNveSourceCoordinates,
    window: SeriesWindow,
    envelope_reasons: Sequence[str],
    entries: Sequence[tuple[int, _SeriesMetadata]],
    capture: str,
    acquired: datetime | None,
    acq_id: str,
) -> tuple[dict[str, SourceSeries], InventorySnapshot, tuple[RetrievalOutcome, ...], tuple[Issue, ...]]:
    scope = SeriesScope(provider_ids=("no_nve",), station_ids=(station,), product_ids=(product,))
    reasons = list(envelope_reasons)
    definitions: dict[str, SourceSeries] = {}
    target_resolution = int(coordinates.resolution_time)
    target_param = int(coordinates.parameter)
    seen: set[int] = set()
    for index, item in entries:
        try:
            if item.station != station or item.parameter != target_param:
                raise ValueError("returned station or parameter contradicts requested coordinates")
            if item.version in seen:
                raise ValueError("duplicate published version identity")
            seen.add(item.version)
            resolutions = [r for r in item.resolutions if r.resolution == target_resolution]
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
                target_resolution,
                resolutions[0].method,
                item.unit,
            )
            definitions[definition.series_id] = definition
        except ValueError as error:
            reasons.append(f"HydAPI current version inventory member {index}: {error}")
    reason = "; ".join(reasons) if reasons else None
    inventory = InventorySnapshot(
        snapshot_id=stable_id(
            "no_nve", "current-version-inventory", capture, scope.model_dump_json(), "acquisition", acq_id
        ),
        scope=scope,
        members=tuple(definitions),
        member_facts=tuple((key, tuple(f.facts_id for f in item.facts)) for key, item in definitions.items()),
        completeness=InventoryCompleteness.INCOMPLETE if reason else InventoryCompleteness.COMPLETE,
        access="HydAPI Series currently published versions for station, parameter and resolution",
        origin="response",
        acquired_at=acquired,
        window=window,
        evidence=(_EVIDENCE, f"source-call:{acq_id}"),
        reason=reason,
    )
    outcomes: tuple[RetrievalOutcome, ...] = ()
    issues: tuple[Issue, ...] = ()
    if reason or not definitions:
        message = reason or "HydAPI current metadata publishes no version for the requested access coordinate"
        outcomes = (
            RetrievalOutcome(
                outcome_id=stable_id(capture, station, product, message, "acquisition", acq_id),
                series_id=None,
                station_id=station,
                product_id=product,
                window=window,
                status=OutcomeStatus.UNRESOLVED if reason else OutcomeStatus.NO_MATCH,
                reason=message,
                retrieved_at=acquired,
                calls=(acq_id,),
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
    return definitions, inventory, outcomes, issues


def _parse_series_entries(content: bytes) -> tuple[list[tuple[int, _SeriesMetadata]], list[str]]:
    reasons: list[str] = []
    parsed_entries: list[tuple[int, _SeriesMetadata]] = []
    try:
        document = json.loads(content)
        if not isinstance(document, dict) or not isinstance(document.get("data"), list):
            raise ValueError("HydAPI current version inventory lacks a data array")
        entries = document["data"]
        if type(document.get("itemCount")) is not int or document["itemCount"] != len(entries):
            raise ValueError("HydAPI current version inventory itemCount contradicts its data array")
    except (ValueError, UnicodeDecodeError) as error:
        reasons.append(str(error))
    else:
        for index, entry in enumerate(entries):
            try:
                parsed_entries.append((index, _SeriesMetadata.model_validate(entry)))
            except ValidationError:
                # Preserve exact per-member validation failure surface.
                reasons.append(f"HydAPI current version inventory member {index}: malformed required metadata fields")
    return parsed_entries, reasons


def resolve_series_lookup(
    response: TransportResponse,
    consumers: tuple[ConsumerNeed, ...],
    acq_id: str,
    config: ProviderConfig,
) -> ResolvedLookup:
    """Decode one deduplicated GET /Series response for all sharing consumers."""
    acquired = response.retrieved_at
    capture = stable_id(hashlib.sha256(response.content).hexdigest(), acquired.isoformat())
    if response.status_code != 200:
        envelope_reasons: list[str] = [f"HydAPI current version inventory returned HTTP {response.status_code}"]
        parsed_entries: list[tuple[int, _SeriesMetadata]] = []
    else:
        parsed_entries, envelope_reasons = _parse_series_entries(response.content)

    all_definitions: dict[str, SourceSeries] = {}
    all_inventories: list[InventorySnapshot] = []
    all_outcomes: list[RetrievalOutcome] = []
    all_issues: list[Issue] = []
    versions_by_pair: dict[tuple[str, ProductId], tuple[tuple[int, ...], tuple[SourceSeries, ...], bool]] = {}
    for need in consumers:
        product_cfg = config.products.get(need.product)
        coordinates = product_cfg.coordinates.value if product_cfg is not None else None
        if not isinstance(coordinates, NoNveSourceCoordinates):
            raise FatalContractError(f"no_nve product has invalid source coordinates: {need.product}")
        requested_window = SeriesWindow(
            start=datetime.fromisoformat(need.fetch_window.start.isoformat()),
            end=datetime.fromisoformat(need.fetch_window.end.isoformat()),
        )
        current, snapshot, base_outcomes, base_issues = _evaluate_series_consumer(
            need.station,
            str(need.product),
            coordinates,
            requested_window,
            envelope_reasons,
            parsed_entries,
            capture,
            acquired,
            acq_id,
        )
        matching_known = tuple(
            item
            for item in need.known_series
            if item.station_id == need.station and item.product_id == need.product and need.scope.matches(item)
        )
        historical = {item.series_id: item for item in matching_known if item.series_id not in current}
        if historical and snapshot.completeness is InventoryCompleteness.COMPLETE:
            reason = (
                "Acquired catalogue versions are absent from current HydAPI metadata; "
                "historical inventory remains unresolved"
            )
            snapshot = snapshot.model_copy(
                update={
                    "completeness": InventoryCompleteness.INCOMPLETE,
                    "reason": reason,
                    "snapshot_id": stable_id(snapshot.snapshot_id, reason, *sorted(historical)),
                }
            )
            all_issues.append(
                Issue(
                    severity="warning",
                    code="source.inventory_unresolved",
                    message=reason,
                    details={"station_id": need.station, "product_id": str(need.product)},
                    provider_id=ProviderId("no_nve"),
                )
            )
        all_inventories.append(snapshot)
        for key, s_def in current.items():
            all_definitions[key] = s_def
        all_outcomes.extend(base_outcomes)
        all_issues.extend(base_issues)

        candidates = {**historical, **current}
        matching = tuple(item for item in candidates.values() if need.scope.matches(item))
        versions = {
            int(item.identity.published_id)
            for item in matching
            if item.identity.namespace == "HydAPI.version"
            and item.identity.published_id is not None
            and item.identity.published_id.isdecimal()
        }
        if need.scope.restriction is RestrictionKind.EXPLICIT:
            versions.update(int(value) for value in need.scope.variants if value.isascii() and value.isdecimal())
        if not versions and snapshot.completeness is InventoryCompleteness.COMPLETE and not base_outcomes:
            unresolved = any(
                admission(fact).status != "supported"
                or any(getattr(fact, predicate.field).value is None for predicate in need.scope.predicates)
                for item in current.values()
                for fact in item.facts
            )
            reason = (
                "Current HydAPI metadata cannot settle physical matching or admission for every version"
                if unresolved
                else "Current HydAPI inventory has no version matching the requested physical facts"
            )
            if unresolved:
                all_issues.append(
                    Issue(
                        severity="warning",
                        code="source.inventory_unresolved",
                        message=reason,
                        provider_id=ProviderId("no_nve"),
                        details={"station_id": need.station, "product_id": str(need.product)},
                    )
                )
            all_outcomes.append(
                RetrievalOutcome(
                    outcome_id=stable_id(snapshot.snapshot_id, reason, need.scope.model_dump_json()),
                    series_id=None,
                    station_id=need.station,
                    product_id=str(need.product),
                    window=requested_window,
                    status=OutcomeStatus.UNRESOLVED if unresolved else OutcomeStatus.NO_MATCH,
                    reason=reason,
                    retrieved_at=snapshot.acquired_at,
                    calls=(acq_id,),
                )
            )
        versions_by_pair[(need.station, need.product)] = (
            tuple(sorted(versions)),
            matching,
            snapshot.completeness is InventoryCompleteness.COMPLETE,
        )
    return ResolvedLookup(
        value=versions_by_pair,
        acquisition_id=acq_id,
        series=tuple(all_definitions.values()),
        inventories=tuple(all_inventories),
        outcomes=tuple(all_outcomes),
        issues=tuple(all_issues),
    )


def fail_series_lookup(
    failure: TransportFailure | CredentialExchangeError,
    request: TransportRequest,
    consumers: tuple[ConsumerNeed, ...],
    call_id: str,
    acq_id: str,
) -> LookupFailureOutcome:
    """Translate a failed GET /Series call into per-consumer unresolved evidence."""
    del call_id
    unknown = UnknownOriginFact()
    status = failure.status_code
    origin = SourceCallOrigin(
        _URL,
        request.params or {},
        status if status is not None else unknown,
        unknown,
        unknown,
        unknown,
        unknown,
        acquisition_id=acq_id,
    )
    capture = uuid4().hex
    message = (
        f"HydAPI current version inventory request failed: {failure.reason.value}"
        + (f" after {failure.attempts} attempts" if isinstance(failure, TransportFailure) else "")
        + (f" (HTTP {status})" if status is not None else "")
    )
    inventories: list[InventorySnapshot] = []
    outcomes: list[RetrievalOutcome] = []
    issues: list[Issue] = []
    for need in consumers:
        product_str = str(need.product)
        inv_scope = SeriesScope(provider_ids=("no_nve",), station_ids=(need.station,), product_ids=(product_str,))
        window = SeriesWindow(
            start=datetime.fromisoformat(need.fetch_window.start.isoformat()),
            end=datetime.fromisoformat(need.fetch_window.end.isoformat()),
        )
        inventories.append(
            InventorySnapshot(
                snapshot_id=stable_id(
                    "no_nve", "current-version-inventory", capture, inv_scope.model_dump_json(), "acquisition", acq_id
                ),
                scope=inv_scope,
                members=(),
                member_facts=(),
                completeness=InventoryCompleteness.INCOMPLETE,
                access="HydAPI Series currently published versions for station, parameter and resolution",
                origin="response",
                acquired_at=None,
                window=window,
                evidence=(_EVIDENCE, f"source-call:{acq_id}"),
                reason=message,
            )
        )
        outcomes.append(
            RetrievalOutcome(
                outcome_id=stable_id(capture, need.station, product_str, message, "acquisition", acq_id),
                series_id=None,
                station_id=need.station,
                product_id=product_str,
                window=window,
                status=OutcomeStatus.UNRESOLVED,
                reason=message,
                retrieved_at=None,
                calls=(acq_id,),
            )
        )
        issues.append(
            Issue(
                severity="warning",
                code="source.inventory_unresolved",
                message=message,
                provider_id=ProviderId("no_nve"),
                details={"station_id": need.station, "product_id": product_str, "url": _URL},
            )
        )
    return LookupFailureOutcome(
        inventories=tuple(inventories),
        outcomes=tuple(outcomes),
        issues=tuple(issues),
        calls=(origin,),
    )


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
        inventory = InventorySnapshot(
            snapshot_id=stable_id("no_nve", "current-version-inventory", capture, scope.model_dump_json()),
            scope=scope,
            members=(),
            member_facts=(),
            completeness=InventoryCompleteness.INCOMPLETE,
            access="HydAPI Series currently published versions for station, parameter and resolution",
            origin="response",
            acquired_at=acquired,
            window=window,
            evidence=(_EVIDENCE,),
            reason=reasons[0],
        )
        outcomes = (
            RetrievalOutcome(
                outcome_id=stable_id(capture, reasons[0]),
                series_id=None,
                station_id=station,
                product_id=product,
                window=window,
                status=OutcomeStatus.UNRESOLVED,
                reason=reasons[0],
                retrieved_at=acquired,
            ),
        )
        issues = (
            Issue(
                severity="warning",
                code="source.inventory_unresolved",
                message=reasons[0],
                provider_id=ProviderId("no_nve"),
                details={"station_id": station, "product_id": product, "url": _URL},
            ),
        )
        return SourceAcquisition(
            value=(),
            issues=issues,
            series=(),
            inventories=(inventory,),
            outcomes=outcomes,
            calls=(origin,),
        )
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
    if response.status_code != 200:
        parsed_entries: list[tuple[int, _SeriesMetadata]] = []
        envelope_reasons: list[str] = [f"HydAPI current version inventory returned HTTP {response.status_code}"]
    else:
        parsed_entries, envelope_reasons = _parse_series_entries(response.content)
    definitions, inventory, outcomes, issues = _evaluate_series_consumer(
        station,
        product,
        coordinates,
        window,
        envelope_reasons,
        parsed_entries,
        capture,
        acquired,
        capture,
    )
    return SourceAcquisition(
        value=(),
        issues=issues,
        series=tuple(definitions.values()),
        inventories=(inventory,),
        outcomes=outcomes,
        calls=(origin,),
    )
