"""Acquire Belgium - Wallonia (`be_wal`) KiWIS series lookups and observation chunks."""

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
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.be_wal.config import (
    BeWalTimeseriesListCoordinates,
    BeWalTimeseriesValuesCoordinates,
)
from rivretrieve._internal.providers.be_wal.parse import (
    interpret_timeseries_list_payload,
    resolve_timeseries_list,
)
from rivretrieve._internal.providers.be_wal.series import (
    KIWIS_NAMESPACE,
    KIWIS_URL,
    PRODUCT_BY_ID,
    ProductSpec,
    reused_series,
    source_series,
    validate_station_id,
    validate_ts_id,
)
from rivretrieve._internal.source_acquisition import (
    FailedSourceRequest,
    SourceRequestTarget,
    attempt_request,
)
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
    stable_id,
)
from rivretrieve._internal.time_axis import TimeAxis
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportFailure,
    TransportRequest,
)

_JSON_HEADERS = {"Accept": "application/json"}
_LIST_RETURNFIELDS = "ts_id,ts_name,station_no,stationparameter_name,parametertype_name,ts_unitsymbol"
_VALUES_RETURNFIELDS = "Timestamp,Value,Quality Code,Quality Code Name"
_VALUES_MD_RETURNFIELDS = "ts_id,ts_name,station_no,stationparameter_name,parametertype_name,ts_unitsymbol"


def _request_target(
    station: str,
    product: ProductId,
    known_series: tuple[SourceSeries, ...],
    *,
    ts_id: str | None = None,
) -> SourceSeries | SourceRequestTarget:
    matching = tuple(item for item in known_series if item.station_id == station and item.product_id == str(product))
    if len(matching) == 1:
        return matching[0]
    if ts_id is not None:
        return reused_series(source_series(station, str(product), ts_id=ts_id, origin="mapping"), known_series)
    return SourceRequestTarget(station, str(product))


def _resolve_from_known(
    station: str,
    product: ProductId,
    pair_scope: SeriesScope,
    known_series: tuple[SourceSeries, ...],
) -> str | None:
    """Return ``KiWIS.ts_id`` when ``known_series`` uniquely matches the active pair scope."""
    matched = [
        item
        for item in known_series
        if item.station_id == station
        and item.product_id == str(product)
        and item.identity.namespace == KIWIS_NAMESPACE
        and item.identity.published_id is not None
        and pair_scope.matches(item)
    ]
    if not matched:
        return None
    if len(matched) != 1:
        raise FatalContractError(
            f"be_wal known_series has multiple matching identities for ({station!r}, {str(product)!r})"
        )
    published_id = matched[0].identity.published_id
    assert published_id is not None
    return validate_ts_id(published_id)


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
    """Acquire SPW KiWIS observation chunks using catalogued or live-resolved ``ts_id`` values."""
    if not stations or not products:
        raise FatalContractError("be_wal fetch requires at least one station and product")
    for station in stations:
        validate_station_id(station)

    validated_products: list[tuple[ProductId, ProductSpec, tuple[RenderedWindow, ...]]] = []
    for product in products:
        try:
            product_config = config.products[product]
        except KeyError as error:
            raise FatalContractError(f"be_wal product is absent from provider config: {product}") from error
        coords = product_config.coordinates.value
        if not isinstance(coords, BeWalTimeseriesValuesCoordinates) or coords.product_id != str(product):
            raise FatalContractError(f"be_wal product has invalid source coordinates: {product}")
        spec = PRODUCT_BY_ID.get(str(product))
        if spec is None:
            raise FatalContractError(f"be_wal product lacks series specification: {product}")
        windows = rendered_windows.get(product, ())
        if not windows:
            raise FatalContractError(f"be_wal product requires at least one rendered window: {product}")
        for window in windows:
            if window.bounds is None or window.stop is None:
                raise FatalContractError(f"be_wal rendered window requires closed bounds and stop: {product}")
        validated_products.append((product, spec, windows))

    requested_window = SeriesWindow(
        start=datetime.fromisoformat(fetch_window.start.isoformat()),
        end=datetime.fromisoformat(fetch_window.end.isoformat()),
        axis=TimeAxis.UTC,
    )
    payloads: list[Payload] = []
    interpretations: list[InterpretedPayload] = []
    failures: list[FailedSourceRequest] = []
    definitions: dict[str, SourceSeries] = {}
    inventories: list[InventorySnapshot] = []

    for station in stations:
        for product, spec, windows in validated_products:
            unrestricted_scope = SeriesScope(
                provider_ids=("be_wal",),
                station_ids=(station,),
                product_ids=(str(product),),
            )
            pair_scope = (scope or unrestricted_scope).model_copy(
                update={"station_ids": (station,), "product_ids": (str(product),)}
            )

            ts_id = _resolve_from_known(station, product, pair_scope, known_series)
            prereq_ids: tuple[str, ...] = ()
            resolved_series: SourceSeries | None = None

            if ts_id is None:
                list_request = TransportRequest(
                    method=HttpMethod.GET,
                    url=KIWIS_URL,
                    params={
                        "service": "kisters",
                        "type": "queryServices",
                        "datasource": "0",
                        "request": "getTimeseriesList",
                        "station_no": station,
                        "ts_name": spec.native_id,
                        "format": "json",
                        "returnfields": _LIST_RETURNFIELDS,
                    },
                    headers=_JSON_HEADERS,
                )
                list_response = attempt_request(transport, list_request)
                if isinstance(list_response, (TransportFailure, CredentialExchangeError)):
                    failures.append(
                        FailedSourceRequest(
                            uuid4().hex,
                            _request_target(station, product, known_series),
                            requested_window,
                            list_request,
                            list_response,
                        )
                    )
                    continue

                list_payload = Payload(
                    source_coordinates=SourceCoordinates(BeWalTimeseriesListCoordinates(str(product), spec.native_id)),
                    station_products=((station, product),),
                    fetch_window=fetch_window,
                    content=list_response.content,
                    origin=SourceCallOrigin.from_response(list_response),
                    prerequisite_calls=list_response.prerequisite_calls,
                    scope=pair_scope,
                    known_series=known_series,
                    attempt_traces=list_response.attempt_traces,
                    acquisition_axis=TimeAxis.UTC,
                )
                payloads.append(list_payload)
                prereq_ids = (list_payload.acquisition_id,)

                list_interp = interpret_timeseries_list_payload(list_payload, config)
                interpretations.append(InterpretedPayload.from_payload(list_payload, list_interp.parsed))
                if not list_interp.scope_matched or list_interp.resolved_ts_id is None:
                    # Reused list_interp.parsed (or fallback parse) classifies FAILED, NO_MATCH, and scope mismatch.
                    continue

                resolved_series = list_interp.parsed.series[0]
                definitions[resolved_series.series_id] = resolved_series
                ts_id = list_interp.resolved_ts_id

            obs_coords = BeWalTimeseriesValuesCoordinates(str(product), ts_id=ts_id)
            target = (
                resolved_series
                if resolved_series is not None
                else reused_series(
                    source_series(station, str(product), ts_id=ts_id, origin="mapping"),
                    known_series,
                )
            )
            pair_payloads: list[Payload] = []
            for window in windows:
                assert window.bounds is not None and window.stop is not None
                chunk_window = SeriesWindow(
                    start=datetime.fromisoformat(window.bounds.start.isoformat()),
                    end=datetime.fromisoformat(window.bounds.end.isoformat()),
                    axis=TimeAxis.UTC,
                )
                request = TransportRequest(
                    method=HttpMethod.GET,
                    url=KIWIS_URL,
                    params={
                        "service": "kisters",
                        "type": "queryServices",
                        "datasource": "0",
                        "request": "getTimeseriesValues",
                        "ts_id": ts_id,
                        "from": window.start,
                        "to": window.stop,
                        "timezone": "UTC",
                        "format": "json",
                        "metadata": "true",
                        "returnfields": _VALUES_RETURNFIELDS,
                        "md_returnfields": _VALUES_MD_RETURNFIELDS,
                    },
                    headers=_JSON_HEADERS,
                )
                attempted = attempt_request(transport, request)
                if isinstance(attempted, (TransportFailure, CredentialExchangeError)):
                    failures.append(
                        FailedSourceRequest(
                            uuid4().hex,
                            target,
                            chunk_window,
                            request,
                            attempted,
                            prerequisite_acquisition_ids=prereq_ids,
                        )
                    )
                    continue
                item_payload = Payload(
                    source_coordinates=SourceCoordinates(obs_coords),
                    station_products=((station, product),),
                    fetch_window=window.bounds,
                    content=attempted.content,
                    origin=SourceCallOrigin.from_response(attempted),
                    prerequisite_calls=attempted.prerequisite_calls,
                    scope=pair_scope,
                    known_series=known_series,
                    attempt_traces=attempted.attempt_traces,
                    acquisition_axis=TimeAxis.UTC,
                    prerequisite_acquisition_ids=prereq_ids,
                )
                payloads.append(item_payload)
                pair_payloads.append(item_payload)

            if pair_payloads:
                definitions[target.series_id] = target
                instants = tuple(
                    item.origin.retrieved_at for item in pair_payloads if isinstance(item.origin.retrieved_at, datetime)
                )
                inventories.append(
                    InventorySnapshot(
                        snapshot_id=stable_id(
                            "be_wal",
                            "kiwis-pair-inventory",
                            station,
                            str(product),
                            ts_id,
                            requested_window.model_dump_json(),
                            *(item.acquisition_id for item in pair_payloads),
                        ),
                        scope=unrestricted_scope,
                        members=(target.series_id,),
                        member_facts=((target.series_id, tuple(fact.facts_id for fact in target.facts)),),
                        completeness=InventoryCompleteness.COMPLETE,
                        access=f"KiWIS getTimeseriesValues ts_id={ts_id}",
                        origin="response",
                        acquired_at=max(instants) if instants else None,
                        window=requested_window,
                        evidence=tuple(
                            f"source-call:{cid}"
                            for cid in (*prereq_ids, *(item.acquisition_id for item in pair_payloads))
                        ),
                    )
                )

    return SourceAcquisition(
        value=tuple(payloads),
        series=tuple(definitions.values()),
        inventories=tuple(inventories),
        failed_requests=tuple(failures),
        interpretations=tuple(interpretations),
    )


__all__ = ["fetch", "resolve_timeseries_list"]
