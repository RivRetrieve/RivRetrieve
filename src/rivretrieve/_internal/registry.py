from __future__ import annotations

import re
from dataclasses import dataclass

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId

_PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class UnknownProviderError(FatalContractError):
    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        super().__init__(f"Provider is not registered: {provider_id}")


@dataclass(frozen=True)
class _ProviderHandle:
    provider_id: ProviderId
    _artifact: PackagedCatalogArtifact


@dataclass(frozen=True)
class _ProviderRecord:
    provider_id: ProviderId
    artifact: PackagedCatalogArtifact
    handle: _ProviderHandle


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, _ProviderRecord] = {}

    def register(self, provider_id: str, packaged_artifact: PackagedCatalogArtifact) -> _ProviderHandle:
        if not _PROVIDER_ID_PATTERN.fullmatch(provider_id):
            raise FatalContractError(f"Provider ID has invalid format: {provider_id}")

        artifact_provider_id = packaged_artifact.provider_info["provider_id"]
        if artifact_provider_id != provider_id:
            raise FatalContractError(
                f"Registered provider ID {provider_id} does not match artifact provider_id {artifact_provider_id}"
            )

        if provider_id in self._providers:
            raise FatalContractError(f"Provider ID is already registered: {provider_id}")

        typed_provider_id = ProviderId(provider_id)
        handle = _ProviderHandle(provider_id=typed_provider_id, _artifact=packaged_artifact)
        self._providers[provider_id] = _ProviderRecord(
            provider_id=typed_provider_id,
            artifact=packaged_artifact,
            handle=handle,
        )
        return handle

    def get(self, provider_id: str) -> _ProviderHandle:
        try:
            return self._providers[provider_id].handle
        except KeyError as exc:
            raise UnknownProviderError(provider_id) from exc

    def list_provider_ids(self) -> list[str]:
        return sorted(self._providers)

    def iter_records(self) -> tuple[_ProviderRecord, ...]:
        return tuple(self._providers[provider_id] for provider_id in self.list_provider_ids())

    def clear(self) -> None:
        self._providers.clear()


_registry = ProviderRegistry()
