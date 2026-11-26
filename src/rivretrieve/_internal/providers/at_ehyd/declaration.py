"""Austria eHYD live observation stages and packaged discovery catalogue."""

from pathlib import Path

from rivretrieve._internal.providers.at_ehyd.config import (
    config,
    window_declarations,
)
from rivretrieve._internal.providers.at_ehyd.fetch import AtEhydRequestPlanner, fetch
from rivretrieve._internal.providers.at_ehyd.parse import parse, parse_group
from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration


class _Stages:
    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    request_planner = AtEhydRequestPlanner()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)
    parse_group = staticmethod(parse_group)


declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=LiveStages(stages=_Stages),
    required_credentials=(),
)
