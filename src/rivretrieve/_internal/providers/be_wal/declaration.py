"""Provider declaration for Belgium - Wallonia (SPW Hydrométrie) (`be_wal`)."""

from __future__ import annotations

from pathlib import Path

from rivretrieve._internal.providers.be_wal.config import config, window_declarations
from rivretrieve._internal.providers.be_wal.fetch import fetch
from rivretrieve._internal.providers.be_wal.parse import parse
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
