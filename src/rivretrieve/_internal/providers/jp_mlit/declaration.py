"""provider declaration : PackagedCatalogue × LiveStages → DeclaredProvider."""

from pathlib import Path

from rivretrieve._internal.providers.jp_mlit.config import config, window_declarations
from rivretrieve._internal.providers.jp_mlit.fetch import fetch
from rivretrieve._internal.providers.jp_mlit.parse import parse
from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration, ProviderRateLimit


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
    # MLIT's notes on use ask automated tools to refrain from collection that
    # loads its server, and software requests have returned HTTP 403 before.
    # RivRetrieve paces jp_mlit more conservatively than the shared default
    # as a courtesy; this is not a numeric limit MLIT itself publishes. See
    # docs/providers/jp_mlit.md#automated-access-and-caching and issue #698.
    rate_limit=ProviderRateLimit(minimum_interval_seconds=3.0),
)
