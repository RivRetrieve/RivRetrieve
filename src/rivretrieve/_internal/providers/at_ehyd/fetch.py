"""Acquire Austria eHYD historical CSV and live JSON payloads with bounded failures."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Literal, cast
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
from rivretrieve._internal.providers.at_ehyd.config import (
    AtEhydInfoCoordinates,
    AtEhydOwfCoordinates,
    AtEhydPegelCoordinates,
    AtEhydPegelEndpointCoordinates,
)
from rivretrieve._internal.providers.at_ehyd.series import IN_SCOPE_OWF_FTYPES
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

_PREFIX_TO_PRODUCT: dict[str, ProductId] = {
    prefix: ProductId(ftyp) for ftyp, (prefix, _) in IN_SCOPE_OWF_FTYPES.items()
}


def resolve_messstellen_info_files(content: bytes, station: str) -> dict[ProductId, int]:
    """Resolve in-scope ``owf`` ``fileNr`` indices for ``station`` from ``Messstellen/info``."""
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedSourceStructureError("eHYD Messstellen/info response is not valid JSON") from error
    if not isinstance(document, list):
        raise UnsupportedSourceStructureError("eHYD Messstellen/info response must be a JSON array")
    if document in ([], [[]]):
        return {}

    matched_station = False
    file_entries: list[object] = []
    for section in document:
        if not isinstance(section, dict) or section.get("caption") != "Messstelle":
            continue
        blocks = section.get("data")
        if not isinstance(blocks, list):
            raise UnsupportedSourceStructureError("eHYD Messstellen/info Messstelle block must contain a list")
        for block in blocks:
            if not isinstance(block, dict):
                raise UnsupportedSourceStructureError("eHYD Messstellen/info station entry must be an object")
            info_obj = block.get("info")
            if not isinstance(info_obj, dict) or not isinstance(info_obj.get("data"), list):
                raise UnsupportedSourceStructureError("eHYD Messstellen/info station info.data must be a list")
            for field in cast("list[object]", info_obj["data"]):
                if not isinstance(field, dict):
                    raise UnsupportedSourceStructureError("eHYD Messstellen/info field must be an object")
                field_map = cast("dict[str, object]", field)
                if field_map.get("caption") == "HZBNR":
                    raw_hzb = field_map.get("text")
                    if type(raw_hzb) not in (int, str) or str(raw_hzb).strip() != station:
                        raise UnsupportedSourceStructureError(
                            f"eHYD Messstellen/info HZBNR {raw_hzb!r} contradicts requested station {station!r}"
                        )
                    matched_station = True
                if field_map.get("tag") == "dl_mstfiles":
                    dl_data = field_map.get("data")
                    if not isinstance(dl_data, dict):
                        raise UnsupportedSourceStructureError(
                            "eHYD Messstellen/info dl_mstfiles.data.fileData must be a list"
                        )
                    dl_map = cast("dict[str, object]", dl_data)
                    raw_files = dl_map.get("fileData")
                    if not isinstance(raw_files, list):
                        raise UnsupportedSourceStructureError(
                            "eHYD Messstellen/info dl_mstfiles.data.fileData must be a list"
                        )
                    file_entries.extend(cast("list[object]", raw_files))

    if not matched_station:
        raise UnsupportedSourceStructureError("eHYD Messstellen/info lacks a matching HZBNR station entry")

    resolved: dict[ProductId, int] = {}
    suffix = f"-{station}.csv"
    for raw_entry in file_entries:
        if not isinstance(raw_entry, dict):
            raise UnsupportedSourceStructureError("eHYD Messstellen/info fileData entry must be an object")
        entry_map = cast("dict[str, object]", raw_entry)
        if entry_map.get("msttyp") != "owf":
            continue
        entry_hzb = entry_map.get("hzbnr")
        if type(entry_hzb) not in (int, str) or str(entry_hzb).strip() != station:
            raise UnsupportedSourceStructureError("eHYD Messstellen/info fileData hzbnr contradicts requested station")
        file_nr = entry_map.get("fileNr")
        file_name = entry_map.get("fileName")
        if type(file_nr) is not int or file_nr < 1 or not isinstance(file_name, str) or not file_name:
            raise UnsupportedSourceStructureError("eHYD Messstellen/info fileData entry lacks valid fileNr or fileName")
        if not file_name.endswith(suffix):
            continue
        prefix = file_name[: -len(suffix)]
        product_id = _PREFIX_TO_PRODUCT.get(prefix)
        if product_id is None:
            continue
        if product_id in resolved and resolved[product_id] != file_nr:
            raise UnsupportedSourceStructureError(
                f"eHYD Messstellen/info lists conflicting fileNr values for {station} {product_id}"
            )
        resolved[product_id] = file_nr
    return resolved


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
                try:
                    file_map = resolve_messstellen_info_files(info_response.content, station)
                except UnsupportedSourceStructureError:
                    # Parse retains info_payload and classifies the invalid prerequisite per product.
                    file_map = None
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
