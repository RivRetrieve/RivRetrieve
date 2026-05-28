from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.issues import FatalContractError, ObservationsUnavailableError
from rivretrieve._internal.observations import (
    AnnotationSchema,
    ObservationRequest,
    ObservationResult,
    validate_annotation_names,
)
from rivretrieve._internal.primitives import CatalogSource, OnIssue, ProviderId
from rivretrieve._internal.provider_info import ProviderInfo
from rivretrieve._internal.provider_module import ProviderModule
from rivretrieve._internal.results import CatalogResult

_PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class UnknownProviderError(FatalContractError):
    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        super().__init__(f"Provider is not registered: {provider_id}")


@dataclass(frozen=True)
class _ProviderHandle:
    provider_id: ProviderId
    _artifact: PackagedCatalogArtifact
    _module: ProviderModule | None = None

    def info(self) -> ProviderInfo:
        return ProviderInfo.from_row(self._artifact.provider_info)

    def products(
        self,
        *,
        source: CatalogSource = "packaged",
        observed_property: str | None = None,
        frequency: str | None = None,
        statistic: str | None = None,
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]:
        return CatalogueReader(self._artifact, self.provider_id).read_products(
            source=source,
            observed_property=observed_property,
            frequency=frequency,
            statistic=statistic,
            on_issue=on_issue,
        )

    def stations(
        self,
        *,
        source: CatalogSource = "packaged",
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]:
        return CatalogueReader(self._artifact, self.provider_id).read_stations(source=source, on_issue=on_issue)

    def station_products(
        self,
        stations: Sequence[str] | None = None,
        *,
        source: CatalogSource = "packaged",
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]:
        return CatalogueReader(self._artifact, self.provider_id).read_station_products(
            stations,
            source=source,
            on_issue=on_issue,
        )

    def row_annotation_schema(self) -> list[AnnotationSchema]:
        if self._module is None:
            raise ObservationsUnavailableError(f"Provider {self.provider_id} has no observation module registered")
        return self._module.row_annotation_schema()

    def series_annotation_schema(self) -> list[AnnotationSchema]:
        if self._module is None:
            raise ObservationsUnavailableError(f"Provider {self.provider_id} has no observation module registered")
        return self._module.series_annotation_schema()

    def observations(
        self,
        *,
        stations: str | Sequence[str],
        products: str | Sequence[str],
        start: object,
        end: object,
        on_issue: OnIssue = "warn",
    ) -> ObservationResult:
        if self._module is None:
            raise ObservationsUnavailableError(f"Provider {self.provider_id} has no observation module registered")

        request = ObservationRequest.from_inputs(
            provider_id=self.provider_id,
            stations=stations,
            products=products,
            start=start,
            end=end,
        )
        result = self._module.observations(request, on_issue=on_issue)
        row_schemas = self._module.row_annotation_schema()
        validate_annotation_names(result.row_annotations, row_schemas)
        series_schemas = self._module.series_annotation_schema()
        validate_annotation_names(result.series_annotations, series_schemas)
        return result


@dataclass(frozen=True)
class _ProviderRecord:
    provider_id: ProviderId
    artifact: PackagedCatalogArtifact
    handle: _ProviderHandle


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, _ProviderRecord] = {}

    def register(
        self,
        provider_id: str,
        packaged_artifact: PackagedCatalogArtifact,
        provider_module: ProviderModule | None = None,
    ) -> _ProviderHandle:
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
        handle = _ProviderHandle(provider_id=typed_provider_id, _artifact=packaged_artifact, _module=provider_module)
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
