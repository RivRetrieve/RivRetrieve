"""Required acquisition evidence for readable provider caches."""

from collections.abc import Mapping
from types import MappingProxyType

# Older caches from these acquisition routes omitted necessary support. Other
# providers retain their existing revision-8 compatibility.
_REQUIRED_SOURCE_CALL_FIELDS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {"jp_mlit": ("prerequisite_acquisition_ids",)}
)


def required_source_call_fields(provider_id: str) -> tuple[str, ...]:
    """Declare source-call fields required to reuse a provider's saved history."""
    return _REQUIRED_SOURCE_CALL_FIELDS.get(provider_id, ())
