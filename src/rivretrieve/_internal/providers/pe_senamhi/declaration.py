"""SENAMHI live observation stages and packaged discovery catalogue."""

from collections.abc import Mapping
from pathlib import Path

from rivretrieve._internal.engine import FetchWindow, ProviderConfig, RenderedWindow, SourceAcquisition
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.pe_senamhi.config import config, window_declarations
from rivretrieve._internal.providers.pe_senamhi.fetch import (
    PeSenamhiRequestPlanner,
    SenamhiSourceCoordinates,
    fetch,
)
from rivretrieve._internal.providers.pe_senamhi.parse import parse, parse_group
from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration
from rivretrieve._internal.source_series import SeriesScope, SourceSeries
from rivretrieve._internal.transport import Transport


def _fetch(
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
    coordinates = {}
    for product in products:
        route = config.products[product].coordinates.value
        if not isinstance(route, SenamhiSourceCoordinates):
            raise FatalContractError("SENAMHI products require SENAMHI source coordinates")
        coordinates[product] = route
    return fetch(
        stations,
        coordinates,
        rendered_windows,
        transport,
        scope=scope,
        known_series=known_series,
        config=config,
    )


class _Stages:
    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    request_planner = PeSenamhiRequestPlanner()
    fetch = staticmethod(_fetch)
    parse = staticmethod(parse)
    parse_group = staticmethod(parse_group)


declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=LiveStages(stages=_Stages),
    required_credentials=(),
)
