from __future__ import annotations

import polars as pl

from rivretrieve._internal.catalogues.schemas import ProviderInfoCatalog, validate_catalogue
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
