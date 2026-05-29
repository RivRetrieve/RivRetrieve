from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    ProductCatalog,
    ProviderInfoCatalog,
    StationCatalog,
    validate_catalogue,
)
from rivretrieve._internal.handle import ProviderHandle
from rivretrieve._internal.registry import _registry
from rivretrieve._internal.results import CatalogProvenance, CatalogResult

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rivretrieve._internal.observations import ObservationResult
    from rivretrieve._internal.primitives import OnIssue

_DEFAULT_PROVIDER_REGISTRATION_ENABLED = True


def providers() -> list[str]:
    _ensure_default_providers_registered()
    return _registry.list_provider_ids()


def provider(provider_id: str) -> ProviderHandle:
    _ensure_default_providers_registered()
    return _registry.get(provider_id)


_provider_lookup = provider


def observations(
    *,
    provider: str,
    stations: str | Sequence[str],
    products: str | Sequence[str],
    start: object,
    end: object,
    on_issue: OnIssue = "warn",
) -> ObservationResult:
    provider_handle = _provider_lookup(provider)
    return provider_handle.observations(
        stations=stations,
        products=products,
        start=start,
        end=end,
        on_issue=on_issue,
    )


def provider_info() -> CatalogResult[ProviderInfoCatalog]:
    from rivretrieve import __version__

    _ensure_default_providers_registered()
    rows = [record.artifact.provider_info for record in _registry.iter_records()]
    if rows:
        data = pl.DataFrame(rows, schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema).sort("provider_id")
    else:
        data = pl.DataFrame(schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)

    issues = validate_catalogue(data, PROVIDER_INFO_CATALOG_SCHEMA, on_issue="raise")
    provenance = CatalogProvenance(
        source="packaged",
        provider_id=None,
        rivretrieve_version=__version__,
        catalogue_version=None,
        artifact_id=None,
        artifact_path=None,
        artifact_hash=None,
        generated_at=None,
        retrieved_at=None,
        endpoints=(),
        query=None,
        response_version=None,
    )
    return CatalogResult(data=data, provenance=provenance, issues=tuple(issues))


def stations() -> CatalogResult[StationCatalog]:
    _ensure_default_providers_registered()
    frames = [
        CatalogueReader(record.artifact, record.provider_id).read_stations().data for record in _registry.iter_records()
    ]
    data = _concat_or_empty(frames, STATION_CATALOG_SCHEMA.polars_schema)
    if data.height:
        data = data.sort("provider_id", "station_id")
    issues = validate_catalogue(data, STATION_CATALOG_SCHEMA, on_issue="raise")
    return CatalogResult(data=data, provenance=_global_provenance(), issues=tuple(issues))


def products() -> CatalogResult[ProductCatalog]:
    return _global_products()


def product_info() -> CatalogResult[ProductCatalog]:
    return _global_products()


def _global_products() -> CatalogResult[ProductCatalog]:
    _ensure_default_providers_registered()
    frames = [
        CatalogueReader(record.artifact, record.provider_id).read_products().data for record in _registry.iter_records()
    ]
    data = _concat_or_empty(frames, PRODUCT_CATALOG_SCHEMA.polars_schema)
    if data.height:
        data = data.sort("provider_id", "product_id")
    issues = validate_catalogue(data, PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    return CatalogResult(data=data, provenance=_global_provenance(), issues=tuple(issues))


def _concat_or_empty(frames: list[pl.DataFrame], schema: pl.Schema) -> pl.DataFrame:
    if not frames:
        return pl.DataFrame(schema=schema)
    return pl.concat(frames)


def _ensure_default_providers_registered() -> None:
    if not _DEFAULT_PROVIDER_REGISTRATION_ENABLED:
        return
    if "ch_foen" in _registry.list_provider_ids():
        return

    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.providers.ch_foen import module as ch_foen_module

    packaged_artifact = load_packaged_catalogue_artifact(ch_foen_module._CATALOGUE_PATH, on_issue="raise")
    _registry.register(
        "ch_foen",
        packaged_artifact,
        provider_module=ch_foen_module,
    )


def _global_provenance() -> CatalogProvenance:
    from rivretrieve import __version__

    return CatalogProvenance(
        source="packaged",
        provider_id=None,
        rivretrieve_version=__version__,
        catalogue_version=None,
        artifact_id=None,
        artifact_path=None,
        artifact_hash=None,
        generated_at=None,
        retrieved_at=None,
        endpoints=(),
        query=None,
        response_version=None,
    )
