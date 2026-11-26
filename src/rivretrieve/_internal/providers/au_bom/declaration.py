"""BoM live observation stages and packaged discovery catalogue."""

from pathlib import Path

from rivretrieve._internal.providers.au_bom.config import (
    config,
    window_declarations,
)
from rivretrieve._internal.providers.au_bom.fetch import AuBomRequestPlanner, fetch
from rivretrieve._internal.providers.au_bom.parse import parse, parse_values_group
from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration


class _Stages:
    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    request_planner = AuBomRequestPlanner()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)
    parse_group = staticmethod(parse_values_group)


declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=LiveStages(stages=_Stages),
    required_credentials=(),
)
