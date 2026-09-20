"""Compose Swiss public access from resolved engine bounds and the retrieval clock.

Existenz publishes shared read-only archive access at https://api.existenz.ch/.
The bundled credential avoids fetching a credential-bearing document during retrieval.
Publisher credential rotation requires updating this source provisioning artifact.
"""

from datetime import UTC, datetime, timedelta

from rivretrieve._internal.engine import FetchWindow
from rivretrieve._internal.transport import (
    AuthenticatedTransport,
    AuthenticationCapability,
    CredentialHeader,
    Transport,
)

_ARCHIVE = "https://influx.konzept.space/api/v2/query"
_REST_HORIZON = timedelta(days=32)
_SHARED_ARCHIVE_CREDENTIAL = CredentialHeader(
    "Authorization",
    "Token 0yLbh-D7RMe1sX1iIudFel8CcqCI8sVfuRTaliUp56MgE6kub8-nSd05_EJ4zTTKt0lUzw8zcO73zL9QhC3jtA==",
    ("https://influx.konzept.space",),
)


def compose_transport(base: Transport, fetch_window: FetchWindow, now: datetime) -> Transport:
    """Keep recent REST access; authenticate archive windows without caller credentials.

    The engine supplies padded bounds. A window crossing the REST horizon uses
    the archive in full, so the existing route declaration renders its exclusive
    stop. Neither this composition step nor provider fetch shifts rendered bounds.
    """
    if isinstance(base, AuthenticationCapability) and base.can_authenticate(_ARCHIVE):
        return base
    start = datetime.fromisoformat(fetch_window.start.isoformat()).replace(tzinfo=UTC)
    if start >= now - _REST_HORIZON:
        return base
    return AuthenticatedTransport(base, (_SHARED_ARCHIVE_CREDENTIAL,))
