"""provider-info parsing : ProviderInfoRow → ProviderInfo."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import polars as pl

from rivretrieve._internal.catalogues.schemas import PROVIDER_INFO_CATALOG_SCHEMA, validate_catalogue
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId


class ProviderInfoValidationError(FatalContractError):
    """Raised when a provider info row cannot satisfy its contract."""


@dataclass(frozen=True)
class ProviderInfo:
    provider_id: ProviderId
    name: str
    live_stations: bool
    live_products: bool
    live_station_products: bool
    bulk_observations: str
    catalogue_version: str | None
    license: str | None
    citation: str | None

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> ProviderInfo:
        try:
            selected = {column.name: row[column.name] for column in PROVIDER_INFO_CATALOG_SCHEMA.columns}
            provider_info = pl.DataFrame(
                [
                    pl.Series(
                        column.name,
                        [selected[column.name]],
                        dtype=column.dtype,
                        strict=True,
                    )
                    for column in PROVIDER_INFO_CATALOG_SCHEMA.columns
                ]
            )
            validate_catalogue(provider_info, PROVIDER_INFO_CATALOG_SCHEMA, on_issue="raise")
            validated_row = provider_info.row(0, named=True)
        except KeyError as exc:
            missing_name = exc.args[0]
            raise ProviderInfoValidationError(
                f"{PROVIDER_INFO_CATALOG_SCHEMA.name} is missing required columns: {missing_name}"
            ) from exc
        except (FatalContractError, TypeError, pl.exceptions.PolarsError) as exc:
            raise ProviderInfoValidationError(str(exc)) from exc

        return cls(
            provider_id=ProviderId(validated_row["provider_id"]),
            name=validated_row["name"],
            live_stations=validated_row["live_stations"],
            live_products=validated_row["live_products"],
            live_station_products=validated_row["live_station_products"],
            bulk_observations=validated_row["bulk_observations"],
            catalogue_version=validated_row["catalogue_version"],
            license=validated_row["license"],
            citation=validated_row["citation"],
        )

    def to_row(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "name": self.name,
            "live_stations": self.live_stations,
            "live_products": self.live_products,
            "live_station_products": self.live_station_products,
            "bulk_observations": self.bulk_observations,
            "catalogue_version": self.catalogue_version,
            "license": self.license,
            "citation": self.citation,
        }
