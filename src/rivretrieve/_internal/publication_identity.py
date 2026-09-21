"""Publication-service identity requirements for durable artifact boundaries.

A reused provider identifier cannot establish which publication service authored
an older artifact. These declarations require explicit source identity without
invalidating the shared format version for unrelated providers. They do not
select observation routes or infer identity from a current catalogue.
"""

from collections.abc import Iterable, Mapping
from types import MappingProxyType

_REQUIRED_PUBLICATION_SERVICES: Mapping[str, str] = MappingProxyType({"fr_hubeau": "hubeau"})


def publication_identity_fields(provider_ids: Iterable[str]) -> dict[str, str]:
    """Resolve the source-identity fields required by an artifact's providers."""
    services = {
        service
        for provider_id in provider_ids
        if (service := _REQUIRED_PUBLICATION_SERVICES.get(provider_id)) is not None
    }
    if not services:
        return {}
    if len(services) != 1:
        raise ValueError("Artifact contains conflicting publication-service identity requirements")
    return {"publication_service": services.pop()}
