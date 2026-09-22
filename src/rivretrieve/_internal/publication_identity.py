"""Publication-service identity requirements for durable artifact boundaries.

A reused provider identifier cannot establish which publication service authored
an older artifact. These declarations require explicit source identity without
invalidating the shared format version for unrelated providers. They do not
select observation routes or infer identity from a current catalogue.
"""

from collections.abc import Iterable, Mapping
from types import MappingProxyType

_REQUIRED_PUBLICATION_SERVICES: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "fr_hubeau": ("publication_service", "hubeau"),
        "usgs_nwis": ("usgs_publication_service", "usgs-waterdata-v1"),
    }
)


def publication_identity_fields(provider_ids: Iterable[str]) -> dict[str, str]:
    """Resolve independent source identities, including mixed-provider artifacts.

    The existing French field remains unchanged. USGS uses its own field so a
    selection retaining both providers' evidence can declare both services.
    """
    return dict(
        identity
        for provider_id in provider_ids
        if (identity := _REQUIRED_PUBLICATION_SERVICES.get(provider_id)) is not None
    )
