"""provider declaration : PackagedCatalogue × LiveStages → DeclaredProvider."""

from pathlib import Path

from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration
from rivretrieve._internal.providers.za_dws.config import config, window_declarations
from rivretrieve._internal.providers.za_dws.fetch import fetch
from rivretrieve._internal.providers.za_dws.parse import parse


class _Stages:
    """DWS Verified Hydrology live observation stages consumed by the shared engine."""

    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=LiveStages(stages=_Stages),
)
