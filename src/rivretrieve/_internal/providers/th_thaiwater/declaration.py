"""provider declaration : PackagedCatalogue × LiveStages → DeclaredProvider."""

from pathlib import Path

from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration
from rivretrieve._internal.providers.th_thaiwater.config import config, window_declarations
from rivretrieve._internal.providers.th_thaiwater.fetch import fetch
from rivretrieve._internal.providers.th_thaiwater.parse import parse


class _Stages:
    """ThaiWater live observation stages consumed by the shared engine."""

    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=LiveStages(stages=_Stages),
)
