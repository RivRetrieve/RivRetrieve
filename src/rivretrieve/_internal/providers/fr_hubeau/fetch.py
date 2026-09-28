"""fr_hubeau fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]].

Contributed by: Thiago von Däniken
"""

import json
from collections.abc import Mapping
from datetime import datetime
from typing import cast
from uuid import uuid4

from rivretrieve._internal.authentication import CredentialExchangeError
from rivretrieve._internal.engine import (
    FetchWindow,
    Payload,
    ProviderConfig,
    RenderedWindow,
    SourceAcquisition,
    SourceCallOrigin,
    UnknownOriginFact,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.fr_hubeau.config import SERIES_MAPPINGS, FrHubeauSourceCoordinates
from rivretrieve._internal.providers.fr_hubeau.parse import parse
from rivretrieve._internal.source_acquisition import FailedSourceRequest, attempt_request
from rivretrieve._internal.source_series import (
    OutcomeStatus,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
)
from rivretrieve._internal.transport import HttpMethod, Transport, TransportFailure, TransportRequest, TransportResponse

_DAILY_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab"
_TEMPERATURE_URL = "https://hubeau.eaufrance.fr/api/v1/temperature/chronique"


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
    failures = []
    outcomes = []
    issues = []
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
                request = TransportRequest(
                    HttpMethod.GET,
                    _DAILY_URL,
                    {
                        "code_entite": station,
                        "date_debut_obs_elab": window.start,
                        "date_fin_obs_elab": window.stop,
                        "grandeur_hydro_elab": coordinates.field,
                        "size": 20,
                    },
                    {"Accept": "application/json"},
                )
            elif coordinates.family == "temperature":
                request = TransportRequest(
                    HttpMethod.GET,
                    _TEMPERATURE_URL,
                    {
                        "code_station": station,
                        "date_debut_mesure": window.start,
                        "date_fin_mesure": window.stop,
                        "size": 20,
                    },
                    {"Accept": "application/json"},
                )
            definition = SERIES_MAPPINGS[product].source_series("fr_hubeau", station, product)
            bounds = SeriesWindow(
                start=datetime.fromisoformat(fetch_window.start.isoformat()),
                end=datetime.fromisoformat(fetch_window.end.isoformat()),
            )
            visited = set()
            calls = []
            reason = None
            while True:
                response = attempt_request(transport, request)
                if isinstance(response, (TransportFailure, CredentialExchangeError)):
                    failed = FailedSourceRequest(uuid4().hex, definition, bounds, request, response)
                    failures.append(failed)
                    calls.append(failed.call_id or failed.event_id)
                    reason = str(response)
                    break
                payloads.append(
                    Payload(
                        source,
                        ((station, product),),
                        fetch_window,
                        response.content,
                        _origin(response),
                        response.prerequisite_calls,
                        scope=scope,
                        known_series=known_series,
                        attempt_traces=response.attempt_traces,
                    )
                )
                calls.extend(item.attempt_id for item in payloads[-1].attempt_traces)
                if not payloads[-1].attempt_traces:
                    calls.append(payloads[-1].acquisition_id)
                parsed = parse(payloads[-1], config)
                if any(
                    outcome.status in (OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNRESOLVED, OutcomeStatus.FAILED)
                    for outcome in parsed.outcomes
                ):
                    reason = "Hub Eau cursor chain contains an unsupported observation page"
                    break
                try:
                    next_url = next_url_from_response(response.content)
                except UnsupportedSourceStructureError as error:
                    reason = str(error)
                    issues.append(_cursor_issue(station, product, definition.series_id, reason))
                    break
                if next_url is None:
                    break
                if next_url in visited:
                    reason = "Hub Eau pagination cursor cycle"
                    issues.append(_cursor_issue(station, product, definition.series_id, reason))
                    break
                visited.add(next_url)
                request = TransportRequest(HttpMethod.GET, next_url, None, {"Accept": "application/json"})
            if reason is not None:
                outcomes.append(
                    RetrievalOutcome(
                        outcome_id=uuid4().hex,
                        series_id=definition.series_id,
                        station_id=station,
                        product_id=product,
                        window=bounds,
                        status=OutcomeStatus.UNRESOLVED,
                        reason=reason,
                        facts_ids=tuple(f.facts_id for f in definition.facts),
                        calls=tuple(dict.fromkeys(calls)),
                    )
                )
    return SourceAcquisition(
        value=tuple(payloads), failed_requests=tuple(failures), outcomes=tuple(outcomes), issues=tuple(issues)
    )


def next_url_from_response(content: bytes) -> str | None:
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedSourceStructureError("fr_hubeau payload content is not valid JSON") from error
    if not isinstance(document, dict):
        raise UnsupportedSourceStructureError("fr_hubeau payload must be a JSON object")
    value = cast("dict[str, object]", document).get("next")
    if value is not None and not isinstance(value, str):
        raise UnsupportedSourceStructureError("fr_hubeau response next must be a URL or null")
    if value is not None and not value.startswith("https://hubeau.eaufrance.fr/api/"):
        raise UnsupportedSourceStructureError("fr_hubeau response next URL is outside Hub Eau")
    return value


def _origin(response: TransportResponse) -> SourceCallOrigin:
    return SourceCallOrigin(
        response.url,
        response.request_parameters,
        response.status_code,
        response.retrieved_at,
        response.content_type if response.content_type else UnknownOriginFact(),
        UnknownOriginFact(),
        UnknownOriginFact(),
        attempts=response.attempts,
    )


def _cursor_issue(station: str, product: ProductId, series_id: str, reason: str) -> Issue:
    return Issue(
        severity="error",
        code="source.acquisition_incomplete",
        message=reason,
        provider_id=ProviderId("fr_hubeau"),
        details={"station_id": station, "product_id": product, "series_id": series_id},
    )
