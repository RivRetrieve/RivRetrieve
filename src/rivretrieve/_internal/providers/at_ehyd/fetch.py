"""Acquire Austria eHYD historical CSV and live JSON payloads with bounded failures."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal
from uuid import uuid4

from rivretrieve._internal.authentication import CredentialExchangeError
from rivretrieve._internal.engine import (
    FetchWindow,
    InterpretedPayload,
    Payload,
    ProviderConfig,
    RenderedWindow,
    SourceAcquisition,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    narrow_payload_for_pair,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.at_ehyd.config import (
    AtEhydInfoCoordinates,
    AtEhydOwfCoordinates,
    AtEhydPegelCoordinates,
    AtEhydPegelEndpointCoordinates,
)
from rivretrieve._internal.providers.at_ehyd.parse import (
    interpret_info_file_map,
    interpret_structure_failure,
)
from rivretrieve._internal.providers.at_ehyd.parse import (
    resolve_messstellen_info_files as resolve_messstellen_info_files,
)
from rivretrieve._internal.source_acquisition import (
    FailedSourceRequest,
    SourceRequestTarget,
    attempt_request,
)
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportFailure,
    TransportRequest,
    TransportResponse,
)

_INFO_URL = "https://ehyd.gv.at/services/Messstellen/info"
_OWF_URL = "https://ehyd.gv.at/services/MessstellenExtraData/owf"
_PEGEL_URLS: dict[Literal["pegel_bgis", "pegel_longterm"], str] = {
    "pegel_bgis": "https://ehyd.gv.at/services/Diagram/pegelBgis",
    "pegel_longterm": "https://ehyd.gv.at/services/Diagram/pegelLongterm",
}


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
    """Fetch source-fixed eHYD responses while isolating independent route and file failures."""
    if not stations or not products:
        raise FatalContractError("at_ehyd fetch requires at least one station and product")

    owf_products: list[tuple[ProductId, AtEhydOwfCoordinates]] = []
    pegel_groups: dict[Literal["pegel_bgis", "pegel_longterm"], list[ProductId]] = {}
    for product in products:
        try:
            product_config = config.products[product]
        except KeyError as error:
            raise FatalContractError(f"at_ehyd product is absent from provider config: {product}") from error
        if rendered_windows.get(product) != ():
            raise FatalContractError(f"at_ehyd source-fixed product received unexpected rendered windows: {product}")
        coords = product_config.coordinates.value
        if isinstance(coords, AtEhydOwfCoordinates):
            owf_products.append((product, coords))
        elif isinstance(coords, AtEhydPegelCoordinates):
            pegel_groups.setdefault(coords.subsystem, []).append(product)
        else:
            raise FatalContractError(f"at_ehyd product has invalid source coordinates: {product}")

    window = SeriesWindow(
        start=datetime.fromisoformat(fetch_window.start.isoformat()),
        end=datetime.fromisoformat(fetch_window.end.isoformat()),
    )
    payloads: list[Payload] = []
    failures: list[FailedSourceRequest] = []
    interpretations: list[InterpretedPayload] = []

    for station in stations:
        if owf_products:
            info_request = TransportRequest(
                method=HttpMethod.GET,
                url=_INFO_URL,
                params={"hzbnr": station},
                headers={"Accept": "application/json"},
            )
            info_response = attempt_request(transport, info_request)
            if isinstance(info_response, (TransportFailure, CredentialExchangeError)):
                call_id = uuid4().hex
                for product, _ in owf_products:
                    failures.append(
                        FailedSourceRequest(
                            uuid4().hex,
                            _request_target(station, product, known_series),
                            window,
                            info_request,
                            info_response,
                            call_id=call_id,
                        )
                    )
            else:
                info_payload = Payload(
                    source_coordinates=SourceCoordinates(AtEhydInfoCoordinates()),
                    station_products=tuple((station, product) for product, _ in owf_products),
                    fetch_window=fetch_window,
                    content=info_response.content,
                    origin=_origin(info_response),
                    prerequisite_calls=info_response.prerequisite_calls,
                    scope=scope,
                    known_series=known_series,
                    attempt_traces=info_response.attempt_traces,
                )
                payloads.append(info_payload)
                structure_error: str | None = None
                try:
                    file_map = resolve_messstellen_info_files(info_response.content, station)
                except UnsupportedSourceStructureError as error:
                    # Parse retains info_payload and classifies the invalid prerequisite per product.
                    file_map = None
                    structure_error = str(error)
                for product, _ in owf_products:
                    pair_payload = narrow_payload_for_pair(info_payload, station, product)
                    if file_map is not None:
                        pair_parsed = interpret_info_file_map(pair_payload, station, product, file_map)
                    else:
                        assert structure_error is not None
                        pair_parsed = interpret_structure_failure(pair_payload, station, product, structure_error)
                    interpretations.append(InterpretedPayload.from_payload(pair_payload, pair_parsed))
                if file_map is not None:
                    for product, _ in owf_products:
                        file_nr = file_map.get(product)
                        if file_nr is None:
                            continue
                        csv_request = TransportRequest(
                            method=HttpMethod.GET,
                            url=_OWF_URL,
                            params={"id": station, "file": str(file_nr)},
                        )
                        csv_response = attempt_request(transport, csv_request)
                        if isinstance(csv_response, (TransportFailure, CredentialExchangeError)):
                            failures.append(
                                FailedSourceRequest(
                                    uuid4().hex,
                                    _request_target(station, product, known_series),
                                    window,
                                    csv_request,
                                    csv_response,
                                    prerequisite_acquisition_ids=(info_payload.acquisition_id,),
                                )
                            )
                            continue
                        payloads.append(
                            Payload(
                                source_coordinates=config.products[product].coordinates,
                                station_products=((station, product),),
                                fetch_window=fetch_window,
                                content=csv_response.content,
                                origin=_origin(csv_response),
                                prerequisite_calls=csv_response.prerequisite_calls,
                                scope=scope,
                                known_series=known_series,
                                attempt_traces=csv_response.attempt_traces,
                                prerequisite_acquisition_ids=(info_payload.acquisition_id,),
                            )
                        )

        for subsystem, group_products in pegel_groups.items():
            pegel_request = TransportRequest(
                method=HttpMethod.GET,
                url=_PEGEL_URLS[subsystem],
                params={"hzbnr": station},
                headers={"Accept": "application/json"},
            )
            pegel_response = attempt_request(transport, pegel_request)
            if isinstance(pegel_response, (TransportFailure, CredentialExchangeError)):
                call_id = uuid4().hex
                for product in group_products:
                    failures.append(
                        FailedSourceRequest(
                            uuid4().hex,
                            _request_target(station, product, known_series),
                            window,
                            pegel_request,
                            pegel_response,
                            call_id=call_id,
                        )
                    )
                continue
            coordinates = (
                config.products[group_products[0]].coordinates
                if len(group_products) == 1
                else SourceCoordinates(AtEhydPegelEndpointCoordinates(subsystem))
            )
            payloads.append(
                Payload(
                    source_coordinates=coordinates,
                    station_products=tuple((station, product) for product in group_products),
                    fetch_window=fetch_window,
                    content=pegel_response.content,
                    origin=_origin(pegel_response),
                    prerequisite_calls=pegel_response.prerequisite_calls,
                    scope=scope,
                    known_series=known_series,
                    attempt_traces=pegel_response.attempt_traces,
                )
            )

    return SourceAcquisition(
        value=tuple(payloads),
        failed_requests=tuple(failures),
        interpretations=tuple(interpretations),
    )


def _request_target(
    station: str, product: ProductId, known_series: tuple[SourceSeries, ...]
) -> SourceSeries | SourceRequestTarget:
    matching = tuple(item for item in known_series if item.station_id == station and item.product_id == str(product))
    if len(matching) == 1:
        return matching[0]
    return SourceRequestTarget(station, str(product))


def _origin(response: TransportResponse) -> SourceCallOrigin:
    return SourceCallOrigin(
        url=response.url,
        request_parameters=response.request_parameters,
        status_code=response.status_code,
        retrieved_at=response.retrieved_at,
        content_type=response.content_type if response.content_type is not None else UnknownOriginFact(),
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
        attempts=response.attempts,
    )
