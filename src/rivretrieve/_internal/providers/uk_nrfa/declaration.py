"""NRFA catalogue and live observation stages registration."""

from pathlib import Path

from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration
from rivretrieve._internal.providers.uk_nrfa.config import (
    SHARED_ACQUISITION_PRODUCTS,
    config,
    window_declarations,
)
from rivretrieve._internal.providers.uk_nrfa.fetch import fetch
from rivretrieve._internal.providers.uk_nrfa.parse import parse


class _Stages:
    """NRFA live observation stages consumed by the shared engine."""

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
