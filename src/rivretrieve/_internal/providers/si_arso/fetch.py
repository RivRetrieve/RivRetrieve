"""Acquire Slovenia ARSO hydrological archive CSVs and operational amp HTML tables."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
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
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.si_arso.config import (
    SiArsoAmpCoordinates,
    SiArsoArchiveCoordinates,
)
from rivretrieve._internal.providers.si_arso.series import validate_station_id
from rivretrieve._internal.source_acquisition import FailedSourceRequest, SourceRequestTarget, attempt_request
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportFailure,
    TransportRequest,
)

ARCHIVE_URL = "https://vode.arso.gov.si/hidarhiv/pov_arhiv_tab.php"
AMP_BASE_URL = "https://www.arso.gov.si/vode/podatki/amp"


@dataclass(frozen=True, slots=True)
class SiArsoRouteCoordinates:
    """Source-call route coordinates shared by all co-published products in one HTTP response."""

    stream: Literal["archive_daily", "archive_monthly_extremes", "amp"]
    b_flag: Literal["b_oddo_CSV", "b_eks_CSV"] | None = None
    amp_cadence: Literal["t_1", "t_7", "t_30"] | None = None

    def __post_init__(self) -> None:
        if self.stream == "archive_daily":
            if self.b_flag != "b_oddo_CSV" or self.amp_cadence is not None:
                raise ValueError("si_arso archive_daily route requires b_oddo_CSV and no amp_cadence")
            return
        if self.stream == "archive_monthly_extremes":
            if self.b_flag != "b_eks_CSV" or self.amp_cadence is not None:
                raise ValueError("si_arso archive_monthly_extremes route requires b_eks_CSV and no amp_cadence")
            return
        if self.stream == "amp":
            if self.amp_cadence not in ("t_1", "t_7", "t_30") or self.b_flag is not None:
                raise ValueError("si_arso amp route requires amp_cadence in {t_1, t_7, t_30} and no b_flag")
            return
        raise ValueError(f"Unsupported si_arso route stream: {self.stream!r}")


def _validate_archive_year_pair(rendered: RenderedWindow) -> tuple[str, str]:
    if rendered.stop is None or len(rendered.start) < 4 or len(rendered.stop) < 4:
        raise FatalContractError(f"si_arso archive rendered window must carry start and stop dates: {rendered!r}")
    start_year = rendered.start[:4]
    stop_year = rendered.stop[:4]
    if not (start_year.isascii() and start_year.isdigit() and stop_year.isascii() and stop_year.isdigit()):
        raise FatalContractError(f"si_arso archive rendered window has invalid year endpoints: {rendered!r}")
    if int(start_year) > int(stop_year):
        raise FatalContractError(f"si_arso archive start year exceeds stop year: {start_year}..{stop_year}")
    return start_year, stop_year


def _request_target(
    station: str, product: ProductId, known_series: tuple[SourceSeries, ...]
) -> SourceSeries | SourceRequestTarget:
    matching = tuple(item for item in known_series if item.station_id == station and item.product_id == str(product))
    if len(matching) == 1:
        return matching[0]
    return SourceRequestTarget(station, str(product))


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
    """Acquire one HTTP response per ``(station, route[, years])`` and share across co-published products.

    Archive requests omit ``p_vodotok`` intentionally so ARSO routes strictly by
    4-digit gauge ``p_postaja`` (empirically byte-identical across single-river
    and multi-river dropdown stations).
    """
    if not stations or not products:
        raise FatalContractError("si_arso fetch requires at least one station and product")

    type _GroupKey = tuple[str, SiArsoRouteCoordinates, tuple[str, str] | None]
    groups: dict[_GroupKey, tuple[FetchWindow, list[ProductId]]] = {}

    for station in stations:
        clean_station = validate_station_id(station)
        for product in products:
            try:
                configured = config.products[product]
            except KeyError as error:
                raise FatalContractError(f"si_arso product is absent from provider config: {product}") from error
            coords = configured.coordinates.value
            if isinstance(coords, SiArsoArchiveCoordinates):
                route = SiArsoRouteCoordinates(stream=coords.stream, b_flag=coords.b_flag)
                windows = rendered_windows.get(product, ())
                if not windows:
                    raise FatalContractError(f"si_arso archive product requires rendered windows: {product}")
                for rendered in windows:
                    years = _validate_archive_year_pair(rendered)
                    bounds = rendered.bounds if rendered.bounds is not None else fetch_window
                    key: _GroupKey = (clean_station, route, years)
                    entry = groups.get(key)
                    if entry is None:
                        groups[key] = (bounds, [product])
                    else:
                        if entry[0] != bounds:
                            raise FatalContractError("si_arso shared archive route received differing fetch bounds")
                        if product not in entry[1]:
                            entry[1].append(product)
            elif isinstance(coords, SiArsoAmpCoordinates):
                route = SiArsoRouteCoordinates(stream="amp", amp_cadence=coords.amp_cadence)
                key = (clean_station, route, None)
                entry = groups.get(key)
                if entry is None:
                    groups[key] = (fetch_window, [product])
                elif product not in entry[1]:
                    entry[1].append(product)
            else:
                raise FatalContractError(f"si_arso product has invalid source coordinates: {product}")

    payloads: list[Payload] = []
    failures: list[FailedSourceRequest] = []

    for (station, route, years), (bounds, group_products) in groups.items():
        if route.stream in ("archive_daily", "archive_monthly_extremes"):
            assert route.b_flag is not None and years is not None
            start_year, stop_year = years
            request = TransportRequest(
                method=HttpMethod.GET,
                url=ARCHIVE_URL,
                params={
                    "p_postaja": station,
                    "p_od_leto": start_year,
                    "p_do_leto": stop_year,
                    route.b_flag: "1",
                },
                headers={"Accept": "text/csv,*/*"},
            )
        else:
            assert route.amp_cadence is not None
            request = TransportRequest(
                method=HttpMethod.GET,
                url=f"{AMP_BASE_URL}/H{station}_{route.amp_cadence}.html",
                headers={"Accept": "text/html,*/*"},
            )

        response = attempt_request(transport, request)
        if isinstance(response, (TransportFailure, CredentialExchangeError)):
            call_id = uuid4().hex
            series_window = SeriesWindow(
                start=datetime.fromisoformat(bounds.start.isoformat()),
                end=datetime.fromisoformat(bounds.end.isoformat()),
            )
            for product in group_products:
                failures.append(
                    FailedSourceRequest(
                        uuid4().hex,
                        _request_target(station, product, known_series),
                        series_window,
                        request,
                        response,
                        call_id=call_id,
                    )
                )
            continue

        payloads.append(
            Payload(
                source_coordinates=SourceCoordinates(route),
                station_products=tuple((station, product) for product in group_products),
                fetch_window=bounds,
                content=response.content,
                origin=SourceCallOrigin.from_response(response),
                prerequisite_calls=response.prerequisite_calls,
                scope=scope,
                known_series=known_series,
                attempt_traces=response.attempt_traces,
            )
        )

    return SourceAcquisition(value=tuple(payloads), failed_requests=tuple(failures))
