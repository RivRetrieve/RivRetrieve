"""fr_hubeau fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → SourceAcquisition.

Contributed by: Thiago von Däniken
"""

import json
from collections.abc import Mapping
from datetime import datetime
from uuid import uuid4

from rivretrieve._internal.engine import (
    FetchWindow,
    InterpretedPayload,
    Payload,
    ProviderConfig,
    RenderedWindow,
    SourceAcquisition,
    SourceCallOrigin,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.page_acquisition import PageStep, acquire_pages
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.fr_hubeau.config import SERIES_MAPPINGS, FrHubeauSourceCoordinates
from rivretrieve._internal.providers.fr_hubeau.parse import interpret_page, next_url_from_document
from rivretrieve._internal.source_acquisition import FailedSourceRequest
from rivretrieve._internal.source_series import (
    OutcomeStatus,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
)
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest, TransportResponse

_DAILY_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab"
_TEMPERATURE_URL = "https://hubeau.eaufrance.fr/api/v1/temperature/chronique"
_PAGE_SIZE = 2500


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
    payloads: list[Payload] = []
    interpretations: list[InterpretedPayload] = []
    failures: list[FailedSourceRequest] = []
    outcomes: list[RetrievalOutcome] = []
    issues: list[Issue] = []
    for station in stations:
        for product in products:
            source = config.products[product].coordinates
            coordinates = source.value
            if not isinstance(coordinates, FrHubeauSourceCoordinates):
                raise FatalContractError(f"fr_hubeau product has invalid source coordinates: {product}")
            (window,) = rendered_windows[product]
            if window.stop is None:
                raise FatalContractError("fr_hubeau product requires a rendered stop")
            if coordinates.family == "daily":
                initial = TransportRequest(
                    HttpMethod.GET,
                    _DAILY_URL,
                    {
                        "code_entite": station,
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
                        "code_station": station,
                        "date_debut_mesure": window.start,
                        "date_fin_mesure": window.stop,
                        "size": _PAGE_SIZE,
                    },
                    {"Accept": "application/json"},
                )
            definition = SERIES_MAPPINGS[product].source_series("fr_hubeau", station, product)
            bounds = SeriesWindow(
                start=datetime.fromisoformat(fetch_window.start.isoformat()),
                end=datetime.fromisoformat(fetch_window.end.isoformat()),
            )

            def _build_payload(
                response: TransportResponse,
                *,
                source=source,
                station=station,
                product=product,
            ) -> Payload:
                return Payload(
                    source,
                    ((station, product),),
                    fetch_window,
                    response.content,
                    SourceCallOrigin.from_response(response),
                    response.prerequisite_calls,
                    scope=scope,
                    known_series=known_series,
                    attempt_traces=response.attempt_traces,
                )

            def _step_page(
                payload: Payload,
                *,
                station=station,
                product=product,
                definition=definition,
            ) -> PageStep:
                interpreted = interpret_page(payload, config)
                if any(
                    outcome.status in (OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNRESOLVED, OutcomeStatus.FAILED)
                    for outcome in interpreted.parsed.outcomes
                ):
                    return PageStep(
                        parsed=interpreted.parsed,
                        stop_reason="Hub Eau cursor chain contains an unsupported observation page",
                    )
                if interpreted.next_url_error is not None:
                    return PageStep(
                        parsed=interpreted.parsed,
                        stop_reason=interpreted.next_url_error,
                        issues=(_cursor_issue(station, product, definition.series_id, interpreted.next_url_error),),
                    )
                if interpreted.next_url is None:
                    return PageStep(parsed=interpreted.parsed)
                return PageStep(
                    parsed=interpreted.parsed,
                    next_request=TransportRequest(
                        HttpMethod.GET, interpreted.next_url, None, {"Accept": "application/json"}
                    ),
                    cursor_key=interpreted.next_url,
                )

            page_acq = acquire_pages(
                initial,
                transport=transport,
                window=bounds,
                build_payload=_build_payload,
                interpret_page=_step_page,
                failure_targets=lambda definition=definition: (definition,),
                on_cycle=lambda station=station, product=product, definition=definition: (
                    "Hub Eau pagination cursor cycle",
                    (_cursor_issue(station, product, definition.series_id, "Hub Eau pagination cursor cycle"),),
                ),
            )
            payloads.extend(page_acq.payloads)
            interpretations.extend(page_acq.interpretations)
            failures.extend(page_acq.failed_requests)
            issues.extend(page_acq.issues)
            if page_acq.stop_reason is not None:
                outcomes.append(
                    RetrievalOutcome(
                        outcome_id=uuid4().hex,
                        series_id=definition.series_id,
                        station_id=station,
                        product_id=product,
                        window=bounds,
                        status=OutcomeStatus.UNRESOLVED,
                        reason=page_acq.stop_reason,
                        facts_ids=tuple(f.facts_id for f in definition.facts),
                        calls=tuple(dict.fromkeys(page_acq.calls)),
                    )
                )
    return SourceAcquisition(
        value=tuple(payloads),
        failed_requests=tuple(failures),
        outcomes=tuple(outcomes),
        issues=tuple(issues),
        interpretations=tuple(interpretations),
    )


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
