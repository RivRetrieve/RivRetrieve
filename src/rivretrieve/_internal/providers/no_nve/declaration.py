"""provider declaration : PackagedCatalogue × LiveStages → DeclaredProvider."""

from pathlib import Path

from rivretrieve._internal.providers.no_nve.config import config, window_declarations
from rivretrieve._internal.providers.no_nve.fetch import fetch
from rivretrieve._internal.providers.no_nve.parse import parse
from rivretrieve._internal.providers.registration import CredentialHeaderBinding, LiveStages, ProviderDeclaration


class _Stages:
    """NVE HydAPI live observation stages consumed by the shared engine."""

    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=LiveStages(stages=_Stages),
    required_credentials=("NVE_API_KEY",),
    credential_headers=(CredentialHeaderBinding("NVE_API_KEY", "X-API-Key", ("https://hydapi.nve.no",)),),
)
