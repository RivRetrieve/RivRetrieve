from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    validate_catalogue,
)
from rivretrieve._internal.issues import (
    FatalContractError,
)
from rivretrieve._internal.primitives import OnIssue, ProviderId
from rivretrieve._internal.results import CatalogProvenance, CatalogResult


@dataclass(frozen=True)
class CatalogueReader:
    artifact: PackagedCatalogArtifact
    provider_id: ProviderId | None

    def read_products(
        self,
        *,
        observed_property: str | None = None,
        frequency: str | None = None,
        statistic: str | None = None,
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]:
        _ensure_filter_value("observed_property", observed_property)
        _ensure_filter_value("frequency", frequency)
        _ensure_filter_value("statistic", statistic)

        data = self.artifact.products
        for column_name, value in (
            ("observed_property", observed_property),
            ("frequency", frequency),
            ("statistic", statistic),
        ):
            if value is not None:
                data = data.filter(pl.col(column_name) == value)

        issues = validate_catalogue(data, PRODUCT_CATALOG_SCHEMA, on_issue=on_issue)
        return CatalogResult(data=data, provenance=self._provenance(), issues=tuple(issues))

    def read_stations(
        self,
        *,
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]:
        data = self.artifact.stations
        issues = validate_catalogue(data, STATION_CATALOG_SCHEMA, on_issue=on_issue)
        return CatalogResult(data=data, provenance=self._provenance(), issues=tuple(issues))

    def read_station_products(
        self,
        stations: Sequence[str] | None = None,
        *,
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]:
        data = self.artifact.station_products
        if stations:
            data = data.filter(pl.col("station_id").is_in(list(stations)))

        issues = validate_catalogue(data, STATION_PRODUCT_CATALOG_SCHEMA, on_issue=on_issue)
        return CatalogResult(data=data, provenance=self._provenance(), issues=tuple(issues))

    def _provenance(self) -> CatalogProvenance:
        from rivretrieve import __version__

        catalogue_version = self.artifact.provider_info["catalogue_version"]
        return CatalogProvenance(
            source="packaged",
            provider_id=self.provider_id,
            rivretrieve_version=__version__,
            catalogue_version=catalogue_version if isinstance(catalogue_version, str) else None,
            artifact_id=None,
            artifact_path=None,
            artifact_hash=None,
            generated_at=None,
            retrieved_at=None,
            endpoints=(),
            query=None,
            response_version=None,
            acquisition_provenance=self.artifact.acquisition_provenance,
        )


def _ensure_filter_value(name: str, value: object) -> None:
    if value is not None and not isinstance(value, str):
        raise FatalContractError(f"Product filter {name} must be a string or None")
