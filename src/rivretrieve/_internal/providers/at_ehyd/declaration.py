"""Austria eHYD live observation stages and packaged discovery catalogue."""

from pathlib import Path

from rivretrieve._internal.providers.at_ehyd.config import (
    SHARED_ACQUISITION_PRODUCTS,
    config,
    window_declarations,
)
from rivretrieve._internal.providers.at_ehyd.fetch import fetch
from rivretrieve._internal.providers.at_ehyd.parse import parse
from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration


class _Stages:
    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    shared_acquisition_products = SHARED_ACQUISITION_PRODUCTS
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=LiveStages(stages=_Stages),
    required_credentials=(),
)
