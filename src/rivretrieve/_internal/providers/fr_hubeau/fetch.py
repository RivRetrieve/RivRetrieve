"""fr_hubeau fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → SourceAcquisition.

Contributed by: Thiago von Däniken
"""

import hashlib
import json
from collections.abc import Hashable, Mapping
from datetime import date, datetime
from uuid import uuid4

from rivretrieve._internal.coverage import RequestedInterval
from rivretrieve._internal.engine import (
    FetchWindow,
    ProviderConfig,
    RenderedWindow,
    SourceAcquisition,
    SourceCoordinates,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.page_acquisition import PageAcquisition
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.fr_hubeau.config import SERIES_MAPPINGS, FrHubeauSourceCoordinates
from rivretrieve._internal.providers.fr_hubeau.parse import (
    interpret_batch_page,
    next_url_from_document,
)
from rivretrieve._internal.request_planning import (
    BatchPageStep,
    BatchPaginationSpec,
    BatchSelector,
    ConsumerNeed,
    LookupResolution,
    ObservationPlan,
    PlannedLookup,
    PlannedObservationRequest,
    UnseenConsumerEvidence,
    execute_planned_acquisition,
)
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
    TimeAxis,
    stable_id,
)
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest

_DAILY_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab"
_TEMPERATURE_URL = "https://hubeau.eaufrance.fr/api/v1/temperature/chronique"
_PAGE_SIZE = 2500
_DAILY_BATCH_LIMIT = 50
_TEMPERATURE_BATCH_LIMIT = 50
_TEMPERATURE_ROWS_PER_STATION_DAY = 48
_TEMPERATURE_SAFE_PAGE_BUDGET = 10_000


def _temperature_batch_limit(window: RenderedWindow) -> int:
    if window.stop is None:
        raise FatalContractError("fr_hubeau product requires a rendered stop")
    start_day = date.fromisoformat(window.start)
    stop_day = date.fromisoformat(window.stop)
    days = max(1, (stop_day - start_day).days + 1)
    return max(
        1,
        min(_TEMPERATURE_BATCH_LIMIT, _TEMPERATURE_SAFE_PAGE_BUDGET // (_TEMPERATURE_ROWS_PER_STATION_DAY * days)),
    )


def _definition_for(need: ConsumerNeed) -> SourceSeries:
    return SERIES_MAPPINGS[need.product].source_series("fr_hubeau", need.station, need.product)


def _step_batch_page(
    payload,
    consumers: tuple[ConsumerNeed, ...],
    config: ProviderConfig,
) -> BatchPageStep:
    interpreted = interpret_batch_page(payload, consumers, config)
    if interpreted.stop_reason is not None:
        issues: list[Issue] = []
        if interpreted.next_url_error is not None and not any(
            outcome.status in (OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNRESOLVED, OutcomeStatus.FAILED)
            for parsed in interpreted.interpretations.values()
            for outcome in parsed.outcomes
        ):
            for need in consumers:
                definition = _definition_for(need)
                issues.append(
                    _cursor_issue(need.station, need.product, definition.series_id, interpreted.next_url_error)
                )
        return BatchPageStep(
            interpretations=interpreted.interpretations,
            stop_reason=interpreted.stop_reason,
            issues=tuple(issues),
        )
    if interpreted.next_url is None:
        return BatchPageStep(interpretations=interpreted.interpretations)
    return BatchPageStep(
        interpretations=interpreted.interpretations,
        next_request=TransportRequest(HttpMethod.GET, interpreted.next_url, None, {"Accept": "application/json"}),
        cursor_key=interpreted.next_url,
    )


def _on_batch_cycle(consumers: tuple[ConsumerNeed, ...]) -> tuple[str, tuple[Issue, ...]]:
    issues = tuple(
        _cursor_issue(
            need.station,
            need.product,
            _definition_for(need).series_id,
            "Hub Eau pagination cursor cycle",
        )
        for need in consumers
    )
    return ("Hub Eau pagination cursor cycle", issues)


def _finalize_unseen_consumer(
    need: ConsumerNeed,
    payloads: tuple,
    config: ProviderConfig,
) -> UnseenConsumerEvidence:
    del config
    definition = _definition_for(need)
    bounds = SeriesWindow(
        start=datetime.fromisoformat(need.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(need.fetch_window.end.isoformat()),
        axis=need.window.axis,
    )
    call_refs = tuple(
        dict.fromkeys(attempt.attempt_id for payload in payloads for attempt in (payload.attempt_traces or ()))
    ) or tuple(dict.fromkeys(payload.acquisition_id for payload in payloads))
    instants = tuple(
        payload.origin.retrieved_at for payload in payloads if isinstance(payload.origin.retrieved_at, datetime)
    )
    retrieved_at = max(instants) if instants else None
    matching_facts = tuple(f.facts_id for f in definition.facts if need.scope.matches_facts(f))
    matched = need.scope.matches(definition) and bool(matching_facts)
    hasher = hashlib.sha256()
    for index, payload in enumerate(payloads):
        if index > 0:
            hasher.update(b"|")
        hasher.update(payload.content)
    content_digest = hasher.hexdigest()
    inv = InventorySnapshot(
        snapshot_id=stable_id(
            "fr-hubeau-empty-inv",
            definition.series_id
            if matched
            else f"unmatched:{need.station}:{need.product}:{need.scope.model_dump_json()}",
            bounds.model_dump_json(),
            *call_refs,
            content_digest,
        ),
        scope=need.scope,
        members=(definition.series_id,) if matched else (),
        member_facts=((definition.series_id, matching_facts),) if matched else (),
        completeness=InventoryCompleteness.INCOMPLETE,
        access="fr_hubeau supported source mapping",
        origin="response",
        acquired_at=retrieved_at,
        window=bounds,
        evidence=("fr_hubeau parsed payload",),
        reason="Supported access does not establish exhaustive source-series inventory",
    )
    if not matched:
        return UnseenConsumerEvidence(series=(), inventories=(inv,), outcomes=())
    outcome = RetrievalOutcome(
        outcome_id=stable_id(
            "fr-hubeau-empty",
            definition.series_id,
            bounds.model_dump_json(),
            *call_refs,
            str(retrieved_at),
        ),
        series_id=definition.series_id,
        station_id=need.station,
        product_id=str(need.product),
        window=bounds,
        status=OutcomeStatus.EMPTY,
        facts_ids=matching_facts,
        retrieved_at=retrieved_at,
        calls=call_refs,
    )
    return UnseenConsumerEvidence(series=(definition,), inventories=(inv,), outcomes=(outcome,))


def _build_unresolved_outcome(
    need: ConsumerNeed,
    page_acq: PageAcquisition,
    config: ProviderConfig,
) -> RetrievalOutcome:
    del config
    definition = _definition_for(need)
    bounds = SeriesWindow(
        start=datetime.fromisoformat(need.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(need.fetch_window.end.isoformat()),
        axis=need.window.axis,
    )
    matched = need.scope.matches(definition)
    facts_ids = tuple(f.facts_id for f in definition.facts if need.scope.matches_facts(f)) if matched else ()
    return RetrievalOutcome(
        outcome_id=uuid4().hex,
        series_id=definition.series_id if matched else None,
        station_id=need.station,
        product_id=str(need.product),
        window=bounds,
        status=OutcomeStatus.UNRESOLVED,
        reason=page_acq.stop_reason,
        facts_ids=facts_ids,
        calls=tuple(dict.fromkeys(page_acq.calls)),
    )


_PAGINATION_SPEC = BatchPaginationSpec(
    step_page=_step_batch_page,
    finalize_unseen_consumer=_finalize_unseen_consumer,
    build_unresolved_outcome=_build_unresolved_outcome,
    on_cycle=_on_batch_cycle,
)


class FrHubeauRequestPlanner:
    """Plan bounded multi-station paginated GET requests for Hub'Eau endpoints."""

    def plan_lookups(
        self,
        needs: tuple[ConsumerNeed, ...],
        config: ProviderConfig,
    ) -> tuple[PlannedLookup, ...]:
        del needs, config
        return ()

    def plan_observations(
        self,
        needs: tuple[ConsumerNeed, ...],
        lookups: Mapping[tuple[Hashable, str, ProductId], LookupResolution],
        config: ProviderConfig,
    ) -> ObservationPlan:
        del lookups
        if not needs:
            return ObservationPlan()
        grouped: dict[tuple[ProductId, tuple[RenderedWindow, ...]], list[ConsumerNeed]] = {}
        all_definitions: list[SourceSeries] = []
        for need in needs:
            grouped.setdefault((need.product, need.rendered), []).append(need)
            all_definitions.append(_definition_for(need))

        requests: list[PlannedObservationRequest] = []
        for (product, rendered_windows), group_needs in grouped.items():
            source: SourceCoordinates = config.products[product].coordinates
            coordinates = source.value
            if not isinstance(coordinates, FrHubeauSourceCoordinates):
                raise FatalContractError(f"fr_hubeau product has invalid source coordinates: {product}")
            if len(rendered_windows) != 1:
                raise FatalContractError("fr_hubeau product requires one rendered window")
            window = rendered_windows[0]
            if window.stop is None:
                raise FatalContractError("fr_hubeau product requires a rendered stop")
            batch_limit = _DAILY_BATCH_LIMIT if coordinates.family == "daily" else _temperature_batch_limit(window)
            batches = BatchSelector(max_items=batch_limit).pack_batches(group_needs)
            for batch in batches:
                station_codes = ",".join(need.station for need in batch)
                if coordinates.family == "daily":
                    initial = TransportRequest(
                        HttpMethod.GET,
                        _DAILY_URL,
                        {
                            "code_entite": station_codes,
                            "date_debut_obs_elab": window.start,
                            "date_fin_obs_elab": window.stop,
                            "grandeur_hydro_elab": coordinates.field,
                            "size": _PAGE_SIZE,
                        },
                        {"Accept": "application/json"},
                    )
                elif coordinates.family == "temperature":
                    initial = TransportRequest(
                        HttpMethod.GET,
                        _TEMPERATURE_URL,
                        {
                            "code_station": station_codes,
                            "date_debut_mesure": window.start,
                            "date_fin_mesure": window.stop,
                            "size": _PAGE_SIZE,
                        },
                        {"Accept": "application/json"},
                    )
                else:
                    raise FatalContractError(f"Unsupported fr_hubeau family: {coordinates.family}")
                requests.append(
                    PlannedObservationRequest(
                        consumers=batch,
                        request=initial,
                        source_coordinates=source,
                        fetch_window=batch[0].fetch_window,
                        failure_targets=tuple(_definition_for(need) for need in batch),
                        pagination=_PAGINATION_SPEC,
                    )
                )
        return ObservationPlan(requests=tuple(requests), series=tuple(all_definitions))


def fetch(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    fetch_window: FetchWindow,
    config: ProviderConfig,
    transport: Transport,
    *,
    scope: SeriesScope | None = None,
    known_series: tuple[SourceSeries, ...] = (),
) -> SourceAcquisition:
    start = datetime.fromisoformat(fetch_window.start.isoformat())
    end = datetime.fromisoformat(fetch_window.end.isoformat())
    interval = RequestedInterval(start, end, axis=TimeAxis.NATIVE)
    window = SeriesWindow(start=start, end=end, axis=TimeAxis.NATIVE)
    needs = tuple(
        ConsumerNeed(
            station=station,
            product=product,
            scope=(
                scope.model_copy(
                    update={
                        "provider_ids": ("fr_hubeau",),
                        "station_ids": (station,),
                        "product_ids": (str(product),),
                    }
                )
                if scope is not None
                else SeriesScope(provider_ids=("fr_hubeau",), station_ids=(station,), product_ids=(str(product),))
            ),
            known_series=known_series,
            interval=interval,
            window=window,
            fetch_window=fetch_window,
            rendered=rendered_windows[product],
        )
        for station in stations
        for product in products
    )
    return execute_planned_acquisition(FrHubeauRequestPlanner(), needs, config, transport)


def next_url_from_response(content: bytes) -> str | None:
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedSourceStructureError("fr_hubeau payload content is not valid JSON") from error
    return next_url_from_document(document)


def _cursor_issue(station: str, product: ProductId, series_id: str, reason: str) -> Issue:
    return Issue(
        severity="error",
        code="source.acquisition_incomplete",
        message=reason,
        provider_id=ProviderId("fr_hubeau"),
        details={"station_id": station, "product_id": product, "series_id": series_id},
    )
