"""Provider declaration for Ireland Office of Public Works (`ie_opw`)."""

from __future__ import annotations

from pathlib import Path

from rivretrieve._internal.providers.ie_opw.config import config, window_declarations
from rivretrieve._internal.providers.ie_opw.fetch import IeOpwRequestPlanner, fetch
from rivretrieve._internal.providers.ie_opw.parse import parse, parse_group
from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration


class _Stages:
    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    request_planner = IeOpwRequestPlanner()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)
    parse_group = staticmethod(parse_group)


declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=LiveStages(stages=_Stages),
    required_credentials=(),
)
