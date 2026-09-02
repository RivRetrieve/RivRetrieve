"""provider declaration : PackagedCatalogue × LiveStages → DeclaredProvider."""

from pathlib import Path

from rivretrieve._internal.providers.lt_lhmt.config import config, window_declarations
from rivretrieve._internal.providers.lt_lhmt.fetch import fetch
from rivretrieve._internal.providers.lt_lhmt.parse import parse
from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration


class _Stages:
    """Meteo.lt live observation stages consumed by the shared engine."""

    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=LiveStages(stages=_Stages),
)
