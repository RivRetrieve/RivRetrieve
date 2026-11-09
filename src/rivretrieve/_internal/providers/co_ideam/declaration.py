"""Colombia IDEAM live S3 observation stages and packaged discovery catalogue."""

from pathlib import Path

from rivretrieve._internal.providers.co_ideam.config import config, window_declarations
from rivretrieve._internal.providers.co_ideam.fetch import fetch
from rivretrieve._internal.providers.co_ideam.parse import parse
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
