"""provider declaration : PackagedCatalogue × TransportSelectedLiveStages → DeclaredProvider."""

from datetime import timedelta
from pathlib import Path

from rivretrieve._internal.providers.ch_foen.config import config, flux_window_declarations, window_declarations
from rivretrieve._internal.providers.ch_foen.fetch import fetch
from rivretrieve._internal.providers.ch_foen.parse import parse
from rivretrieve._internal.providers.registration import LiveStages, ProviderDeclaration, PublicArchiveAccess
from rivretrieve._internal.transport import AuthenticationCapability, CredentialHeader, Transport


class _Stages:
    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)

    @staticmethod
    def window_declarations_for_transport(transport: Transport):
        if isinstance(transport, AuthenticationCapability) and transport.can_authenticate(
            "https://influx.konzept.space/api/v2/query"
        ):
            return flux_window_declarations()
        return window_declarations()


declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=LiveStages(stages=_Stages),
    required_credentials=(),
    # Published shared read-only access: https://api.existenz.ch/.
    # Bundling avoids fetching credential-bearing documentation during retrieval.
    # Publisher rotation requires updating this provisioning artifact.
    public_archive_access=PublicArchiveAccess(
        CredentialHeader(
            "Authorization",
            "Token 0yLbh-D7RMe1sX1iIudFel8CcqCI8sVfuRTaliUp56MgE6kub8-nSd05_EJ4zTTKt0lUzw8zcO73zL9QhC3jtA==",
            ("https://influx.konzept.space",),
        ),
        endpoint="https://influx.konzept.space/api/v2/query",
        recent_horizon=timedelta(days=32),
    ),
)
