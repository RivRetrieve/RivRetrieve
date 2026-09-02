"""ch_foen fetch : stations × products × windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]].

Contributed by: Nicolas Lazaro
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from rivretrieve._internal.engine import (
    FetchWindow,
    Payload,
    ProviderConfig,
    RenderedWindow,
    SourceCallOrigin,
    SourceQuery,
    UnknownOriginFact,
    WithIssues,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.ch_foen.config import ChFoenSourceCoordinates
from rivretrieve._internal.transport import AuthenticationCapability, HttpMethod, Transport, TransportRequest

_REST = "https://api.existenz.ch/apiv1/hydro/daterange"
_FLUX = "https://influx.konzept.space/api/v2/query"


def fetch(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    fetch_window: FetchWindow,
    config: ProviderConfig,
    transport: Transport,
) -> WithIssues[tuple[Payload, ...]]:
    fields: list[str] = []
    for product in products:
        try:
            coordinates = config.products[product].coordinates.value
        except KeyError as exc:
            raise FatalContractError(f"ch_foen product is absent from provider config: {product}") from exc
        if not isinstance(coordinates, ChFoenSourceCoordinates):
            raise FatalContractError(f"ch_foen product has invalid source coordinates: {product}")
        fields.extend(field.name for field in coordinates.fields)
    fields = list(dict.fromkeys(fields))
    query_fields = ["flow", "flow_ls", "height_abs", "height", "temperature"]
    if not products or not stations:
        return WithIssues(())
    start, stop = _common_window(products, rendered_windows)
    if isinstance(transport, AuthenticationCapability) and transport.can_authenticate(_FLUX):
        payloads: list[Payload] = []
        for station in stations:
            query = _flux(station, query_fields, start, stop)
            request = TransportRequest(
                HttpMethod.POST,
                _FLUX,
                {"org": "api.existenz.ch"},
                {"Content-Type": "application/vnd.flux", "Accept": "application/csv"},
                query,
            )
            response = transport.send(request)
            _require_success(response.status_code)
            payloads.append(
                _payload(
                    config.products[products[0]].coordinates,
                    tuple((station, product) for product in products),
                    fetch_window,
                    response,
                    SourceQuery(query, ()),
                )
            )
        return WithIssues(tuple(payloads))
    params = {
        "locations": ",".join(stations),
        "parameters": ",".join(query_fields),
        "startdate": _rest_time(start),
        "enddate": _rest_time(stop),
        "timeseriesformat": "rows",
        "app": "RivRetrieve",
        "version": "1",
    }
    response = transport.send(TransportRequest(HttpMethod.GET, _REST, params, {"Accept": "application/json"}))
    _require_success(response.status_code)
    return WithIssues(
        (
            _payload(
                config.products[products[0]].coordinates,
                tuple((station, product) for station in stations for product in products),
                fetch_window,
                response,
                UnknownOriginFact(),
            ),
        )
    )


def _common_window(
    products: tuple[ProductId, ...], rendered: Mapping[ProductId, tuple[RenderedWindow, ...]]
) -> tuple[str, str]:
    pairs: list[tuple[str, str]] = []
    for product in products:
        try:
            (window,) = rendered[product]
        except (KeyError, ValueError) as exc:
            raise FatalContractError("ch_foen requires one common rendered window per product") from exc
        if window.stop is None:
            raise FatalContractError("ch_foen requires a bounded window")
        pairs.append((window.start, window.stop))
    if len(set(pairs)) != 1:
        raise FatalContractError("ch_foen products must share one rendered window")
    return pairs[0]


def _rest_time(value: str) -> str:
    return datetime.fromisoformat(value.removesuffix("Z")).strftime("%Y-%m-%d %H:%M:%S")


def _flux(station: str, fields: list[str], start: str, stop: str) -> str:
    field_filter = " or ".join(f'r["_field"] == "{field}"' for field in fields)
    return (
        'from(bucket: "existenzApi")\n'
        f"  |> range(start: {start}, stop: {stop})\n"
        '  |> filter(fn: (r) => r["_measurement"] == "hydro")\n'
        f'  |> filter(fn: (r) => r["loc"] == "{station}")\n'
        f"  |> filter(fn: (r) => {field_filter})\n"
        '  |> keep(columns: ["_start", "_stop", "_time", "_value", "_field", "_measurement", "loc"])\n'
        '  |> sort(columns: ["_time", "_field"])\n'
    )


def _require_success(status: int) -> None:
    if not 200 <= status < 300:
        raise FatalContractError(f"ch_foen request returned unexpected HTTP status {status}")


def _payload(coordinates, pairs, window, response, query) -> Payload:
    return Payload(
        coordinates,
        pairs,
        window,
        response.content,
        SourceCallOrigin(
            response.url,
            response.request_parameters,
            response.status_code,
            response.retrieved_at,
            response.content_type if response.content_type else UnknownOriginFact(),
            UnknownOriginFact(),
            query,
        ),
    )
