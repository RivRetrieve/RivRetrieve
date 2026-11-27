"""Netherlands Rijkswaterstaat DDAPI 2.0 live observation stages and packaged discovery catalogue."""

from pathlib import Path

from rivretrieve._internal.providers.nl_rws.config import (
    SHARED_ACQUISITION_PRODUCTS,
    config,
    window_declarations,
)
from rivretrieve._internal.providers.nl_rws.fetch import fetch
from rivretrieve._internal.providers.nl_rws.parse import parse, parse_group
from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration


class _Stages:
    """Rijkswaterstaat DDAPI 2.0 live observation stages consumed by the shared engine."""

    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    shared_acquisition_products = SHARED_ACQUISITION_PRODUCTS
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)
    parse_group = staticmethod(parse_group)


declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=LiveStages(stages=_Stages),
    required_credentials=(),
)
