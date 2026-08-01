"""CatalogueOrigin ≔ Field(NativeColumn) | NotPublished(Evidence); origin gate : EnrolledProvider × OriginDeclarations × NativeTable × StationCatalog → list[Issue]."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

import polars as pl

from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.schemas import STATION_CATALOG_SCHEMA, StationCatalog
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId

_HTTP_DOCUMENTATION_URL = re.compile(r"https?://[^\s/?#]+(?:[/?#][^\s]*)?")


class NativeColumn(str):
    """An exact, non-empty column name in a provider's native table."""

    def __new__(cls, value: str) -> NativeColumn:
        if not isinstance(value, str):
            raise TypeError("native column name must be a string")
        if not value.strip():
            raise ValueError("native column name must not be empty")
        return super().__new__(cls, value)


class Evidence(str):
    """An absolute HTTP(S) link to a provider's own documentation."""

    def __new__(cls, value: str) -> Evidence:
        if not isinstance(value, str):
            raise TypeError("evidence must be a string")
        if _HTTP_DOCUMENTATION_URL.fullmatch(value) is None:
            raise ValueError("evidence must be an absolute HTTP(S) documentation link")
        return super().__new__(cls, value)


@dataclass(frozen=True, slots=True)
class Field:
    native_column: NativeColumn

    def __post_init__(self) -> None:
        if not isinstance(self.native_column, NativeColumn):
            raise TypeError("Field.native_column must be a NativeColumn")


@dataclass(frozen=True, slots=True)
class NotPublished:
    evidence: Evidence

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, Evidence):
            raise TypeError("NotPublished.evidence must be Evidence")


type CatalogueOrigin = Field | NotPublished
type OriginDeclarations = Mapping[str, object]

ORIGIN_GATE_ENROLLED_PROVIDERS = frozenset({ProviderId("lt_lhmt")})


def validate_catalogue_origins(
    provider_id: ProviderId,
    declarations: OriginDeclarations,
    native_table: NativeTable,
    stations: StationCatalog,
) -> list[Issue]:
    issues: list[Issue] = []
    for column in STATION_CATALOG_SCHEMA.columns:
        canonical_column = column.name
        details: dict[str, object] = {"canonical_column": canonical_column}
        if canonical_column not in declarations:
            issues.append(
                Issue(
                    severity="error",
                    code="catalogue_origin.undeclared_column",
                    message=f"{provider_id}.{canonical_column}: canonical column has no origin declaration",
                    details=details,
                    provider_id=provider_id,
                )
            )
            continue

        origin = declarations[canonical_column]
        if isinstance(origin, Field):
            native_column = str(origin.native_column)
            if native_column not in native_table.data.columns:
                issues.append(
                    Issue(
                        severity="error",
                        code="catalogue_origin.absent_native_column",
                        message=(f"{provider_id}.{canonical_column}: native column '{native_column}' does not exist"),
                        details=details,
                        provider_id=provider_id,
                    )
                )
                continue
            if _has_unpropagated_value(canonical_column, native_column, declarations, native_table, stations):
                issues.append(
                    Issue(
                        severity="error",
                        code="catalogue_origin.unpropagated_value",
                        message=(
                            f"{provider_id}.{canonical_column}: canonical value is null where native column "
                            f"'{native_column}' has a value"
                        ),
                        details=details,
                        provider_id=provider_id,
                    )
                )
        elif not isinstance(origin, NotPublished) or not isinstance(origin.evidence, Evidence):
            issues.append(
                Issue(
                    severity="error",
                    code="catalogue_origin.missing_evidence",
                    message=f"{provider_id}.{canonical_column}: NotPublished origin must carry Evidence",
                    details=details,
                    provider_id=provider_id,
                )
            )
    return issues


def enforce_catalogue_origins(
    provider_id: ProviderId,
    declarations: OriginDeclarations,
    native_table: NativeTable,
    stations: StationCatalog,
) -> None:
    if provider_id not in ORIGIN_GATE_ENROLLED_PROVIDERS:
        raise FatalContractError(f"{provider_id}: provider is not enrolled in catalogue origin gate")
    issues = validate_catalogue_origins(provider_id, declarations, native_table, stations)
    if issues:
        raise FatalContractError(issues[0].message, issues=issues)


def _has_unpropagated_value(
    canonical_column: str,
    native_column: str,
    declarations: OriginDeclarations,
    native_table: NativeTable,
    stations: StationCatalog,
) -> bool:
    station_id_origin = declarations.get("station_id")
    if not isinstance(station_id_origin, Field):
        return False
    native_station_id = str(station_id_origin.native_column)
    if native_station_id not in native_table.data.columns or "station_id" not in stations.columns:
        return False
    native_values = native_table.data.select(
        pl.col(native_station_id).alias("station_id"),
        pl.col(native_column).alias("native_value"),
    )
    canonical_values = stations.select(
        pl.col("station_id"),
        pl.col(canonical_column).alias("canonical_value"),
    )
    aligned = canonical_values.join(native_values, on="station_id", how="left")
    return aligned.filter(pl.col("native_value").is_not_null() & pl.col("canonical_value").is_null()).height > 0
