from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.schemas import (
    ProductCatalog,
    StationCatalog,
    StationProductCatalog,
    validate_catalogue,
)
from rivretrieve._internal.issues import (
    FatalContractError,
    InvalidCatalogueSourceError,
    LiveCatalogueRoutingNotImplementedError,
    LiveCatalogueUnsupportedIssue,
    apply_on_issue,
)
from rivretrieve._internal.primitives import CatalogSource, OnIssue, ProviderId
from rivretrieve._internal.provider_info import ProviderInfo
from rivretrieve._internal.results import CatalogProvenance, CatalogResult


@dataclass(frozen=True)
class CatalogueReader:
    artifact: PackagedCatalogArtifact
    provider_id: ProviderId | None

    def read_products(
        self,
        *,
        source: CatalogSource = "packaged",
        observed_property: str | None = None,
        frequency: str | None = None,
        statistic: str | None = None,
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]:
        if source not in {"packaged", "live"}:
            raise InvalidCatalogueSourceError(source)

        _ensure_filter_value("observed_property", observed_property)
        _ensure_filter_value("frequency", frequency)
        _ensure_filter_value("statistic", statistic)

        if source == "live":
            provider_info = ProviderInfo.from_row(self.artifact.provider_info)
            if provider_info.live_products:
                raise LiveCatalogueRoutingNotImplementedError("Live catalogue product routing is not implemented")
            issue = LiveCatalogueUnsupportedIssue(
                provider_id=self.provider_id,
                method="read_products",
                capability="live_products",
            )
            apply_on_issue((issue,), on_issue)
            return CatalogResult(
                data=_empty_frame(ProductCatalog.polars_schema),
                provenance=self._live_provenance(),
                issues=(issue,),
            )

        data = self.artifact.products
        for column_name, value in (
            ("observed_property", observed_property),
            ("frequency", frequency),
            ("statistic", statistic),
        ):
            if value is not None:
                data = data.filter(pl.col(column_name) == value)

        issues = validate_catalogue(data, ProductCatalog, on_issue=on_issue)
        return CatalogResult(data=data, provenance=self._provenance(), issues=tuple(issues))

    def read_stations(
        self,
        *,
        source: CatalogSource = "packaged",
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]:
        if source not in {"packaged", "live"}:
            raise InvalidCatalogueSourceError(source)

        if source == "live":
            provider_info = ProviderInfo.from_row(self.artifact.provider_info)
            if provider_info.live_stations:
                raise LiveCatalogueRoutingNotImplementedError("Live catalogue station routing is not implemented")
            issue = LiveCatalogueUnsupportedIssue(
                provider_id=self.provider_id,
                method="read_stations",
                capability="live_stations",
            )
            apply_on_issue((issue,), on_issue)
            return CatalogResult(
                data=_empty_frame(StationCatalog.polars_schema),
                provenance=self._live_provenance(),
                issues=(issue,),
            )

        data = self.artifact.stations
        issues = validate_catalogue(data, StationCatalog, on_issue=on_issue)
        return CatalogResult(data=data, provenance=self._provenance(), issues=tuple(issues))

    def read_station_products(
        self,
        stations: Sequence[str] | None = None,
        *,
        source: CatalogSource = "packaged",
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]:
        if source not in {"packaged", "live"}:
            raise InvalidCatalogueSourceError(source)

        if source == "live":
            provider_info = ProviderInfo.from_row(self.artifact.provider_info)
            if provider_info.live_station_products:
                raise LiveCatalogueRoutingNotImplementedError(
                    "Live catalogue station-product routing is not implemented"
                )
            issue = LiveCatalogueUnsupportedIssue(
                provider_id=self.provider_id,
                method="read_station_products",
                capability="live_station_products",
            )
            apply_on_issue((issue,), on_issue)
            return CatalogResult(
                data=_empty_frame(StationProductCatalog.polars_schema),
                provenance=self._live_provenance(),
                issues=(issue,),
            )

        data = self.artifact.station_products
        if stations:
            data = data.filter(pl.col("station_id").is_in(list(stations)))

        issues = validate_catalogue(data, StationProductCatalog, on_issue=on_issue)
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
        )

    def _live_provenance(self) -> CatalogProvenance:
        from rivretrieve import __version__

        catalogue_version = self.artifact.provider_info["catalogue_version"]
        return CatalogProvenance(
            source="live",
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
        )


def _ensure_filter_value(name: str, value: object) -> None:
    if value is not None and not isinstance(value, str):
        raise FatalContractError(f"Product filter {name} must be a string or None")


def _empty_frame(schema: pl.Schema) -> pl.DataFrame:
    return pl.DataFrame(schema=schema)
