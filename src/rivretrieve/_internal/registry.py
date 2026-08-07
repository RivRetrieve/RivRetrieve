from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import polars as pl

from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.driver import ProviderStages, drive
from rivretrieve._internal.engine import ObservationRequest as EngineObservationRequest
from rivretrieve._internal.engine import ProductWindowDeclarations, RequestedWindow
from rivretrieve._internal.issues import (
    FatalContractError,
    Issue,
    ObservationsUnavailableError,
    apply_on_issue,
)
from rivretrieve._internal.observations import (
    AnnotationSchema,
    AnnotationTable,
    ObservationProvenance,
    ObservationResult,
    RawPayload,
    RowAnnotationTableSchema,
    SeriesAnnotationTableSchema,
    validate_annotation_names,
)
from rivretrieve._internal.observations import ObservationRequest as LegacyObservationRequest
from rivretrieve._internal.primitives import CatalogSource, OnIssue, ProductId, ProviderId
from rivretrieve._internal.provider_info import ProviderInfo
from rivretrieve._internal.provider_module import ProviderModule
from rivretrieve._internal.results import CatalogResult

_PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class EngineProviderModule(ProviderModule, ProviderStages, Protocol):
    window_declarations: ProductWindowDeclarations
    observation_source: str


class UnknownProviderError(FatalContractError):
    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        super().__init__(f"Provider is not registered: {provider_id}")


@dataclass(frozen=True)
class _ProviderHandle:
    provider_id: ProviderId
    _artifact: PackagedCatalogArtifact
    _module: ProviderModule | None = None
    _stages: ProviderStages | None = None
    _observation_source: str | None = None

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

        request = LegacyObservationRequest.from_inputs(
            provider_id=self.provider_id,
            stations=stations,
            products=products,
            start=start,
            end=end,
        )
        if self._stages is None:
            raise ObservationsUnavailableError(f"Provider {self.provider_id} has no observation stages registered")
        if self._observation_source is None:
            raise FatalContractError(f"Provider {self.provider_id} has engine stages without an observation source")
        result = self._drive_engine(request, self._stages, self._observation_source)
        apply_on_issue(result.issues, on_issue)

        row_schemas = self._module.row_annotation_schema()
        validate_annotation_names(result.row_annotations, row_schemas)
        series_schemas = self._module.series_annotation_schema()
        validate_annotation_names(result.series_annotations, series_schemas)
        return result

    def _drive_engine(
        self,
        request: LegacyObservationRequest,
        stages: ProviderStages,
        observation_source: str,
    ) -> ObservationResult:
        engine_request = EngineObservationRequest(
            provider_id=self.provider_id,
            stations=request.stations,
            products=tuple(ProductId(product_id) for product_id in request.products),
            window=RequestedWindow(
                start=request.start,
                end=request.end,
            ),
        )
        requested_at = datetime.now(UTC)
        provider_info = self.info()
        provenance_issues: tuple[Issue, ...] = (
            *(
                (
                    Issue(
                        severity="info",
                        code="provenance.license_not_established",
                        message=f"RivRetrieve has not yet established the license for provider {self.provider_id}.",
                        details={"field": "license"},
                        provider_id=self.provider_id,
                    ),
                )
                if provider_info.license is None
                else ()
            ),
            *(
                (
                    Issue(
                        severity="info",
                        code="provenance.citation_not_established",
                        message=f"RivRetrieve has not yet established the citation for provider {self.provider_id}.",
                        details={"field": "citation"},
                        provider_id=self.provider_id,
                    ),
                )
                if provider_info.citation is None
                else ()
            ),
        )
        assembled = drive(
            engine_request,
            stages,
            provenance=ObservationProvenance(
                source=observation_source,
                provider_id=self.provider_id,
                catalogue_version=provider_info.catalogue_version,
                license=provider_info.license,
                citation=provider_info.citation,
                requested_at=requested_at,
                request={
                    "stations": list(request.stations),
                    "products": list(request.products),
                    "start": request.start.isoformat(),
                    "end": request.end.isoformat(),
                },
            ),
            raw=RawPayload(provider_id=self.provider_id),
        )
        return ObservationResult(
            data=assembled.canonical_rows.select("time", "station_id", "product_id", "value"),
            row_annotations=AnnotationTable(
                data=pl.DataFrame(schema=RowAnnotationTableSchema.polars_schema),
                schema=RowAnnotationTableSchema,
            ),
            series_annotations=AnnotationTable(
                data=pl.DataFrame(schema=SeriesAnnotationTableSchema.polars_schema),
                schema=SeriesAnnotationTableSchema,
            ),
            provenance=assembled.provenance,
            issues=(*assembled.issues, *provenance_issues),
            raw=assembled.raw,
        )

    def __getattr__(self, name: str) -> object:
        """Forward provider-specific extras to the module.

        Protocol methods are resolved normally (defined above).
        Any other attribute is delegated to the provider module when it exists,
        allowing provider-specific methods such as ``cache_status()`` or
        ``refresh_cache()`` to be called through the handle without adding them
        to the shared Protocol.
        """
        module = object.__getattribute__(self, "_module")
        if module is not None and hasattr(module, name):
            return getattr(module, name)
        raise AttributeError(f"Provider '{object.__getattribute__(self, 'provider_id')}' has no attribute '{name}'")


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
        *,
        engine_provider_module: EngineProviderModule | None = None,
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

        if provider_module is not None and engine_provider_module is not None:
            raise FatalContractError("Register either provider_module or engine_provider_module, not both")

        typed_provider_id = ProviderId(provider_id)
        registered_module: ProviderModule | None
        stages: ProviderStages | None
        observation_source: str | None
        if engine_provider_module is not None:
            registered_module = engine_provider_module
            stages = engine_provider_module
            observation_source = engine_provider_module.observation_source
        else:
            registered_module = provider_module
            stages = None
            observation_source = None
        handle = _ProviderHandle(
            provider_id=typed_provider_id,
            _artifact=packaged_artifact,
            _module=registered_module,
            _stages=stages,
            _observation_source=observation_source,
        )
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
