"""provider declaration : PackagedCatalogue × LiveStages → DeclaredProvider."""

from pathlib import Path

from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration
from rivretrieve._internal.providers.th_thaiwater.config import config, window_declarations
from rivretrieve._internal.providers.th_thaiwater.fetch import ThThaiWaterRequestPlanner, fetch
from rivretrieve._internal.providers.th_thaiwater.parse import parse, parse_group


class _Stages:
    """ThaiWater live observation stages consumed by the shared engine."""

    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    request_planner = ThThaiWaterRequestPlanner()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)
    parse_group = staticmethod(parse_group)


declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=LiveStages(stages=_Stages),
    required_credentials=(),
)
