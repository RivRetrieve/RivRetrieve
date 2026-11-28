"""Acquire exact USGS Water Data pages and transaction-bounded inventory evidence.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit  # noqa: TID251 - URL validation only; no network access
from uuid import uuid4

from rivretrieve._internal.engine import (
    FetchWindow,
    InterpretedPayload,
    Payload,
    ProviderConfig,
    RenderedWindow,
    SourceAcquisition,
    SourceCallOrigin,
    SourceCoordinates,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.page_acquisition import PageStep, acquire_pages
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.usgs_nwis.config import UsgsNwisSourceCoordinates
from rivretrieve._internal.providers.usgs_nwis.parse import interpret_page
from rivretrieve._internal.source_acquisition import FailedSourceRequest, SourceRequestTarget
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
from rivretrieve._internal.time_axis import TimeAxis
from rivretrieve._internal.transport import (
    HttpMethod,
    RedirectPolicy,
    Transport,
    TransportRequest,
    TransportResponse,
)

_BASE_URL = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/"
_PAGE_LIMIT = 50000


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
    payloads: list[Payload] = []
    interpretations: list[InterpretedPayload] = []
    definitions: dict[str, SourceSeries] = {}
    inventories: list[InventorySnapshot] = []
    outcomes: list[RetrievalOutcome] = []
    issues: list[Issue] = []
    failed_requests: list[FailedSourceRequest] = []
    for station in stations:
        try:
            location = monitoring_locations[station]
        except KeyError as error:
            raise FatalContractError(f"No acquired USGS monitoring location identity for {station}") from error
        for product in products:
            if not rendered_windows.get(product):
                raise FatalContractError("USGS acquisition requires at least one rendered request window")
            acquisition_axis = (
                TimeAxis.UTC if _coordinates(product, config).endpoint == "continuous" else TimeAxis.NATIVE
            )
            for rendered in rendered_windows[product]:
                if rendered.bounds is None and len(rendered_windows[product]) != 1:
                    raise FatalContractError("USGS capped spans require engine-established bounds")
                acquisition_window = rendered.bounds or fetch_window
                window = SeriesWindow(
                    start=datetime.fromisoformat(acquisition_window.start.isoformat()),
                    end=datetime.fromisoformat(acquisition_window.end.isoformat()),
                    axis=acquisition_axis,
                )
                coordinates = replace(_coordinates(product, config), monitoring_location_id=location)
                local_scope = (scope or SeriesScope(provider_ids=("usgs_nwis",))).model_copy(
                    update={"station_ids": (station,), "product_ids": (str(product),)}
                )
                known = tuple(
                    item
                    for item in {**{s.series_id: s for s in known_series}, **definitions}.values()
                    if local_scope.matches(item)
                )
                members = {item.series_id: item for item in known}
                selectors: tuple[str | None, ...] = (None,)
                if local_scope.restriction is RestrictionKind.EXPLICIT:
                    selectors = tuple(
                        sorted(
                            {item.identity.published_id for item in known if item.identity.published_id is not None}
                            | set(local_scope.variants)
                        )
                    )
                transaction_errors: list[str] = []
                transaction_calls: list[str] = []
                retrieved_at: datetime | None = None
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
                    selected = tuple(
                        item for item in known if selector is None or item.identity.published_id == selector
                    )
                    target_members = {item.series_id: item for item in selected}
                    observed_ids: set[str] = set()
                    target_errors: list[str] = []
                    source_failures: dict[str, RetrievalOutcome] = {}
                    unsupported_ids: set[str] = set()
                    # A logical source observation is series + published time, not feature id.
                    seen_observations: set[tuple[str, datetime]] = set()
                    initial = _request(coordinates, rendered, selector)
                    identity_scope = request_scope.model_copy(update={"predicates": ()})

                    def _build_payload(
                        response: TransportResponse,
                        *,
                        coordinates=coordinates,
                        station=station,
                        product=product,
                        acquisition_window=acquisition_window,
                        request_scope=request_scope,
                        target_members=target_members,
                    ) -> Payload:
                        return _payload(
                            coordinates,
                            station,
                            product,
                            acquisition_window,
                            response,
                            request_scope,
                            tuple(target_members.values()),
                        )

                    def _step_page(
                        payload: Payload,
                        *,
                        station=station,
                        product=product,
                        selector=selector,
                        initial=initial,
                        selected=selected,
                        target_members=target_members,
                        observed_ids=observed_ids,
                        target_errors=target_errors,
                        source_failures=source_failures,
                        unsupported_ids=unsupported_ids,
                        seen_observations=seen_observations,
                        identity_scope=identity_scope,
                    ) -> PageStep:
                        interpreted = interpret_page(payload, config)
                        parsed = interpreted.parsed
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
                        requested_ids = {item.series_id for item in parsed.series if identity_scope.matches(item)}
                        requested_ids.update(item.series_id for item in selected)
                        for outcome in parsed.outcomes:
                            if outcome.status not in (
                                OutcomeStatus.FAILED,
                                OutcomeStatus.UNSUPPORTED,
                                OutcomeStatus.UNRESOLVED,
                            ):
                                continue
                            if outcome.series_id is None or (
                                selector is not None and outcome.series_id not in requested_ids
                            ):
                                target_errors.append(
                                    "An observation page contains an unattributable or out-of-scope source failure"
                                )
                            else:
                                # An identified malformed series cannot invalidate a
                                # fully acquired, independently valid sibling.
                                source_failures[outcome.outcome_id] = outcome.model_copy(
                                    update={
                                        "outcome_id": uuid4().hex,
                                        "status": OutcomeStatus.UNRESOLVED,
                                        "reason": "Incomplete source-series parsing: "
                                        + (outcome.reason or "unsupported source data"),
                                    }
                                )
                        if interpreted.document_error is not None:
                            return PageStep(
                                parsed=parsed,
                                stop_reason=interpreted.document_error,
                                issues=tuple(
                                    _issue(station, product, interpreted.document_error, failed_id)
                                    for failed_id in target_members or (None,)
                                ),
                            )
                        repeated = {key[0] for key in interpreted.observation_keys if key in seen_observations}
                        seen_observations.update(interpreted.observation_keys)
                        if repeated:
                            unsupported_ids.update(repeated)
                            reason = "USGS cursor chain repeats a logical series/time observation"
                            return PageStep(
                                parsed=parsed,
                                stop_reason=reason,
                                issues=tuple(
                                    _issue(station, product, reason, failed_id)
                                    for failed_id in target_members or (None,)
                                ),
                            )
                        if interpreted.links_error is not None:
                            return PageStep(
                                parsed=parsed,
                                stop_reason=interpreted.links_error,
                                issues=tuple(
                                    _issue(station, product, interpreted.links_error, failed_id)
                                    for failed_id in target_members or (None,)
                                ),
                            )
                        if interpreted.next_href is None:
                            return PageStep(parsed=parsed)
                        try:
                            next_request, cursor_key = _next_request_from_href(interpreted.next_href, initial)
                        except ValueError as error:
                            reason = str(error)
                            return PageStep(
                                parsed=parsed,
                                stop_reason=reason,
                                issues=tuple(
                                    _issue(station, product, reason, failed_id)
                                    for failed_id in target_members or (None,)
                                ),
                            )
                        return PageStep(parsed=parsed, next_request=next_request, cursor_key=cursor_key)

                    page_acq = acquire_pages(
                        initial,
                        transport=transport,
                        window=window,
                        build_payload=_build_payload,
                        interpret_page=_step_page,
                        failure_targets=lambda station=station, product=product, target_members=target_members: (
                            tuple(target_members.values()) or (SourceRequestTarget(station, str(product)),)
                        ),
                        on_cycle=lambda station=station, product=product, target_members=target_members: (
                            "USGS pagination cursor cycle",
                            tuple(
                                _issue(station, product, "USGS pagination cursor cycle", failed_id)
                                for failed_id in target_members or (None,)
                            ),
                        ),
                    )
                    payloads.extend(page_acq.payloads)
                    interpretations.extend(page_acq.interpretations)
                    failed_requests.extend(page_acq.failed_requests)
                    issues.extend(page_acq.issues)
                    if page_acq.retrieved_at is not None:
                        retrieved_at = page_acq.retrieved_at
                    if page_acq.stop_reason is not None:
                        target_errors.append(page_acq.stop_reason)
                    target_calls = page_acq.calls

                    if selector is not None and not target_members and not target_errors:
                        target_errors.append(
                            "An empty selected response does not establish the requested source identity"
                        )
                    transaction_calls.extend(target_calls)
                    members.update(target_members)
                    if source_failures:
                        outcomes.extend(source_failures.values())
                        transaction_errors.extend(
                            dict.fromkeys(
                                item.reason or "Identified source series is unsupported"
                                for item in source_failures.values()
                            )
                        )
                    if target_errors:
                        reason = "; ".join(dict.fromkeys(target_errors))
                        transaction_errors.append(reason)
                        # Page successes never certify a failed cursor chain.
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
                                    calls=target_calls,
                                )
                            )
                        if not target_members:
                            outcomes.append(
                                _outcome(
                                    None,
                                    station,
                                    product,
                                    window,
                                    OutcomeStatus.UNRESOLVED,
                                    reason,
                                    retrieved_at,
                                    calls=target_calls,
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
                                    _outcome(
                                        definition,
                                        station,
                                        product,
                                        window,
                                        OutcomeStatus.EMPTY,
                                        None,
                                        retrieved_at,
                                        calls=target_calls,
                                    )
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
                            calls=tuple(transaction_calls),
                        )
                    )
                for identifier, member in members.items():
                    previous = definitions.get(identifier)
                    if previous is not None:
                        facts = {fact.facts_id: fact for fact in previous.facts}
                        for fact in member.facts:
                            if fact.facts_id in facts and facts[fact.facts_id] != fact:
                                raise FatalContractError("USGS physical fact identity changes between spans")
                            facts[fact.facts_id] = fact
                        member = member.model_copy(update={"facts": tuple(facts.values())})
                    definitions[identifier] = member
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
                        member_facts=tuple(
                            (key, tuple(f.facts_id for f in item.facts)) for key, item in members.items()
                        ),
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
        interpretations=tuple(interpretations),
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
        "limit": _PAGE_LIMIT,
        "skipGeometry": "true",
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


def _next_request_from_href(
    href: str, initial: TransportRequest
) -> tuple[TransportRequest, tuple[tuple[str, str], ...]]:
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
    return (
        TransportRequest(
            method=HttpMethod.GET,
            url=href,
            headers={"Accept": "application/json"},
            redirect_policy=RedirectPolicy.REFUSE,
        ),
        identity,
    )


def _outcome(definition, station, product, window, status, reason, retrieved_at, *, calls=()) -> RetrievalOutcome:
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
        calls=tuple(dict.fromkeys(calls)),
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
        origin=SourceCallOrigin.from_response(response),
        prerequisite_calls=response.prerequisite_calls,
        scope=scope,
        known_series=known,
        attempt_traces=response.attempt_traces,
        acquisition_axis=TimeAxis.UTC if coordinates.endpoint == "continuous" else TimeAxis.NATIVE,
    )
