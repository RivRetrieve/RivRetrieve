"""Acquire exact USGS Water Data pages and transaction-bounded inventory evidence.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit  # noqa: TID251 - URL validation only; no network access
from uuid import uuid4

from rivretrieve._internal.authentication import CredentialExchangeError
from rivretrieve._internal.engine import (
    FetchWindow,
    Payload,
    ProviderConfig,
    RenderedWindow,
    SourceAcquisition,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.usgs_nwis.config import UsgsNwisSourceCoordinates
from rivretrieve._internal.providers.usgs_nwis.parse import parse, parse_time_label
from rivretrieve._internal.source_acquisition import FailedSourceRequest, attempt_request
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    RequestedSelector,
    RestrictionKind,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
)
from rivretrieve._internal.transport import (
    HttpMethod,
    RedirectPolicy,
    Transport,
    TransportFailure,
    TransportRequest,
    TransportResponse,
)

_BASE_URL = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/"


class _RepeatedObservationError(ValueError):
    """A source cursor chain repeated concrete series/time keys."""

    def __init__(self, published_ids: set[str]) -> None:
        self.published_ids = published_ids
        super().__init__("USGS cursor chain repeats a logical series/time observation")


def fetch(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    fetch_window: FetchWindow,
    config: ProviderConfig,
    transport: Transport,
    *,
    monitoring_locations: Mapping[str, str],
    scope: SeriesScope | None = None,
    known_series: tuple[SourceSeries, ...] = (),
) -> SourceAcquisition:
    payloads = []
    definitions: dict[str, SourceSeries] = {}
    inventories = []
    outcomes = []
    issues = []
    failed_requests = []
    window = SeriesWindow(
        start=datetime.fromisoformat(fetch_window.start.isoformat()),
        end=datetime.fromisoformat(fetch_window.end.isoformat()),
    )
    for station in stations:
        try:
            location = monitoring_locations[station]
        except KeyError as error:
            raise FatalContractError(f"No acquired USGS monitoring location identity for {station}") from error
        for product in products:
            if not rendered_windows.get(product):
                raise FatalContractError("USGS acquisition requires at least one rendered request window")
            coordinates = replace(_coordinates(product, config), monitoring_location_id=location)
            local_scope = (scope or SeriesScope(provider_ids=("usgs_nwis",))).model_copy(
                update={"station_ids": (station,), "product_ids": (str(product),)}
            )
            known = tuple(item for item in known_series if local_scope.matches(item))
            members = {item.series_id: item for item in known}
            selectors: tuple[str | None, ...] = (None,)
            if local_scope.restriction is RestrictionKind.EXPLICIT:
                selectors = tuple(
                    sorted(
                        {item.identity.published_id for item in known if item.identity.published_id is not None}
                        | set(local_scope.variants)
                    )
                )
            transaction_errors = []
            retrieved_at = None
            if not selectors:
                transaction_errors.append("No published USGS series ID is established for the requested selector")
            for selector in selectors:
                request_scope = (
                    local_scope
                    if selector is None
                    else local_scope.model_copy(
                        update={"restriction": RestrictionKind.EXPLICIT, "variants": (selector,), "series_ids": ()}
                    )
                )
                selected = tuple(item for item in known if selector is None or item.identity.published_id == selector)
                target_members = {item.series_id: item for item in selected}
                observed_ids: set[str] = set()
                target_errors = []
                unsupported_ids: set[str] = set()
                # A logical source observation is series + published time, not feature id.
                seen_observations: set[tuple[str, datetime]] = set()
                for rendered in rendered_windows[product]:
                    initial = _request(coordinates, rendered, selector)
                    request: TransportRequest | None = initial
                    visited: set[tuple[tuple[str, str], ...]] = set()
                    while request is not None:
                        attempted = attempt_request(transport, request)
                        if isinstance(attempted, (TransportFailure, CredentialExchangeError)):
                            error = attempted
                            reason = str(error)
                            target_errors.append(reason)
                            for definition in target_members.values():
                                failed_requests.append(
                                    FailedSourceRequest(uuid4().hex, definition, window, request, error)
                                )
                            # Concrete failures are classified once by the shared driver.
                            # An anonymous broad call still needs a retained diagnostic.
                            if not target_members:
                                issues.append(
                                    _issue(station, product, reason).model_copy(
                                        update={
                                            "details": {
                                                "station_id": station,
                                                "product_id": product,
                                                "series_id": None,
                                                "url": request.url,
                                                "request_parameters": dict(request.params or {}),
                                                "status_code": error.status_code
                                                if isinstance(error, TransportFailure)
                                                else None,
                                                "failure_reason": str(error.reason)
                                                if isinstance(error, TransportFailure)
                                                else "credential_exchange",
                                            }
                                        }
                                    )
                                )
                            break
                        response = attempted
                        retrieved_at = response.retrieved_at
                        payload = _payload(
                            coordinates,
                            station,
                            product,
                            fetch_window,
                            response,
                            request_scope,
                            tuple(target_members.values()),
                        )
                        payloads.append(payload)
                        # Pure decoding is also run by the driver. Here it establishes whether
                        # this complete chain can certify inventory/empty coverage.
                        parsed = parse(payload, config)
                        for definition in parsed.series:
                            if definition.series_id in observed_ids:
                                previous = target_members[definition.series_id]
                                facts = {item.facts_id: item for item in previous.facts}
                                for item in definition.facts:
                                    if item.facts_id in facts and facts[item.facts_id] != item:
                                        raise FatalContractError("USGS physical fact identity changes between pages")
                                    facts[item.facts_id] = item
                                definition = definition.model_copy(update={"facts": tuple(facts.values())})
                            target_members[definition.series_id] = definition
                            observed_ids.add(definition.series_id)
                        if any(
                            item.status in (OutcomeStatus.FAILED, OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNRESOLVED)
                            for item in parsed.outcomes
                        ) or any(item.severity == "error" for item in parsed.issues):
                            target_errors.append("An observation page contains unresolved or unsupported source data")
                        try:
                            document = _document(response.content)
                            _check_duplicates(document, seen_observations, coordinates)
                            request = _next_request(document, initial, visited)
                        except ValueError as error:
                            if isinstance(error, _RepeatedObservationError):
                                unsupported_ids.update(error.published_ids)
                            target_errors.append(str(error))
                            issues.extend(
                                _issue(station, product, str(error), failed_id)
                                for failed_id in target_members or (None,)
                            )
                            break
                    if target_errors:
                        break
                if selector is not None and not target_members and not target_errors:
                    target_errors.append("An empty selected response does not establish the requested source identity")
                members.update(target_members)
                if target_errors:
                    reason = "; ".join(dict.fromkeys(target_errors))
                    transaction_errors.append(reason)
                    # Page successes never certify a failed multi-page/multi-chunk transaction.
                    for definition in target_members.values():
                        outcomes.append(
                            _outcome(
                                definition,
                                station,
                                product,
                                window,
                                OutcomeStatus.UNSUPPORTED
                                if definition.identity.published_id in unsupported_ids
                                else OutcomeStatus.UNRESOLVED,
                                reason,
                                retrieved_at,
                            )
                        )
                    if not target_members:
                        outcomes.append(
                            _outcome(
                                None, station, product, window, OutcomeStatus.UNRESOLVED, reason, retrieved_at
                            ).model_copy(
                                update={
                                    "requested_selector": RequestedSelector(kind="variant", value=selector)
                                    if selector
                                    else None
                                }
                            )
                        )
                else:
                    for definition in target_members.values():
                        if definition.series_id not in observed_ids:
                            outcomes.append(
                                _outcome(definition, station, product, window, OutcomeStatus.EMPTY, None, retrieved_at)
                            )
            if not members and not transaction_errors:
                outcomes.append(
                    _outcome(
                        None,
                        station,
                        product,
                        window,
                        OutcomeStatus.NO_MATCH,
                        "Exhausted observation response contains no matching series in this finite window",
                        retrieved_at,
                    )
                )
            definitions.update(members)
            reason = "; ".join(dict.fromkeys(transaction_errors)) or None
            if not selectors:
                outcomes.append(
                    _outcome(None, station, product, window, OutcomeStatus.UNRESOLVED, reason, retrieved_at)
                )
            inventories.append(
                InventorySnapshot(
                    snapshot_id=uuid4().hex,
                    scope=local_scope,
                    members=tuple(members),
                    member_facts=tuple((key, tuple(f.facts_id for f in item.facts)) for key, item in members.items()),
                    completeness=InventoryCompleteness.INCOMPLETE if reason else InventoryCompleteness.COMPLETE,
                    access=f"USGS Water Data v1 {coordinates.endpoint} exhausted observation cursor chains",
                    origin="response",
                    acquired_at=retrieved_at,
                    window=window,
                    evidence=(
                        "Exact publisher pages; finite requested observation scope, not historical availability",
                    ),
                    reason=reason,
                )
            )
    return SourceAcquisition(
        value=tuple(payloads),
        issues=tuple(issues),
        series=tuple(definitions.values()),
        inventories=tuple(inventories),
        outcomes=tuple(outcomes),
        failed_requests=tuple(failed_requests),
    )


def _coordinates(product: ProductId, config: ProviderConfig) -> UsgsNwisSourceCoordinates:
    try:
        coordinates = config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"usgs_nwis product is absent from provider config: {product}") from error
    if not isinstance(coordinates, UsgsNwisSourceCoordinates):
        raise FatalContractError(f"usgs_nwis product has invalid source coordinates: {product}")
    return coordinates


def _request(coordinates: UsgsNwisSourceCoordinates, window: RenderedWindow, selector: str | None) -> TransportRequest:
    if window.stop is None:
        raise FatalContractError("USGS requests require closed rendered bounds")
    params: dict[str, str | int | float | None] = {
        "f": "json",
        "monitoring_location_id": coordinates.monitoring_location_id,
        "parameter_code": coordinates.parameter_code,
        "datetime": f"{window.start}/{window.stop}",
        "limit": 10000,
    }
    if coordinates.statistic_code is not None:
        params["statistic_id"] = coordinates.statistic_code
    if selector is not None:
        params["time_series_id"] = selector
    return TransportRequest(
        method=HttpMethod.GET,
        url=f"{_BASE_URL}{coordinates.endpoint}/items",
        params=params,
        headers={"Accept": "application/json"},
        redirect_policy=RedirectPolicy.REFUSE,
    )


def _document(content: bytes) -> dict:
    try:
        document = json.loads(content)
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("USGS observation response is not valid JSON") from error
    if (
        not isinstance(document, dict)
        or document.get("type") != "FeatureCollection"
        or not isinstance(document.get("features"), list)
    ):
        raise ValueError("USGS observation response must be a FeatureCollection")
    return document


def _check_duplicates(document: dict, seen: set[tuple[str, datetime]], coordinates: UsgsNwisSourceCoordinates) -> None:
    repeated: set[str] = set()
    for feature in document["features"]:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(properties, dict):
            raise ValueError("USGS feature has malformed properties")
        identifier = properties.get("time_series_id")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("USGS observation lacks series/time identity")
        stamp, zone = parse_time_label(properties.get("time"), coordinates.endpoint == "daily")
        identity_time = stamp if zone == "unknown" else datetime.fromisoformat(f"{stamp.isoformat()}{zone}")
        key = (identifier, identity_time)
        if key in seen:
            repeated.add(key[0])
        seen.add(key)
    if repeated:
        raise _RepeatedObservationError(repeated)


def _next_request(
    document: dict, initial: TransportRequest, visited: set[tuple[tuple[str, str], ...]]
) -> TransportRequest | None:
    links = document.get("links")
    if not isinstance(links, list) or any(
        not isinstance(link, dict) or not isinstance(link.get("rel"), str) for link in links
    ):
        raise ValueError("USGS observation page has malformed links")
    following = [link for link in links if link["rel"] == "next"]
    if not following:
        return None
    if len(following) != 1 or not isinstance(following[0].get("href"), str):
        raise ValueError("USGS observation page requires one valid next link")
    href = following[0]["href"]
    parsed = urlsplit(href)
    expected = urlsplit(initial.url)
    if (parsed.scheme, parsed.netloc, parsed.path) != (
        expected.scheme,
        expected.netloc,
        expected.path,
    ) or parsed.fragment:
        raise ValueError("USGS next link changes publisher origin or v1 collection")
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    params = dict(pairs)
    base = {key: str(value) for key, value in (initial.params or {}).items()}
    if len(pairs) != len(params) or set(params) != set(base) | {"cursor"} or not params.get("cursor"):
        raise ValueError("USGS next link has malformed cursor or query parameters")
    if any(params.get(key) != value for key, value in base.items()):
        raise ValueError("USGS next link changes request filters")
    identity = tuple(sorted(params.items()))
    if identity in visited:
        raise ValueError("USGS pagination cursor cycle")
    visited.add(identity)
    return TransportRequest(
        method=HttpMethod.GET, url=href, headers={"Accept": "application/json"}, redirect_policy=RedirectPolicy.REFUSE
    )


def _outcome(definition, station, product, window, status, reason, retrieved_at) -> RetrievalOutcome:
    return RetrievalOutcome(
        outcome_id=uuid4().hex,
        series_id=definition.series_id if definition else None,
        station_id=station,
        product_id=product,
        window=window,
        status=status,
        facts_ids=tuple(f.facts_id for f in definition.facts) if definition else (),
        reason=reason,
        retrieved_at=retrieved_at,
    )


def _issue(station: str, product: ProductId, reason: str, series_id: str | None = None) -> Issue:
    return Issue(
        severity="error",
        code="source.acquisition_incomplete",
        message=reason,
        provider_id=ProviderId("usgs_nwis"),
        details={"station_id": station, "product_id": product, "series_id": series_id},
    )


def _payload(coordinates, station, product, fetch_window, response: TransportResponse, scope, known) -> Payload:
    return Payload(
        source_coordinates=SourceCoordinates(coordinates),
        station_products=((station, product),),
        fetch_window=fetch_window,
        content=response.content,
        origin=SourceCallOrigin(
            url=response.url,
            request_parameters=response.request_parameters,
            status_code=response.status_code,
            retrieved_at=response.retrieved_at,
            content_type=response.content_type if response.content_type is not None else UnknownOriginFact(),
            source_path=UnknownOriginFact(),
            query=UnknownOriginFact(),
        ),
        prerequisite_calls=response.prerequisite_calls,
        scope=scope,
        known_series=known,
    )
