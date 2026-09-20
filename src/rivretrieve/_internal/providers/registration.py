"""provider registration inputs : Manifest × ProviderDeclarations → RegistryEntries."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from importlib import import_module
from pathlib import Path

from platformdirs import user_cache_dir

from rivretrieve._internal.authentication import ExchangeSpec
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact, load_packaged_catalogue_artifact
from rivretrieve._internal.engine import ProviderConfig
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.registry import EngineProviderModule, ProviderRegistry
from rivretrieve._internal.store import StoreRoot, ValidatedStore
from rivretrieve._internal.transport import CredentialHeader, _request_origin


@dataclass(frozen=True, slots=True)
class CatalogueOnly:
    """Declare a provider with a packaged catalogue and no observation stages."""


@dataclass(frozen=True, slots=True)
class LiveStages:
    """Declare a provider whose observations are fetched through engine stages."""

    stages: EngineProviderModule


BulkProbe = Callable[[str], int]
BulkTransfer = Callable[[str, Path], None]


@dataclass(frozen=True, slots=True)
class BulkDownloadRequest:
    """Engine-owned inputs for one provider-declared publisher download."""

    destination: Path
    today: date
    probe: BulkProbe
    transfer: BulkTransfer


@dataclass(frozen=True, slots=True)
class DownloadedBulkArtifact:
    """Publisher artifact identity returned by a bulk download operation."""

    path: Path
    url: str
    source_vintage: date


@dataclass(frozen=True, slots=True)
class BulkCompileRequest:
    """Engine-owned inputs for one atomic store compilation from downloaded artifacts."""

    publisher_artifacts: tuple[DownloadedBulkArtifact, ...]
    destination: StoreRoot
    built_at: datetime
    compiler_version: str

    def __post_init__(self) -> None:
        if not self.publisher_artifacts:
            raise ValueError("bulk compile requires at least one publisher artifact")

    @property
    def publisher_artifact(self) -> Path:
        return self.publisher_artifacts[0].path

    @property
    def publisher_url(self) -> str:
        return self.publisher_artifacts[0].url

    @property
    def source_vintage(self) -> date:
        return max(item.source_vintage for item in self.publisher_artifacts)


BulkDownload = Callable[[BulkDownloadRequest], tuple[DownloadedBulkArtifact, ...]]
BulkCompile = Callable[[BulkCompileRequest], ValidatedStore]


@dataclass(frozen=True, slots=True)
class BulkStore:
    """Declare a provider whose observations are read from a compiled local store."""

    config: ProviderConfig
    download: BulkDownload
    compile: BulkCompile


type ProviderKind = CatalogueOnly | LiveStages | BulkStore


@dataclass(frozen=True, slots=True)
class CredentialHeaderBinding:
    """Bind one declared credential variable to one source-scoped HTTP header."""

    variable: str
    header: str
    origins: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CredentialExchangeBinding:
    """Bind declared credential variables to one source credential exchange."""

    spec: ExchangeSpec
    credential_headers: tuple[CredentialHeaderBinding, ...]


@dataclass(frozen=True, slots=True)
class PublicArchiveAccess:
    """Shared source credential for an archive beyond a UTC-labelled recent horizon.

    This is published source access data, not a caller credential requirement.
    Public composition owns clock resolution and the comparison with engine bounds.
    """

    credential: CredentialHeader
    endpoint: str
    recent_horizon: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.credential, CredentialHeader) or len(self.credential.origins) != 1:
            raise TypeError("public archive access requires one origin-scoped credential")
        if _request_origin(self.endpoint) != self.credential.origins[0]:
            raise ValueError("public archive endpoint must match its credential origin")
        if not isinstance(self.recent_horizon, timedelta) or self.recent_horizon <= timedelta(0):
            raise ValueError("public archive recent horizon must be positive")


@dataclass(frozen=True, slots=True)
class ProviderDeclaration:
    """State one provider's packaged catalogue, observation kind, and credentials."""

    catalogue: Path
    observations: ProviderKind
    required_credentials: tuple[str, ...] = ()
    credential_headers: tuple[CredentialHeaderBinding, ...] = ()
    credential_exchange: CredentialExchangeBinding | None = None
    public_archive_access: PublicArchiveAccess | None = None


@dataclass(frozen=True, slots=True)
class DeclaredProvider:
    """Bind a manifest provider id to its declaration."""

    provider_id: str
    declaration: ProviderDeclaration


type DeclarationLoader = Callable[[str], object]
type ArtifactLoader = Callable[[Path], PackagedCatalogArtifact]


def load_manifest(
    provider_ids: Sequence[str],
    *,
    declaration_loader: DeclarationLoader = lambda provider_id: (
        import_module(f"rivretrieve._internal.providers.{provider_id}.declaration").declaration
    ),
) -> tuple[DeclaredProvider, ...]:
    """Load and validate all provider declarations named by a manifest.

    Parameters
    ----------
    provider_ids
        Provider directory ids in manifest order.
    declaration_loader
        Resolver from a provider directory id to its declaration value.

    Returns
    -------
    tuple[DeclaredProvider, ...]
        Validated declarations in manifest order.

    Raises
    ------
    FatalContractError
        If an id is duplicated or a declaration has an invalid shape or kind.
    """
    duplicates = sorted(provider_id for provider_id in set(provider_ids) if provider_ids.count(provider_id) > 1)
    if duplicates:
        raise FatalContractError(f"Built-in provider manifest contains duplicate provider id: {duplicates[0]}")

    declared: list[DeclaredProvider] = []
    for provider_id in provider_ids:
        try:
            value = declaration_loader(provider_id)
        except (ImportError, AttributeError) as exc:
            raise FatalContractError(f"Cannot load declaration for provider {provider_id}") from exc
        if not isinstance(value, ProviderDeclaration):
            raise FatalContractError(f"Provider {provider_id} has a malformed declaration: {value!r}")
        if not isinstance(value.observations, CatalogueOnly | LiveStages | BulkStore):
            raise FatalContractError(
                f"Provider {provider_id} has unrecognised observation kind: {value.observations!r}"
            )
        credentials = value.required_credentials
        if (
            not isinstance(credentials, tuple)
            or any(not isinstance(name, str) or re.fullmatch(r"[A-Z][A-Z0-9_]*", name) is None for name in credentials)
            or len(credentials) != len(set(credentials))
        ):
            raise FatalContractError(f"Provider {provider_id} has malformed required credentials: {credentials!r}")
        archive = value.public_archive_access
        if archive is not None:
            if not isinstance(archive, PublicArchiveAccess) or not isinstance(value.observations, LiveStages):
                raise FatalContractError(f"Provider {provider_id} public archive access requires LiveStages")
            if credentials or value.credential_headers or value.credential_exchange is not None:
                raise FatalContractError(f"Provider {provider_id} cannot mix public archive and caller credentials")
            if value.observations.stages.config.zone.value != "+00:00":
                raise FatalContractError(f"Provider {provider_id} public archive horizon requires UTC source labels")
        exchange = value.credential_exchange
        if exchange is not None:
            if not isinstance(exchange, CredentialExchangeBinding) or not isinstance(exchange.spec, ExchangeSpec):
                raise FatalContractError(f"Provider {provider_id} has malformed credential exchange")
            if not isinstance(value.observations, LiveStages):
                raise FatalContractError(f"Provider {provider_id} credential exchange requires LiveStages")
            if value.credential_headers != ():
                raise FatalContractError(f"Provider {provider_id} cannot mix direct and exchange credential bindings")
        bindings = value.credential_headers if exchange is None else exchange.credential_headers
        if not isinstance(bindings, tuple) or any(not isinstance(item, CredentialHeaderBinding) for item in bindings):
            raise FatalContractError(f"Provider {provider_id} has malformed credential header bindings: {bindings!r}")
        for binding in bindings:
            if binding.variable not in credentials:
                raise FatalContractError(
                    f"Provider {provider_id} credential header references undeclared variable {binding.variable!r}"
                )
            try:
                header = CredentialHeader(binding.header, "declaration-validation", binding.origins)
                if exchange is not None and header.origins != (_request_origin(exchange.spec.exchange_url),):
                    raise ValueError("exchange credential scope must contain only the exact exchange origin")
            except (TypeError, ValueError) as exc:
                raise FatalContractError(
                    f"Provider {provider_id} has malformed credential header binding for {binding.variable}: {exc}"
                ) from exc
        if exchange is not None:
            names = tuple(binding.header.casefold() for binding in bindings)
            if not names or len(names) != len(set(names)):
                raise FatalContractError(
                    f"Provider {provider_id} exchange credential headers must be nonempty and unique"
                )
        if isinstance(value.observations, LiveStages):
            bound_variables = tuple(binding.variable for binding in bindings)
            if set(bound_variables) != set(credentials) or len(bound_variables) != len(set(bound_variables)):
                raise FatalContractError(
                    f"Provider {provider_id} live credential bindings do not match required credentials"
                )
            required_stage_members = ("config", "window_declarations", "observation_source", "fetch", "parse")
            missing_stage_members = tuple(
                member for member in required_stage_members if not hasattr(value.observations.stages, member)
            )
            if missing_stage_members:
                missing = ", ".join(missing_stage_members)
                raise FatalContractError(
                    f"Provider {provider_id} has malformed LiveStages declaration: "
                    f"stages missing required members: {missing}"
                )
        if isinstance(value.observations, BulkStore):
            non_callable_operations = tuple(
                operation
                for operation in ("download", "compile")
                if not callable(getattr(value.observations, operation))
            )
            if non_callable_operations:
                operations = ", ".join(non_callable_operations)
                raise FatalContractError(
                    f"Provider {provider_id} has malformed BulkStore declaration: "
                    f"operations must be callable: {operations}"
                )
        declared.append(DeclaredProvider(provider_id, value))
    return tuple(declared)


def register_manifest(
    registry: ProviderRegistry,
    provider_ids: Sequence[str],
    *,
    declaration_loader: DeclarationLoader = lambda provider_id: (
        import_module(f"rivretrieve._internal.providers.{provider_id}.declaration").declaration
    ),
    artifact_loader: ArtifactLoader = lambda path: load_packaged_catalogue_artifact(path, on_issue="raise"),
    cache_root: Path | None = None,
) -> None:
    """Load every manifest catalogue, then register the complete valid batch.

    Loading the whole batch before its first registry mutation makes a missing or
    corrupt catalogue refuse the manifest rather than exposing a partial catalogue.

    Parameters
    ----------
    registry
        Registry that receives the validated built-in providers.
    provider_ids
        Provider directory ids in manifest order.
    declaration_loader
        Resolver from a provider directory id to its declaration value.
    artifact_loader
        Loader for one declared packaged catalogue path.
    cache_root
        Engine-owned cache root, or the platform default when omitted.

    Raises
    ------
    FatalContractError
        If the manifest, a declaration, or any packaged catalogue is invalid.
    """
    declared = load_manifest(provider_ids, declaration_loader=declaration_loader)
    loaded_artifacts: list[PackagedCatalogArtifact] = []
    for item in declared:
        try:
            loaded_artifacts.append(artifact_loader(item.declaration.catalogue))
        except FatalContractError as exc:
            raise FatalContractError(
                f"Provider {item.provider_id} catalogue {item.declaration.catalogue} cannot be loaded: {exc}"
            ) from exc
    artifacts = tuple(loaded_artifacts)

    for item, artifact in zip(declared, artifacts, strict=True):
        provider_id = item.provider_id
        artifact_provider_id = artifact.provider_info["provider_id"]
        if artifact_provider_id != provider_id:
            raise FatalContractError(
                f"Provider directory id {provider_id} does not match packaged catalogue provider_id {artifact_provider_id}"
            )

    registered = set(registry.list_provider_ids())
    root = cache_root if cache_root is not None else Path(user_cache_dir("rivretrieve"))
    for item, artifact in zip(declared, artifacts, strict=True):
        if item.provider_id in registered:
            continue
        declaration = item.declaration
        kind = declaration.observations
        if isinstance(kind, CatalogueOnly):
            registry.register(
                item.provider_id,
                artifact,
                required_credentials=declaration.required_credentials,
                credential_headers=declaration.credential_headers,
                credential_exchange=declaration.credential_exchange,
                public_archive_access=declaration.public_archive_access,
            )
        elif isinstance(kind, LiveStages):
            registry.register(
                item.provider_id,
                artifact,
                engine_provider_module=kind.stages,
                required_credentials=declaration.required_credentials,
                credential_headers=declaration.credential_headers,
                credential_exchange=declaration.credential_exchange,
                public_archive_access=declaration.public_archive_access,
            )
        elif isinstance(kind, BulkStore):
            registry.register(
                item.provider_id,
                artifact,
                bulk_config=kind.config,
                observation_store=StoreRoot(root / item.provider_id / "store"),
                bulk_operations=kind,
                required_credentials=declaration.required_credentials,
                credential_headers=declaration.credential_headers,
                credential_exchange=declaration.credential_exchange,
                public_archive_access=declaration.public_archive_access,
            )
        else:  # load_manifest closes this union before any catalogue is loaded.
            raise AssertionError(f"unreachable provider kind for {item.provider_id}")
