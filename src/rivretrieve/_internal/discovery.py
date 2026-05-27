from __future__ import annotations

import polars as pl

from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.schemas import (
    ProductCatalog,
    ProviderInfoCatalog,
    StationCatalog,
    validate_catalogue,
)
from rivretrieve._internal.registry import _registry
from rivretrieve._internal.results import CatalogProvenance, CatalogResult


def providers() -> list[str]:
    return _registry.list_provider_ids()


def provider(provider_id: str) -> object:
    return _registry.get(provider_id)


def provider_info() -> CatalogResult[pl.DataFrame]:
    from rivretrieve import __version__

    rows = [record.artifact.provider_info for record in _registry.iter_records()]
    if rows:
        data = pl.DataFrame(rows, schema=ProviderInfoCatalog.polars_schema).sort("provider_id")
    else:
        data = pl.DataFrame(schema=ProviderInfoCatalog.polars_schema)

    issues = validate_catalogue(data, ProviderInfoCatalog, on_issue="raise")
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


def stations() -> CatalogResult[pl.DataFrame]:
    frames = [
        CatalogueReader(record.artifact, record.provider_id).read_stations().data for record in _registry.iter_records()
    ]
    data = _concat_or_empty(frames, StationCatalog.polars_schema)
    if data.height:
        data = data.sort("provider_id", "station_id")
    issues = validate_catalogue(data, StationCatalog, on_issue="raise")
    return CatalogResult(data=data, provenance=_global_provenance(), issues=tuple(issues))


def products() -> CatalogResult[pl.DataFrame]:
    return _global_products()


def product_info() -> CatalogResult[pl.DataFrame]:
    return _global_products()


def _global_products() -> CatalogResult[pl.DataFrame]:
    frames = [
        CatalogueReader(record.artifact, record.provider_id).read_products().data for record in _registry.iter_records()
    ]
    data = _concat_or_empty(frames, ProductCatalog.polars_schema)
    if data.height:
        data = data.sort("provider_id", "product_id")
    issues = validate_catalogue(data, ProductCatalog, on_issue="raise")
    return CatalogResult(data=data, provenance=_global_provenance(), issues=tuple(issues))


def _concat_or_empty(frames: list[pl.DataFrame], schema: pl.Schema) -> pl.DataFrame:
    if not frames:
        return pl.DataFrame(schema=schema)
    return pl.concat(frames)


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
