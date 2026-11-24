"""Slovenia ARSO provider declaration combining packaged catalogue and live stages."""

from __future__ import annotations

from pathlib import Path

from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration
from rivretrieve._internal.providers.si_arso.config import (
    SHARED_ACQUISITION_PRODUCTS,
    config,
    window_declarations,
)
from rivretrieve._internal.providers.si_arso.fetch import fetch
from rivretrieve._internal.providers.si_arso.parse import parse, parse_group


class _Stages:
    """Slovenia ARSO live observation stages consumed by the shared engine."""

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
