"""Official Swiss catalogue and anonymous observation access."""

from pathlib import Path

from rivretrieve._internal.providers.ch_foen.official_config import config, window_declarations
from rivretrieve._internal.providers.ch_foen.official_fetch import fetch
from rivretrieve._internal.providers.ch_foen.official_parse import parse
from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration


class _Stages:
    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=LiveStages(stages=_Stages),
    required_credentials=(),
)
