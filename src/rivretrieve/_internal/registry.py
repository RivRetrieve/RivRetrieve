"""provider dispatch : ProviderRegistration × ObservationRequest → ObservationResult."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import polars as pl

from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.terms import verified_catalogue_terms
from rivretrieve._internal.driver import ProviderStages, drive, drive_store
from rivretrieve._internal.engine import CanonicalRowsSchema, ProductWindowDeclarations, ProviderConfig, RequestedWindow
from rivretrieve._internal.engine import ObservationRequest as EngineObservationRequest
from rivretrieve._internal.issues import (
    FatalContractError,
    Issue,
    ObservationsUnavailableError,
    apply_on_issue,
)
from rivretrieve._internal.observations import (
    ObservationProvenance,
    ObservationResult,
    ReceiptMode,
    Receipts,
)
from rivretrieve._internal.observations import ObservationRequest as LegacyObservationRequest
from rivretrieve._internal.primitives import CacheMode, OnIssue, ProductId, ProviderId
from rivretrieve._internal.provider_info import ProviderInfo
from rivretrieve._internal.provider_module import ProviderModule
from rivretrieve._internal.results import CatalogResult
from rivretrieve._internal.store import StoreRoot

if TYPE_CHECKING:
    from rivretrieve._internal.providers.registration import BulkStore, CredentialHeaderBinding
    from rivretrieve._internal.transport import Transport

_PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class EngineProviderModule(ProviderStages, Protocol):
    window_declarations: ProductWindowDeclarations
    observation_source: str


class UnknownProviderError(FatalContractError):
    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        super().__init__(f"Provider is not registered: {provider_id}")


def _unestablished_terms_issues(
    provider_id: ProviderId, license: str | None, citation: str | None
) -> tuple[Issue, ...]:
    """unestablished terms : ProviderId × OptionalLicense × OptionalCitation → Issues (pure)."""
    return tuple(
        Issue(
            severity="info",
            code=f"provenance.{kind}_not_established",
            message=f"RivRetrieve has not yet established the {kind} for provider {provider_id}.",
            details={"field": kind},
            provider_id=provider_id,
        )
        for kind, value in (("license", license), ("citation", citation))
        if value is None
    )


@dataclass(frozen=True)
class _ProviderHandle:
    provider_id: ProviderId
    _artifact: PackagedCatalogArtifact
    _module: ProviderModule | None = None
    _stages: ProviderStages | None = None
    _observation_source: str | None = None
    _store_config: ProviderConfig | None = None
    _store_root: StoreRoot | None = None
    _bulk_operations: BulkStore | None = None
    required_credentials: tuple[str, ...] = ()
    credential_headers: tuple[CredentialHeaderBinding, ...] = ()

    def info(self) -> ProviderInfo:
        provenance = self._artifact.acquisition_provenance
        terms = verified_catalogue_terms(provenance) if provenance is not None else {}
        return replace(
            ProviderInfo.from_row(self._artifact.provider_info),
            license=terms.get("license"),
            citation=terms.get("citation"),
        )

    def products(
        self,
        *,
        observed_property: str | None = None,
        frequency: str | None = None,
        statistic: str | None = None,
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]:
        return CatalogueReader(self._artifact, self.provider_id).read_products(
            observed_property=observed_property,
            frequency=frequency,
            statistic=statistic,
            on_issue=on_issue,
        )

    def stations(
        self,
        *,
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]:
        return CatalogueReader(self._artifact, self.provider_id).read_stations(on_issue=on_issue)

    def station_products(
        self,
        stations: Sequence[str] | None = None,
        *,
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]:
        return CatalogueReader(self._artifact, self.provider_id).read_station_products(
            stations,
            on_issue=on_issue,
        )

    def observations(
        self,
        *,
        stations: str | Sequence[str],
        products: str | Sequence[str],
        start: object,
        end: object,
        on_issue: OnIssue = "warn",
        receipts: ReceiptMode = ReceiptMode.OMIT,
        transport: Transport | None = None,
        cache: CacheMode = "bypass",
        store: StoreRoot | None = None,
    ) -> ObservationResult:
        if self._stages is None and self._store_config is None:
            if self._module is not None:
                raise ObservationsUnavailableError(f"Provider {self.provider_id} has no observation stages registered")
            raise ObservationsUnavailableError(f"Provider {self.provider_id} has no observations registered")
        request = LegacyObservationRequest.from_inputs(
            provider_id=self.provider_id,
            stations=stations,
            products=products,
            start=start,
            end=end,
        )
        if self._stages is not None:
            if self._observation_source is None:
                raise FatalContractError(f"Provider {self.provider_id} has engine stages without an observation source")
            result = self._drive_engine(
                request,
                self._stages,
                self._observation_source,
                receipts=receipts,
                transport=transport,
                cache=cache,
                store=store,
            )
        elif self._store_config is not None and self._store_root is not None:
            if cache == "refresh":
                raise FatalContractError(
                    f"Provider {self.provider_id} uses a compiled store; refresh requires "
                    f'rivretrieve.download("{self.provider_id}"). No transfer was started.'
                )
            result = self._drive_store(
                request, self._store_config, self._store_root if store is None else store, receipts=receipts
            )
        else:
            raise ObservationsUnavailableError(f"Provider {self.provider_id} has no observation stages registered")
        apply_on_issue(result.issues, on_issue)
        return result

    def _drive_engine(
        self,
        request: LegacyObservationRequest,
        stages: ProviderStages,
        observation_source: str,
        *,
        receipts: ReceiptMode = ReceiptMode.OMIT,
        transport: Transport | None = None,
        cache: CacheMode = "bypass",
        store: StoreRoot | None = None,
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
        provenance_issues = _unestablished_terms_issues(self.provider_id, provider_info.license, provider_info.citation)
        assembled = drive(
            engine_request,
            stages,
            provenance=ObservationProvenance(
                source=observation_source,
                provider_id=self.provider_id,
                catalogue_version=provider_info.catalogue_version,
                acquisition_provenance=self._artifact.acquisition_provenance,
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
            receipts=receipts,
            transport=transport,
            credential_names=self.required_credentials,
            cache=cache,
            store=store,
        )
        return ObservationResult(
            data=assembled.canonical_rows.select(
                "time",
                "time_zone",
                "station_id",
                "product_id",
                "value",
            ),
            provenance=assembled.provenance,
            issues=(*assembled.issues, *provenance_issues),
            receipts=assembled.receipts,
        )

    def _drive_store(
        self,
        request: LegacyObservationRequest,
        config: ProviderConfig,
        store: StoreRoot,
        *,
        receipts: ReceiptMode = ReceiptMode.OMIT,
    ) -> ObservationResult:
        engine_request = EngineObservationRequest(
            provider_id=self.provider_id,
            stations=request.stations,
            products=tuple(ProductId(product_id) for product_id in request.products),
            window=RequestedWindow(start=request.start, end=request.end),
        )
        requested_at = datetime.now(UTC)
        provider_info = self.info()
        if not Path(store).exists():
            issue = Issue(
                severity="warning",
                code="bulk.store_missing",
                message=(
                    f"No compiled observation store exists for {self.provider_id}. "
                    f'Run rivretrieve.download("{self.provider_id}") to download and compile it.'
                ),
                details={
                    "command": f'rivretrieve.download("{self.provider_id}")',
                    "store": str(store),
                },
                provider_id=self.provider_id,
            )
            return ObservationResult(
                data=pl.DataFrame(schema=CanonicalRowsSchema.polars_schema).select(
                    "time", "time_zone", "station_id", "product_id", "value"
                ),
                provenance=ObservationProvenance(
                    source="local",
                    provider_id=self.provider_id,
                    catalogue_version=provider_info.catalogue_version,
                    acquisition_provenance=self._artifact.acquisition_provenance,
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
                issues=(
                    issue,
                    *_unestablished_terms_issues(self.provider_id, provider_info.license, provider_info.citation),
                ),
                receipts=Receipts(provider_id=self.provider_id, entries=()),
            )
        assembled = drive_store(
            engine_request,
            config,
            store,
            provenance=ObservationProvenance(
                source="local",
                provider_id=self.provider_id,
                catalogue_version=provider_info.catalogue_version,
                acquisition_provenance=self._artifact.acquisition_provenance,
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
            receipts=receipts,
        )
        provenance_issues = _unestablished_terms_issues(self.provider_id, provider_info.license, provider_info.citation)
        return ObservationResult(
            data=assembled.canonical_rows.select("time", "time_zone", "station_id", "product_id", "value"),
            provenance=assembled.provenance,
            issues=(*assembled.issues, *provenance_issues),
            receipts=assembled.receipts,
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
        self._clear_generation = 0

    @property
    def clear_generation(self) -> int:
        """Return a token that changes whenever all registrations are cleared."""
        return self._clear_generation

    def register(
        self,
        provider_id: str,
        packaged_artifact: PackagedCatalogArtifact,
        provider_module: ProviderModule | None = None,
        *,
        engine_provider_module: EngineProviderModule | None = None,
        bulk_config: ProviderConfig | None = None,
        observation_store: StoreRoot | None = None,
        bulk_operations: BulkStore | None = None,
        required_credentials: tuple[str, ...] = (),
        credential_headers: tuple[CredentialHeaderBinding, ...] = (),
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
        if (bulk_config is None) != (observation_store is None):
            raise FatalContractError("Bulk registration requires both config and observation store")
        if bulk_operations is not None and bulk_config is None:
            raise FatalContractError("Bulk operations require config and observation store")
        if engine_provider_module is not None and bulk_config is not None:
            raise FatalContractError("Register either provider stages or an observation store, not both")
        if bulk_config is not None and (bulk_config.cache is None or bulk_config.cache.store is None):
            raise FatalContractError("Bulk provider config must declare an observation store")

        typed_provider_id = ProviderId(provider_id)
        registered_module: ProviderModule | None
        stages: ProviderStages | None
        observation_source: str | None
        if engine_provider_module is not None:
            registered_module = None
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
            _store_config=bulk_config,
            _store_root=observation_store,
            _bulk_operations=bulk_operations,
            required_credentials=required_credentials,
            credential_headers=credential_headers,
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
        self._clear_generation += 1


_registry = ProviderRegistry()
