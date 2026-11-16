"""Acquire NRFA ``/time-series`` and shared ``/station-info`` peak metadata payloads."""

from __future__ import annotations

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
    SourceCoordinates,
    UnknownOriginFact,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.uk_nrfa.config import (
    UkNrfaPeakMetadataCoordinates,
    UkNrfaSourceCoordinates,
)
from rivretrieve._internal.providers.uk_nrfa.series import (
    PEAK_REJECTED_PERIOD_PRODUCTS,
    build_peak_rejection_annotations,
)
from rivretrieve._internal.source_acquisition import FailedSourceRequest, SourceRequestTarget, attempt_request
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportFailure,
    TransportRequest,
    TransportResponse,
)

_BASE_URL = "https://nrfaapps.ceh.ac.uk/nrfa/ws"
_MONTHLY_PRODUCTS: frozenset[str] = frozenset({"gmf", "nmf"})


def extract_peak_metadata_row(content: bytes, station: str) -> Mapping[str, object]:
    """Decode and validate one station's ``/station-info`` ``peak-flow-metadata`` JSON row."""
    try:
        text = content.decode("utf-8")
        document = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UnsupportedSourceStructureError(
            f"NRFA station-info payload for station {station} is not valid JSON"
        ) from exc

    if not isinstance(document, dict):
        raise UnsupportedSourceStructureError(f"NRFA station-info payload for station {station} must be a JSON object")
    rows = document.get("data")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise UnsupportedSourceStructureError(
            f"NRFA station-info payload for station {station} must carry one station row in data"
        )
    row = cast("Mapping[str, object]", rows[0])
    raw_id = row.get("id")
    if type(raw_id) is not int or raw_id < 0 or str(raw_id) != station:
        raise UnsupportedSourceStructureError(
            f"NRFA station-info row id {raw_id!r} differs from requested station {station!r}"
        )
    build_peak_rejection_annotations(row, series=())
    return row


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
    """Fetch bounded NRFA time-series responses with one shared peak-metadata lookup per station."""
    _validate_inputs(stations, products, rendered_windows, config)
    window = SeriesWindow(
        start=datetime.fromisoformat(fetch_window.start.isoformat()),
        end=datetime.fromisoformat(fetch_window.end.isoformat()),
    )
    payloads: list[Payload] = []
    failures: list[FailedSourceRequest] = []
    peak_products = tuple(product for product in products if str(product) in PEAK_REJECTED_PERIOD_PRODUCTS)

    for station in stations:
        peak_state: tuple[str, bytes] | None = None
        peak_checked = False
        for product in products:
            if str(product) in PEAK_REJECTED_PERIOD_PRODUCTS:
                if not peak_checked:
                    peak_checked = True
                    peak_state = _acquire_peak_prerequisite(
                        station,
                        peak_products,
                        fetch_window,
                        window,
                        transport,
                        scope,
                        known_series,
                        payloads,
                        failures,
                    )
                if peak_state is None:
                    continue
                prerequisite_ids: tuple[str, ...] = (peak_state[0],)
                peak_metadata_content: bytes | None = peak_state[1]
            else:
                prerequisite_ids = ()
                peak_metadata_content = None

            _acquire_time_series(
                station,
                product,
                rendered_windows.get(product, ()),
                fetch_window,
                window,
                transport,
                scope,
                known_series,
                prerequisite_ids,
                peak_metadata_content,
                payloads,
                failures,
            )

    return SourceAcquisition(value=tuple(payloads), failed_requests=tuple(failures))


def _validate_inputs(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    config: ProviderConfig,
) -> None:
    if not stations or not products or any(not isinstance(s, str) or not s for s in stations):
        raise FatalContractError("uk_nrfa fetch requires non-empty stations and products")
    for product in products:
        product_cfg = config.products.get(product)
        if product_cfg is None:
            raise FatalContractError(f"uk_nrfa product is absent from provider config: {product}")
        coords = product_cfg.coordinates.value
        if (
            not isinstance(coords, UkNrfaSourceCoordinates)
            or coords.data_type != str(product)
            or coords.peak_metadata_content is not None
        ):
            raise FatalContractError(f"uk_nrfa product has invalid configured source coordinates: {product}")
        windows = rendered_windows.get(product, ())
        if str(product) in _MONTHLY_PRODUCTS:
            if windows != ():
                raise FatalContractError(f"uk_nrfa unwindowed monthly product received rendered windows: {product}")
        elif len(windows) != 1 or windows[0].stop is None:
            raise FatalContractError(f"uk_nrfa windowed product requires one bounded rendered window: {product}")


def _acquire_peak_prerequisite(
    station: str,
    peak_products: tuple[ProductId, ...],
    fetch_window: FetchWindow,
    window: SeriesWindow,
    transport: Transport,
    scope: SeriesScope | None,
    known_series: tuple[SourceSeries, ...],
    payloads: list[Payload],
    failures: list[FailedSourceRequest],
) -> tuple[str, bytes] | None:
    request = TransportRequest(
        method=HttpMethod.GET,
        url=f"{_BASE_URL}/station-info",
        params={"station": station, "format": "json-object", "fields": "id,peak-flow-metadata"},
        headers={"Accept": "application/json"},
    )
    response = attempt_request(transport, request)
    if isinstance(response, (TransportFailure, CredentialExchangeError)):
        shared_call_id = uuid4().hex
        for product in peak_products:
            failures.append(
                FailedSourceRequest(
                    uuid4().hex,
                    _request_target(station, product, known_series),
                    window,
                    request,
                    response,
                    call_id=shared_call_id,
                )
            )
        return None

    meta_payload = Payload(
        source_coordinates=SourceCoordinates(UkNrfaPeakMetadataCoordinates()),
        station_products=tuple((station, product) for product in peak_products),
        fetch_window=fetch_window,
        content=response.content,
        origin=_origin(response),
        prerequisite_calls=response.prerequisite_calls,
        scope=scope,
        known_series=known_series,
        attempt_traces=response.attempt_traces,
    )
    payloads.append(meta_payload)
    try:
        extract_peak_metadata_row(response.content, station)
    except UnsupportedSourceStructureError:
        # Retain meta_payload so parse reports source.unsupported_structure for each peak product.
        return None
    return meta_payload.acquisition_id, response.content


def _acquire_time_series(
    station: str,
    product: ProductId,
    rendered: tuple[RenderedWindow, ...],
    fetch_window: FetchWindow,
    window: SeriesWindow,
    transport: Transport,
    scope: SeriesScope | None,
    known_series: tuple[SourceSeries, ...],
    prerequisite_ids: tuple[str, ...],
    peak_metadata_content: bytes | None,
    payloads: list[Payload],
    failures: list[FailedSourceRequest],
) -> None:
    params: dict[str, str] = {
        "station": station,
        "data-type": str(product),
        "format": "json-object",
        "dates": "true",
        "flags": "true",
    }
    if str(product) not in _MONTHLY_PRODUCTS:
        window_item = rendered[0]
        assert window_item.stop is not None
        params["start-date"] = window_item.start
        params["end-date"] = window_item.stop

    request = TransportRequest(
        method=HttpMethod.GET,
        url=f"{_BASE_URL}/time-series",
        params=params,
        headers={"Accept": "application/json"},
    )
    response = attempt_request(transport, request)
    if isinstance(response, (TransportFailure, CredentialExchangeError)):
        failures.append(
            FailedSourceRequest(
                uuid4().hex,
                _request_target(station, product, known_series),
                window,
                request,
                response,
                prerequisite_acquisition_ids=prerequisite_ids,
            )
        )
        return

    payloads.append(
        Payload(
            source_coordinates=SourceCoordinates(
                UkNrfaSourceCoordinates(data_type=str(product), peak_metadata_content=peak_metadata_content)
            ),
            station_products=((station, product),),
            fetch_window=fetch_window,
            content=response.content,
            origin=_origin(response),
            prerequisite_calls=response.prerequisite_calls,
            scope=scope,
            known_series=known_series,
            attempt_traces=response.attempt_traces,
            prerequisite_acquisition_ids=prerequisite_ids,
        )
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
        attempt_traces=response.attempt_traces,
    )


__all__ = ("extract_peak_metadata_row", "fetch")
