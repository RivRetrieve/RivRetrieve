"""provider declaration : PackagedCatalogue × LiveStages → DeclaredProvider.

Terms of use and attribution are now established (Effort #800, step 5:
Danmarks Miljøportal's own open-data catalogue record states CC0 for this
exact dataset and API distribution; see
research/dk-vanda-source-access.md's "Terms and attribution: resolved
(2026-11-14)" section in the evidence repository), so the real packaged
catalogue now exists and `dk_vanda` is a `LiveStages` provider, registered in
`BUILTIN_PROVIDER_IDS`.
"""

from pathlib import Path

from rivretrieve._internal.providers.dk_vanda.config import config, window_declarations
from rivretrieve._internal.providers.dk_vanda.fetch import fetch
from rivretrieve._internal.providers.dk_vanda.parse import parse
from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration


class _Stages:
    """VandA live observation stages consumed by the shared engine."""

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
