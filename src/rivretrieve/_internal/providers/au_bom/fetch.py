"""Acquire BoM KiWIS getTimeseriesList/getTimeseriesValues payloads with bounded failures."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
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
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.au_bom.config import (
    NATIVE_UNIT_SYMBOLS,
    AuBomTimeseriesListCoordinates,
    AuBomTimeseriesValuesCoordinates,
)
from rivretrieve._internal.providers.au_bom.parse import (
    interpret_timeseries_list,
    interpret_timeseries_list_failure,
    resolve_timeseries_list,
)
from rivretrieve._internal.providers.au_bom.series import PRODUCT_DEFINITIONS
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
_QUANTITY_BY_PRODUCT_ID = {d.product_id: d.quantity for d in PRODUCT_DEFINITIONS}


def _base_params(request: str) -> dict[str, str]:
    return {"service": "kisters", "type": "queryServices", "request": request, "datasource": "0", "format": "json"}


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
    interpretations: list[InterpretedPayload] = []

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
        except UnsupportedSourceStructureError as error:
            # Hand off this acquisition-time interpretation so the driver does not decode
            # the same (invalid) response again when it would otherwise re-parse list_payload.
            failed_interpretation = interpret_timeseries_list_failure(list_payload, str(error))
            interpretations.append(InterpretedPayload.from_payload(list_payload, failed_interpretation))
            continue

        # Hand off this acquisition-time interpretation (built from the one
        # resolve_timeseries_list call above) so the driver reuses it instead of decoding
        # and re-resolving the same getTimeseriesList response again during parsing.
        interpretations.append(
            InterpretedPayload.from_payload(list_payload, interpret_timeseries_list(list_payload, config, ts_id_map))
        )

        for product in products:
            coords = config.products[product].coordinates.value
            if not isinstance(coords, AuBomTimeseriesValuesCoordinates):
                raise FatalContractError(f"au_bom product has invalid source coordinates: {product}")
            pairs = ts_id_map.get((coords.native_id, coords.parametertype_name), ())
            # parse.py hardcodes each product's native unit rather than trusting this
            # per-series ts_unitsymbol (the values response itself carries no unit at
            # all); verify it here, at the boundary where both are available, so a
            # series BoM ever reports in a different unit is excluded rather than
            # silently mislabeled as the assumed one.
            expected_unit = NATIVE_UNIT_SYMBOLS[_QUANTITY_BY_PRODUCT_ID[str(product)]]
            pairs = tuple(pair for pair in pairs if pair[1] == expected_unit)
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

    return SourceAcquisition(
        value=tuple(payloads), failed_requests=tuple(failures), interpretations=tuple(interpretations)
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
