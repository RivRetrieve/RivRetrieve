"""provider declaration : PackagedCatalogue × LiveStages × CredentialExchangeBinding → DeclaredProvider."""

from pathlib import Path

from rivretrieve._internal.authentication import ExchangeSpec
from rivretrieve._internal.providers.br_ana.config import config, window_declarations
from rivretrieve._internal.providers.br_ana.fetch import fetch
from rivretrieve._internal.providers.br_ana.parse import parse
from rivretrieve._internal.providers.registration import (
    CredentialExchangeBinding,
    CredentialHeaderBinding,
    LiveStages,
    ProviderDeclaration,
)


class _Stages:
    """Adopted ANA telemetry stages consumed by the shared engine."""

    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=LiveStages(stages=_Stages),
    required_credentials=("ANA_IDENTIFICADOR", "ANA_SENHA"),
    credential_exchange=CredentialExchangeBinding(
        spec=ExchangeSpec.ana(),
        credential_headers=(
            CredentialHeaderBinding("ANA_IDENTIFICADOR", "Identificador", ("https://www.ana.gov.br",)),
            CredentialHeaderBinding("ANA_SENHA", "Senha", ("https://www.ana.gov.br",)),
        ),
    ),
)
