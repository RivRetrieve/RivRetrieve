"""Acquire BoM KiWIS getTimeseriesList/getTimeseriesValues payloads with bounded failures."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
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
from rivretrieve._internal.providers.au_bom.config import (
    AuBomTimeseriesListCoordinates,
    AuBomTimeseriesValuesCoordinates,
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

_URL = "https://www.bom.gov.au/waterdata/services"
_LIST_RETURNFIELDS = "ts_id,ts_name,parametertype_name,ts_unitsymbol,station_no"
_VALUES_RETURNFIELDS = "Timestamp,Value,Quality Code,Quality Code Name"


def _base_params(request: str) -> dict[str, str]:
    return {"service": "kisters", "type": "queryServices", "request": request, "datasource": "0", "format": "json"}


def resolve_timeseries_list(content: bytes, station: str) -> dict[tuple[str, str], tuple[tuple[str, str], ...]]:
    """Map each ``(ts_name, parametertype_name)`` at ``station`` to its ``(ts_id, ts_unitsymbol)`` pairs.

    ``ts_name`` alone is ambiguous (confirmed live, 2026-11-03: station 410730's
    ``DMQaQc.Merged.DailyMean.24HR`` is shared by discharge, stage, pH,
    turbidity, conductivity and water temperature alike); ``parametertype_name``
    disambiguates it. A resolved pair can still map to more than one ``ts_id``
    (confirmed live, 2026-11-03: 74 discharge, 79 stage and 4 water-temperature
    stations each carry two ``ts_id`` for one admitted series, with no field
    distinguishing them). This returns every pair found, never collapsing them.
    """
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedSourceStructureError("BoM getTimeseriesList response is not valid JSON") from error
    if not isinstance(document, list) or not document or not isinstance(document[0], list):
        raise UnsupportedSourceStructureError("BoM getTimeseriesList response must be a JSON array of arrays")
    header = document[0]
    try:
        name_index = header.index("ts_name")
        parameter_index = header.index("parametertype_name")
        id_index = header.index("ts_id")
        unit_index = header.index("ts_unitsymbol")
        station_index = header.index("station_no")
    except ValueError as error:
        raise UnsupportedSourceStructureError("BoM getTimeseriesList header lacks a required column") from error

    resolved: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for row in document[1:]:
        if not isinstance(row, list) or len(row) != len(header):
            raise UnsupportedSourceStructureError("BoM getTimeseriesList row does not match its header width")
        if str(row[station_index]) != station:
            raise UnsupportedSourceStructureError(
                f"BoM getTimeseriesList row station_no {row[station_index]!r} contradicts requested station {station!r}"
            )
        key = (str(row[name_index]), str(row[parameter_index]))
        resolved.setdefault(key, []).append((str(row[id_index]), str(row[unit_index])))
    return {key: tuple(pairs) for key, pairs in resolved.items()}


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
    """Resolve each station's live ts_id per product, then fetch bounded observation windows."""
    if not stations or not products:
        raise FatalContractError("au_bom fetch requires at least one station and product")

    rendered_starts_stops: set[tuple[str, str | None]] = set()
    for product in products:
        if product not in config.products:
            raise FatalContractError(f"au_bom product is absent from provider config: {product}")
        windows = rendered_windows.get(product, ())
        if len(windows) != 1:
            raise FatalContractError(f"au_bom product requires exactly one rendered window: {product}")
        rendered_starts_stops.add((windows[0].start, windows[0].stop))
    if len(rendered_starts_stops) != 1:
        raise FatalContractError("au_bom shared-acquisition products received disagreeing rendered windows")
    rendered = next(iter(rendered_starts_stops))

    window = SeriesWindow(
        start=datetime.fromisoformat(fetch_window.start.isoformat()),
        end=datetime.fromisoformat(fetch_window.end.isoformat()),
    )
    payloads: list[Payload] = []
    failures: list[FailedSourceRequest] = []

    for station in stations:
        list_request = TransportRequest(
            method=HttpMethod.GET,
            url=_URL,
            params={**_base_params("getTimeseriesList"), "station_no": station, "returnfields": _LIST_RETURNFIELDS},
        )
        list_response = attempt_request(transport, list_request)
        if isinstance(list_response, (TransportFailure, CredentialExchangeError)):
            call_id = uuid4().hex
            for product in products:
                failures.append(
                    FailedSourceRequest(
                        uuid4().hex,
                        _request_target(station, product, known_series),
                        window,
                        list_request,
                        list_response,
                        call_id=call_id,
                    )
                )
            continue

        list_payload = Payload(
            source_coordinates=SourceCoordinates(AuBomTimeseriesListCoordinates()),
            station_products=tuple((station, product) for product in products),
            fetch_window=fetch_window,
            content=list_response.content,
            origin=_origin(list_response),
            prerequisite_calls=list_response.prerequisite_calls,
            scope=scope,
            known_series=known_series,
            attempt_traces=list_response.attempt_traces,
        )
        payloads.append(list_payload)
        try:
            ts_id_map = resolve_timeseries_list(list_response.content, station)
        except UnsupportedSourceStructureError:
            # Parse retains list_payload and classifies the invalid prerequisite per product.
            continue

        for product in products:
            coords = config.products[product].coordinates.value
            if not isinstance(coords, AuBomTimeseriesValuesCoordinates):
                raise FatalContractError(f"au_bom product has invalid source coordinates: {product}")
            pairs = ts_id_map.get((coords.native_id, coords.parametertype_name), ())
            if not pairs:
                continue
            ts_ids = tuple(ts_id for ts_id, _ in pairs)
            values_request = TransportRequest(
                method=HttpMethod.GET,
                url=_URL,
                params={
                    **_base_params("getTimeseriesValues"),
                    "ts_id": ",".join(ts_ids),
                    "from": rendered[0],
                    "to": rendered[1] or "",
                    "returnfields": _VALUES_RETURNFIELDS,
                },
            )
            values_response = attempt_request(transport, values_request)
            if isinstance(values_response, (TransportFailure, CredentialExchangeError)):
                failures.append(
                    FailedSourceRequest(
                        uuid4().hex,
                        _request_target(station, product, known_series),
                        window,
                        values_request,
                        values_response,
                        prerequisite_acquisition_ids=(list_payload.acquisition_id,),
                    )
                )
                continue
            payloads.append(
                Payload(
                    source_coordinates=config.products[product].coordinates,
                    station_products=((station, product),),
                    fetch_window=fetch_window,
                    content=values_response.content,
                    origin=_origin(values_response),
                    prerequisite_calls=values_response.prerequisite_calls,
                    scope=scope,
                    known_series=known_series,
                    attempt_traces=values_response.attempt_traces,
                    prerequisite_acquisition_ids=(list_payload.acquisition_id,),
                )
            )

    return SourceAcquisition(value=tuple(payloads), failed_requests=tuple(failures))


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
