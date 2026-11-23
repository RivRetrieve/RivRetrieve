"""Provider declaration for Estonia Keskkonnaagentuur (ee_est)."""

from __future__ import annotations

from pathlib import Path

from rivretrieve._internal.providers.ee_est.config import config, window_declarations
from rivretrieve._internal.providers.ee_est.fetch import fetch
from rivretrieve._internal.providers.ee_est.parse import parse
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
